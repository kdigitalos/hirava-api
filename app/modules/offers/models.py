from datetime import date
from decimal import Decimal
from sqlalchemy import Date, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.data.database import Record


class Offer(Record):
    __tablename__ = "offers"
    __table_args__ = (UniqueConstraint("application_id"),)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"))
    annual_salary: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3))
    start_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(30), default="draft")
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    approved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    acceptance_evidence: Mapped[str | None] = mapped_column(Text)
