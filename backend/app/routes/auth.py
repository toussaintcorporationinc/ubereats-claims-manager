from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.database import get_db
from app.core.security import create_access_token, create_refresh_token, decode_refresh_token, hash_password, verify_password
from app.models import User
from app.schemas.domain import LoginRequest, RefreshTokenRequest, RegisterRequest, TokenResponse, UserRead
from app.services.audit import add_audit_log

router = APIRouter(prefix="/v1/auth", tags=["auth"])


def normalize_email(email: str) -> str:
    return email.strip().lower()


def build_token_response(user: User) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(str(user.id), {"role": user.role}),
        refresh_token=create_refresh_token(str(user.id), {"role": user.role}),
        token_type="bearer",
        user=UserRead.model_validate(user),
    )


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
