from datetime import date
from sqlalchemy import Date, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.data.database import Record


class ExpenseClaim(Record):
    __tablename__ = "expense_claims"
    requester_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    category: Mapped[str] = mapped_column(String(100))
    expense_type: Mapped[str] = mapped_column(String(150))
    expense_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[str] = mapped_column(String(30))
    currency: Mapped[str] = mapped_column(String(3))
    description: Mapped[str] = mapped_column(Text)
    receipt_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id"))
    status: Mapped[str] = mapped_column(String(20), default="draft")
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    decision_reason: Mapped[str | None] = mapped_column(Text)
