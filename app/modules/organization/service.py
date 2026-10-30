from fastapi import HTTPException
from sqlalchemy import update
from app.core.models import User
from app.core.service import find
from app.modules.organization.models import Position


def position_reference(db, position_id, customer_id):
    return find(db, Position, position_id, customer_id)


def reserve_position(db, position_id, customer_id):
    position = position_reference(db, position_id, customer_id)
    changed = db.execute(update(Position).where(Position.id == position_id, Position.customer_id == customer_id,
                         Position.occupied < Position.capacity).values(occupied=Position.occupied + 1,
                         version=Position.version + 1).execution_options(synchronize_session=False)).rowcount
    if changed != 1:
        raise HTTPException(409, "Position has no available headcount")
    db.refresh(position)
    return position


def release_position(db, position_id, customer_id):
    changed = db.execute(update(Position).where(Position.id == position_id, Position.customer_id == customer_id,
                         Position.occupied > 0).values(occupied=Position.occupied - 1,
                         version=Position.version + 1).execution_options(synchronize_session=False)).rowcount
    if changed != 1:
        raise HTTPException(409, "Position occupancy requires reconciliation")


def manager_reference(db, manager_id, customer_id):
    if manager_id:
        manager = find(db, User, manager_id, customer_id)
        if manager.role not in {"manager", "hr", "admin"} or not manager.active:
            raise HTTPException(422, "Manager must be an active manager, HR user, or administrator")
