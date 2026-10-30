from fastapi import HTTPException
from sqlalchemy import select
from app.core.models import User
from app.core.service import audit, find, notify
from app.modules.organization.service import reserve_position
from app.modules.workforce.models import Employment, LifecycleCase, Task, Worker


def employment_for(db, worker_id, customer_id, lock=False):
    query = select(Employment).where(Employment.worker_id == worker_id, Employment.customer_id == customer_id)
    if lock:
        query = query.with_for_update()
    employment = db.scalar(query)
    if not employment:
        raise HTTPException(404, "Employment not found")
    return employment


def worker_access(db, worker_id, user, *, allow_self=True, lock=False):
    worker = find(db, Worker, worker_id, user.customer_id, lock=lock)
    employment = employment_for(db, worker_id, user.customer_id)
    permitted = user.role in {"hr", "admin"} or (user.role == "manager" and employment.manager_id == user.id)
    if allow_self and worker.user_id == user.id:
        permitted = True
    if not permitted:
        raise HTTPException(404, "Worker not found")
    return worker


def visible_worker_ids(db, user):
    query = select(Worker.id).join(Employment, Employment.worker_id == Worker.id).where(Worker.customer_id == user.customer_id)
    if user.role not in {"hr", "admin"}:
        if user.role == "manager":
            query = query.where((Worker.user_id == user.id) | (Employment.manager_id == user.id))
        else:
            query = query.where(Worker.user_id == user.id)
    return query


def create_case(db, user, employment, kind):
    record = LifecycleCase(customer_id=user.customer_id, employment_id=employment.id, kind=kind)
    db.add(record)
    db.flush()
    titles = {"onboarding": ["Verify approved employment documents", "Complete day-one readiness review"],
              "offboarding": ["Record access-revocation evidence", "Reconcile assets and provider tasks"]}
    for title in titles[kind]:
        db.add(Task(customer_id=user.customer_id, case_id=record.id, title=title, owner_id=user.id))
    return record


def create_prehire(db, user, *, name, email, position_id, start_date, user_id=None, request=None):
    duplicate = db.scalar(select(Worker).where(Worker.customer_id == user.customer_id, Worker.email == email.lower()))
    if duplicate:
        raise HTTPException(409, "Existing worker requires a reviewed rehire/linkage workflow")
    if user_id:
        linked = find(db, User, user_id, user.customer_id)
        if not linked.active or linked.email != email.lower():
            raise HTTPException(422, "Linked account must be active and match the worker email")
    position = reserve_position(db, position_id, user.customer_id)
    worker = Worker(customer_id=user.customer_id, name=name, email=email.lower(), user_id=user_id)
    db.add(worker)
    db.flush()
    employment = Employment(customer_id=user.customer_id, worker_id=worker.id, position_id=position.id,
                            manager_id=position.manager_id, start_date=start_date)
    db.add(employment)
    db.flush()
    case = create_case(db, user, employment, "onboarding")
    audit(db, user, "worker.prehire_created", worker, request)
    notify(db, user, user.id, "An HR-approved prehire is ready for onboarding")
    return worker, employment, case
