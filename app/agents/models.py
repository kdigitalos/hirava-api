"""Durable, tenant-scoped screening queue and retained assessment results."""
from datetime import datetime

from sqlalchemy import Boolean, UniqueConstraint, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.data.database import Record


class VoiceInterview(Record):
    __tablename__ = "voice_interviews"
    interview_id: Mapped[int] = mapped_column(Integer, index=True)
    candidate_id: Mapped[int] = mapped_column(Integer)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    title: Mapped[str] = mapped_column(String(200))
    job_description: Mapped[str] = mapped_column(Text)
    questions: Mapped[list] = mapped_column(JSON)
    answers: Mapped[list] = mapped_column(JSON, default=list)
    current_question: Mapped[str] = mapped_column(Text)
    question_index: Mapped[int] = mapped_column(Integer, default=0)
    followup: Mapped[bool] = mapped_column(Boolean, default=False)
    allow_followups: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(30), default="invited")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    minutes: Mapped[int] = mapped_column(Integer, default=10)
    speech_calls: Mapped[int] = mapped_column(Integer, default=0)
    transcription_calls: Mapped[int] = mapped_column(Integer, default=0)
    lease: Mapped[str | None] = mapped_column(String(36))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summary: Mapped[dict | None] = mapped_column(JSON)
    summary_calls: Mapped[int] = mapped_column(Integer, default=0)
    realtime_call_id: Mapped[str | None] = mapped_column(String(200))
    realtime_attempts: Mapped[int] = mapped_column(Integer, default=0)
    realtime_transcript: Mapped[list] = mapped_column(JSON, default=list)
    realtime_error: Mapped[str | None] = mapped_column(String(300))


class ScreeningJob(Record):
    __tablename__ = "screening_jobs"
    candidate_id: Mapped[int] = mapped_column(Integer, index=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    # NULL once finished. Unique across processes, not just this Python worker.
    active_slot: Mapped[str | None] = mapped_column(String(150), unique=True)
    source_hash: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    rubric: Mapped[dict] = mapped_column(JSON)
    provider: Mapped[str] = mapped_column(String(30))
    model: Mapped[str] = mapped_column(String(150))
    result: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InterviewQuestionSet(Record):
    """Staff-saved question text; immutable versions, not claims of AI provenance."""
    __tablename__ = "interview_question_sets"
    interview_id: Mapped[int] = mapped_column(Integer, index=True)
    candidate_id: Mapped[int] = mapped_column(Integer)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    round: Mapped[str] = mapped_column(String(30))
    text: Mapped[str] = mapped_column(Text)


class InterviewPanelFeedback(Record):
    __tablename__ = "interview_panel_feedback"
    __table_args__ = (UniqueConstraint("customer_id", "interview_id", "slot_ref", "reviewer_id", name="uq_interview_panel_reviewer"),)
    interview_id: Mapped[int] = mapped_column(Integer, index=True)
    candidate_id: Mapped[int] = mapped_column(Integer)
    level: Mapped[int] = mapped_column(Integer)
    slot_ref: Mapped[str] = mapped_column(String(50))
    reviewer_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    assigned_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cancelled: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text)
    rating: Mapped[int | None] = mapped_column(Integer)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CandidateLink(Record):
    __tablename__ = "candidate_identity_links"
    __table_args__ = (UniqueConstraint("customer_id", "left_id", "right_id", name="uq_candidate_link_pair"),)
    left_id: Mapped[int] = mapped_column(Integer)
    right_id: Mapped[int] = mapped_column(Integer)
    decision: Mapped[str] = mapped_column(String(30))
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    note: Mapped[str] = mapped_column(String(1000), default="")


class TalentPool(Record):
    __tablename__ = "talent_pools"
    __table_args__ = (UniqueConstraint("customer_id", "name", name="uq_talent_pool_name"),)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(1000), default="")
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))


class TalentPoolMember(Record):
    __tablename__ = "talent_pool_members"
    __table_args__ = (UniqueConstraint("pool_id", "candidate_id", name="uq_talent_pool_member"),)
    pool_id: Mapped[str] = mapped_column(ForeignKey("talent_pools.id"))
    candidate_id: Mapped[int] = mapped_column(Integer)
    contact_preference: Mapped[str] = mapped_column(String(30), default="unknown")
    review_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))


class RecruitmentActivity(Record):
    __tablename__ = "recruitment_activity"
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    candidate_id: Mapped[int] = mapped_column(Integer, index=True)
    job_id: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(40))
    from_stage: Mapped[str | None] = mapped_column(String(50))
    to_stage: Mapped[str | None] = mapped_column(String(50))


class RecruitmentReport(Record):
    __tablename__ = "recruitment_reports"
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(150))
    metrics: Mapped[dict] = mapped_column(JSON)
    sections: Mapped[list] = mapped_column(JSON)


class RecruitmentSignal(Record):
    __tablename__ = "recruitment_signals"
    __table_args__ = (UniqueConstraint("customer_id", "signal_key", name="uq_recruitment_signal"),)
    signal_key: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(40))
    resource_id: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(30), default="open")
    message: Mapped[str] = mapped_column(String(300))
    href: Mapped[str] = mapped_column(String(200))


class InterviewReservation(Record):
    __tablename__ = "interview_reservations"
    __table_args__ = (UniqueConstraint("customer_id", "interview_id", "slot_ref", "reviewer_id", name="uq_interview_reservation"),)
    interview_id: Mapped[int] = mapped_column(Integer)
    slot_ref: Mapped[str] = mapped_column(String(50))
    reviewer_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RecruitmentCost(Record):
    __tablename__ = "recruitment_costs"
    voided: Mapped[bool] = mapped_column(Boolean, default=False)
    job_id: Mapped[int] = mapped_column(Integer)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    amount_minor: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))
    category: Mapped[str] = mapped_column(String(40))
    note: Mapped[str] = mapped_column(String(500))
    incurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
