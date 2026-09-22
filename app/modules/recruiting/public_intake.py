"""Anonymous intake into the existing RMS pipeline; no login account is created."""
from datetime import datetime, timezone
from io import BytesIO
from time import monotonic
from uuid import uuid4
import logging

from fastapi import Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import Column, DateTime, Integer, JSON, MetaData, String, Table, select
from starlette.datastructures import UploadFile

from app.core import object_storage
from app.core.security import require
from app.data.database import get_db
from app.modules.recruiting.models import JobReference, Requisition


def pipeline_table(db):
    # This is an existing imported table, deliberately not part of native migrations.
    return Table("rms_candidate", MetaData(),
        Column("id", Integer, primary_key=True), Column("job_opening_id", Integer),
        Column("object", JSON), Column("questions", JSON), Column("status", String),
        Column("contacted", String), Column("updated_by", String),
        Column("created_at", DateTime), Column("updated_at", DateTime),
        schema="public" if db.bind.dialect.name == "postgresql" else None)


def published_job(db, alias, settings):
    job = db.scalar(select(Requisition).join(JobReference, JobReference.requisition_id == Requisition.id)
        .where(JobReference.id == alias, Requisition.customer_id == settings.customer_id,
               Requisition.status == "published").with_for_update())
    if not settings.rms_enabled or not job:
        raise HTTPException(404, "This job is no longer accepting applications.")
    return job


def field(name, label, value, kind="text"):
    return {"name": name, "label": label, "value": value, "type": kind, "isChecked": True, "mandator": False}


