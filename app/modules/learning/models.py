from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.data.database import Record


class Course(Record):
    __tablename__ = "courses"
    title: Mapped[str] = mapped_column(String(200))
    reference_url: Mapped[str] = mapped_column(Text)


class LearningAssignment(Record):
    __tablename__ = "learning_assignments"
    __table_args__ = (UniqueConstraint("course_id", "worker_id"),)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"))
    worker_id: Mapped[str] = mapped_column(ForeignKey("workers.id"))
    status: Mapped[str] = mapped_column(String(30), default="assigned")
    evidence: Mapped[str | None] = mapped_column(Text)
