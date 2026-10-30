from datetime import date
from sqlalchemy import Date, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.data.database import Record


class Goal(Record):
    __tablename__ = "performance_goals"
    worker_id: Mapped[str] = mapped_column(ForeignKey("workers.id"))
    title: Mapped[str] = mapped_column(String(200))
    due_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(30), default="open")


class Review(Record):
    __tablename__ = "performance_reviews"
    worker_id: Mapped[str] = mapped_column(ForeignKey("workers.id"))
    reviewer_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    period: Mapped[str] = mapped_column(String(100))
    feedback: Mapped[str] = mapped_column(Text)
    acknowledged: Mapped[bool] = mapped_column(default=False)
