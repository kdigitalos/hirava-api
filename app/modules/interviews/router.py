from datetime import timezone
from app.core.routing import APIRouter
from fastapi import Depends, HTTPException, Query, Request
from pydantic import AwareDatetime, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.models import User
from app.core.schemas import Decision, Input
from app.core.security import require
from app.core.service import audit, find, notify, rows, state_is, view
from app.data.database import get_db, utcnow
from app.modules.interviews.models import Interview, Scorecard
from app.modules.recruiting.service import application_reference, interview_packet

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


@router.post("", status_code=201)
def create_interview(body: InterviewCreate, request: Request, user=Depends(require("recruiter", module="rms")), db: Session = Depends(get_db)):
    application = application_reference(db, body.application_id, user.customer_id)
    state_is(application, "interviewing")
    interviewer = find(db, User, body.interviewer_id, user.customer_id)
    if not interviewer.active or interviewer.role not in {"interviewer", "manager", "recruiter"}:
        raise HTTPException(422, "An active interviewer, manager, or recruiter is required")
    if body.scheduled_at <= utcnow():
        raise HTTPException(422, "Interview must be scheduled in the future")
    fields = body.model_dump()
    fields["scheduled_at"] = body.scheduled_at.astimezone(timezone.utc)
    record = Interview(customer_id=user.customer_id, **fields)
    db.add(record)
    audit(db, user, "interview.scheduled", record, request)
    notify(db, user, interviewer.id, "An interview has been assigned to you")
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


@router.get("/{record_id}/packet")
def packet(record_id: str, user=Depends(require("recruiter", "interviewer", "manager", module="rms")), db: Session = Depends(get_db)):
    interview = find(db, Interview, record_id, user.customer_id)
    if user.role not in {"admin", "recruiter"} and interview.interviewer_id != user.id:
        raise HTTPException(404, "Interview not found")
    return {"interview": view(interview), "packet": interview_packet(db, interview.application_id, user.customer_id)}
