from app.core.routing import APIRouter
from fastapi import Depends, Query, Request
from sqlalchemy.orm import Session
from app.core.security import require
from app.core.service import audit, find, rows, view
from app.data.database import get_db
from app.modules.organization.models import OrganizationUnit, Position
from app.modules.organization.schemas import PositionCreate, UnitCreate
from app.modules.organization.service import manager_reference

router = APIRouter(prefix="/organization", tags=["organization"])


@router.post("/units", status_code=201)
def create_unit(body: UnitCreate, request: Request, user=Depends(require("hr")), db: Session = Depends(get_db)):
    if body.parent_id:
        find(db, OrganizationUnit, body.parent_id, user.customer_id)
    record = OrganizationUnit(customer_id=user.customer_id, **body.model_dump())
    db.add(record)
    audit(db, user, "organization.created", record, request)
    return view(record)


@router.get("/units")
def list_units(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
               user=Depends(require("hr", "recruiter", "manager", "employee", "interviewer")), db: Session = Depends(get_db)):
    return [view(row) for row in rows(db, OrganizationUnit, user.customer_id, offset, limit)]


@router.post("/positions", status_code=201)
def create_position(body: PositionCreate, request: Request, user=Depends(require("hr")), db: Session = Depends(get_db)):
    find(db, OrganizationUnit, body.unit_id, user.customer_id)
    manager_reference(db, body.manager_id, user.customer_id)
    record = Position(customer_id=user.customer_id, **body.model_dump())
    db.add(record)
    audit(db, user, "position.created", record, request)
    return view(record)


@router.get("/positions")
def list_positions(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
                   user=Depends(require("hr", "recruiter", "manager")), db: Session = Depends(get_db)):
    return [view(row) for row in rows(db, Position, user.customer_id, offset, limit)]
