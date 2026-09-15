from datetime import datetime
from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.data.database import Base, Record


class JobReference(Base):
    """Stable legacy aliases only; job content remains on Requisition."""
    __tablename__ = "job_references"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    requisition_id: Mapped[str] = mapped_column(ForeignKey("requisitions.id"), unique=True)


class Requisition(Record):
    __tablename__ = "requisitions"
    position_id: Mapped[str] = mapped_column(ForeignKey("positions.id"))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    requested_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    approved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(30), default="draft")
    # Typed by JobDetails at the command boundary. Kept on the existing
    # requisition so richer job forms do not create another vacancy master.
    job_details: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class Candidate(Record):
    __tablename__ = "candidates"
    __table_args__ = (UniqueConstraint("customer_id", "email"),)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(320))
    consent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consent_notice: Mapped[str] = mapped_column(String(100))


class Application(Record):
    __tablename__ = "applications"
    __table_args__ = (UniqueConstraint("candidate_id", "requisition_id"),)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidates.id"))
    requisition_id: Mapped[str] = mapped_column(ForeignKey("requisitions.id"))
    status: Mapped[str] = mapped_column(String(30), default="applied")
    disposition_reason: Mapped[str | None] = mapped_column(Text)
