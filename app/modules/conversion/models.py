from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.data.database import Record


class Conversion(Record):
    __tablename__ = "conversions"
    __table_args__ = (UniqueConstraint("offer_id"), UniqueConstraint("customer_id", "idempotency_key"))
    offer_id: Mapped[str] = mapped_column(ForeignKey("offers.id"))
    worker_id: Mapped[str] = mapped_column(ForeignKey("workers.id"))
    employment_id: Mapped[str] = mapped_column(ForeignKey("employments.id"))
    approved_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    idempotency_key: Mapped[str] = mapped_column(String(100))
    request_hash: Mapped[str] = mapped_column(String(64))
