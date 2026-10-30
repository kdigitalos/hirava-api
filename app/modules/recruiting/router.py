from app.core.routing import APIRouter
from fastapi import Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from app.core.schemas import Decision
from app.core.security import require
from app.core.service import audit, find, rows, state_is, view
from app.data.database import get_db, utcnow
from app.modules.organization.service import position_reference
from app.modules.recruiting.models import Application, Candidate, Requisition
from app.modules.recruiting.schemas import ApplicationCreate, ApplicationTransition, CandidateCreate, RequisitionCreate

router = APIRouter(prefix="/rms", tags=["recruiting"])
recruiter = require("recruiter", module="rms")


@router.post("/requisitions", status_code=201)
def create_requisition(body: RequisitionCreate, request: Request,
                       user=Depends(require("recruiter", "manager", module="rms")), db: Session = Depends(get_db)):
    position = position_reference(db, body.position_id, user.customer_id)
    if user.role == "manager" and position.manager_id != user.id:
        raise HTTPException(403, "Managers can request only their own positions")
    record = Requisition(customer_id=user.customer_id, requested_by=user.id, **body.model_dump())
    db.add(record)
    audit(db, user, "requisition.created", record, request)
    return view(record)


@router.get("/requisitions")
def list_requisitions(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
                      user=Depends(require("recruiter", "hr", "manager", module="rms")), db: Session = Depends(get_db)):
    conditions = [Requisition.requested_by == user.id] if user.role == "manager" else []
    return [view(row) for row in rows(db, Requisition, user.customer_id, offset, limit, *conditions)]


@router.post("/requisitions/{record_id}/submit")
def submit_requisition(record_id: str, request: Request, user=Depends(require("recruiter", "manager", module="rms")),
                       db: Session = Depends(get_db)):
    record = find(db, Requisition, record_id, user.customer_id, lock=True)
    if user.role == "manager" and record.requested_by != user.id:
        raise HTTPException(404, "Record not found")
    state_is(record, "draft")
    record.status = "submitted"
    audit(db, user, "requisition.submitted", record, request)
    return view(record)


@router.post("/requisitions/{record_id}/approve")
def approve_requisition(record_id: str, body: Decision, request: Request,
                        user=Depends(require("hr", module="rms")), db: Session = Depends(get_db)):
    record = find(db, Requisition, record_id, user.customer_id, lock=True)
    state_is(record, "submitted")
    if record.requested_by == user.id:
        raise HTTPException(403, "A different approver must approve the requisition")
    record.status, record.approved_by = "approved", user.id
    audit(db, user, "requisition.approved", record, request, reason=body.reason)
    return view(record)


@router.post("/requisitions/{record_id}/publish")
def publish_requisition(record_id: str, request: Request, user=Depends(recruiter), db: Session = Depends(get_db)):
    record = find(db, Requisition, record_id, user.customer_id, lock=True)
    state_is(record, "approved")
    record.status = "published"
    audit(db, user, "requisition.published", record, request)
    return view(record)


@router.post("/requisitions/{record_id}/close")
def close_requisition(record_id: str, body: Decision, request: Request, user=Depends(recruiter), db: Session = Depends(get_db)):
    record = find(db, Requisition, record_id, user.customer_id, lock=True)
    state_is(record, "approved", "published")
    record.status = "closed"
    audit(db, user, "requisition.closed", record, request, reason=body.reason)
    return view(record)


@router.post("/candidates", status_code=201)
def create_candidate(body: CandidateCreate, request: Request, user=Depends(recruiter), db: Session = Depends(get_db)):
    record = Candidate(customer_id=user.customer_id, name=body.name, email=str(body.email).lower(),
                       consent_at=utcnow(), consent_notice=body.consent_notice)
    db.add(record)
    audit(db, user, "candidate.created", record, request)
    return view(record)


@router.get("/candidates")
def candidates(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
               user=Depends(recruiter), db: Session = Depends(get_db)):
    return [view(row) for row in rows(db, Candidate, user.customer_id, offset, limit)]


@router.post("/applications", status_code=201)
def create_application(body: ApplicationCreate, request: Request, user=Depends(recruiter), db: Session = Depends(get_db)):
    find(db, Candidate, body.candidate_id, user.customer_id)
    requisition = find(db, Requisition, body.requisition_id, user.customer_id, lock=True)
    state_is(requisition, "published")
    record = Application(customer_id=user.customer_id, **body.model_dump())
    db.add(record)
    audit(db, user, "application.created", record, request)
    return view(record)


@router.get("/applications")
def applications(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
                 user=Depends(recruiter), db: Session = Depends(get_db)):
    return [view(row) for row in rows(db, Application, user.customer_id, offset, limit)]


@router.post("/applications/{record_id}/transition")
def transition_application(record_id: str, body: ApplicationTransition, request: Request,
                           user=Depends(recruiter), db: Session = Depends(get_db)):
    record = find(db, Application, record_id, user.customer_id, lock=True)
    allowed = {"applied": {"screening", "rejected", "withdrawn"},
               "screening": {"interviewing", "rejected", "withdrawn"},
               "interviewing": {"selected", "rejected", "withdrawn"}}
    if body.status not in allowed.get(record.status, set()):
        raise HTTPException(409, "Invalid application transition")
    record.status, record.disposition_reason = body.status, body.reason
    audit(db, user, "application.transitioned", record, request, status=body.status)
    return view(record)
