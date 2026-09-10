from datetime import date, timedelta
from app.core.routing import APIRouter
from fastapi import Depends, HTTPException, Query, Request
from pydantic import Field, model_validator
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from app.core.schemas import Decision, Input
from app.core.security import require
from app.core.service import audit, find, rows, state_is, view
from app.data.database import get_db
from app.modules.leave.models import LeaveBalance, LeaveRequest, LeaveType
from app.modules.workforce.service import employment_for, visible_worker_ids, worker_access

router = APIRouter(prefix="/hrms/leave", tags=["leave"])
staff = require("hr", "manager", "employee", module="hrms")


class LeaveTypeCreate(Input):
    name: str = Field(min_length=1, max_length=100)


class BalanceGrant(Input):
    worker_id: str
    leave_type_id: str
    year: int = Field(ge=2000, le=2200)
    granted: int = Field(ge=0, le=366)


class LeaveCreate(Input):
    worker_id: str
    leave_type_id: str
    start_date: date
    end_date: date
    reason: str = Field(min_length=3, max_length=2000)

    @model_validator(mode="after")
    def dates_valid(self):
        if self.end_date < self.start_date or self.start_date.year != self.end_date.year:
            raise ValueError("Use an ordered date range within one leave year")
        return self


@router.post("/types", status_code=201)
def create_type(body: LeaveTypeCreate, request: Request, user=Depends(require("hr", module="hrms")), db: Session = Depends(get_db)):
    record = LeaveType(customer_id=user.customer_id, name=body.name)
    db.add(record)
    audit(db, user, "leave_type.created", record, request)
    return view(record)


@router.get("/types")
def types(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), user=Depends(staff), db: Session = Depends(get_db)):
    return [view(row) for row in rows(db, LeaveType, user.customer_id, offset, limit)]


@router.post("/balances", status_code=201)
def grant_balance(body: BalanceGrant, request: Request, user=Depends(require("hr", module="hrms")), db: Session = Depends(get_db)):
    worker_access(db, body.worker_id, user)
    find(db, LeaveType, body.leave_type_id, user.customer_id)
    record = LeaveBalance(customer_id=user.customer_id, **body.model_dump())
    db.add(record)
    audit(db, user, "leave_balance.granted", record, request)
    return view(record)


@router.get("/balances")
def balances(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), user=Depends(staff), db: Session = Depends(get_db)):
    return [view(row) for row in rows(db, LeaveBalance, user.customer_id, offset, limit,
                                     LeaveBalance.worker_id.in_(visible_worker_ids(db, user)))]


@router.post("/requests", status_code=201)
def request_leave(body: LeaveCreate, request: Request, user=Depends(staff), db: Session = Depends(get_db)):
    worker = worker_access(db, body.worker_id, user, lock=True)
    if worker.user_id != user.id and user.role not in {"hr", "admin"}:
        raise HTTPException(403, "Submit your own leave request")
    employment = employment_for(db, worker.id, user.customer_id)
    state_is(employment, "active")
    if body.start_date < max(date.today(), employment.start_date):
        raise HTTPException(422, "Leave cannot precede today or employment commencement")
    find(db, LeaveType, body.leave_type_id, user.customer_id)
    overlap = db.scalar(select(LeaveRequest.id).where(LeaveRequest.worker_id == worker.id,
                        LeaveRequest.status.in_(["pending", "approved"]), LeaveRequest.start_date <= body.end_date,
                        LeaveRequest.end_date >= body.start_date))
    if overlap:
        raise HTTPException(409, "Leave overlaps an existing pending or approved request")
    days = sum((body.start_date + timedelta(days=i)).weekday() < 5 for i in range((body.end_date - body.start_date).days + 1))
    if not days:
        raise HTTPException(422, "Range contains no Monday-Friday working days")
    record = LeaveRequest(customer_id=user.customer_id, days=days, **body.model_dump())
    db.add(record)
    audit(db, user, "leave.requested", record, request)
    return view(record)


@router.get("/requests")
def requests(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), user=Depends(staff), db: Session = Depends(get_db)):
    return [view(row) for row in rows(db, LeaveRequest, user.customer_id, offset, limit,
                                     LeaveRequest.worker_id.in_(visible_worker_ids(db, user)))]


def decide(db, user, record_id, reason, approve, request):
    record = find(db, LeaveRequest, record_id, user.customer_id, lock=True)
    worker = worker_access(db, record.worker_id, user, allow_self=False, lock=True)
    if worker.user_id == user.id:
        raise HTTPException(403, "Self-approval is not allowed")
    state_is(record, "pending")
    if approve:
        state_is(employment_for(db, record.worker_id, user.customer_id), "active")
        updated = db.execute(update(LeaveBalance).where(LeaveBalance.worker_id == record.worker_id,
            LeaveBalance.customer_id == user.customer_id, LeaveBalance.leave_type_id == record.leave_type_id,
            LeaveBalance.year == record.start_date.year, LeaveBalance.used + record.days <= LeaveBalance.granted
        ).values(used=LeaveBalance.used + record.days, version=LeaveBalance.version + 1)).rowcount
        if updated != 1:
            raise HTTPException(409, "Insufficient granted leave balance")
    record.status, record.decided_by, record.decision_reason = "approved" if approve else "rejected", user.id, reason
    audit(db, user, f"leave.{record.status}", record, request)
    return view(record)


@router.post("/requests/{record_id}/approve")
def approve_leave(record_id: str, body: Decision, request: Request,
                  user=Depends(require("hr", "manager", module="hrms")), db: Session = Depends(get_db)):
    return decide(db, user, record_id, body.reason, True, request)


@router.post("/requests/{record_id}/reject")
def reject_leave(record_id: str, body: Decision, request: Request,
                 user=Depends(require("hr", "manager", module="hrms")), db: Session = Depends(get_db)):
    return decide(db, user, record_id, body.reason, False, request)


@router.post("/requests/{record_id}/cancel")
def cancel_leave(record_id: str, body: Decision, request: Request, user=Depends(staff), db: Session = Depends(get_db)):
    record = find(db, LeaveRequest, record_id, user.customer_id, lock=True)
    worker = worker_access(db, record.worker_id, user, lock=True)
    if worker.user_id != user.id and user.role not in {"hr", "admin"}:
        raise HTTPException(403, "Only the requester or HR may cancel")
    state_is(record, "pending", "approved")
    if record.start_date <= date.today() and record.status == "approved":
        raise HTTPException(409, "Started leave requires an HR reconciliation workflow")
    if record.status == "approved":
        updated = db.execute(update(LeaveBalance).where(LeaveBalance.worker_id == record.worker_id,
            LeaveBalance.customer_id == user.customer_id, LeaveBalance.leave_type_id == record.leave_type_id,
            LeaveBalance.year == record.start_date.year, LeaveBalance.used >= record.days
        ).values(used=LeaveBalance.used - record.days, version=LeaveBalance.version + 1)).rowcount
        if updated != 1:
            raise HTTPException(409, "Leave balance requires reconciliation")
    record.status = "cancelled"
    audit(db, user, "leave.cancelled", record, request, reason=body.reason)
    return view(record)
