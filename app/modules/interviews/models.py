from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.data.database import Record


class Interview(Record):
    __tablename__ = "interviews"
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"))
    interviewer_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_minutes: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="scheduled")


class Scorecard(Record):
    __tablename__ = "scorecards"
    __table_args__ = (UniqueConstraint("interview_id"),)
    interview_id: Mapped[str] = mapped_column(ForeignKey("interviews.id"))
    interviewer_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    competency: Mapped[str] = mapped_column(String(200))
    score: Mapped[int] = mapped_column(Integer)
    evidence: Mapped[str] = mapped_column(Text)
