from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.data.database import Record


class User(Record):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("customer_id", "email"), UniqueConstraint("customer_id", "auth_subject"))
    email: Mapped[str] = mapped_column(String(320))
    name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(30))
    password_hash: Mapped[str | None] = mapped_column(Text)
    auth_subject: Mapped[str | None] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    token_version: Mapped[int] = mapped_column(Integer, default=1)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AccountInvitation(Record):
    __tablename__ = "account_invitations"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), unique=True)
    employee_id: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(30), default="pending")
    attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(100))


class AuditEvent(Record):
    __tablename__ = "audit_events"
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(100))
    resource_type: Mapped[str] = mapped_column(String(100))
    resource_id: Mapped[str] = mapped_column(String(36))
    correlation_id: Mapped[str] = mapped_column(String(36))
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class OutboxEvent(Record):
    __tablename__ = "outbox_events"
    topic: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(100))


class Notification(Record):
    __tablename__ = "notifications"
    __table_args__ = (UniqueConstraint("event_id"),)
    event_id: Mapped[str] = mapped_column(ForeignKey("outbox_events.id"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    message: Mapped[str] = mapped_column(String(250))
    read: Mapped[bool] = mapped_column(Boolean, default=False)


class Policy(Record):
    __tablename__ = "policies"
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, default=1)


class Acknowledgement(Record):
    __tablename__ = "policy_acknowledgements"
    __table_args__ = (UniqueConstraint("policy_id", "user_id", "revision"),)
    policy_id: Mapped[str] = mapped_column(ForeignKey("policies.id"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    revision: Mapped[int] = mapped_column(Integer)


class Document(Record):
    __tablename__ = "documents"
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    domain: Mapped[str] = mapped_column(String(20))
    filename: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(36), unique=True)
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
