"""Screen actual candidate documents, using reviewed criteria and a durable queue."""
import asyncio
import hashlib
import json
import logging
import re
from datetime import timedelta
from pathlib import PurePosixPath
from uuid import uuid4

from fastapi import Depends, HTTPException, Request
from pydantic import Field, ValidationError
from sqlalchemy import select, update

from app.agents.models import ScreeningJob
from app.agents.providers import provider_config as shared_provider_config
from app.agents.employment import refined_review
from app.agents.pilot import extract_document
from app.agents.screening import (
    Criterion, Finding, ScreeningError, ScreeningInput, StrictModel, build_screening_graph,
    candidate_summary, create_provider, validated_criteria,
)
from app.core import imported_storage, object_storage
from app.core.compatibility_routing import APIRouter
from app.core.models import AuditEvent, User
from app.core.security import require
from app.data.database import get_db, utcnow
from app.modules.recruiting.pipeline_api import candidate, job, profile

router = APIRouter(prefix="/api/candidate", tags=["Candidate assessments"])
allowed = require("hr", "recruiter", module="rms")
ACTIVE = ("queued", "processing")


class AssessmentRequest(StrictModel):
    rubric_version: str = Field(default="auto-v1", min_length=1, max_length=100)
    criteria: list[Criterion] | None = Field(default=None, min_length=1, max_length=20)
    allow_provider_processing: bool = False


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def context(db, user, candidate_id, lock=False):
    _, row = candidate(db, user, candidate_id, lock=lock)
    parent = job(db, user, row["job_opening_id"], lock=lock)
    # Any profile edit invalidates a previous assessment, including a replaced resume.
    source_hash = digest([row["job_opening_id"], row["object"], parent.description])
    return row, parent, source_hash


def resume_location(db, user, row):
    ref = profile(row).get("resume")
    if not isinstance(ref, str):
        raise ScreeningError("Upload a resume before running an assessment.")
    match = re.fullmatch(r"/api/v1/careers/resumes/([0-9a-f]{32})", ref)
    if match:
        return "core", f"resumes/{match[1]}.pdf", ".pdf"
    # Only immutable uploads owned by this customer's users; never follow a URL.
    match = re.fullmatch(r"/api/uploads/(user-uploads/([^/]+)/[0-9a-f]{32}\.(pdf|docx|txt|png|jpg|jpeg))", ref)
    if match:
        owner = db.scalar(select(User.id).where(User.id == match[2], User.customer_id == user.customer_id))
        if owner:
            from app.workers.imported_storage_cleanup import is_deleted
            if not is_deleted(db, user.customer_id, match[1]):
                return "imported", match[1], PurePosixPath(match[1]).suffix
    raise ScreeningError("This resume cannot be assessed. Upload a PDF, DOCX, TXT, PNG or JPEG through Hirava.")


def provider_config(settings):
    config = shared_provider_config(settings)
    return config.provider, config.model, config.ready


def latest(db, user, candidate_id):
    return db.scalar(select(ScreeningJob).where(ScreeningJob.customer_id == user.customer_id,
        ScreeningJob.candidate_id == candidate_id).order_by(ScreeningJob.created_at.desc(), ScreeningJob.id.desc()))


def serialized(record, source_hash):
    if record is None:
        return None
    stale = record.source_hash != source_hash
    result = None if stale else record.result
    if result and result.get("employment_history"):
        result = {**result, "employment_history": refined_review(result["employment_history"])}
    if result and "candidate_summary" not in result:
        # Derive a display summary for older validated results without mutating history.
        try:
            criteria = [Criterion.model_validate(item) for item in result["criteria"]]
            findings = [Finding.model_validate(item) for item in result["findings"]]
            result = {**result, "candidate_summary": candidate_summary(criteria, findings),
                      "summary_version": "evidence-summary-v1"}
        except (KeyError, TypeError, ValidationError):
            pass  # Older incompatible results remain readable without a summary.
    return {"id": record.id, "status": record.status, "stale": stale,
        "created_at": record.created_at, "finished_at": record.finished_at,
        "rubric": record.rubric, "provider": record.provider, "model": record.model,
        "result": result, "error": record.error}


