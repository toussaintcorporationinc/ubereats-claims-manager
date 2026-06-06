from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Restaurant
from app.schemas.domain import RestaurantCreate, RestaurantRead, RestaurantUpdate
from app.services.audit import add_audit_log

router = APIRouter(prefix="/v1/restaurants", tags=["restaurants"])


@router.get("", response_model=list[RestaurantRead])
def list_restaurants(db: Session = Depends(get_db)) -> list[Restaurant]:
    return list(db.scalars(select(Restaurant).order_by(Restaurant.id)).all())


@router.post("", response_model=RestaurantRead, status_code=status.HTTP_201_CREATED)
def create_restaurant(payload: RestaurantCreate, db: Session = Depends(get_db)) -> Restaurant:
    restaurant = Restaurant(**payload.model_dump())
    db.add(restaurant)
    db.flush()
    add_audit_log(
        db,
        entity_type="restaurant",
        entity_id=restaurant.id,
        action="restaurant.created",
        new_value={"name": restaurant.name, "sender_email": restaurant.sender_email},
    )
    db.commit()
    db.refresh(restaurant)
    return restaurant


@router.get("/{restaurant_id}", response_model=RestaurantRead)
def get_restaurant(restaurant_id: int, db: Session = Depends(get_db)) -> Restaurant:
    restaurant = db.get(Restaurant, restaurant_id)
    if restaurant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")
    return restaurant


@router.patch("/{restaurant_id}", response_model=RestaurantRead)
def update_restaurant(
    restaurant_id: int,
    payload: RestaurantUpdate,
    db: Session = Depends(get_db),
) -> Restaurant:
    restaurant = db.get(Restaurant, restaurant_id)
    if restaurant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(restaurant, field, value)

    db.commit()
    db.refresh(restaurant)
    return restaurant

