from collections.abc import Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models import ClaimOrder, Restaurant, User, UserRestaurantAccess

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/v1/auth/login")


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    try:
        payload = decode_access_token(token)
        user_id = int(payload.get("sub", ""))
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.get(User, user_id)
    if user is None or not user.active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or inactive user",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_roles(*roles: str) -> Callable[[User], User]:
    def dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return current_user

    return dependency


require_owner = require_roles("owner")
require_owner_or_manager = require_roles("owner", "manager")


def get_accessible_restaurant_ids(db: Session, user: User, *, include_inactive: bool = False) -> set[int] | None:
    if user.role == "owner" and include_inactive:
        return None

    if user.role == "owner":
        statement = select(Restaurant.id)
    else:
        statement = select(UserRestaurantAccess.restaurant_id).where(UserRestaurantAccess.user_id == user.id)
        if not include_inactive:
            statement = statement.join(Restaurant, Restaurant.id == UserRestaurantAccess.restaurant_id)

    if not include_inactive:
        statement = statement.where(Restaurant.active.is_(True))

    return set(db.scalars(statement).all())


def can_access_restaurant(db: Session, user: User, restaurant_id: int, *, include_inactive: bool = False) -> bool:
    accessible_ids = get_accessible_restaurant_ids(db, user, include_inactive=include_inactive)
    return accessible_ids is None or restaurant_id in accessible_ids


def ensure_can_access_restaurant(db: Session, user: User, restaurant_id: int, *, include_inactive: bool = False) -> None:
    if not can_access_restaurant(db, user, restaurant_id, include_inactive=include_inactive):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Restaurant access denied")


def ensure_can_access_order(db: Session, user: User, order: ClaimOrder) -> None:
    ensure_can_access_restaurant(db, user, order.restaurant_id)