@router.get("/{candidate_id}/assessment")
def read_assessment(candidate_id: int, request: Request, user=Depends(allowed), db=Depends(get_db)):
    row, parent, source_hash = context(db, user, candidate_id)
    settings = request.app.state.settings
    provider, model, key_present = provider_config(settings)
    reason = None
    if not settings.ai_screening_enabled or not model or not key_present:
        reason = "AI assessment is not configured. Contact your administrator."
    elif len((parent.description or "").strip()) < 50:
        reason = "Add a meaningful job description (at least 50 characters) before assessing candidates."
    else:
        try:
            resume_location(db, user, row)
        except ScreeningError as exc:
            reason = str(exc)
    return {"job_description": parent.description, "job_title": parent.title,
        "can_run": reason is None, "unavailable_reason": reason,
        "provider": provider, "model": model, "assessment": serialized(latest(db, user, candidate_id), source_hash)}


@router.post("/{candidate_id}/assessment", status_code=202)
def queue_assessment(candidate_id: int, body: AssessmentRequest, request: Request,
                     user=Depends(allowed), db=Depends(get_db)):
    row, parent, source_hash = context(db, user, candidate_id, lock=True)
    settings = request.app.state.settings
    provider, model, key_present = provider_config(settings)
    if not settings.ai_screening_enabled or not model or not key_present:
        raise HTTPException(503, "AI assessment is not configured. Contact your administrator.")
    if not body.allow_provider_processing:
        raise HTTPException(422, "Confirm permission to process this resume and job description.")
    try:
        resume_location(db, user, row)
        # Validate the reviewed rubric before queuing or reading sensitive S3 content.
        ScreeningInput(resume_text="Validation placeholder. " * 3,
                       job_description=parent.description,
                       rubric_version=body.rubric_version, criteria=body.criteria or [Criterion(
                           id="validation", description="Job description validation",
                           jd_quote=(parent.description or "")[:100], weight=1)])
    except ValidationError:
        raise HTTPException(422, "Use a job description of 50–20,000 characters, unique criterion IDs and exact quotes from that description.") from None
    except ScreeningError as exc:
        raise HTTPException(422, str(exc)) from None
    rubric = body.model_dump(exclude={"allow_provider_processing"})
    if body.criteria is None:
        rubric = {"rubric_version": "auto-v1", "criteria": [], "mode": "automatic",
                  "job_id": parent.id, "jd_hash": digest(parent.description)}
    request_hash = digest([source_hash, rubric, provider, model])
    previous = latest(db, user, candidate_id)
    if previous and (previous.status in ACTIVE or (
            previous.request_hash == request_hash and previous.status in ("needs_review", "insufficient_evidence")
            and "employment_history" in (previous.result or {}))):
        return serialized(previous, source_hash)
    record = ScreeningJob(customer_id=user.customer_id, candidate_id=candidate_id,
        actor_id=user.id, active_slot=f"{user.customer_id}:{candidate_id}",
        source_hash=source_hash, request_hash=request_hash, rubric=rubric, provider=provider, model=model)
    db.add(record)
    db.flush()
    db.add(AuditEvent(customer_id=user.customer_id, actor_id=user.id,
        action="screening.requested", resource_type="screening_job", resource_id=record.id,
        correlation_id=request.state.correlation_id,
        details={"candidate_id": candidate_id, "rubric_version": body.rubric_version,
                 "provider_processing_confirmed": True, "provider": provider, "model": model}))
    return serialized(record, source_hash)


