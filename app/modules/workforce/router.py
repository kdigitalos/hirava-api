from datetime import date
from app.core.routing import APIRouter
from fastapi import Depends, HTTPException, Query, Request
from pydantic import EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.models import User
from app.core.schemas import Decision, Input
from app.core.security import require
from app.core.service import audit, find, rows, state_is, view
from app.data.database import get_db
from app.modules.organization.service import release_position
from app.modules.workforce.models import Employment, LifecycleCase, Task, Worker
from app.modules.workforce.service import create_case, create_prehire, visible_worker_ids, worker_access

router = APIRouter(prefix="/hrms", tags=["workforce"])
hr = require("hr", module="hrms")
staff = require("hr", "manager", "employee", module="hrms")


class DirectHire(Input):
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    position_id: str
    start_date: date
    user_id: str | None = None
    approval_reason: str = Field(min_length=3, max_length=2000)


class UserLink(Input):
    user_id: str


class TaskCreate(Input):
    title: str = Field(min_length=1, max_length=200)
    owner_id: str


@router.post("/workers", status_code=201)
def direct_hire(body: DirectHire, request: Request, user=Depends(hr), db: Session = Depends(get_db)):
    worker, employment, case = create_prehire(db, user, **body.model_dump(exclude={"approval_reason"}), request=request)
    audit(db, user, "direct_hire.approved", employment, request, reason=body.approval_reason)
    return {"worker": view(worker), "employment": view(employment), "onboarding": view(case)}


@router.get("/workers")
def workers(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), user=Depends(staff), db: Session = Depends(get_db)):
    return [view(row) for row in rows(db, Worker, user.customer_id, offset, limit, Worker.id.in_(visible_worker_ids(db, user)))]


@router.get("/workers/{record_id}")
def worker(record_id: str, user=Depends(staff), db: Session = Depends(get_db)):
    return view(worker_access(db, record_id, user))


@router.post("/workers/{record_id}/link-user")
def link_user(record_id: str, body: UserLink, request: Request, user=Depends(hr), db: Session = Depends(get_db)):
    record = find(db, Worker, record_id, user.customer_id, lock=True)
    linked = find(db, User, body.user_id, user.customer_id)
    if record.user_id or not linked.active or linked.email != record.email:
        raise HTTPException(409, "Worker must be unlinked and account must be active with matching email")
    record.user_id = linked.id
    audit(db, user, "worker.account_linked", record, request)
    return view(record)


@router.get("/employments")
def employments(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), user=Depends(staff), db: Session = Depends(get_db)):
    return [view(row) for row in rows(db, Employment, user.customer_id, offset, limit,
                                     Employment.worker_id.in_(visible_worker_ids(db, user)))]


@router.post("/employments/{record_id}/commence")
def commence(record_id: str, body: Decision, request: Request, user=Depends(hr), db: Session = Depends(get_db)):
    record = find(db, Employment, record_id, user.customer_id, lock=True)
    state_is(record, "prehire")
    if record.start_date > date.today():
        raise HTTPException(409, "Employment cannot commence before its start date")
    case = db.scalar(select(LifecycleCase).where(LifecycleCase.employment_id == record.id, LifecycleCase.kind == "onboarding"))
    if not case or case.status != "closed":
        raise HTTPException(409, "Close onboarding before commencement")
    record.status = "active"
    worker = find(db, Worker, record.worker_id, user.customer_id)
    if worker.user_id:
        linked = find(db, User, worker.user_id, user.customer_id, lock=True)
        if linked.role == "candidate":
            linked.role = "employee"
            linked.token_version += 1
    audit(db, user, "employment.commenced", record, request, reason=body.reason)
    return view(record)


