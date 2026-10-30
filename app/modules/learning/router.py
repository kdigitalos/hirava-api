from app.core.routing import APIRouter
from fastapi import Depends, HTTPException, Query, Request
from pydantic import Field, HttpUrl
from sqlalchemy.orm import Session
from app.core.schemas import Decision, Input
from app.core.security import require
from app.core.service import audit, find, rows, state_is, view
from app.data.database import get_db
from app.modules.learning.models import Course, LearningAssignment
from app.modules.workforce.service import visible_worker_ids, worker_access

router = APIRouter(prefix="/hrms/learning", tags=["learning"])
staff = require("hr", "manager", "employee", module="hrms")


class CourseCreate(Input):
    title: str = Field(min_length=1, max_length=200)
    reference_url: HttpUrl


class AssignmentCreate(Input):
    course_id: str
    worker_id: str


@router.post("/courses", status_code=201)
def create_course(body: CourseCreate, request: Request, user=Depends(require("hr", module="hrms")), db: Session = Depends(get_db)):
    record = Course(customer_id=user.customer_id, title=body.title, reference_url=str(body.reference_url))
    db.add(record)
    audit(db, user, "learning.course_created", record, request)
    return view(record)


@router.get("/courses")
def courses(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), user=Depends(staff), db: Session = Depends(get_db)):
    return [view(row) for row in rows(db, Course, user.customer_id, offset, limit)]


@router.post("/assignments", status_code=201)
def assign(body: AssignmentCreate, request: Request,
           user=Depends(require("hr", "manager", module="hrms")), db: Session = Depends(get_db)):
    find(db, Course, body.course_id, user.customer_id)
    worker_access(db, body.worker_id, user, allow_self=False)
    record = LearningAssignment(customer_id=user.customer_id, **body.model_dump())
    db.add(record)
    audit(db, user, "learning.assigned", record, request)
    return view(record)


@router.get("/assignments")
def assignments(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), user=Depends(staff), db: Session = Depends(get_db)):
    return [view(row) for row in rows(db, LearningAssignment, user.customer_id, offset, limit,
                                     LearningAssignment.worker_id.in_(visible_worker_ids(db, user)))]


@router.post("/assignments/{record_id}/complete")
def complete(record_id: str, body: Decision, request: Request, user=Depends(staff), db: Session = Depends(get_db)):
    record = find(db, LearningAssignment, record_id, user.customer_id, lock=True)
    worker = worker_access(db, record.worker_id, user)
    if worker.user_id != user.id and user.role not in {"hr", "admin"}:
        raise HTTPException(403, "Only the learner or HR can record completion evidence")
    state_is(record, "assigned")
    record.status, record.evidence = "completed", body.reason
    audit(db, user, "learning.completed", record, request)
    return view(record)
