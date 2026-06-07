from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import require_owner
from app.core.database import get_db
from app.core.security import hash_password
from app.models import Restaurant, User, UserRestaurantAccess
from app.routes.auth import normalize_email
from app.schemas.domain import (
    UserCreate,
    UserRead,
    UserRestaurantAccessCreate,
    UserRestaurantAccessRead,
    UserUpdate,
)
from app.services.audit import add_audit_log

router = APIRouter(prefix="/v1/users", tags=["users"])


def get_user_or_404(user_id: int, db: Session) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


def ensure_restaurant_exists(restaurant_id: int, db: Session) -> None:
    if db.get(Restaurant, restaurant_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")


@router.get("", response_model=list[UserRead])
def list_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner),
) -> list[User]:
    return list(db.scalars(select(User).order_by(User.id)).all())


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner),
) -> User:
    user = User(
        email=normalize_email(payload.email),
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        role=payload.role,
        active=payload.active,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User email already exists") from exc

    add_audit_log(
        db,
        entity_type="user",
        entity_id=user.id,
        action="user.created",
        user_id=current_user.id,
        new_value={"email": user.email, "role": user.role, "active": user.active},
    )
    db.commit()
    db.refresh(user)
    return user


@router.get("/{user_id}", response_model=UserRead)
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner),
) -> User:
    return get_user_or_404(user_id, db)


@router.patch("/{user_id}", response_model=UserRead)
def update_user(
    user_id: int,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner),
) -> User:
    user = get_user_or_404(user_id, db)
    old_value = {"email": user.email, "role": user.role, "active": user.active, "full_name": user.full_name}

    updates = payload.model_dump(exclude_unset=True)
    if "email" in updates and updates["email"] is not None:
        user.email = normalize_email(updates["email"])
    if "password" in updates and updates["password"] is not None:
        user.hashed_password = hash_password(updates["password"])
    if "full_name" in updates:
        user.full_name = updates["full_name"]
    if "role" in updates and updates["role"] is not None:
        user.role = updates["role"]
    if "active" in updates and updates["active"] is not None:
        user.active = updates["active"]

    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User email already exists") from exc

    add_audit_log(
        db,
        entity_type="user",
        entity_id=user.id,
        action="user.updated",
        user_id=current_user.id,
        old_value=old_value,
        new_value={"email": user.email, "role": user.role, "active": user.active, "full_name": user.full_name},
    )
    db.commit()
    db.refresh(user)
    return user


@router.post("/{user_id}/restaurants", response_model=UserRestaurantAccessRead, status_code=status.HTTP_201_CREATED)
def assign_restaurant_access(
    user_id: int,
    payload: UserRestaurantAccessCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner),
) -> UserRestaurantAccess:
    get_user_or_404(user_id, db)
    ensure_restaurant_exists(payload.restaurant_id, db)

    existing_access = db.scalar(
        select(UserRestaurantAccess).where(
            UserRestaurantAccess.user_id == user_id,
            UserRestaurantAccess.restaurant_id == payload.restaurant_id,
        )
    )
    if existing_access is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Restaurant access already exists")

    access = UserRestaurantAccess(user_id=user_id, restaurant_id=payload.restaurant_id)
    db.add(access)
    db.flush()
    add_audit_log(
        db,
        entity_type="user_restaurant_access",
        entity_id=access.id,
        action="user_restaurant_access.created",
        user_id=current_user.id,
        new_value={"user_id": user_id, "restaurant_id": payload.restaurant_id},
    )
    db.commit()
    db.refresh(access)
    return access


@router.delete("/{user_id}/restaurants/{restaurant_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_restaurant_access(
    user_id: int,
    restaurant_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner),
) -> Response:
    access = db.scalar(
        select(UserRestaurantAccess).where(
            UserRestaurantAccess.user_id == user_id,
            UserRestaurantAccess.restaurant_id == restaurant_id,
        )
    )
    if access is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant access not found")

    access_id = access.id
    db.delete(access)
    add_audit_log(
        db,
        entity_type="user_restaurant_access",
        entity_id=access_id,
        action="user_restaurant_access.deleted",
        user_id=current_user.id,
        old_value={"user_id": user_id, "restaurant_id": restaurant_id},
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
