"""Opt-in public-intake screening. Never performs provider I/O during submission."""
import hashlib
import json

from sqlalchemy import select

from app.core.models import AuditEvent, User

NOTICE_VERSION = "intake-screening-v1"


def intake_offer(settings, db):
    """Only advertise processing that this installation is ready to queue."""
    from app.agents.application import provider_config
    provider, model, key_present = provider_config(settings)
    if not (settings.rms_enabled and settings.ai_screening_enabled and settings.ai_screening_on_intake
            and model and key_present and settings.ai_screening_intake_actor_id):
        return None
    actor = db.scalar(select(User).where(User.id == settings.ai_screening_intake_actor_id,
        User.customer_id == settings.customer_id, User.active.is_(True),
        User.role.in_(("admin", "hr", "recruiter"))))
    if actor is None:
        return None
    token = hashlib.sha256(json.dumps([NOTICE_VERSION, provider, model]).encode()).hexdigest()
    return {"provider": provider, "consent_token": token, "notice_version": NOTICE_VERSION}


def queue_intake(db, request, parent, row, offer, consent_text):
    from app.agents.application import digest
    from app.agents.models import ScreeningJob
    from app.agents.application import provider_config
    settings = request.app.state.settings
    provider, model, _ = provider_config(settings)
    source_hash = digest([row["job_opening_id"], row["object"], parent.description])
    rubric = {"rubric_version": "auto-v1", "criteria": [], "mode": "automatic",
              "job_id": parent.id, "jd_hash": digest(parent.description),
              "trigger": "public_intake", "intake_consent": consent_text,
              "consent_token": offer["consent_token"]}
    record = ScreeningJob(customer_id=settings.customer_id, candidate_id=row["id"],
        actor_id=settings.ai_screening_intake_actor_id,
        active_slot=f"{settings.customer_id}:{row['id']}", source_hash=source_hash,
        request_hash=digest([source_hash, rubric, provider, model]), rubric=rubric,
        provider=provider, model=model)
    db.add(record)
    db.flush()
    db.add(AuditEvent(customer_id=settings.customer_id, actor_id=None,
        action="screening.intake_requested", resource_type="screening_job", resource_id=record.id,
        correlation_id=request.state.correlation_id,
        details={"candidate_id": row["id"], "trigger": "public_intake",
                 "authorization_user_id": record.actor_id, "notice_version": NOTICE_VERSION,
                 "provider": provider, "model": model, "provider_processing_confirmed": True}))
