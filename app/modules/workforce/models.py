from datetime import date
from sqlalchemy import Date, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.data.database import Record


class Worker(Record):
    __tablename__ = "workers"
    __table_args__ = (UniqueConstraint("customer_id", "email"), UniqueConstraint("user_id"))
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(320))
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))


class Employment(Record):
    __tablename__ = "employments"
    worker_id: Mapped[str] = mapped_column(ForeignKey("workers.id"), unique=True)
    position_id: Mapped[str] = mapped_column(ForeignKey("positions.id"))
    manager_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(30), default="prehire")


class LifecycleCase(Record):
    __tablename__ = "lifecycle_cases"
    __table_args__ = (UniqueConstraint("employment_id", "kind"),)
    employment_id: Mapped[str] = mapped_column(ForeignKey("employments.id"))
    kind: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30), default="open")


class Task(Record):
    __tablename__ = "tasks"
    case_id: Mapped[str] = mapped_column(ForeignKey("lifecycle_cases.id"))
    title: Mapped[str] = mapped_column(String(200))
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    evidence: Mapped[str | None] = mapped_column(Text)


class ProfileChange(Record):
    __tablename__ = "profile_changes"
    worker_id: Mapped[str] = mapped_column(ForeignKey("workers.id"))
    requested_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    proposed_name: Mapped[str] = mapped_column(String(200))
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    decided_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
