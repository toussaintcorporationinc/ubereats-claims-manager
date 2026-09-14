import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import create_access_token, decode_access_token
from app.models import (
    Restaurant,
    UberIntegrationAccount,
    UberOrderSnapshot,
    UberStoreMapping,
    User,
)
from app.models.domain import utc_now
from app.services.audit import add_audit_log
from app.services.restaurant_identity_service import canonical_restaurant_lookup_key
from app.services.token_cipher_service import TokenCipherError, TokenCipherService

UBER_AUTH_URL = "https://auth.uber.com/oauth/v2/authorize"
UBER_TOKEN_URL = "https://auth.uber.com/oauth/v2/token"
UBER_API_BASE = "https://api.uber.com"
UBER_USER_SCOPE = "eats.pos_provisioning"
UBER_APP_SCOPES = "eats.store eats.order eats.store.orders.read eats.report"


class UberConnectorError(Exception):
    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class UberPollResult:
    stores_checked: int = 0
    cancellations_seen: int = 0
    snapshots_created: int = 0
    snapshots_updated: int = 0
    errors: tuple[str, ...] = ()


class UberConnectorService:
    """Official Uber Eats Marketplace connector.

    TENNET is deliberately a passive observer: store activation always uses
    is_order_manager=false so it cannot replace the merchant's current order
    manager or become responsible for accepting/rejecting live orders.
    """

    provider = "uber_eats"

    def __init__(self, token_cipher: TokenCipherService | None = None) -> None:
        self.token_cipher = token_cipher or TokenCipherService()

    def get_status(self, db: Session, current_user: User) -> dict[str, object]:
        account = self._account(db)
        mappings_count = db.scalar(select(func.count(UberStoreMapping.id))) or 0
        configured = self._credentials_available(account)
        connected = bool(
            account
            and account.status == "connected"
            and account.access_token_encrypted
            and account.token_expires_at
            and account.token_expires_at > utc_now() + timedelta(minutes=5)
        )
        return {
            "provider": self.provider,
            "status": account.status if account else "not_configured",
            "official_api_enabled": connected,
            "approval_required": not connected,
            "credentials_configured": configured,
            "oauth_ready": configured,
            "oauth_redirect_uri": self.oauth_redirect_uri(),
            "webhook_url": self.webhook_url(),
            "scopes": account.scopes if account else UBER_APP_SCOPES,
            "store_mappings_count": mappings_count if current_user.role == "owner" else 0,
        }

    def configure_credentials(
        self,
        db: Session,
        current_user: User,
        *,
        client_id: str,
        client_secret: str,
    ) -> UberIntegrationAccount:
        if current_user.role != "owner":
            raise UberConnectorError("Owner role required", 403)
        client_id = client_id.strip()
        client_secret = client_secret.strip()
        if not client_id or not client_secret:
            raise UberConnectorError("Uber client_id and client_secret are required", 422)
        account = self._account(db)
        if account is None:
            account = UberIntegrationAccount(
                provider=self.provider,
                created_by_user_id=current_user.id,
            )
            db.add(account)
        account.client_id_encrypted = self.token_cipher.encrypt(client_id)
        account.client_secret_encrypted = self.token_cipher.encrypt(client_secret)
        account.access_token_encrypted = None
        account.token_expires_at = None
        account.scopes = UBER_APP_SCOPES
        account.status = "pending_approval"
        account.disconnected_at = None
        db.flush()
        add_audit_log(
            db,
            entity_type="uber_integration_account",
            entity_id=account.id,
            action="uber.credentials_configured",
            user_id=current_user.id,
            new_value={"status": account.status, "scopes": account.scopes},
        )
        db.commit()
        db.refresh(account)
        return account

    def build_authorization_url(self, db: Session, current_user: User) -> str:
        account = self._require_credentials(db)
        client_id, _secret = self._credentials(account)
        state = create_access_token(
            str(current_user.id),
            {"purpose": "uber_oauth_state", "provider": self.provider},
        )
        return f"{UBER_AUTH_URL}?{urlencode({
            'client_id': client_id,
            'response_type': 'code',
            'redirect_uri': self.oauth_redirect_uri(),
            'scope': UBER_USER_SCOPE,
            'state': state,
        })}"

    def handle_oauth_callback(self, db: Session, *, state: str, code: str) -> dict[str, object]:
        try:
            payload = decode_access_token(state)
            if payload.get("purpose") != "uber_oauth_state" or payload.get("provider") != self.provider:
                raise ValueError("invalid state")
            user_id = int(payload.get("sub") or "")
        except Exception as exc:
            raise UberConnectorError("Invalid Uber OAuth state", 400) from exc

        user = db.get(User, user_id)
        if user is None or not user.active:
            raise UberConnectorError("Uber OAuth user is invalid", 400)

        account = self._require_credentials(db)
        client_id, client_secret = self._credentials(account)
        user_token = self._token_request({
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "authorization_code",
            "redirect_uri": self.oauth_redirect_uri(),
            "code": code,
        })
        access_token = str(user_token.get("access_token") or "")
        if not access_token:
            raise UberConnectorError("Uber OAuth response did not include an access token")

        stores = self._list_all_stores(access_token)
        activated = 0
        activation_errors: list[str] = []
        for store in stores:
            store_id = str(store.get("store_id") or store.get("id") or "").strip()
            if not store_id:
                continue
            try:
                # Passive observer only. Never nominate TENNET as order manager.
                self._post_json(
                    f"{UBER_API_BASE}/v1/eats/stores/{store_id}/pos_data?is_order_manager=false",
                    {},
                    token=access_token,
                )
                activated += 1
            except UberConnectorError as exc:
                activation_errors.append(f"{store_id}:{exc.message}")
            self._upsert_mapping_for_discovered_store(db, store)

        app_token = self._token_request({
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "client_credentials",
            "scope": UBER_APP_SCOPES,
        })
        app_access_token = str(app_token.get("access_token") or "")
        expires_in = int(app_token.get("expires_in") or 2592000)
        if not app_access_token:
            raise UberConnectorError("Uber app token was not returned; production scopes may not be approved", 409)

        account.access_token_encrypted = self.token_cipher.encrypt(app_access_token)
        account.token_expires_at = utc_now() + timedelta(seconds=max(300, expires_in - 120))
        account.status = "connected"
        account.scopes = str(app_token.get("scope") or UBER_APP_SCOPES)
        account.disconnected_at = None
        db.flush()
        add_audit_log(
            db,
            entity_type="uber_integration_account",
            entity_id=account.id,
            action="uber.oauth_connected",
            user_id=user.id,
            new_value={
                "stores_discovered": len(stores),
                "stores_activated_passive": activated,
                "activation_errors": activation_errors[:20],
                "scopes": account.scopes,
            },
        )
        db.commit()
        return {
            "status": "connected",
            "stores_discovered": len(stores),
            "stores_activated_passive": activated,
            "activation_errors": activation_errors,
        }

    def disconnect(self, db: Session, current_user: User) -> None:
        if current_user.role != "owner":
            raise UberConnectorError("Owner role required", 403)
        account = self._account(db)
        if account is None:
            return
        account.access_token_encrypted = None
        account.token_expires_at = None
        account.status = "disconnected"
        account.disconnected_at = utc_now()
        db.commit()

    def verify_webhook_signature(self, db: Session, raw_body: bytes, signature: str | None) -> bool:
        if not signature:
            return False
        account = self._require_credentials(db)
        _client_id, client_secret = self._credentials(account)
        expected = hmac.new(client_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature.strip().lower())

    def process_webhook(self, db: Session, payload: dict[str, object]) -> dict[str, object]:
        event_type = str(payload.get("event_type") or "")
        if event_type in {"store.provisioned", "store.deprovisioned"}:
            add_audit_log(
                db,
                entity_type="uber_integration_account",
                entity_id=0,
                action=f"uber.webhook.{event_type}",
                user_id=None,
                new_value=payload,
            )
            db.commit()
            return {"processed": True, "event_type": event_type}

        if event_type not in {"orders.cancel", "orders.failure"}:
            return {"processed": False, "event_type": event_type}

        order_id = str(payload.get("resource_id") or "").strip()
        store_id = str(payload.get("user_id") or "").strip()
        if not order_id:
            return {"processed": False, "event_type": event_type}

        try:
            order_payload = self._get_json(
                f"{UBER_API_BASE}/v2/eats/order/{order_id}",
                token=self.app_access_token(db),
            )
        except UberConnectorError:
            order_payload = {
                "id": order_id,
                "current_state": "CANCELED",
                "store": {"id": store_id} if store_id else {},
            }
        snapshot = self._upsert_order_snapshot(db, order_payload, fallback_store_id=store_id)
        add_audit_log(
            db,
            entity_type="uber_order_snapshot",
            entity_id=snapshot.id if snapshot is not None else 0,
            action="uber.webhook.cancellation_received",
            user_id=None,
            new_value={
                "event_type": event_type,
                "order_id": order_id,
                "store_id": store_id,
                "snapshot_id": snapshot.id if snapshot else None,
            },
        )
        db.commit()
        return {"processed": snapshot is not None, "event_type": event_type, "order_id": order_id}

    def poll_cancellations(self, db: Session) -> UberPollResult:
        token = self.app_access_token(db)
        mappings = list(
            db.scalars(
                select(UberStoreMapping)
                .where(UberStoreMapping.active.is_(True))
                .order_by(UberStoreMapping.id)
            )
        )
        seen = created = updated = 0
        errors: list[str] = []
        for mapping in mappings:
            try:
                payload = self._get_json(
                    f"{UBER_API_BASE}/v1/eats/stores/{mapping.uber_store_id}/canceled-orders",
                    token=token,
                )
                for item in payload.get("orders") or []:
                    if not isinstance(item, dict):
                        continue
                    seen += 1
                    order_id = str(item.get("id") or "").strip()
                    if not order_id:
                        continue
                    try:
                        full = self._get_json(
                            f"{UBER_API_BASE}/v2/eats/order/{order_id}",
                            token=token,
                        )
                    except UberConnectorError:
                        full = {**item, "store": {"id": mapping.uber_store_id}}
                    existing = db.scalar(
                        select(UberOrderSnapshot).where(
                            UberOrderSnapshot.restaurant_id == mapping.restaurant_id,
                            UberOrderSnapshot.uber_order_id == order_id,
                        )
                    )
                    snapshot = self._upsert_order_snapshot(
                        db,
                        full,
                        fallback_store_id=mapping.uber_store_id,
                        fallback_restaurant_id=mapping.restaurant_id,
                    )
                    if snapshot is not None:
                        if existing is None:
                            created += 1
                        else:
                            updated += 1
            except Exception as exc:
                errors.append(f"{mapping.uber_store_id}:{exc}")
        db.commit()
        return UberPollResult(
            stores_checked=len(mappings),
            cancellations_seen=seen,
            snapshots_created=created,
            snapshots_updated=updated,
            errors=tuple(errors[:50]),
        )

    def app_access_token(self, db: Session) -> str:
        account = self._require_credentials(db)
        now = utc_now()
        if (
            account.access_token_encrypted
            and account.token_expires_at is not None
            and account.token_expires_at > now + timedelta(minutes=5)
        ):
            try:
                token = self.token_cipher.decrypt(account.access_token_encrypted)
            except TokenCipherError:
                token = None
            if token:
                return token

        client_id, client_secret = self._credentials(account)
        token_payload = self._token_request({
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "client_credentials",
            "scope": UBER_APP_SCOPES,
        })
        token = str(token_payload.get("access_token") or "")
        if not token:
            account.status = "pending_approval"
            db.commit()
            raise UberConnectorError("Uber production API scopes are not approved", 409)
        expires_in = int(token_payload.get("expires_in") or 2592000)
        account.access_token_encrypted = self.token_cipher.encrypt(token)
        account.token_expires_at = now + timedelta(seconds=max(300, expires_in - 120))
        account.status = "connected"
        account.scopes = str(token_payload.get("scope") or UBER_APP_SCOPES)
        db.commit()
        return token

    def oauth_redirect_uri(self) -> str:
        settings = get_settings()
        configured = getattr(settings, "uber_oauth_redirect_uri", None)
        if configured:
            return configured
        if settings.runtime_environment == "production" or settings.vercel:
            return "https://ubereats-claims-manager.vercel.app/api/v1/uber/oauth/callback"
        return "http://localhost:8000/v1/uber/oauth/callback"

    def webhook_url(self) -> str:
        settings = get_settings()
        configured = getattr(settings, "uber_webhook_url", None)
        if configured:
            return configured
        if settings.runtime_environment == "production" or settings.vercel:
            return "https://ubereats-claims-manager.vercel.app/api/v1/uber/webhook"
        return "http://localhost:8000/v1/uber/webhook"

    def _account(self, db: Session) -> UberIntegrationAccount | None:
        return db.scalar(
            select(UberIntegrationAccount)
            .where(UberIntegrationAccount.provider == self.provider)
            .order_by(UberIntegrationAccount.id.desc())
            .limit(1)
        )

    def _require_credentials(self, db: Session) -> UberIntegrationAccount:
        account = self._account(db)
        if not self._credentials_available(account):
            raise UberConnectorError("Uber developer credentials are not configured", 409)
        assert account is not None
        return account

    def _credentials_available(self, account: UberIntegrationAccount | None) -> bool:
        if account is None or not account.client_id_encrypted or not account.client_secret_encrypted:
            return False
        try:
            return bool(
                self.token_cipher.decrypt(account.client_id_encrypted)
                and self.token_cipher.decrypt(account.client_secret_encrypted)
            )
        except TokenCipherError:
            return False

    def _credentials(self, account: UberIntegrationAccount) -> tuple[str, str]:
        try:
            client_id = self.token_cipher.decrypt(account.client_id_encrypted) or ""
            client_secret = self.token_cipher.decrypt(account.client_secret_encrypted) or ""
        except TokenCipherError as exc:
            raise UberConnectorError("Stored Uber credentials cannot be decrypted", 500) from exc
        if not client_id or not client_secret:
            raise UberConnectorError("Uber developer credentials are not configured", 409)
        return client_id, client_secret

    def _token_request(self, fields: dict[str, str]) -> dict:
        encoded = urlencode(fields).encode("utf-8")
        request = Request(
            UBER_TOKEN_URL,
            data=encoded,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        return self._read_json(request)

    def _list_all_stores(self, token: str) -> list[dict]:
        stores: list[dict] = []
        start_key: str | None = None
        for _ in range(200):
            query = {"limit": "50"}
            if start_key:
                query["start_key"] = start_key
            payload = self._get_json(
                f"{UBER_API_BASE}/v1/eats/stores?{urlencode(query)}",
                token=token,
            )
            page = payload.get("stores") or []
            stores.extend(item for item in page if isinstance(item, dict))
            next_key = payload.get("next_key")
            if not next_key:
                break
            start_key = str(next_key)
        return stores

    def _upsert_mapping_for_discovered_store(self, db: Session, store: dict) -> UberStoreMapping | None:
        store_id = str(store.get("store_id") or store.get("id") or "").strip()
        name = str(store.get("name") or "").strip()
        if not store_id:
            return None
        mapping = db.scalar(select(UberStoreMapping).where(UberStoreMapping.uber_store_id == store_id))
        if mapping is not None:
            mapping.uber_store_name = name or mapping.uber_store_name
            mapping.merchant_store_id = store.get("merchant_store_id") or mapping.merchant_store_id
            mapping.active = True
            db.flush()
            return mapping

        direct = db.scalar(select(Restaurant).where(Restaurant.uber_merchant_id == store_id))
        restaurant = direct
        if restaurant is None and name:
            key = canonical_restaurant_lookup_key(name)
            candidates = [
                item for item in db.scalars(select(Restaurant).where(Restaurant.active.is_(True))).all()
                if canonical_restaurant_lookup_key(item.name) == key
            ]
            if len(candidates) == 1:
                restaurant = candidates[0]
        if restaurant is None:
            return None
        mapping = UberStoreMapping(
            restaurant_id=restaurant.id,
            uber_store_id=store_id,
            uber_store_name=name or restaurant.name,
            merchant_store_id=store.get("merchant_store_id"),
            external_reference_id=store.get("external_reference_id"),
            active=True,
        )
        db.add(mapping)
        db.flush()
        return mapping

    def _upsert_order_snapshot(
        self,
        db: Session,
        payload: dict,
        *,
        fallback_store_id: str | None = None,
        fallback_restaurant_id: int | None = None,
    ) -> UberOrderSnapshot | None:
        order_id = str(payload.get("id") or payload.get("order_id") or "").strip()
        store = payload.get("store") if isinstance(payload.get("store"), dict) else {}
        store_id = str(store.get("id") or store.get("store_id") or fallback_store_id or "").strip()
        if not order_id or not store_id:
            return None
        mapping = db.scalar(select(UberStoreMapping).where(UberStoreMapping.uber_store_id == store_id))
        restaurant_id = mapping.restaurant_id if mapping is not None else fallback_restaurant_id
        if restaurant_id is None:
            return None

        snapshot = db.scalar(
            select(UberOrderSnapshot).where(
                UberOrderSnapshot.restaurant_id == restaurant_id,
                UberOrderSnapshot.uber_order_id == order_id,
            )
        )
        if snapshot is None:
            snapshot = UberOrderSnapshot(
                restaurant_id=restaurant_id,
                uber_store_id=store_id,
                uber_order_id=order_id,
                display_id=str(payload.get("display_id") or "") or None,
                customer_name=self._customer_name(payload),
                current_state=str(payload.get("current_state") or "CANCELED").upper(),
                placed_at=self._parse_datetime(payload.get("placed_at")),
                canceled_at=utc_now(),
                order_total_amount=self._extract_order_amount(payload),
                currency=self._extract_currency(payload),
                raw_payload_json=payload,
                imported_from="api_orders",
            )
            db.add(snapshot)
        else:
            snapshot.display_id = str(payload.get("display_id") or snapshot.display_id or "") or None
            snapshot.customer_name = self._customer_name(payload) or snapshot.customer_name
            snapshot.current_state = str(payload.get("current_state") or snapshot.current_state or "CANCELED").upper()
            snapshot.placed_at = self._parse_datetime(payload.get("placed_at")) or snapshot.placed_at
            snapshot.canceled_at = snapshot.canceled_at or utc_now()
            snapshot.order_total_amount = self._extract_order_amount(payload) or snapshot.order_total_amount
            snapshot.currency = self._extract_currency(payload) or snapshot.currency
            snapshot.raw_payload_json = payload
        db.flush()
        return snapshot

    def _customer_name(self, payload: dict) -> str | None:
        eater = payload.get("eater")
        if not isinstance(eater, dict):
            return None
        first = str(eater.get("first_name") or "").strip()
        last = str(eater.get("last_name") or "").strip()
        return " ".join(value for value in (first, last) if value) or None

    def _extract_order_amount(self, payload: dict) -> Decimal | None:
        payment = payload.get("payment")
        if not isinstance(payment, dict):
            return None
        charges = payment.get("charges")
        if not isinstance(charges, dict):
            return None
        total = charges.get("total")
        if not isinstance(total, dict):
            return None
        raw = total.get("amount")
        try:
            amount = Decimal(str(raw))
        except Exception:
            return None
        # Uber Money amounts are commonly represented in minor units.
        if amount == amount.to_integral_value() and abs(amount) >= 100:
            amount = amount / Decimal("100")
        return amount.quantize(Decimal("0.01"))

    def _extract_currency(self, payload: dict) -> str:
        payment = payload.get("payment")
        if isinstance(payment, dict):
            charges = payment.get("charges")
            if isinstance(charges, dict):
                total = charges.get("total")
                if isinstance(total, dict):
                    value = total.get("currency_code") or total.get("currency")
                    if value:
                        return str(value)[:3].upper()
        return "EUR"

    def _parse_datetime(self, value: object) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed

    def _get_json(self, url: str, *, token: str) -> dict:
        request = Request(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Accept-Encoding": "identity",
            },
            method="GET",
        )
        return self._read_json(request)

    def _post_json(self, url: str, payload: dict, *, token: str) -> dict:
        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        return self._read_json(request, allow_empty=True)

    def _read_json(self, request: Request, *, allow_empty: bool = False) -> dict:
        try:
            with urlopen(request, timeout=20) as response:
                raw = response.read()
                if not raw and allow_empty:
                    return {}
                return json.loads(raw.decode("utf-8")) if raw else {}
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            message = f"Uber API error {exc.code}"
            try:
                parsed = json.loads(body)
                message = str(parsed.get("message") or parsed.get("error_description") or parsed.get("error") or message)
            except Exception:
                if body:
                    message = f"{message}: {body[:500]}"
            raise UberConnectorError(message, 502) from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise UberConnectorError("Uber API request failed", 502) from exc
