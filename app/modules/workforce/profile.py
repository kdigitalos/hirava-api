from fastapi import Depends, HTTPException, Query, Request
from pydantic import Field
from sqlalchemy.orm import Session
from app.core.routing import APIRouter
from app.core.schemas import Decision, Input
from app.core.security import require
from app.core.service import audit, find, rows, state_is, view
from app.data.database import get_db
from app.modules.workforce.models import ProfileChange
from app.modules.workforce.service import worker_access

router = APIRouter(prefix="/hrms/profile-changes", tags=["employee self-service"])


class ChangeRequest(Input):
    worker_id: str
    proposed_name: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=3, max_length=2000)


@router.post("", status_code=201)
def request_change(body: ChangeRequest, request: Request,
                   user=Depends(require("employee", "manager", "hr", module="hrms")), db: Session = Depends(get_db)):
    worker = worker_access(db, body.worker_id, user)
    if worker.user_id != user.id:
        raise HTTPException(403, "Request changes only to your own profile")
    record = ProfileChange(customer_id=user.customer_id, requested_by=user.id, **body.model_dump())
    db.add(record)
    audit(db, user, "profile_change.requested", record, request)
    return view(record)


@router.get("")
def changes(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
            user=Depends(require("employee", "manager", "hr", module="hrms")), db: Session = Depends(get_db)):
    conditions = [] if user.role in {"admin", "hr"} else [ProfileChange.requested_by == user.id]
    return [view(row) for row in rows(db, ProfileChange, user.customer_id, offset, limit, *conditions)]


@router.post("/{record_id}/approve")
def approve_change(record_id: str, body: Decision, request: Request,
                   user=Depends(require("hr", module="hrms")), db: Session = Depends(get_db)):
    record = find(db, ProfileChange, record_id, user.customer_id, lock=True)
    state_is(record, "pending")
    if record.requested_by == user.id:
        raise HTTPException(403, "A different HR approver must review the request")
    worker = worker_access(db, record.worker_id, user, lock=True)
    worker.name = record.proposed_name
    record.status, record.decided_by = "approved", user.id
    audit(db, user, "profile_change.approved", record, request, reason=body.reason)
    return view(record)


@router.post("/{record_id}/reject")
def reject_change(record_id: str, body: Decision, request: Request,
                  user=Depends(require("hr", module="hrms")), db: Session = Depends(get_db)):
    record = find(db, ProfileChange, record_id, user.customer_id, lock=True)
    state_is(record, "pending")
    if record.requested_by == user.id:
        raise HTTPException(403, "A different HR approver must review the request")
    record.status, record.decided_by = "rejected", user.id
    audit(db, user, "profile_change.rejected", record, request, reason=body.reason)
    return view(record)
