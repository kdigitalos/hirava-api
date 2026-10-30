from datetime import date
from app.core.routing import APIRouter
from fastapi import Depends, HTTPException, Query, Request
from pydantic import Field
from sqlalchemy.orm import Session
from app.core.schemas import Input
from app.core.security import require
from app.core.service import audit, find, rows, state_is, view
from app.data.database import get_db
from app.modules.performance.models import Goal, Review
from app.modules.workforce.service import visible_worker_ids, worker_access

router = APIRouter(prefix="/hrms/performance", tags=["performance"])
staff = require("hr", "manager", "employee", module="hrms")


class GoalCreate(Input):
    worker_id: str
    title: str = Field(min_length=1, max_length=200)
    due_date: date


class ReviewCreate(Input):
    worker_id: str
    period: str = Field(min_length=1, max_length=100)
    feedback: str = Field(min_length=3, max_length=20000)


@router.post("/goals", status_code=201)
def create_goal(body: GoalCreate, request: Request, user=Depends(staff), db: Session = Depends(get_db)):
    worker_access(db, body.worker_id, user)
    record = Goal(customer_id=user.customer_id, **body.model_dump())
    db.add(record)
    audit(db, user, "performance.goal_created", record, request)
    return view(record)


@router.get("/goals")
def goals(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), user=Depends(staff), db: Session = Depends(get_db)):
    return [view(row) for row in rows(db, Goal, user.customer_id, offset, limit, Goal.worker_id.in_(visible_worker_ids(db, user)))]


@router.post("/goals/{record_id}/complete")
def complete_goal(record_id: str, request: Request, user=Depends(staff), db: Session = Depends(get_db)):
    record = find(db, Goal, record_id, user.customer_id, lock=True)
    worker_access(db, record.worker_id, user)
    state_is(record, "open")
    record.status = "completed"
    audit(db, user, "performance.goal_completed", record, request)
    return view(record)


@router.post("/reviews", status_code=201)
def create_review(body: ReviewCreate, request: Request,
                  user=Depends(require("hr", "manager", module="hrms")), db: Session = Depends(get_db)):
    worker = worker_access(db, body.worker_id, user, allow_self=False)
    if worker.user_id == user.id:
        raise HTTPException(403, "Cannot submit your own manager review")
    record = Review(customer_id=user.customer_id, reviewer_id=user.id, **body.model_dump())
    db.add(record)
    audit(db, user, "performance.review_published", record, request)
    return view(record)


@router.get("/reviews")
def reviews(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), user=Depends(staff), db: Session = Depends(get_db)):
    return [view(row) for row in rows(db, Review, user.customer_id, offset, limit, Review.worker_id.in_(visible_worker_ids(db, user)))]


@router.post("/reviews/{record_id}/acknowledge")
def acknowledge_review(record_id: str, request: Request, user=Depends(staff), db: Session = Depends(get_db)):
    record = find(db, Review, record_id, user.customer_id, lock=True)
    worker = worker_access(db, record.worker_id, user)
    if worker.user_id != user.id:
        raise HTTPException(403, "Only the reviewed worker can acknowledge")
    record.acknowledged = True
    audit(db, user, "performance.review_acknowledged", record, request)
    return view(record)
