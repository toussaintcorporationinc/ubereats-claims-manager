from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import create_access_token, decode_access_token
from app.models import (
    ClaimOrder,
    Restaurant,
    UberIntegrationAccount,
    UberOrderSnapshot,
    UberStoreMapping,
    User,
)
from app.models.domain import utc_now
from app.services.audit import add_audit_log
from app.services.token_cipher_service import TokenCipherError, TokenCipherService

UBER_AUTHORIZATION_URL = "https://auth.uber.com/oauth/v2/authorize"
UBER_TOKEN_URL = "https://auth.uber.com/oauth/v2/token"
UBER_API_BASE_URL = "https://api.uber.com"
UBER_STORES_URL = f"{UBER_API_BASE_URL}/v1/eats/stores"
UBER_ORDER_URL_TEMPLATE = f"{UBER_API_BASE_URL}/v2/eats/order/{'{'}order_id{'}'}"


class UberConnectorError(Exception):
    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class UberConnectorService:
    """Official Uber Eats API connector.

    Merchant authorization uses authorization_code + eats.pos_provisioning
    only for store discovery/activation workflows. Regular Store, Order and
    Reporting API access uses client_credentials after Uber has approved and
    provisioned the application.

    TENNET never auto-activates itself as a POS on a live store because that
    may alter order-management behavior.
    """

    provider = "uber_eats"

    def __init__(self, token_cipher: TokenCipherService | None = None) -> None:
        self.token_cipher = token_cipher or TokenCipherService()

    def get_status(self, db: Session, current_user: User) -> dict[str, object]:
        account = self._latest_account(db)
        mappings_count = db.scalar(select(func.count(UberStoreMapping.id))) or 0
        credentials_configured = self._credentials_configured(account)
        settings = get_settings()
        redirect_uri = self._oauth_redirect_uri()
        webhook_url = self._webhook_url()
        return {
            "provider": self.provider,
            "status": account.status if account else "not_configured",
            "official_api_enabled": bool(
                account
                and account.status == "connected"
                and credentials_configured
                and not account.disconnected_at
            ),
            "approval_required": not bool(account and account.status == "connected"),
            "credentials_configured": credentials_configured,
            "oauth_ready": bool(credentials_configured and redirect_uri),
            "oauth_redirect_uri": redirect_uri,
            "webhook_url": webhook_url,
            "scopes": account.scopes if account else settings.uber_client_scopes,
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
        client_id = client_id.strip()
        client_secret = client_secret.strip()
        if not client_id or not client_secret:
            raise UberConnectorError("Uber client ID and client secret are required", 422)

        account = self._latest_account(db)
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
        account.scopes = get_settings().uber_client_scopes
        account.status = "pending_approval"
        account.disconnected_at = None
        db.flush()
        add_audit_log(
            db,
            entity_type="uber_integration_account",
            entity_id=account.id,
            action="uber.credentials_configured",
            user_id=current_user.id,
            new_value={
                "provider": self.provider,
                "status": account.status,
                "scopes": account.scopes,
                "client_id_configured": True,
                "client_secret_configured": True,
            },
        )
        db.commit()
        db.refresh(account)
        return account

    def disconnect(self, db: Session, current_user: User) -> None:
        account = self._latest_account(db)
        if account is None:
            return
        account.status = "disconnected"
        account.disconnected_at = utc_now()
        account.access_token_encrypted = None
        account.token_expires_at = None
        add_audit_log(
            db,
            entity_type="uber_integration_account",
            entity_id=account.id,
            action="uber.disconnected",
            user_id=current_user.id,
        )
        db.commit()

    def build_authorization_url(self, db: Session, current_user: User) -> str:
        account = self._require_credentials(db)
        client_id, _client_secret = self._decrypt_credentials(account)
        state = create_access_token(
            str(current_user.id),
            {"purpose": "uber_oauth_state", "provider": self.provider},
        )
        query = urlencode(
            {
                "client_id": client_id,
                "response_type": "code",
                "redirect_uri": self._oauth_redirect_uri(),
                "scope": get_settings().uber_provisioning_scope,
                "state": state,
            }
        )
        return f"{UBER_AUTHORIZATION_URL}?{query}"

    def handle_oauth_callback(self, db: Session, *, state: str, code: str) -> dict[str, object]:
        user_id = self._decode_oauth_state(state)
        user = db.get(User, user_id)
        if user is None or not user.active:
            raise UberConnectorError("Uber OAuth state user is invalid", 400)

        account = self._require_credentials(db)
        client_id, client_secret = self._decrypt_credentials(account)
        token_payload = self._post_form(
            UBER_TOKEN_URL,
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "authorization_code",
                "redirect_uri": self._oauth_redirect_uri(),
                "code": code,
            },
        )
        user_token = str(token_payload.get("access_token") or "").strip()
        if not user_token:
            raise UberConnectorError("Uber OAuth response did not include an access token", 502)

        stores = self.list_stores_with_token(user_token)
        exact_mappings = self._sync_exact_store_mappings(db, user, stores)

        connected_store_count = 0
        try:
            app_token = self.client_credentials_token(db, force_refresh=True)
            app_stores = self.list_stores_with_token(app_token)
            connected_store_count = len(app_stores)
        except UberConnectorError:
            connected_store_count = 0

        account.status = "connected" if connected_store_count > 0 else "pending_approval"
        account.disconnected_at = None
        db.flush()
        add_audit_log(
            db,
            entity_type="uber_integration_account",
            entity_id=account.id,
            action="uber.oauth_authorized",
            user_id=user.id,
            new_value={
                "discovered_store_count": len(stores),
                "exact_mappings_created_or_refreshed": exact_mappings,
                "client_credentials_visible_store_count": connected_store_count,
                "status": account.status,
            },
        )
        db.commit()
        return {
            "user_id": user.id,
            "discovered_stores": stores,
            "discovered_store_count": len(stores),
            "exact_mappings": exact_mappings,
            "official_api_enabled": account.status == "connected",
            "status": account.status,
        }

    def client_credentials_token(self, db: Session, *, force_refresh: bool = False) -> str:
        account = self._require_credentials(db)
        now = utc_now()
        if (
            not force_refresh
            and account.access_token_encrypted
            and account.token_expires_at
            and account.token_expires_at > now + timedelta(minutes=5)
        ):
            try:
                token = self.token_cipher.decrypt(account.access_token_encrypted)
            except TokenCipherError as exc:
                raise UberConnectorError("Stored Uber access token cannot be decrypted", 500) from exc
            if token:
                return token

        client_id, client_secret = self._decrypt_credentials(account)
        scopes = (account.scopes or get_settings().uber_client_scopes).strip()
        payload = self._post_form(
            UBER_TOKEN_URL,
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "client_credentials",
                "scope": scopes,
            },
        )
        access_token = str(payload.get("access_token") or "").strip()
        if not access_token:
            raise UberConnectorError("Uber client credentials response did not include an access token", 502)
        expires_in = int(payload.get("expires_in") or 2592000)
        account.access_token_encrypted = self.token_cipher.encrypt(access_token)
        account.token_expires_at = now + timedelta(seconds=max(expires_in - 120, 300))
        account.scopes = str(payload.get("scope") or scopes)
        db.commit()
        return access_token

    def list_stores(self, db: Session) -> list[dict[str, Any]]:
        token = self.client_credentials_token(db)
        stores = self.list_stores_with_token(token)
        account = self._latest_account(db)
        if account is not None and stores:
            account.status = "connected"
            account.disconnected_at = None
            db.commit()
        return stores

    def list_stores_with_token(self, token: str) -> list[dict[str, Any]]:
        stores: list[dict[str, Any]] = []
        start_key: str | None = None
        pages = 0
        while pages < 50:
            query = {"limit": "50"}
            if start_key:
                query["start_key"] = start_key
            payload = self._get_json(
                f"{UBER_STORES_URL}?{urlencode(query)}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                },
            )
            page_stores = payload.get("stores")
            if isinstance(page_stores, list):
                stores.extend(item for item in page_stores if isinstance(item, dict))
            next_key = payload.get("next_key")
            if not next_key:
                break
            start_key = str(next_key)
            pages += 1
        return stores

    def get_order(self, db: Session, order_id: str) -> dict[str, Any]:
        token = self.client_credentials_token(db)
        return self._get_json(
            UBER_ORDER_URL_TEMPLATE.format(order_id=order_id),
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )

    def verify_webhook_signature(self, db: Session, body: bytes, signature: str | None) -> bool:
        if not signature:
            return False
        account = self._latest_account(db)
        if not self._credentials_configured(account):
            return False
        assert account is not None
        _client_id, client_secret = self._decrypt_credentials(account)
        expected = hmac.new(client_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected.lower(), signature.strip().lower())

    def handle_webhook_event(self, db: Session, payload: dict[str, Any]) -> dict[str, object]:
        event_type = str(payload.get("event_type") or "").strip()
        event_id = str(payload.get("event_id") or "").strip() or None

        if event_type == "store.provisioned":
            store_id = str(payload.get("store_id") or payload.get("user_id") or "").strip()
            account = self._latest_account(db)
            if account is not None:
                account.status = "connected"
                account.disconnected_at = None
            mapping = db.scalar(
                select(UberStoreMapping).where(UberStoreMapping.uber_store_id == store_id)
            ) if store_id else None
            if mapping is not None:
                mapping.active = True
            self._audit_webhook(db, event_type, event_id, store_id, None, "store_provisioned")
            db.commit()
            return {"status": "processed", "event_type": event_type, "store_id": store_id}

        if event_type == "store.deprovisioned":
            store_id = str(payload.get("store_id") or payload.get("user_id") or "").strip()
            mapping = db.scalar(
                select(UberStoreMapping).where(UberStoreMapping.uber_store_id == store_id)
            ) if store_id else None
            if mapping is not None:
                mapping.active = False
            self._audit_webhook(db, event_type, event_id, store_id, None, "store_deprovisioned")
            db.commit()
            return {"status": "processed", "event_type": event_type, "store_id": store_id}

        if event_type not in {"orders.cancel", "orders.failure"}:
            self._audit_webhook(db, event_type or "unknown", event_id, None, None, "ignored")
            db.commit()
            return {"status": "ignored", "event_type": event_type or "unknown"}

        meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
        order_id = str(meta.get("resource_id") or payload.get("resource_id") or "").strip()
        store_id = str(meta.get("user_id") or payload.get("user_id") or "").strip()
        if not order_id:
            raise UberConnectorError("Uber cancellation webhook is missing order id", 422)

        mapping = None
        if store_id:
            mapping = db.scalar(
                select(UberStoreMapping)
                .where(
                    UberStoreMapping.uber_store_id == store_id,
                    UberStoreMapping.active.is_(True),
                )
                .limit(1)
            )
        if mapping is None:
            self._audit_webhook(db, event_type, event_id, store_id, order_id, "unmapped_store")
            db.commit()
            return {
                "status": "accepted_unmapped",
                "event_type": event_type,
                "store_id": store_id,
                "order_id": order_id,
            }

        try:
            order_payload = self.get_order(db, order_id)
        except UberConnectorError as exc:
            order_payload = {
                "id": order_id,
                "current_state": "CANCELED",
                "store": {"id": store_id},
                "_tennet_fetch_error": exc.message,
            }

        snapshot = self._upsert_cancelled_snapshot(
            db,
            mapping,
            order_payload,
            webhook_payload=payload,
        )
        claim = self._ensure_provisional_claim(db, mapping, snapshot)
        self._audit_webhook(
            db,
            event_type,
            event_id,
            store_id,
            order_id,
            "captured",
            claim_order_id=claim.id,
        )
        db.commit()
        return {
            "status": "captured",
            "event_type": event_type,
            "store_id": store_id,
            "order_id": order_id,
            "snapshot_id": snapshot.id,
            "claim_order_id": claim.id,
        }

    def _upsert_cancelled_snapshot(
        self,
        db: Session,
        mapping: UberStoreMapping,
        order_payload: dict[str, Any],
        *,
        webhook_payload: dict[str, Any],
    ) -> UberOrderSnapshot:
        order_id = str(order_payload.get("id") or "").strip()
        if not order_id:
            raise UberConnectorError("Uber order payload is missing id", 422)

        store = order_payload.get("store") if isinstance(order_payload.get("store"), dict) else {}
        resolved_store_id = str(store.get("id") or mapping.uber_store_id).strip()
        snapshot = db.scalar(
            select(UberOrderSnapshot).where(
                UberOrderSnapshot.restaurant_id == mapping.restaurant_id,
                UberOrderSnapshot.uber_store_id == resolved_store_id,
                UberOrderSnapshot.uber_order_id == order_id,
            )
        )
        if snapshot is None:
            snapshot = UberOrderSnapshot(
                restaurant_id=mapping.restaurant_id,
                uber_store_id=resolved_store_id,
                uber_order_id=order_id,
                current_state="CANCELED",
                currency="EUR",
                raw_payload_json={},
                imported_from="api_orders",
            )
            db.add(snapshot)

        snapshot.display_id = _optional_text(order_payload.get("display_id")) or snapshot.display_id
        snapshot.customer_name = _customer_name(order_payload) or snapshot.customer_name
        snapshot.current_state = "CANCELED"
        snapshot.placed_at = _parse_datetime(order_payload.get("placed_at")) or snapshot.placed_at
        snapshot.canceled_at = _webhook_event_datetime(webhook_payload) or snapshot.canceled_at or utc_now()
        amount, currency = _order_total(order_payload)
        if amount is not None:
            snapshot.order_total_amount = amount
        if currency:
            snapshot.currency = currency
        snapshot.raw_payload_json = {
            "order": order_payload,
            "webhook": webhook_payload,
            "provisional": True,
        }
        snapshot.imported_from = "api_orders"
        db.flush()
        return snapshot

    def _ensure_provisional_claim(
        self,
        db: Session,
        mapping: UberStoreMapping,
        snapshot: UberOrderSnapshot,
    ) -> ClaimOrder:
        order_numbers = [snapshot.uber_order_id]
        if snapshot.display_id:
            order_numbers.append(snapshot.display_id)
        claim = db.scalar(
            select(ClaimOrder)
            .where(
                ClaimOrder.restaurant_id == mapping.restaurant_id,
                ClaimOrder.uber_order_number.in_(order_numbers),
            )
            .order_by(ClaimOrder.id.desc())
            .limit(1)
        )
        if claim is not None:
            if claim.order_amount is None and snapshot.order_total_amount is not None:
                claim.order_amount = snapshot.order_total_amount
            if claim.customer_name is None and snapshot.customer_name:
                claim.customer_name = snapshot.customer_name
            return claim

        restaurant = db.get(Restaurant, mapping.restaurant_id)
        claim = ClaimOrder(
            restaurant_id=mapping.restaurant_id,
            uber_order_number=snapshot.display_id or snapshot.uber_order_id,
            internal_reference=snapshot.uber_order_id,
            customer_name=snapshot.customer_name,
            order_date=snapshot.placed_at.date() if snapshot.placed_at else None,
            order_time=snapshot.placed_at.timetz().replace(tzinfo=None) if snapshot.placed_at else None,
            cancellation_time=snapshot.canceled_at.timetz().replace(tzinfo=None) if snapshot.canceled_at else None,
            order_amount=snapshot.order_total_amount,
            currency=snapshot.currency,
            accepted_by_restaurant=None,
            prepared_before_cancellation=None,
            loss_type="uber_live_cancellation",
            status="missing_evidence",
            notes=(
                "Annulation captee automatiquement via webhook Uber Eats. "
                "Dossier provisoire: verifier preparation et reconciliation financiere "
                "avant tout envoi de reclamation."
            ),
        )
        db.add(claim)
        db.flush()
        add_audit_log(
            db,
            entity_type="claim_order",
            entity_id=claim.id,
            action="uber.webhook_claim_created",
            user_id=self._integration_user_id(db),
            new_value={
                "restaurant_id": mapping.restaurant_id,
                "restaurant_name": restaurant.name if restaurant else None,
                "uber_order_id": snapshot.uber_order_id,
                "display_id": snapshot.display_id,
                "amount": str(snapshot.order_total_amount) if snapshot.order_total_amount is not None else None,
                "currency": snapshot.currency,
                "status": claim.status,
            },
        )
        return claim

    def _sync_exact_store_mappings(
        self,
        db: Session,
        user: User,
        stores: list[dict[str, Any]],
    ) -> int:
        changed = 0
        for store in stores:
            store_id = _optional_text(store.get("store_id") or store.get("id"))
            if not store_id:
                continue
            existing = db.scalar(
                select(UberStoreMapping).where(UberStoreMapping.uber_store_id == store_id)
            )
            if existing is not None:
                existing.uber_store_name = _optional_text(store.get("name")) or existing.uber_store_name
                existing.active = True
                changed += 1
                continue

            restaurant = db.scalar(
                select(Restaurant).where(Restaurant.uber_merchant_id == store_id)
            )
            if restaurant is None:
                continue
            mapping = UberStoreMapping(
                restaurant_id=restaurant.id,
                uber_store_id=store_id,
                uber_store_name=_optional_text(store.get("name")) or restaurant.name,
                merchant_store_id=_optional_text(store.get("merchant_store_id")),
                external_reference_id=_optional_text(store.get("external_reference_id")),
                active=True,
            )
            db.add(mapping)
            db.flush()
            add_audit_log(
                db,
                entity_type="uber_store_mapping",
                entity_id=mapping.id,
                action="uber.oauth_exact_store_mapping",
                user_id=user.id,
                new_value={
                    "restaurant_id": restaurant.id,
                    "uber_store_id": store_id,
                    "uber_store_name": mapping.uber_store_name,
                },
            )
            changed += 1
        return changed

    def _audit_webhook(
        self,
        db: Session,
        event_type: str,
        event_id: str | None,
        store_id: str | None,
        order_id: str | None,
        outcome: str,
        *,
        claim_order_id: int | None = None,
    ) -> None:
        add_audit_log(
            db,
            entity_type="uber_webhook",
            entity_id=claim_order_id or 0,
            action="uber.webhook_received",
            user_id=self._integration_user_id(db),
            new_value={
                "event_type": event_type,
                "event_id": event_id,
                "store_id": store_id,
                "order_id": order_id,
                "outcome": outcome,
                "claim_order_id": claim_order_id,
            },
        )

    def _integration_user_id(self, db: Session) -> int | None:
        account = self._latest_account(db)
        return account.created_by_user_id if account else None

    def _latest_account(self, db: Session) -> UberIntegrationAccount | None:
        return db.scalar(
            select(UberIntegrationAccount)
            .where(UberIntegrationAccount.provider == self.provider)
            .order_by(UberIntegrationAccount.id.desc())
            .limit(1)
        )

    def _require_credentials(self, db: Session) -> UberIntegrationAccount:
        account = self._latest_account(db)
        if not self._credentials_configured(account):
            raise UberConnectorError("Uber API credentials are not configured", 409)
        assert account is not None
        return account

    def _credentials_configured(self, account: UberIntegrationAccount | None) -> bool:
        if account is None or account.disconnected_at is not None:
            return False
        try:
            client_id = self.token_cipher.decrypt(account.client_id_encrypted)
            client_secret = self.token_cipher.decrypt(account.client_secret_encrypted)
        except TokenCipherError:
            return False
        return bool(client_id and client_secret)

    def _decrypt_credentials(self, account: UberIntegrationAccount) -> tuple[str, str]:
        try:
            client_id = self.token_cipher.decrypt(account.client_id_encrypted)
            client_secret = self.token_cipher.decrypt(account.client_secret_encrypted)
        except TokenCipherError as exc:
            raise UberConnectorError("Uber API credentials cannot be decrypted", 500) from exc
        if not client_id or not client_secret:
            raise UberConnectorError("Uber API credentials are not configured", 409)
        return client_id, client_secret

    def _oauth_redirect_uri(self) -> str:
        settings = get_settings()
        if settings.uber_oauth_redirect_uri:
            return settings.uber_oauth_redirect_uri.rstrip("/")
        return f"{self._external_base_url()}/v1/uber/oauth/callback"

    def _webhook_url(self) -> str:
        return f"{self._external_base_url()}/v1/uber/webhook"

    def _external_base_url(self) -> str:
        settings = get_settings()
        explicit = (settings.uber_public_base_url or "").strip()
        if explicit:
            return explicit.rstrip("/")
        api_base = (settings.api_base_url or "").strip()
        if api_base:
            return api_base.rstrip("/")
        frontend = (settings.frontend_url or "").strip()
        if frontend:
            return frontend.rstrip("/")
        return "http://localhost:8000"

    def _decode_oauth_state(self, state: str) -> int:
        try:
            payload = decode_access_token(state)
            if payload.get("purpose") != "uber_oauth_state" or payload.get("provider") != self.provider:
                raise ValueError("invalid purpose")
            return int(payload.get("sub") or "")
        except (TypeError, ValueError) as exc:
            raise UberConnectorError("Invalid Uber OAuth state", 400) from exc

    def _post_form(self, url: str, payload: dict[str, str]) -> dict[str, Any]:
        request = Request(
            url,
            data=urlencode(payload).encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
            method="POST",
        )
        return self._read_json_response(request)

    def _get_json(self, url: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
        request = Request(url, headers=headers or {}, method="GET")
        return self._read_json_response(request)

    def _read_json_response(self, request: Request) -> dict[str, Any]:
        try:
            with urlopen(request, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise UberConnectorError(_uber_http_error_message(exc.code, body), 502) from exc
        except (URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise UberConnectorError("Uber API request failed", 502) from exc


def _uber_http_error_message(status_code: int, body: str) -> str:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict):
        message = payload.get("message") or payload.get("error_description") or payload.get("error")
        if message:
            return f"Uber API HTTP {status_code}: {message}"
    compact = " ".join(body.split())[:500]
    return f"Uber API HTTP {status_code}: {compact or 'request failed'}"


def _optional_text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _parse_datetime(value: object) -> datetime | None:
    text = _optional_text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _webhook_event_datetime(payload: dict[str, Any]) -> datetime | None:
    value = payload.get("event_time")
    if value in {None, ""}:
        return None
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def _customer_name(order_payload: dict[str, Any]) -> str | None:
    eater = order_payload.get("eater") if isinstance(order_payload.get("eater"), dict) else {}
    first = _optional_text(eater.get("first_name"))
    last = _optional_text(eater.get("last_name"))
    return " ".join(part for part in (first, last) if part) or None


def _order_total(order_payload: dict[str, Any]) -> tuple[Decimal | None, str | None]:
    payment = order_payload.get("payment") if isinstance(order_payload.get("payment"), dict) else {}
    charges = payment.get("charges") if isinstance(payment.get("charges"), dict) else {}
    total = charges.get("total") if isinstance(charges.get("total"), dict) else {}
    raw_amount = total.get("amount")
    currency = _optional_text(total.get("currency_code"))
    if raw_amount is None:
        return None, currency
    try:
        amount = Decimal(str(raw_amount)) / Decimal("100")
    except Exception:
        return None, currency
    return amount.quantize(Decimal("0.01")), currency
