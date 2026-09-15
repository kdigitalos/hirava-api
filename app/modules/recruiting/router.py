from app.core.routing import APIRouter
from fastapi import Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import or_, select
from app.core.models import User
from app.core.schemas import Decision
from app.core.security import require
from app.core.service import audit, find, rows, state_is, view
from app.data.database import get_db, utcnow
from app.modules.organization.service import position_reference
from app.modules.recruiting.models import Application, Candidate, JobReference, Requisition
from app.modules.recruiting.schemas import ApplicationCreate, ApplicationTransition, CandidateCreate, RequisitionCreate, RequisitionUpdate

router = APIRouter(prefix="/rms", tags=["recruiting"])
recruiter = require("recruiter", module="rms")


@router.get("/recruiters")
def recruiter_options(user=Depends(require("recruiter", "hr", "manager", module="rms")), db: Session = Depends(get_db)):
    return [{"id": row.id, "name": row.name} for row in db.scalars(select(User).where(
        User.customer_id == user.customer_id, User.active.is_(True), User.role.in_(["recruiter", "admin"]))).all()]


@router.get("/job-aliases/{legacy_id}")
def resolve_job_alias(legacy_id: int, user=Depends(require("recruiter", "hr", "manager", module="rms")), db: Session = Depends(get_db)):
    ref = db.get(JobReference, legacy_id)
    if ref is None:
        raise HTTPException(404, "Record not found")
    return job_view(db, scoped_requisition(db, ref.requisition_id, user))


def job_view(db, record):
    result = view(record)
    result['legacy_id'] = db.scalar(select(JobReference.id).where(JobReference.requisition_id == record.id))
    return result


def validate_job_details(db, details, position, user):
    if details.no_of_openings > position.capacity:
        raise HTTPException(422, "Openings exceed the linked position capacity")
    if details.recruiter_id:
        assigned = find(db, User, details.recruiter_id, user.customer_id)
        if not assigned.active or assigned.role not in {"recruiter", "admin"}:
            raise HTTPException(422, "Assigned recruiter must be an active recruiter or administrator")


def scoped_requisition(db, record_id, user, *, lock=False):
    record = find(db, Requisition, record_id, user.customer_id, lock=lock)
    if user.role == "manager" and record.requested_by != user.id:
        raise HTTPException(404, "Record not found")
    return record


@router.post("/requisitions", status_code=201)
def create_requisition(body: RequisitionCreate, request: Request,
                       user=Depends(require("recruiter", "manager", module="rms")), db: Session = Depends(get_db)):
    position = position_reference(db, body.position_id, user.customer_id)
    if user.role == "manager" and position.manager_id != user.id:
        raise HTTPException(403, "Managers can request only their own positions")
    validate_job_details(db, body.job_details, position, user)
    record = Requisition(customer_id=user.customer_id, requested_by=user.id, **body.model_dump(mode="json"))
    db.add(record)
    audit(db, user, "requisition.created", record, request)
    db.add(JobReference(requisition_id=record.id))
    db.flush()
    return job_view(db, record)


@router.get("/requisitions")
def list_requisitions(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
                      search: str = Query("", max_length=200), status: str | None = Query(None, max_length=30),
                      user=Depends(require("recruiter", "hr", "manager", module="rms")), db: Session = Depends(get_db)):
    conditions = [Requisition.requested_by == user.id] if user.role == "manager" else []
    if search.strip():
        conditions.append(or_(Requisition.title.icontains(search.strip(), autoescape=True),
                              Requisition.description.icontains(search.strip(), autoescape=True)))
    if status:
        conditions.append(Requisition.status == status)
    return [job_view(db, row) for row in rows(db, Requisition, user.customer_id, offset, limit, *conditions)]


@router.get("/requisitions/{record_id}")
def get_requisition(record_id: str, user=Depends(require("recruiter", "hr", "manager", module="rms")),
                    db: Session = Depends(get_db)):
    return job_view(db, scoped_requisition(db, record_id, user))


@router.patch("/requisitions/{record_id}")
def edit_requisition(record_id: str, body: RequisitionUpdate, request: Request,
                     user=Depends(require("recruiter", "manager", module="rms")), db: Session = Depends(get_db)):
    record = scoped_requisition(db, record_id, user, lock=True)
    state_is(record, "draft")
    if record.version != body.expected_version:
        raise HTTPException(409, "Record changed; reload before editing")
    changes = body.model_dump(mode="json", exclude_unset=True, exclude={"expected_version"})
    if body.job_details is not None:
        position = position_reference(db, record.position_id, user.customer_id)
        validate_job_details(db, body.job_details, position, user)
        # Whole-object replacement is explicit; omitted details leave them intact.
        changes['job_details'] = body.job_details.model_dump(mode="json")
    for field, value in changes.items():
        setattr(record, field, value)
    audit(db, user, "requisition.updated", record, request, fields=sorted(changes))
    return job_view(db, record)


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
