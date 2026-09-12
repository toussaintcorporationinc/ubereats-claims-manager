import hashlib
import hmac
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import (
    create_access_token,
    create_password_reset_token,
    create_refresh_token,
    decode_password_reset_token,
    decode_refresh_token,
    hash_password,
    verify_password,
)
from app.models import User
from app.schemas.domain import LoginRequest, RefreshTokenRequest, RegisterRequest, TokenResponse, UserRead
from app.services.audit import add_audit_log

router = APIRouter(prefix="/v1/auth", tags=["auth"])


class PasswordResetRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)


class PasswordResetConfirm(BaseModel):
    token: str = Field(min_length=20, max_length=4096)
    password: str = Field(min_length=12, max_length=256)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def build_token_response(user: User) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(str(user.id), {"role": user.role}),
        refresh_token=create_refresh_token(str(user.id), {"role": user.role}),
        token_type="bearer",
        user=UserRead.model_validate(user),
    )


def send_password_reset_email(to_email: str, reset_url: str) -> None:
    settings = get_settings()
    if not settings.email_provider_enabled or not settings.resend_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Password reset email service is not enabled",
        )
    if not settings.resend_api_key or not settings.resend_from_email:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Password reset email service is not configured",
        )

    payload = {
        "from": settings.resend_from_email,
        "to": [to_email],
        "subject": "TENNET - Réinitialisation du mot de passe",
        "text": (
            "Une demande de réinitialisation du mot de passe TENNET a été effectuée.\n\n"
            f"Ouvrez ce lien dans les 30 minutes : {reset_url}\n\n"
            "Si vous n'êtes pas à l'origine de cette demande, ignorez cet e-mail."
        ),
    }
    if settings.resend_reply_to:
        payload["reply_to"] = [settings.resend_reply_to]

    request = Request(
        settings.resend_api_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.resend_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=20):
            return
    except HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Password reset email provider returned HTTP {exc.code}",
        ) from exc
    except (URLError, TimeoutError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Password reset email could not be sent",
        ) from exc


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register_first_owner(payload: RegisterRequest, db: Session = Depends(get_db)) -> TokenResponse:
    existing_user_count = db.scalar(select(func.count(User.id))) or 0
    if existing_user_count > 0:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Public registration is closed after the first owner is created",
        )

    user = User(
        email=normalize_email(payload.email),
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        role="owner",
        active=True,
    )
    db.add(user)
    db.flush()
    add_audit_log(
        db,
        entity_type="user",
        entity_id=user.id,
        action="user.created",
        user_id=user.id,
        new_value={"email": user.email, "role": user.role, "active": user.active},
    )
    db.commit()
    db.refresh(user)
    return build_token_response(user)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    email = normalize_email(payload.email)
    user = db.scalar(select(User).where(User.email == email))
    if user is None or not verify_password(payload.password, user.hashed_password):
        add_audit_log(
            db,
            entity_type="user",
            entity_id=user.id if user is not None else 0,
            action="auth.login_failed",
            user_id=user.id if user is not None else None,
            new_value={"email": email},
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    if not user.active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is inactive")

    add_audit_log(
        db,
        entity_type="user",
        entity_id=user.id,
        action="auth.login_success",
        user_id=user.id,
        new_value={"email": user.email},
    )
    db.commit()
    db.refresh(user)
    return build_token_response(user)


@router.post("/password-reset/request", status_code=status.HTTP_202_ACCEPTED)
def request_password_reset(payload: PasswordResetRequest, db: Session = Depends(get_db)) -> dict[str, str]:
    email = normalize_email(payload.email)
    user = db.scalar(select(User).where(User.email == email))
    if user is None or user.role != "owner" or not user.active:
        return {"status": "accepted"}

    password_fingerprint = hashlib.sha256(user.hashed_password.encode("utf-8")).hexdigest()
    token = create_password_reset_token(str(user.id), password_fingerprint)
    settings = get_settings()
    frontend_url = (settings.frontend_url or "https://thetennet.com").rstrip("/")
    reset_url = f"{frontend_url}/reset-password?token={token}"
    send_password_reset_email(user.email, reset_url)

    add_audit_log(
        db,
        entity_type="user",
        entity_id=user.id,
        action="auth.password_reset_requested",
        user_id=user.id,
        new_value={"email": user.email},
    )
    db.commit()
    return {"status": "accepted"}


@router.post("/password-reset/confirm", response_model=TokenResponse)
def confirm_password_reset(payload: PasswordResetConfirm, db: Session = Depends(get_db)) -> TokenResponse:
    try:
        token_payload = decode_password_reset_token(payload.token)
        user_id = int(token_payload["sub"])
        token_password_fingerprint = str(token_payload["password_fingerprint"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired password reset link",
        ) from None

    user = db.get(User, user_id)
    if user is None or user.role != "owner":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired password reset link",
        )

    current_password_fingerprint = hashlib.sha256(user.hashed_password.encode("utf-8")).hexdigest()
    if not hmac.compare_digest(token_password_fingerprint, current_password_fingerprint):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired password reset link",
        )

    user.hashed_password = hash_password(payload.password)
    user.active = True
    add_audit_log(
        db,
        entity_type="user",
        entity_id=user.id,
        action="auth.password_reset_completed",
        user_id=user.id,
        new_value={"email": user.email},
    )
    db.commit()
    db.refresh(user)
    return build_token_response(user)


@router.post("/refresh", response_model=TokenResponse)
def refresh_session(payload: RefreshTokenRequest, db: Session = Depends(get_db)) -> TokenResponse:
    try:
        token_payload = decode_refresh_token(payload.refresh_token)
        user_id = int(token_payload["sub"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token") from None

    user = db.get(User, user_id)
    if user is None or not user.active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    return build_token_response(user)


@router.get("/me", response_model=UserRead)
def read_me(current_user: User = Depends(get_current_user)) -> User:
    return current_user
