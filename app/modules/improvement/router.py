from datetime import date
from typing import Literal
from fastapi import Depends, HTTPException, Query, Request
from pydantic import Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.routing import APIRouter
from app.core.models import User
from app.core.schemas import Input
from app.core.security import require
from app.core.service import audit, find, rows, state_is, view
from app.data.database import get_db, utcnow
from app.modules.improvement.models import ImprovementPlan

router = APIRouter(prefix="/hrms/improvement-plans", tags=["improvement-plans"])
staff = require("hr", "employee", "manager", "recruiter", "interviewer", module="hrms")
hr = require("hr", module="hrms")


class Milestone(Input):
    title: str = Field(min_length=1, max_length=200)
    current_performance: str = Field(min_length=1, max_length=4000)
    expected_performance: str = Field(min_length=1, max_length=4000)
    action_steps: str = Field(min_length=1, max_length=4000)
    support: str = Field(default="", max_length=4000)
    success_criteria: str = Field(min_length=1, max_length=4000)
    due_date: date


class PlanInput(Input):
    employee_id: str
    title: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=3, max_length=10000)
    start_date: date
    end_date: date
    milestones: list[Milestone] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def valid_dates(self):
        if self.end_date < self.start_date:
            raise ValueError("End date must be on or after start date")
        if any(not self.start_date <= item.due_date <= self.end_date for item in self.milestones):
            raise ValueError("Milestone due dates must fall within the plan period")
        return self


class Version(Input):
    expected_version: int = Field(ge=1)


class PlanEdit(PlanInput):
    expected_version: int = Field(ge=1)


class ReviewInput(Version):
    milestone_index: int = Field(ge=0)
    progress: int = Field(ge=0, le=100)
    feedback: str = Field(min_length=3, max_length=10000)


class CloseInput(Version):
    status: Literal["completed", "cancelled"]
    outcome: str = Field(min_length=3, max_length=10000)


def scoped(db, record_id, user, lock=False):
    record = find(db, ImprovementPlan, record_id, user.customer_id, lock=lock)
    if user.role not in {"admin", "hr"} and (record.employee_id != user.id or record.status == "draft"):
        raise HTTPException(404, "Record not found")
    return record


def check_version(record, body):
    if record.version != body.expected_version:
        raise HTTPException(409, "Record changed; reload before editing")


def employee(db, employee_id, user):
    target = find(db, User, employee_id, user.customer_id)
    if not target.active or target.role not in {"employee", "manager", "hr", "recruiter", "interviewer", "admin"}:
        raise HTTPException(422, "Select an active staff account")
    if target.id == user.id:
        raise HTTPException(403, "You cannot author your own improvement plan")
    return target


def result(db, record):
    value = view(record)
    value["employee_name"] = db.get(User, record.employee_id).name
    return value


@router.get("/employees")
def employees(user=Depends(hr), db: Session = Depends(get_db)):
    return [{"id": item.id, "name": item.name} for item in db.scalars(select(User).where(
        User.customer_id == user.customer_id, User.active.is_(True), User.role != "candidate", User.id != user.id))]


@router.get("")
def list_plans(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
               user=Depends(staff), db: Session = Depends(get_db)):
    filters = [] if user.role in {"admin", "hr"} else [ImprovementPlan.employee_id == user.id, ImprovementPlan.status != "draft"]
    return [result(db, item) for item in rows(db, ImprovementPlan, user.customer_id, offset, limit, *filters)]


@router.get("/{record_id}")
def get_plan(record_id: str, user=Depends(staff), db: Session = Depends(get_db)):
    return result(db, scoped(db, record_id, user))


@router.post("", status_code=201)
def create_plan(body: PlanInput, request: Request, user=Depends(hr), db: Session = Depends(get_db)):
    employee(db, body.employee_id, user)
    payload = body.model_dump(exclude={"milestones"})
    payload["milestones"] = [dict(item.model_dump(mode="json"), progress=0) for item in body.milestones]
    record = ImprovementPlan(customer_id=user.customer_id, author_id=user.id, **payload)
    db.add(record)
    audit(db, user, "improvement.created", record, request)
    return result(db, record)


@router.patch("/{record_id}")
def edit_plan(record_id: str, body: PlanEdit, request: Request, user=Depends(hr), db: Session = Depends(get_db)):
    record = scoped(db, record_id, user, lock=True)
    state_is(record, "draft")
    check_version(record, body)
    employee(db, body.employee_id, user)
    for key, value in body.model_dump(exclude={"expected_version", "milestones"}).items():
        setattr(record, key, value)
    record.milestones = [dict(item.model_dump(mode="json"), progress=0) for item in body.milestones]
    audit(db, user, "improvement.edited", record, request)
    return result(db, record)


@router.post("/{record_id}/publish")
def publish(record_id: str, body: Version, request: Request, user=Depends(hr), db: Session = Depends(get_db)):
    record = scoped(db, record_id, user, lock=True)
    check_version(record, body)
    state_is(record, "draft")
    employee(db, record.employee_id, user)
    record.status = "active"
    audit(db, user, "improvement.published", record, request)
    return result(db, record)


@router.post("/{record_id}/acknowledge")
def acknowledge(record_id: str, body: Version, request: Request, user=Depends(staff), db: Session = Depends(get_db)):
    record = scoped(db, record_id, user, lock=True)
    if record.employee_id != user.id:
        raise HTTPException(403, "Only the employee can acknowledge their plan")
    check_version(record, body)
    state_is(record, "active")
    if record.acknowledged_at is None:
        record.acknowledged_at = utcnow()
        audit(db, user, "improvement.acknowledged", record, request)
    return result(db, record)


@router.post("/{record_id}/reviews", status_code=201)
def review(record_id: str, body: ReviewInput, request: Request, user=Depends(hr), db: Session = Depends(get_db)):
    record = scoped(db, record_id, user, lock=True)
    if record.employee_id == user.id:
        raise HTTPException(403, "You cannot review your own improvement plan")
    check_version(record, body)
    state_is(record, "active")
    if body.milestone_index >= len(record.milestones):
        raise HTTPException(422, "Milestone does not exist")
    record.milestones = [dict(item, progress=body.progress) if index == body.milestone_index else item
                         for index, item in enumerate(record.milestones)]
    record.reviews = [*record.reviews, {**body.model_dump(exclude={"expected_version"}),
        "reviewer_id": user.id, "reviewer_name": user.name, "recorded_at": utcnow().isoformat()}]
    audit(db, user, "improvement.reviewed", record, request)
    return result(db, record)


@router.post("/{record_id}/close")
def close(record_id: str, body: CloseInput, request: Request, user=Depends(hr), db: Session = Depends(get_db)):
    record = scoped(db, record_id, user, lock=True)
    if record.employee_id == user.id:
        raise HTTPException(403, "You cannot close your own improvement plan")
    check_version(record, body)
    state_is(record, "active")
    record.status, record.outcome = body.status, body.outcome
    audit(db, user, "improvement.closed", record, request)
    return result(db, record)
