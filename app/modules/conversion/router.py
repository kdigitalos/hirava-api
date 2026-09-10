import hashlib
import json
from app.core.routing import APIRouter
from fastapi import Depends, Header, HTTPException, Query, Request
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.schemas import Input
from app.core.security import require
from app.core.service import audit, rows, view
from app.data.database import get_db
from app.modules.conversion.models import Conversion
from app.modules.offers.service import accepted_hire
from app.modules.workforce.service import create_prehire

router = APIRouter(prefix="/conversion", tags=["hire-to-onboard"], dependencies=[Depends(require("hr", module="rms"))])


class ConversionApproval(Input):
    offer_id: str
    user_id: str | None = None
    approval_reason: str = Field(min_length=3, max_length=2000)


@router.get("/offers/{offer_id}/preview")
def preview(offer_id: str, user=Depends(require("hr", module="hrms")), db: Session = Depends(get_db)):
    return {"offer_id": offer_id, "mapping": accepted_hire(db, offer_id, user.customer_id),
            "excluded": ["interview_notes", "scorecards", "unrelated_consent", "rejected_applications"],
            "requires_hr_approval": True, "employment_status_on_creation": "prehire"}


@router.post("/approve", status_code=201)
def approve_conversion(body: ConversionApproval, request: Request,
                       idempotency_key: str = Header(min_length=8, max_length=100),
                       user=Depends(require("hr", module="hrms")), db: Session = Depends(get_db)):
    fingerprint = hashlib.sha256(json.dumps(body.model_dump(), sort_keys=True).encode()).hexdigest()
    # Lock the source offer first so concurrent retries serialize on PostgreSQL.
    mapping = accepted_hire(db, body.offer_id, user.customer_id)
    existing = db.scalar(select(Conversion).where(Conversion.customer_id == user.customer_id,
                                                Conversion.idempotency_key == idempotency_key))
    if existing:
        if existing.request_hash != fingerprint:
            raise HTTPException(409, "Idempotency key was used with a different request")
        return view(existing)
    prior = db.scalar(select(Conversion).where(Conversion.offer_id == body.offer_id, Conversion.customer_id == user.customer_id))
    if prior:
        raise HTTPException(409, "Offer already converted; use its original idempotency key")
    worker, employment, _ = create_prehire(db, user, **mapping, user_id=body.user_id, request=request)
    record = Conversion(customer_id=user.customer_id, offer_id=body.offer_id, worker_id=worker.id,
                        employment_id=employment.id, approved_by=user.id, idempotency_key=idempotency_key,
                        request_hash=fingerprint)
    db.add(record)
    audit(db, user, "conversion.approved", record, request, reason=body.approval_reason)
    return view(record)


@router.get("")
def conversions(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
                user=Depends(require("hr", module="hrms")), db: Session = Depends(get_db)):
    return [view(row) for row in rows(db, Conversion, user.customer_id, offset, limit)]
