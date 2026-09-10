from sqlalchemy import CheckConstraint, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from app.data.database import Record


class OrganizationUnit(Record):
    __tablename__ = "organization_units"
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(30))
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("organization_units.id"))


class Position(Record):
    __tablename__ = "positions"
    __table_args__ = (CheckConstraint("capacity > 0 AND occupied >= 0 AND occupied <= capacity"),)
    title: Mapped[str] = mapped_column(String(200))
    unit_id: Mapped[str] = mapped_column(ForeignKey("organization_units.id"))
    capacity: Mapped[int] = mapped_column(Integer)
    occupied: Mapped[int] = mapped_column(Integer, default=0)
    manager_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
