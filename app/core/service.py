from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import inspect, select

from app.core.models import AuditEvent, OutboxEvent


def find(db, model, record_id, customer_id, *, lock=False):
    statement = select(model).where(model.id == record_id, model.customer_id == customer_id)
    if lock:
        statement = statement.with_for_update()
    record = db.scalar(statement)
    if record is None:
        raise HTTPException(404, "Record not found")
    return record


def rows(db, model, customer_id, offset=0, limit=50, *conditions):
    return db.scalars(select(model).where(model.customer_id == customer_id, *conditions)
                      .order_by(model.created_at.desc(), model.id).offset(offset).limit(limit)).all()


def view(record, exclude=()):
    hidden = {"password_hash", "auth_subject", "failed_logins", "locked_until", "token_version", "storage_key"} | set(exclude)
    return {column.key: getattr(record, column.key) for column in inspect(record).mapper.column_attrs
            if column.key not in hidden}


def audit(db, user, action, record, request=None, **details):
    db.flush()
    db.add(AuditEvent(customer_id=user.customer_id, actor_id=user.id, action=action,
                      resource_type=record.__tablename__, resource_id=record.id,
                      correlation_id=getattr(getattr(request, "state", None), "correlation_id", str(uuid4())),
                      details=details))


def notify(db, user, recipient_id, message):
    db.add(OutboxEvent(customer_id=user.customer_id, topic="notification",
                       payload={"user_id": recipient_id, "message": message}))


def state_is(record, *allowed):
    if record.status not in allowed:
        raise HTTPException(409, f"Action requires status: {', '.join(allowed)}")