@router.post("/employments/{record_id}/cancel-prehire")
def cancel_prehire(record_id: str, body: Decision, request: Request, user=Depends(hr), db: Session = Depends(get_db)):
    record = find(db, Employment, record_id, user.customer_id, lock=True)
    state_is(record, "prehire")
    record.status = "cancelled"
    release_position(db, record.position_id, user.customer_id)
    case = db.scalar(select(LifecycleCase).where(LifecycleCase.employment_id == record.id, LifecycleCase.kind == "onboarding").with_for_update())
    if case:
        case.status = "cancelled"
        for task in db.scalars(select(Task).where(Task.case_id == case.id, Task.status == "pending")):
            task.status = "cancelled"
    audit(db, user, "employment.prehire_cancelled", record, request, reason=body.reason)
    return view(record)


@router.post("/employments/{record_id}/offboard", status_code=201)
def offboard(record_id: str, body: Decision, request: Request, user=Depends(hr), db: Session = Depends(get_db)):
    record = find(db, Employment, record_id, user.customer_id, lock=True)
    state_is(record, "active")
    record.status = "offboarding"
    case = create_case(db, user, record, "offboarding")
    audit(db, user, "offboarding.approved", record, request, reason=body.reason)
    return view(case)


@router.get("/lifecycle-cases")
def lifecycle_cases(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), user=Depends(staff), db: Session = Depends(get_db)):
    employment_ids = select(Employment.id).where(Employment.worker_id.in_(visible_worker_ids(db, user)))
    return [view(row) for row in rows(db, LifecycleCase, user.customer_id, offset, limit, LifecycleCase.employment_id.in_(employment_ids))]


@router.post("/lifecycle-cases/{record_id}/tasks", status_code=201)
def add_task(record_id: str, body: TaskCreate, request: Request, user=Depends(hr), db: Session = Depends(get_db)):
    case = find(db, LifecycleCase, record_id, user.customer_id, lock=True)
    state_is(case, "open")
    owner = find(db, User, body.owner_id, user.customer_id)
    if not owner.active or owner.role not in {"admin", "hr", "manager", "employee"}:
        raise HTTPException(422, "Task owner must be an active HRMS user")
    record = Task(customer_id=user.customer_id, case_id=case.id, **body.model_dump())
    db.add(record)
    audit(db, user, "task.assigned", record, request)
    return view(record)


@router.get("/tasks")
def tasks(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), user=Depends(staff), db: Session = Depends(get_db)):
    conditions = [] if user.role in {"hr", "admin"} else [Task.owner_id == user.id]
    return [view(row) for row in rows(db, Task, user.customer_id, offset, limit, *conditions)]


@router.post("/tasks/{record_id}/complete")
def complete_task(record_id: str, body: Decision, request: Request, user=Depends(staff), db: Session = Depends(get_db)):
    task = find(db, Task, record_id, user.customer_id, lock=True)
    if task.owner_id != user.id:
        raise HTTPException(403, "Only the assigned owner can attest task completion")
    case = find(db, LifecycleCase, task.case_id, user.customer_id, lock=True)
    state_is(case, "open")
    state_is(task, "pending")
    task.status, task.evidence = "completed", body.reason
    audit(db, user, "task.completed", task, request)
    return view(task)


@router.post("/lifecycle-cases/{record_id}/close")
def close_case(record_id: str, body: Decision, request: Request, user=Depends(hr), db: Session = Depends(get_db)):
    case = find(db, LifecycleCase, record_id, user.customer_id, lock=True)
    state_is(case, "open")
    pending = db.scalar(select(Task.id).where(Task.case_id == case.id, Task.status != "completed"))
    if pending:
        raise HTTPException(409, "All tasks require completion evidence")
    if case.kind == "offboarding":
        employment = find(db, Employment, case.employment_id, user.customer_id, lock=True)
        state_is(employment, "offboarding")
        employment.status, employment.end_date = "ended", date.today()
        release_position(db, employment.position_id, user.customer_id)
        worker = find(db, Worker, employment.worker_id, user.customer_id)
        if worker.user_id:
            linked = find(db, User, worker.user_id, user.customer_id)
            if linked.role == "admin":
                raise HTTPException(409, "Transfer administrator access before offboarding")
            linked.active = False
            linked.token_version += 1
    case.status = "closed"
    audit(db, user, "lifecycle.closed", case, request, reason=body.reason)
    return view(case)