async def submit_public(alias: int, request: Request, db=Depends(get_db)):
    settings = request.app.state.settings
    # Bounded application-wide throttle also works behind the local BFF without trusting forwarded IPs.
    with request.app.state.login_lock:
        now = monotonic()
        attempts = [t for t in getattr(request.app.state, "public_intake_attempts", []) if now - t < 60]
        if len(attempts) >= 20:
            raise HTTPException(429, "Too many applications at once. Please wait a minute and try again.")
        request.app.state.public_intake_attempts = attempts + [now]
    parent = published_job(db, alias, settings)
    limit = min(settings.max_upload_bytes, 5 * 1024 * 1024)
    # Bound the entire multipart body, including requests without Content-Length.
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > limit + 64 * 1024:
            raise HTTPException(413, "Your resume must be a PDF, PNG or JPEG no larger than 5 MB.")
    request._body = bytes(body)
    async with request.form(max_files=1, max_fields=6) as form:
        name, email, phone = (str(form.get(k, "")).strip() for k in ("name", "email", "phone"))
        if not 2 <= len(name) <= 200:
            raise HTTPException(422, "Enter your full name (2 to 200 characters).")
        try:
            email = str(TypeAdapter(EmailStr).validate_python(email)).lower()
        except ValidationError:
            raise HTTPException(422, "Enter a valid email address.") from None
        if not 7 <= len(''.join(c for c in phone if c.isdigit())) <= 15 or len(phone) > 30 or any(c not in "0123456789+()- ." for c in phone):
            raise HTTPException(422, "Enter a valid phone number, including your country code.")
        if form.get("consent") != "on":
            raise HTTPException(422, "Please agree to share your details with the hiring team.")
        ai_consent = str(form.get("ai_consent", ""))
        resume = form.get("resume")
        if not isinstance(resume, UploadFile) or not (resume.filename or "").lower().endswith((".pdf", ".png", ".jpg", ".jpeg")):
            raise HTTPException(422, "Attach your resume as a PDF, PNG or JPEG file.")
        content = await resume.read(limit + 1)
        if len(content) > limit:
            raise HTTPException(413, "Your resume must be no larger than 5 MB.")
        if not (resume.filename or "").lower().endswith(".pdf"):
            from app.agents.ocr import image_pdf
            try:
                content = image_pdf(content)
            except Exception:
                raise HTTPException(422, "Use a valid single PNG or JPEG image of at most 20 megapixels.") from None
            if len(content) > limit:
                raise HTTPException(413, "Converted resume exceeds 5 MB. Upload a smaller image.")
        if not content.startswith(b"%PDF-") or b"%%EOF" not in content[-2048:]:
            raise HTTPException(422, "This file is not a valid PDF. Please choose a PDF resume.")
    table = pipeline_table(db)
    # The job lock serializes guest retries, including concurrent submissions.
    existing = db.execute(select(table.c.object).where(table.c.job_opening_id == alias)).scalars()
    for profile in existing:
        if isinstance(profile, list) and any(f.get("name") == "email" and str(f.get("value", "")).lower() == email for f in profile if isinstance(f, dict)):
            return {"message": "Your application has been received. The hiring team will review it."}
    if not settings.aws_bucket_name:
        raise HTTPException(503, "Resume storage is temporarily unavailable. Please try again later.")
    receipt = uuid4().hex
    key = f"resumes/{receipt}.pdf"
    object_storage.upload(settings, key, BytesIO(content))
    now = datetime.now(timezone.utc)
    first, _, last = name.partition(" ")
    from app.agents.intake import intake_offer, queue_intake
    offer = intake_offer(settings, db) if 50 <= len((parent.description or "").strip()) <= 20000 else None
    opted_in = bool(offer and ai_consent == offer["consent_token"])
    consent_text = (f"Agreed to resume and job-description processing by {offer['provider']}; "
                    f"{offer['notice_version']}; {now.isoformat()}" if opted_in else "Not opted in to automatic AI screening.")
    profile = [field("firstName", "First name", first), field("lastName", "Last name", last),
        field("email", "Email", email, "email"), field("mobile", "Phone", phone, "tel"),
        {**field("resume", "Resume", f"/api/v1/careers/resumes/{receipt}", "file"), "fileName": "resume.pdf"},
        field("consent", "Application consent", "Agreed to share profile with the hiring team for this application; careers-application-v1; " + now.isoformat()),
        field("aiConsent", "Automatic AI screening consent", consent_text)]
    try:
        inserted = db.execute(table.insert().values(job_opening_id=alias, object=profile, questions=[],
            status="", contacted="Not contacted", updated_by="public-application",
            created_at=now, updated_at=now).returning(table)).mappings().one()
        from app.agents.tracking import activity
        activity(db, settings.customer_id, None, "application_created", inserted["id"], alias, after="Unassessed")
        if opted_in:
            try:
                with db.begin_nested():
                    queue_intake(db, request, parent, inserted, offer, consent_text)
            except Exception:
                # A queue outage must not discard an otherwise valid application.
                logging.getLogger(__name__).error("Intake screening queue failed; application retained for manual review")
                from app.core.models import AuditEvent
                db.add(AuditEvent(customer_id=settings.customer_id, actor_id=None,
                    action="screening.intake_queue_failed", resource_type="candidate", resource_id=str(inserted["id"]),
                    correlation_id=request.state.correlation_id, details={"manual_review_required": True}))
        db.commit()  # Commit before acknowledging; remove an orphan object on a failed write.
    except Exception:
        db.rollback()
        try:
            object_storage.s3_client(settings).delete_object(Bucket=settings.aws_bucket_name,
                Key=object_storage.object_key(settings, key))
        except Exception:
            pass
        raise
    return {"message": "Your application has been received. The hiring team will review it."}


def staff_resume(receipt: str, request: Request, preview: bool = False, user=Depends(require("admin", "hr", "recruiter", module="rms")), db=Depends(get_db)):
    if len(receipt) != 32 or any(c not in "0123456789abcdef" for c in receipt):
        raise HTTPException(404, "Resume not found")
    table = pipeline_table(db)
    records = db.execute(select(table.c.object).join(JobReference, JobReference.id == table.c.job_opening_id)
        .join(Requisition, Requisition.id == JobReference.requisition_id)
        .where(Requisition.customer_id == user.customer_id)).scalars()
    url = f"/api/v1/careers/resumes/{receipt}"
    if not any(isinstance(profile, list) and any(isinstance(f, dict) and f.get("name") == "resume" and f.get("value") == url for f in profile) for profile in records):
        raise HTTPException(404, "Resume not found")
    stream = object_storage.download(request.app.state.settings, f"resumes/{receipt}.pdf")
    def chunks():
        try:
            while chunk := stream.read(64 * 1024):
                yield chunk
        finally:
            stream.close()
    disposition = "inline" if preview else "attachment"
    return StreamingResponse(chunks(), media_type="application/pdf", headers={"Content-Disposition": f'{disposition}; filename="resume.pdf"'})
