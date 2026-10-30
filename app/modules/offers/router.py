from datetime import date
from decimal import Decimal
from app.core.routing import APIRouter
from fastapi import Depends, HTTPException, Query, Request
from pydantic import Field
from sqlalchemy.orm import Session
from app.core.schemas import Decision, Input
from app.core.security import require
from app.core.service import audit, find, rows, state_is, view
from app.data.database import get_db
from app.modules.offers.models import Offer
from app.modules.recruiting.service import application_reference

router = APIRouter(prefix="/rms/offers", tags=["offers"])


class OfferCreate(Input):
    application_id: str
    annual_salary: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    currency: str = Field(pattern="^[A-Z]{3}$")
    start_date: date


@router.post("", status_code=201)
def create_offer(body: OfferCreate, request: Request, user=Depends(require("recruiter", module="rms")), db: Session = Depends(get_db)):
    application = application_reference(db, body.application_id, user.customer_id, lock=True)
    state_is(application, "selected")
    if body.start_date < date.today():
        raise HTTPException(422, "Start date cannot be in the past")
    record = Offer(customer_id=user.customer_id, created_by=user.id, **body.model_dump())
    db.add(record)
    audit(db, user, "offer.created", record, request)
    return view(record)


@router.get("")
def list_offers(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
                user=Depends(require("recruiter", "hr", module="rms")), db: Session = Depends(get_db)):
    return [view(row) for row in rows(db, Offer, user.customer_id, offset, limit)]


@router.post("/{record_id}/submit")
def submit_offer(record_id: str, request: Request, user=Depends(require("recruiter", module="rms")), db: Session = Depends(get_db)):
    record = find(db, Offer, record_id, user.customer_id, lock=True)
    state_is(record, "draft")
    record.status = "submitted"
    audit(db, user, "offer.submitted", record, request)
    return view(record)


@router.post("/{record_id}/approve")
def approve_offer(record_id: str, body: Decision, request: Request,
                  user=Depends(require("hr", module="rms")), db: Session = Depends(get_db)):
    record = find(db, Offer, record_id, user.customer_id, lock=True)
    state_is(record, "submitted")
    if record.created_by == user.id:
        raise HTTPException(403, "A different approver must approve the offer")
    record.status, record.approved_by = "approved", user.id
    audit(db, user, "offer.approved", record, request, reason=body.reason)
    return view(record)


@router.post("/{record_id}/accept")
def accept_offer(record_id: str, body: Decision, request: Request,
                 user=Depends(require("recruiter", module="rms")), db: Session = Depends(get_db)):
    record = find(db, Offer, record_id, user.customer_id, lock=True)
    state_is(record, "approved")
    record.status, record.acceptance_evidence = "accepted", body.reason
    audit(db, user, "offer.acceptance_recorded", record, request)
    return view(record)


@router.post("/{record_id}/decline")
def decline_offer(record_id: str, body: Decision, request: Request,
                  user=Depends(require("recruiter", module="rms")), db: Session = Depends(get_db)):
    record = find(db, Offer, record_id, user.customer_id, lock=True)
    state_is(record, "approved")
    record.status = "declined"
    audit(db, user, "offer.declined", record, request, reason=body.reason)
    return view(record)