def claim(sessions, settings):
    """CAS claim prevents duplicate provider calls across FastAPI processes."""
    with sessions.begin() as db:
        # Crashed work is never automatically re-sent to the paid provider.
        cutoff = utcnow() - timedelta(minutes=15)
        db.execute(update(ScreeningJob).where(ScreeningJob.customer_id == settings.customer_id,
            ScreeningJob.status == "processing", ScreeningJob.started_at < cutoff).values(
                status="failed", active_slot=None, finished_at=utcnow(),
                error="Assessment interrupted. Review and run it again; the previous request may have reached the provider."))
        record_id = db.scalar(select(ScreeningJob.id).where(
            ScreeningJob.customer_id == settings.customer_id, ScreeningJob.status == "queued")
            .order_by(ScreeningJob.created_at).limit(1))
        if not record_id:
            return None
        changed = db.execute(update(ScreeningJob).where(ScreeningJob.id == record_id,
            ScreeningJob.status == "queued").values(status="processing", started_at=utcnow()))
        return record_id if changed.rowcount == 1 else None


def authorized_source(db, settings, record, lock=False):
    user = db.get(User, record.actor_id)
    if (not settings.rms_enabled or not user or not user.active or
            user.customer_id != settings.customer_id or user.customer_id != record.customer_id or
            user.role not in ("admin", "hr", "recruiter")):
        raise ScreeningError("The requesting user no longer has permission to assess this candidate.")
    row, parent, source_hash = context(db, user, record.candidate_id, lock=lock)
    if record.rubric.get("trigger") == "public_intake":
        from app.agents.intake import intake_offer
        offer = intake_offer(settings, db)
        if (not offer or settings.ai_screening_intake_actor_id != record.actor_id
                or offer["consent_token"] != record.rubric.get("consent_token")
                or profile(row).get("aiConsent") != record.rubric.get("intake_consent")):
            raise ScreeningError("Automatic screening permission or configuration changed. A reviewer must assess this application manually.")
    if source_hash != record.source_hash:
        raise ScreeningError("The candidate or job description changed. Review the criteria and run a new assessment.")
    return user, row, parent


def automatic_rubric(sessions, settings, record_id, provider, description, rubric):
    """Reuse generated criteria for this tenant/job/JD/provider; never reuse resume evidence."""
    with sessions() as db:
        record = db.get(ScreeningJob, record_id)
        cached = db.scalar(select(ScreeningJob).where(
            ScreeningJob.customer_id == record.customer_id,
            ScreeningJob.provider == record.provider, ScreeningJob.model == record.model,
            ScreeningJob.rubric["job_id"].as_string() == rubric["job_id"],
            ScreeningJob.rubric["jd_hash"].as_string() == rubric["jd_hash"],
            ScreeningJob.rubric["mode"].as_string() == "automatic",
            ScreeningJob.rubric["rubric_version"].as_string() == "auto-v1",
            ScreeningJob.status.in_(("needs_review", "insufficient_evidence")),
        ).order_by(ScreeningJob.created_at.desc()).limit(1))
        cached_rubric = cached.rubric if cached else None
    if cached_rubric:
        criteria = validated_criteria(description, {"criteria": cached_rubric["criteria"]})
        generated = {**rubric, "criteria": criteria, "generation": cached_rubric["generation"],
                     "reused": True}
    else:
        generation = provider.generate_criteria(description)
        criteria = validated_criteria(description, {"criteria": generation["criteria"]})
        generated = {**rubric, "criteria": criteria,
                     "generation": {k: v for k, v in generation.items() if k != "criteria"}, "reused": False}
    with sessions.begin() as db:
        record = db.get(ScreeningJob, record_id)
        authorized_source(db, settings, record)
        if record.status != "processing":
            raise ScreeningError("Assessment interrupted. Run it again.")
        record.rubric = generated
    return generated


