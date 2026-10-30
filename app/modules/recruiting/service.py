from app.core.service import find
from app.modules.recruiting.models import Application, Candidate, Requisition


def application_reference(db, application_id, customer_id, lock=False):
    return find(db, Application, application_id, customer_id, lock=lock)


def hire_identity(db, application_id, customer_id):
    application = application_reference(db, application_id, customer_id)
    candidate = find(db, Candidate, application.candidate_id, customer_id)
    requisition = find(db, Requisition, application.requisition_id, customer_id)
    # Explicit allowlist: interview notes, scorecards, and consent are excluded.
    return {"name": candidate.name, "email": candidate.email, "position_id": requisition.position_id}


def interview_packet(db, application_id, customer_id):
    application = application_reference(db, application_id, customer_id)
    candidate = find(db, Candidate, application.candidate_id, customer_id)
    requisition = find(db, Requisition, application.requisition_id, customer_id)
    return {"candidate_name": candidate.name, "job_title": requisition.title, "job_description": requisition.description}
