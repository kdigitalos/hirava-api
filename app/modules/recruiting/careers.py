"""Candidate APIs expose public jobs and records owned by the authenticated candidate."""
from fastapi import Depends, HTTPException, Query, Request
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.models import User
from app.core.routing import APIRouter
from app.core.schemas import Decision, Input
from app.core.security import hash_password, issue_token, require
from app.core.service import audit, find, rows, state_is
from app.data.database import get_db, utcnow
from app.modules.offers.service import candidate_accept_offer, candidate_offers
from app.modules.recruiting.models import Application, Candidate, Requisition, JobReference
from app.modules.recruiting.schemas import CandidateCreate

router = APIRouter(prefix="/careers", tags=["candidate self-service"])
from app.modules.recruiting.public_intake import submit_public, staff_resume
router.add_api_route("/jobs/{alias}/apply", submit_public, methods=["POST"])
router.add_api_route("/resumes/{receipt}", staff_resume, methods=["GET"])
candidate_role = require("candidate", module="rms")


class CandidateRegistration(CandidateCreate):
    password: str = Field(min_length=12, max_length=128)


class Apply(Input):
    requisition_id: str


def require_rms(request: Request):
    if not request.app.state.settings.rms_enabled:
        raise HTTPException(404, "Careers unavailable")


def own_candidate(db, user):
    record = db.scalar(select(Candidate).where(Candidate.customer_id == user.customer_id, Candidate.email == user.email))
    if not record:
        raise HTTPException(404, "Create your candidate profile first")
    return record


@router.get("/jobs", dependencies=[Depends(require_rms)])
def public_jobs(request: Request, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), db: Session = Depends(get_db)):
    records = rows(db, Requisition, request.app.state.settings.customer_id, offset, limit, Requisition.status == "published")
    return [{"id": row.id, "title": row.title, "description": row.description} for row in records]


@router.get("/jobs/{alias}", dependencies=[Depends(require_rms)])
def public_job(alias: int, request: Request, db: Session = Depends(get_db)):
    record = db.scalar(select(Requisition).join(JobReference, JobReference.requisition_id == Requisition.id)
        .where(JobReference.id == alias, Requisition.customer_id == request.app.state.settings.customer_id,
               Requisition.status == "published"))
    if not record:
        raise HTTPException(404, "This job is not available for applications")
    details = record.job_details or {}
    return {"id": record.id, "title": record.title, "description": record.description,
            "company": details.get("company_name", ""), "location": details.get("location", "")}


@router.post("/register", status_code=201, dependencies=[Depends(require_rms)])
def register(body: CandidateRegistration, request: Request, db: Session = Depends(get_db)):
    settings = request.app.state.settings
    if settings.auth_mode != "local" or settings.environment not in {"local", "test"}:
        raise HTTPException(404, "Candidate registration is managed by Auth0")
    email = str(body.email).lower()
    if db.scalar(select(Candidate.id).where(Candidate.customer_id == settings.customer_id, Candidate.email == email)):
        raise HTTPException(409, "Existing profile requires account provisioning by an administrator")
    user = User(customer_id=settings.customer_id, email=email, name=body.name, role="candidate", password_hash=hash_password(body.password))
    db.add(user)
    db.flush()
    candidate = Candidate(customer_id=settings.customer_id, name=body.name, email=email, consent_at=utcnow(), consent_notice=body.consent_notice)
    db.add(candidate)
    audit(db, user, "candidate.self_registered", candidate, request)
    return {"access_token": issue_token(user, settings), "token_type": "bearer", "expires_in": settings.token_minutes * 60}


@router.post("/profile", status_code=201)
def candidate_profile(body: CandidateCreate, request: Request, user=Depends(candidate_role), db: Session = Depends(get_db)):
    if str(body.email).lower() != user.email:
        raise HTTPException(422, "Use your authenticated account email")
    record = Candidate(customer_id=user.customer_id, name=body.name, email=user.email, consent_at=utcnow(), consent_notice=body.consent_notice)
    db.add(record)
    audit(db, user, "candidate.profile_created", record, request)
    return {"name": record.name, "email": record.email}


@router.get("/profile")
def profile(user=Depends(candidate_role), db: Session = Depends(get_db)):
    record = own_candidate(db, user)
    return {"name": record.name, "email": record.email, "consent_notice": record.consent_notice}


@router.post("/applications", status_code=201)
def apply(body: Apply, request: Request, user=Depends(candidate_role), db: Session = Depends(get_db)):
    candidate = own_candidate(db, user)
    requisition = find(db, Requisition, body.requisition_id, user.customer_id, lock=True)
    state_is(requisition, "published")
    record = Application(customer_id=user.customer_id, candidate_id=candidate.id, requisition_id=requisition.id)
    db.add(record)
    audit(db, user, "application.self_submitted", record, request)
    return {"id": record.id, "requisition_id": record.requisition_id, "status": record.status}


@router.get("/applications")
def own_applications(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
                     user=Depends(candidate_role), db: Session = Depends(get_db)):
    candidate = own_candidate(db, user)
    return [{"id": row.id, "requisition_id": row.requisition_id, "status": row.status}
            for row in rows(db, Application, user.customer_id, offset, limit, Application.candidate_id == candidate.id)]


@router.post("/applications/{record_id}/withdraw")
def withdraw(record_id: str, body: Decision, request: Request, user=Depends(candidate_role), db: Session = Depends(get_db)):
    candidate = own_candidate(db, user)
    record = find(db, Application, record_id, user.customer_id, lock=True)
    if record.candidate_id != candidate.id:
        raise HTTPException(404, "Application not found")
    state_is(record, "applied", "screening", "interviewing")
    record.status, record.disposition_reason = "withdrawn", body.reason
    audit(db, user, "application.self_withdrawn", record, request)
    return {"id": record.id, "status": record.status}


@router.get("/offers")
def own_offers(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
               user=Depends(candidate_role), db: Session = Depends(get_db)):
    candidate = own_candidate(db, user)
    ids = select(Application.id).where(Application.candidate_id == candidate.id, Application.customer_id == user.customer_id)
    return candidate_offers(db, ids, user.customer_id, offset, limit)


@router.post("/offers/{record_id}/accept")
def accept_own_offer(record_id: str, body: Decision, request: Request, user=Depends(candidate_role), db: Session = Depends(get_db)):
    candidate = own_candidate(db, user)
    ids = select(Application.id).where(Application.candidate_id == candidate.id, Application.customer_id == user.customer_id)
    return candidate_accept_offer(db, record_id, ids, user, body.reason, request)
