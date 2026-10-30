from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.data.database import Record


class HRCase(Record):
    __tablename__ = "hr_cases"
    requester_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    assigned_to: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    subject: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="open")


class CaseNote(Record):
    __tablename__ = "case_notes"
    case_id: Mapped[str] = mapped_column(ForeignKey("hr_cases.id"))
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    content: Mapped[str] = mapped_column(Text)
