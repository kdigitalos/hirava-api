from datetime import date
from sqlalchemy import Date, ForeignKey, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.data.database import Record


class SalaryStructure(Record):
    __tablename__ = "salary_structures"
    __table_args__ = (UniqueConstraint("customer_id", "code", "effective_from"),)
    code: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(160))
    effective_from: Mapped[date] = mapped_column(Date)
    components: Mapped[list] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(String(1000))
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
