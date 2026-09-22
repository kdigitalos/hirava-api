"""Signed-in individual feedback and durable in-app reminder scheduling. No email dispatch."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from app.agents.models import InterviewPanelFeedback
from app.agents.recruiter_tools import question_owner, staff
from app.core.compatibility_routing import APIRouter
from app.core.models import AuditEvent, User
from app.core.security import require
from app.data.database import get_db, utcnow
from app.modules.recruiting.pipeline_api import candidate, job, profile

router = APIRouter(prefix="/api/interview-panel", tags=["Interviewer feedback tasks"])
reviewer_access = require("employee", "interviewer", "manager", "hr", "recruiter", module="rms")


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Assign(Body):
    reviewer_id: str = Field(min_length=1, max_length=36)
    level: int = Field(ge=1, le=4)
    due_at: datetime | None = None


class Reminder(Body):
    version: int = Field(ge=1)
    due_at: datetime


class Feedback(Body):
    version: int = Field(ge=1)
    notes: str = Field(min_length=20, max_length=12000)
    rating: int | None = Field(default=None, ge=1, le=5)


def check_due(value):
    if value.tzinfo is None:
        raise HTTPException(422, "Provide a reminder time including its timezone.")
    value = aware(value)
    if not utcnow() < value <= utcnow() + timedelta(days=365):
        raise HTTPException(422, "Choose a future reminder within the next year.")
    return value


def slot_ref(parent, level):
    value = parent.get("id") if level == 1 else parent.get(f"S{level}")
    return f"L{level}:{value}" if value else None


def is_scheduled(parent, level):
    return slot_ref(parent, level) is not None


def same_slot(parent, row):
    return slot_ref(parent, row.level) == row.slot_ref


def audit(db, user, row, action):
    db.add(AuditEvent(customer_id=user.customer_id, actor_id=user.id, action=action,
        resource_type="interview_panel", resource_id=row.id, correlation_id=str(uuid4()),
        details={"interview_id": row.interview_id, "level": row.level, "reviewer_id": row.reviewer_id}))


def owned(db, user, row_id):
    row = db.scalar(select(InterviewPanelFeedback).where(InterviewPanelFeedback.id == row_id,
        InterviewPanelFeedback.customer_id == user.customer_id))
    if row is None:
        raise HTTPException(404, "Feedback task not found.")
    # Match schedule deletion's parent-first lock order and refresh after waiting.
    parent = question_owner(db, user, row.interview_id, lock=True)
    db.refresh(row, with_for_update=True)
    if parent["candidateId"] != row.candidate_id:
        raise HTTPException(409, "Interview candidate changed.")
    return row, parent


def serialize(db, row, parent):
    reviewer = db.get(User, row.reviewer_id)
    reviewer_available = bool(reviewer and reviewer.active and reviewer.customer_id == row.customer_id)
    status = "cancelled" if row.cancelled else "submitted" if row.submitted_at else "unavailable" if not reviewer_available or not same_slot(parent, row) else "due" if aware(row.due_at) <= utcnow() else "scheduled"
    return {"id": row.id, "version": row.version, "level": row.level, "interview_id": row.interview_id,
        "reviewer_id": row.reviewer_id, "current_round": same_slot(parent, row),
        "reviewer_name": reviewer.name if reviewer_available else "Unavailable reviewer",
        "due_at": aware(row.due_at), "status": status, "notes": row.notes,
        "rating": row.rating, "submitted_at": aware(row.submitted_at) if row.submitted_at else None}


@router.get("/reviewers")
def reviewers(user=Depends(staff), db=Depends(get_db)):
    rows = db.scalars(select(User).where(User.customer_id == user.customer_id, User.active.is_(True),
        User.role.in_(["admin", "hr", "recruiter", "employee", "interviewer", "manager"])).order_by(User.name).limit(200)).all()
    return {"data": [{"id": r.id, "name": r.name, "email": r.email} for r in rows]}


@router.get("/interviews/{interview_id}")
def panel(interview_id: int, user=Depends(staff), db=Depends(get_db)):
    parent = question_owner(db, user, interview_id)
    rows = db.scalars(select(InterviewPanelFeedback).where(InterviewPanelFeedback.customer_id == user.customer_id,
        InterviewPanelFeedback.interview_id == interview_id).order_by(InterviewPanelFeedback.created_at)).all()
    return {"data": [serialize(db, row, parent) for row in rows]}


@router.post("/interviews/{interview_id}")
def assign(interview_id: int, body: Assign, user=Depends(staff), db=Depends(get_db)):
    parent = question_owner(db, user, interview_id, lock=True)
    if not is_scheduled(parent, body.level):
        raise HTTPException(409, "Schedule this round before assigning feedback.")
    reviewer = db.scalar(select(User).where(User.id == body.reviewer_id, User.customer_id == user.customer_id,
        User.active.is_(True), User.role.in_(["admin", "hr", "recruiter", "employee", "interviewer", "manager"])))
    if reviewer is None:
        raise HTTPException(422, "Select an active interviewer from this organization.")
    existing = db.scalar(select(InterviewPanelFeedback).where(InterviewPanelFeedback.customer_id == user.customer_id,
        InterviewPanelFeedback.interview_id == interview_id, InterviewPanelFeedback.slot_ref == slot_ref(parent, body.level),
        InterviewPanelFeedback.reviewer_id == body.reviewer_id))
    if existing:
        raise HTTPException(409, "This interviewer already has a task for this round.")
    row = InterviewPanelFeedback(customer_id=user.customer_id, interview_id=interview_id,
        candidate_id=parent["candidateId"], level=body.level, slot_ref=slot_ref(parent, body.level), reviewer_id=reviewer.id,
        assigned_by=user.id, due_at=check_due(body.due_at) if body.due_at else utcnow() + timedelta(hours=24))
    db.add(row); db.flush(); audit(db, user, row, "interview.panel_assigned")
    return serialize(db, row, parent)


@router.patch("/assignments/{row_id}/reminder")
def schedule_reminder(row_id: str, body: Reminder, user=Depends(staff), db=Depends(get_db)):
    row, parent = owned(db, user, row_id)
    if row.cancelled or row.submitted_at or not same_slot(parent, row):
        raise HTTPException(409, "This task no longer needs a reminder.")
    if row.version != body.version:
        raise HTTPException(409, "Task changed; reload before rescheduling.")
    row.due_at = check_due(body.due_at); db.flush(); audit(db, user, row, "interview.reminder_scheduled")
    return serialize(db, row, parent)


@router.delete("/assignments/{row_id}")
def cancel(row_id: str, user=Depends(staff), db=Depends(get_db)):
    row, parent = owned(db, user, row_id)
    row.cancelled = True; db.flush(); audit(db, user, row, "interview.panel_cancelled")
    return serialize(db, row, parent)


@router.get("/mine")
def my_tasks(user=Depends(reviewer_access), db=Depends(get_db)):
    rows = db.scalars(select(InterviewPanelFeedback).where(InterviewPanelFeedback.customer_id == user.customer_id,
        InterviewPanelFeedback.reviewer_id == user.id, InterviewPanelFeedback.cancelled.is_(False))
        .order_by(InterviewPanelFeedback.due_at)).all()
    results = []
    for row in rows:
        try:
            parent = question_owner(db, user, row.interview_id)
        except HTTPException as error:
            if error.status_code in (404, 409):
                continue
            raise
        if parent["candidateId"] != row.candidate_id:
            continue
        _, person = candidate(db, user, row.candidate_id)
        fields = profile(person)
        results.append({**serialize(db, row, parent), "candidate_name": " ".join(str(fields.get(k) or "") for k in ("firstName", "lastName")).strip(), "job_title": job(db, user, parent["jobId"]).title})
    return {"data": results}


@router.put("/assignments/{row_id}/feedback")
def submit_feedback(row_id: str, body: Feedback, user=Depends(reviewer_access), db=Depends(get_db)):
    row, parent = owned(db, user, row_id)
    if row.reviewer_id != user.id:
        raise HTTPException(403, "Only the assigned interviewer may submit this feedback.")
    if row.cancelled or not same_slot(parent, row):
        raise HTTPException(409, "This feedback task is no longer active.")
    if row.version != body.version:
        raise HTTPException(409, "Feedback changed; reload before editing.")
    row.notes, row.rating, row.submitted_at = body.notes, body.rating, utcnow()
    db.flush(); audit(db, user, row, "interview.panel_feedback_submitted")
    return serialize(db, row, parent)


class RoundReviewers(Body):
    reviewer_ids: list[str] = Field(max_length=20)
    feedback_due_at: datetime | None = None


def synchronize(db, user, parent, level, reviewer_ids, due_at=None, starts_at=None, duration=None):
    reference = slot_ref(parent, level)
    if not reference:
        raise HTTPException(409, "Schedule this round first.")
    ids = list(dict.fromkeys(reviewer_ids))
    people = db.scalars(select(User).where(User.id.in_(ids), User.customer_id == user.customer_id,
        User.active.is_(True), User.role.in_(["admin", "hr", "recruiter", "employee", "interviewer", "manager"]))).all()
    if len(people) != len(ids):
        raise HTTPException(422, "Select active interviewers from this organization.")
    from app.agents.calendar_slots import reserve
    reserve(db,user,parent,level,ids,starts_at,duration)
    due = check_due(due_at) if due_at else utcnow() + timedelta(hours=24)
    rows = db.scalars(select(InterviewPanelFeedback).where(
        InterviewPanelFeedback.customer_id == user.customer_id,
        InterviewPanelFeedback.interview_id == parent["id"],
        InterviewPanelFeedback.slot_ref == reference).with_for_update()).all()
    by_user = {row.reviewer_id: row for row in rows}
    for row in rows:
        # Preserve submitted feedback even when a reviewer is later removed.
        if row.reviewer_id not in ids and not row.submitted_at:
            row.cancelled = True
    for reviewer_id in ids:
        row = by_user.get(reviewer_id)
        if row:
            row.cancelled = False
            if due_at and not row.submitted_at:
                row.due_at = due
        else:
            row = InterviewPanelFeedback(customer_id=user.customer_id, interview_id=parent["id"],
                candidate_id=parent["candidateId"], level=level, slot_ref=reference,
                reviewer_id=reviewer_id, assigned_by=user.id, due_at=due)
            db.add(row)
    db.flush()
    from app.modules.recruiting.pipeline_interviews import interview_table
    table = interview_table(db, level != 1)
    record_id = parent["id"] if level == 1 else int(parent[f"S{level}"])
    names = ", ".join(person.name for person in people)
    # Legacy display column is bounded; authoritative account IDs remain in tasks.
    db.execute(table.update().where(table.c.id == record_id).values(panelMembers=names[:100]))
    db.add(AuditEvent(customer_id=user.customer_id, actor_id=user.id, action="interview.reviewers_selected",
        resource_type="interview", resource_id=str(parent["id"]), correlation_id=str(uuid4()),
        details={"level": level, "reviewer_ids": ids}))


@router.put("/interviews/{interview_id}/rounds/{level}")
def select_round_reviewers(interview_id: int, level: int, body: RoundReviewers,
                           user=Depends(staff), db=Depends(get_db)):
    if level not in (1, 2, 3, 4):
        raise HTTPException(422, "Choose L1 through L4.")
    parent = question_owner(db, user, interview_id, lock=True)
    synchronize(db, user, parent, level, body.reviewer_ids, body.feedback_due_at)
    return {"saved": True}