def process_one(app):
    settings, sessions = app.state.settings, app.state.sessions
    if not settings.ai_screening_enabled:
        return False
    record_id = claim(sessions, settings)
    if not record_id:
        return False
    provider = None
    result, error = None, None
    try:
        with sessions() as db:
            record = db.get(ScreeningJob, record_id)
            user, row, parent = authorized_source(db, settings, record)
            storage, key, suffix = resume_location(db, user, row)
            rubric, description = record.rubric, parent.description
            requested_rubric = dict(rubric)
            if (record.provider, record.model) != provider_config(settings)[:2]:
                raise ScreeningError("AI configuration changed. Review and run the assessment again.")
        stream = (object_storage.download(settings, key) if storage == "core"
                  else imported_storage.open_file(settings, key)[0])
        try:
            content = stream.read(5 * 1024 * 1024 + 1)
        finally:
            stream.close()
        extraction = extract_document(content, suffix)
        resume_text = extraction["text"]
        provider = create_provider(settings)
        from langsmith import tracing_context
        with tracing_context(enabled=False):
            if rubric.get("mode") == "automatic":
                rubric = automatic_rubric(sessions, settings, record_id, provider, description, rubric)
            with sessions() as db:
                authorized_source(db, settings, db.get(ScreeningJob, record_id))
            source = ScreeningInput(resume_text=resume_text, job_description=description,
                                    rubric_version=rubric["rubric_version"], criteria=rubric["criteria"])
            result = build_screening_graph(provider).invoke({"source": source})["result"]
            result["document_extraction"] = {key: value for key, value in extraction.items() if key != "text"}
            if extraction["ocr_pages"]:
                result["limitations"].append("Local OCR was used. Verify names, dates, skills and quoted passages against the original resume; OCR can misread text.")
            if rubric.get("mode") == "automatic":
                result["criteria_generation"] = rubric["generation"]
                result["criteria_reused"] = rubric["reused"]
                result["workflow_version"] = "screening-auto-v1"
    except ScreeningError as exc:
        error = str(exc)
    except ValidationError:
        error = "The resume or job criteria exceed the assessment limits. Review the documents and try again."
    except Exception:
        # Never record provider exception bodies, credentials or resume content in logs.
        error = "Assessment could not be completed. Check the resume and AI service configuration, then retry."
    finally:
        if provider is not None:
            provider.close()
    with sessions.begin() as db:
        record = db.get(ScreeningJob, record_id)
        if record.status != "processing":
            return True
        if not error:
            try:
                _, current_row, current_parent = authorized_source(db, settings, record, lock=True)
            except (ScreeningError, HTTPException):
                error = "Candidate details or access changed during assessment. Review and run it again."
        if not error and result.get("profile_extraction"):
            from app.agents.profile_extraction import fill_blank_fields
            from app.modules.recruiting.public_intake import pipeline_table
            extraction = result["profile_extraction"]
            updated, filled, preserved = fill_blank_fields(current_row["object"], extraction["fields"], record.id)
            extraction.update(filled_fields=filled, preserved_fields=preserved)
            if filled:
                table = pipeline_table(db)
                db.execute(table.update().where(table.c.id == record.candidate_id).values(
                    object=updated, updated_at=utcnow(), updated_by="resume-ai"))
                # Our own atomic fill must not invalidate the assessment it belongs to.
                record.source_hash = digest([current_row["job_opening_id"], updated, current_parent.description])
                record.request_hash = digest([record.source_hash, requested_rubric, record.provider, record.model])
                db.add(AuditEvent(customer_id=record.customer_id, actor_id=None,
                    action="candidate.profile_autofilled", resource_type="candidate", resource_id=str(record.candidate_id),
                    correlation_id=str(uuid4()), details={"assessment_id": record.id,
                        "authorization_user_id": record.actor_id, "filled_fields": filled, "review_required": True}))
        record.status = "failed" if error else result["status"]
        record.result = None if error else result
        record.error, record.active_slot, record.finished_at = error, None, utcnow()
        db.add(AuditEvent(customer_id=record.customer_id, actor_id=record.actor_id,
            action=f"screening.{record.status}", resource_type="screening_job", resource_id=record.id,
            correlation_id=str(uuid4()), details={"candidate_id": record.candidate_id}))
    return True


async def run_screening(app, stop):
    while not stop.is_set():
        try:
            await asyncio.to_thread(process_one, app)
        except Exception:
            logging.getLogger(__name__).error("Screening queue unavailable; no sensitive details logged")
        try:
            await asyncio.wait_for(stop.wait(), timeout=3)
        except TimeoutError:
            pass
