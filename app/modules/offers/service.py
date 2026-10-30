from fastapi import HTTPException
from app.core.service import find, state_is
from app.modules.offers.models import Offer
from app.modules.recruiting.service import hire_identity
from sqlalchemy import select
from app.core.service import audit


def accepted_hire(db, offer_id, customer_id):
    offer = find(db, Offer, offer_id, customer_id, lock=True)
    state_is(offer, "accepted")
    if not offer.acceptance_evidence:
        raise HTTPException(409, "Acceptance evidence is required")
    return {**hire_identity(db, offer.application_id, customer_id), "start_date": offer.start_date}


def candidate_offers(db, application_ids, customer_id, offset, limit):
    records = db.scalars(select(Offer).where(Offer.customer_id == customer_id, Offer.application_id.in_(application_ids),
                        Offer.status.in_(["approved", "accepted", "declined"])).order_by(Offer.created_at.desc(), Offer.id).offset(offset).limit(limit))
    return [{"id": row.id, "application_id": row.application_id, "annual_salary": row.annual_salary,
             "currency": row.currency, "start_date": row.start_date, "status": row.status} for row in records]


def candidate_accept_offer(db, offer_id, application_ids, user, evidence, request):
    record = db.scalar(select(Offer).where(Offer.id == offer_id, Offer.customer_id == user.customer_id,
                       Offer.application_id.in_(application_ids)).with_for_update())
    if not record:
        raise HTTPException(404, "Offer not found")
    state_is(record, "approved")
    record.status, record.acceptance_evidence = "accepted", evidence
    audit(db, user, "offer.accepted_by_candidate", record, request)
    return {"id": record.id, "status": record.status}
