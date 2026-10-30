from datetime import date
from sqlalchemy import CheckConstraint, Date, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.data.database import Record


class LeaveType(Record):
    __tablename__ = "leave_types"
    __table_args__ = (UniqueConstraint("customer_id", "name"),)
    name: Mapped[str] = mapped_column(String(100))


class LeaveBalance(Record):
    __tablename__ = "leave_balances"
    __table_args__ = (UniqueConstraint("worker_id", "leave_type_id", "year"),
                      CheckConstraint("granted >= 0 AND used >= 0 AND used <= granted"))
    worker_id: Mapped[str] = mapped_column(ForeignKey("workers.id"))
    leave_type_id: Mapped[str] = mapped_column(ForeignKey("leave_types.id"))
    year: Mapped[int] = mapped_column(Integer)
    granted: Mapped[int] = mapped_column(Integer)
    used: Mapped[int] = mapped_column(Integer, default=0)


class LeaveRequest(Record):
    __tablename__ = "leave_requests"
    worker_id: Mapped[str] = mapped_column(ForeignKey("workers.id"))
    leave_type_id: Mapped[str] = mapped_column(ForeignKey("leave_types.id"))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    days: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    decided_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    decision_reason: Mapped[str | None] = mapped_column(Text)
