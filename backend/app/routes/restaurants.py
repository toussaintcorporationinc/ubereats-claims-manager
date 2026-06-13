from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import ensure_can_access_restaurant, get_accessible_restaurant_ids, get_current_user, require_owner
from app.core.database import get_db
from app.models import Restaurant, User
from app.schemas.domain import RestaurantCreate, RestaurantRead, RestaurantUpdate
from app.services.audit import add_audit_log

router = APIRouter(prefix="/v1/restaurants", tags=["restaurants"])


def _normalise_restaurant_values(values: dict) -> dict:
    normalised = dict(values)
    for field in ("name", "legal_name", "address", "phone_number", "sender_email", "uber_merchant_id"):
        if field in normalised and isinstance(normalised[field], str):
            value = normalised[field].strip()
            normalised[field] = value or None
    if normalised.get("name") is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Restaurant name is required")
    if normalised.get("sender_email") is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Sender email is required")
    if isinstance(normalised.get("sender_email"), str):
        normalised["sender_email"] = normalised["sender_email"].lower()
    return normalised


def _restaurant_audit_value(restaurant: Restaurant) -> dict:
    return {
        "name": restaurant.name,
        "legal_name": restaurant.legal_name,
        "address": restaurant.address,
        "phone_number": restaurant.phone_number,
        "sender_email": restaurant.sender_email,
        "uber_merchant_id": restaurant.uber_merchant_id,
        "active": restaurant.active,
        "autopilot_enabled": restaurant.autopilot_enabled,
    }


@router.get("", response_model=list[RestaurantRead])
def list_restaurants(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Restaurant]:
    statement = select(Restaurant).order_by(Restaurant.id)
    accessible_ids = get_accessible_restaurant_ids(db, current_user)
    if accessible_ids is not None:
        if not accessible_ids:
            return []
        statement = statement.where(Restaurant.id.in_(accessible_ids))
    return list(db.scalars(statement).all())


@router.post("", response_model=RestaurantRead, status_code=status.HTTP_201_CREATED)
def create_restaurant(
    payload: RestaurantCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner),
) -> Restaurant:
    restaurant = Restaurant(**_normalise_restaurant_values(payload.model_dump()))
    db.add(restaurant)
    db.flush()
    add_audit_log(
        db,
        entity_type="restaurant",
        entity_id=restaurant.id,
        action="restaurant.created",
        user_id=current_user.id,
        new_value=_restaurant_audit_value(restaurant),
    )
    db.commit()
    db.refresh(restaurant)
    return restaurant


@router.get("/{restaurant_id}", response_model=RestaurantRead)
def get_restaurant(
    restaurant_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Restaurant:
    restaurant = db.get(Restaurant, restaurant_id)
    if restaurant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")
    ensure_can_access_restaurant(db, current_user, restaurant.id)
    return restaurant


@router.patch("/{restaurant_id}", response_model=RestaurantRead)
def update_restaurant(
    restaurant_id: int,
    payload: RestaurantUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner),
) -> Restaurant:
    restaurant = db.get(Restaurant, restaurant_id)
    if restaurant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")

    old_value = _restaurant_audit_value(restaurant)
    values = _normalise_restaurant_values({**old_value, **payload.model_dump(exclude_unset=True)})

    for field, value in values.items():
        setattr(restaurant, field, value)

    add_audit_log(
        db,
        entity_type="restaurant",
        entity_id=restaurant.id,
        action="restaurant.updated",
        old_value=old_value,
        new_value=_restaurant_audit_value(restaurant),
        user_id=current_user.id,
    )
    db.commit()
    db.refresh(restaurant)
    return restaurant

