from datetime import timezone, timedelta
from app.core.routing import APIRouter
from fastapi import Depends, HTTPException, Query, Request
from pydantic import AwareDatetime, Field
from sqlalchemy import select, or_
from sqlalchemy.orm import Session
from app.core.models import User
from app.core.schemas import Decision, Input
from app.core.security import require
from app.core.service import audit, find, notify, rows, state_is, view
from app.data.database import get_db, utcnow
from app.modules.interviews.models import Interview, Scorecard
from app.modules.recruiting.service import application_reference, interview_packet
from app.modules.recruiting.models import Application, Candidate

router = APIRouter(prefix="/rms/interviews", tags=["interviews"])


class InterviewCreate(Input):
    application_id: str
    interviewer_id: str
    scheduled_at: AwareDatetime
    duration_minutes: int = Field(default=60, ge=15, le=480)


class ScorecardCreate(Input):
    competency: str = Field(min_length=1, max_length=200)
    score: int = Field(ge=1, le=5)
    evidence: str = Field(min_length=3, max_length=10000)


class InterviewReschedule(Input):
    scheduled_at: AwareDatetime
    duration_minutes: int = Field(ge=15, le=480)
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=2000)


def reserve_slot(db, application, interviewer_id, scheduled_at, duration_minutes, customer_id, exclude_id=None):
    # Serialize bookings for a person across applications and for an interviewer.
    find(db, Candidate, application.candidate_id, customer_id, lock=True)
    interviewer = find(db, User, interviewer_id, customer_id, lock=True)
    if not interviewer.active or interviewer.role not in {"interviewer", "manager", "recruiter"}:
        raise HTTPException(422, "An active interviewer, manager, or recruiter is required")
    start = scheduled_at.astimezone(timezone.utc)
    if start <= utcnow():
        raise HTTPException(422, "Interview must be scheduled in the future")
    end = start + timedelta(minutes=duration_minutes)
    matches = db.scalars(select(Interview).join(Application, Interview.application_id == Application.id).where(
        Interview.customer_id == customer_id, Interview.status == "scheduled",
        Interview.scheduled_at < end, Interview.scheduled_at > start - timedelta(minutes=480),
        or_(Interview.interviewer_id == interviewer_id, Application.candidate_id == application.candidate_id))).all()
    for existing in matches:
        if existing.id == exclude_id:
            continue
        existing_start = existing.scheduled_at.replace(tzinfo=timezone.utc) if existing.scheduled_at.tzinfo is None else existing.scheduled_at.astimezone(timezone.utc)
        if existing_start + timedelta(minutes=existing.duration_minutes) > start:
            raise HTTPException(409, "The candidate or interviewer already has an interview in this time slot")
    return start


@router.post("", status_code=201)
def create_interview(body: InterviewCreate, request: Request, user=Depends(require("recruiter", module="rms")), db: Session = Depends(get_db)):
    application = application_reference(db, body.application_id, user.customer_id, lock=True)
    state_is(application, "interviewing")
    fields = body.model_dump()
    fields["scheduled_at"] = reserve_slot(db, application, body.interviewer_id, body.scheduled_at, body.duration_minutes, user.customer_id)
    record = Interview(customer_id=user.customer_id, **fields)
    db.add(record)
    audit(db, user, "interview.scheduled", record, request)
    notify(db, user, body.interviewer_id, "An interview has been assigned to you")
    return view(record)


@router.get("")
def interviews(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
               user=Depends(require("recruiter", "interviewer", "manager", module="rms")), db: Session = Depends(get_db)):
    conditions = [] if user.role in {"admin", "recruiter"} else [Interview.interviewer_id == user.id]
    return [view(row) for row in rows(db, Interview, user.customer_id, offset, limit, *conditions)]


@router.post("/{record_id}/cancel")
def cancel_interview(record_id: str, body: Decision, request: Request,
                     user=Depends(require("recruiter", module="rms")), db: Session = Depends(get_db)):
    record = find(db, Interview, record_id, user.customer_id, lock=True)
    state_is(record, "scheduled")
    record.status = "cancelled"
    audit(db, user, "interview.cancelled", record, request, reason=body.reason)
    notify(db, user, record.interviewer_id, "An assigned interview was cancelled")
    return view(record)


@router.post("/{record_id}/scorecard", status_code=201)
def score_interview(record_id: str, body: ScorecardCreate, request: Request,
                    user=Depends(require("interviewer", "manager", "recruiter", module="rms")), db: Session = Depends(get_db)):
    interview = find(db, Interview, record_id, user.customer_id, lock=True)
    if interview.interviewer_id != user.id:
        raise HTTPException(403, "Only the assigned interviewer can submit evidence")
    state_is(interview, "scheduled")
    if interview.scheduled_at.replace(tzinfo=timezone.utc) > utcnow():
        raise HTTPException(409, "Interview has not started")
    record = Scorecard(customer_id=user.customer_id, interview_id=interview.id, interviewer_id=user.id, **body.model_dump())
    interview.status = "completed"
    db.add(record)
    audit(db, user, "scorecard.submitted", record, request)
    return view(record)


@router.get("/{record_id}/scorecard")
def get_scorecard(record_id: str, user=Depends(require("recruiter", "interviewer", "manager", module="rms")), db: Session = Depends(get_db)):
    interview = find(db, Interview, record_id, user.customer_id)
    if user.role not in {"admin", "recruiter"} and interview.interviewer_id != user.id:
        raise HTTPException(404, "Record not found")
    record = db.scalar(select(Scorecard).where(Scorecard.interview_id == interview.id, Scorecard.customer_id == user.customer_id))
    if not record:
        raise HTTPException(404, "Scorecard not submitted")
    return view(record)


@router.post("/{record_id}/reschedule")
def reschedule_interview(record_id: str, body: InterviewReschedule, request: Request,
                         user=Depends(require("recruiter", module="rms")), db: Session = Depends(get_db)):
    record = find(db, Interview, record_id, user.customer_id, lock=True)
    state_is(record, "scheduled")
    if record.version != body.expected_version:
        raise HTTPException(409, "Interview changed; reload before rescheduling")
    old_start = record.scheduled_at.replace(tzinfo=timezone.utc) if record.scheduled_at.tzinfo is None else record.scheduled_at
    if old_start <= utcnow():
        raise HTTPException(409, "An interview that has already started cannot be rescheduled")
    application = application_reference(db, record.application_id, user.customer_id, lock=True)
    state_is(application, "interviewing")
    start = reserve_slot(db, application, record.interviewer_id, body.scheduled_at, body.duration_minutes, user.customer_id, record.id)
    previous_duration = record.duration_minutes
    record.scheduled_at, record.duration_minutes = start, body.duration_minutes
    audit(db, user, "interview.rescheduled", record, request, reason=body.reason,
          previous_start=old_start.isoformat(), previous_duration_minutes=previous_duration,
          scheduled_at=start.isoformat(), duration_minutes=body.duration_minutes)
    notify(db, user, record.interviewer_id, "An assigned interview has been rescheduled")
    return view(record)


@router.get("/{record_id}/packet")
def packet(record_id: str, user=Depends(require("recruiter", "interviewer", "manager", module="rms")), db: Session = Depends(get_db)):
    interview = find(db, Interview, record_id, user.customer_id)
    if user.role not in {"admin", "recruiter"} and interview.interviewer_id != user.id:
        raise HTTPException(404, "Interview not found")
    return {"interview": view(interview), "packet": interview_packet(db, interview.application_id, user.customer_id)}
