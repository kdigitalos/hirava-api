from typing import Literal
from app.core.routing import APIRouter
from fastapi import Depends, HTTPException, Query, Request
from pydantic import Field
from sqlalchemy.orm import Session
from app.core.models import User
from app.core.schemas import Input
from app.core.security import require
from app.core.service import audit, find, rows, view
from app.data.database import get_db
from app.modules.hr_service.models import CaseNote, HRCase

router = APIRouter(prefix="/hrms/cases", tags=["HR service"])


class CaseCreate(Input):
    subject: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=3, max_length=20000)


class CaseUpdate(Input):
    status: Literal["open", "in_progress", "resolved"]
    assigned_to: str | None = None


class NoteCreate(Input):
    content: str = Field(min_length=1, max_length=10000)


@router.post("", status_code=201)
def create_case(body: CaseCreate, request: Request,
                user=Depends(require("hr", "manager", "employee", module="hrms")), db: Session = Depends(get_db)):
    record = HRCase(customer_id=user.customer_id, requester_id=user.id, **body.model_dump())
    db.add(record)
    audit(db, user, "hr_case.created", record, request)
    return view(record)


@router.get("")
def cases(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
          user=Depends(require("hr", "manager", "employee", module="hrms")), db: Session = Depends(get_db)):
    conditions = [] if user.role in {"hr", "admin"} else [HRCase.requester_id == user.id]
    return [view(row) for row in rows(db, HRCase, user.customer_id, offset, limit, *conditions)]


@router.patch("/{record_id}")
def update_case(record_id: str, body: CaseUpdate, request: Request,
                user=Depends(require("hr", module="hrms")), db: Session = Depends(get_db)):
    record = find(db, HRCase, record_id, user.customer_id, lock=True)
    if body.assigned_to:
        owner = find(db, User, body.assigned_to, user.customer_id)
        if not owner.active or owner.role not in {"hr", "admin"}:
            raise HTTPException(422, "Case owner must be active HR or admin")
    record.status, record.assigned_to = body.status, body.assigned_to
    audit(db, user, "hr_case.updated", record, request)
    return view(record)


@router.post("/{record_id}/notes", status_code=201)
def add_note(record_id: str, body: NoteCreate, request: Request,
             user=Depends(require("hr", module="hrms")), db: Session = Depends(get_db)):
    find(db, HRCase, record_id, user.customer_id)
    record = CaseNote(customer_id=user.customer_id, case_id=record_id, author_id=user.id, content=body.content)
    db.add(record)
    audit(db, user, "hr_case.restricted_note_added", record, request)
    return view(record)


@router.get("/{record_id}/notes")
def notes(record_id: str, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
          user=Depends(require("hr", module="hrms")), db: Session = Depends(get_db)):
    find(db, HRCase, record_id, user.customer_id)
    return [view(row) for row in rows(db, CaseNote, user.customer_id, offset, limit, CaseNote.case_id == record_id)]
