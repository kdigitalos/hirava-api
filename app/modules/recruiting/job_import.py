"""Read a job document into an unsaved form; never create jobs or retain uploads."""
import json
import re
from pathlib import Path
from threading import Lock
from typing import Annotated

from fastapi import Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import TypeAdapter, ValidationError

from app.core.routing import APIRouter
from app.core.security import require
from app.agents.pilot import extract_document
from app.agents.screening import ScreeningError
from app.agents.recruiter_tools import generate
from app.modules.recruiting.schemas import JobDetails, RequisitionCreate

router = APIRouter(prefix="/rms", tags=["recruiting"])
MAX_BYTES = 4 * 1024 * 1024
_lock = Lock()
_active = set()
FIELDS = {"title", "company_name", "department", "location", "job_type", "work_mode",
          "job_link", "hiring_due_date", "date_opened", "target_date", "budget", "salary_min",
          "salary_max", "currency", "no_of_openings", "required_skills", "hiring_flow", "experience_years", "notice_period"}


def import_actor(user=Depends(require("recruiter", "manager", module="rms"))):
    key = (user.customer_id, user.id)
    with _lock:
        if key in _active:
            raise HTTPException(409, "A document is already being read. Wait for it to finish.")
        _active.add(key)
    try:
        yield user
    finally:
        with _lock:
            _active.discard(key)


def form_fields(result, text):
    fields = {"description": text}
    warnings = list(result.get("limitations", []))
    seen = set()
    for section in result["sections"]:
        name, raw = section["title"], section["text"]
        if name not in FIELDS:
            continue
        if name in seen:
            fields.pop(name, None)
            warnings.append(f"Conflicting values for {name}; enter it manually.")
            continue
        seen.add(name)
        definition = (RequisitionCreate if name == "title" else JobDetails).model_fields[name]
        try:
            value = json.loads(raw) if name == "required_skills" else raw
            annotation = Annotated[definition.annotation, *definition.metadata] if definition.metadata else definition.annotation
            adapter = TypeAdapter(annotation)
            fields[name] = adapter.dump_python(adapter.validate_python(value), mode="json")
        except (ValueError, ValidationError, TypeError):
            warnings.append(f"Could not read {name}; enter it manually.")
    aliases = {
        "job_type": {"fulltime": "Full-Time", "contract": "Contract", "freelance": "Free-lancing", "freelancing": "Free-lancing"},
        "work_mode": {"remote": "Work from Home", "wfh": "Work from Home", "workfromhome": "Work from Home", "hybrid": "Hybrid", "onsite": "Work from Office", "office": "Work from Office", "wfo": "Work from Office", "workfromoffice": "Work from Office"},
    }
    for name, options in aliases.items():
        if name in fields:
            value = options.get(re.sub(r"[\s_-]", "", fields[name].lower()))
            if value:
                fields[name] = value
            else:
                fields.pop(name)
                warnings.append(f"Choose {name.replace('_', ' ')} manually; the document does not match an available option.")
    if not fields.get("currency"):
        for name in ("budget", "salary_min", "salary_max"):
            if name in fields:
                fields.pop(name)
                warnings.append(f"{name} needs a clear currency; enter it manually.")
    if "salary_min" in fields and "salary_max" in fields:
        from decimal import Decimal
        if Decimal(fields["salary_max"]) < Decimal(fields["salary_min"]):
            fields.pop("salary_min")
            fields.pop("salary_max")
            warnings.append("The salary range is inconsistent; enter it manually.")
    if fields.get("job_link") and not fields["job_link"].startswith(("https://", "http://")):
        fields.pop("job_link")
        warnings.append("The job link is not a valid web address; enter it manually.")
    return {"fields": fields, "warnings": list(dict.fromkeys(warnings)), "review_required": True}


@router.post("/job-document")
def import_job_document(request: Request, file: UploadFile = File(...),
                        allow_provider_processing: bool = Form(False), user=Depends(import_actor)):
    try:
        if not allow_provider_processing:
            raise HTTPException(422, "Confirm AI processing of this job document before uploading.")
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in {".pdf", ".docx"}:
            raise HTTPException(422, "Upload a PDF or Word (.docx) file. Save older .doc files as .docx first.")
        content = file.file.read(MAX_BYTES + 1)
        if len(content) > MAX_BYTES:
            raise HTTPException(413, "The job document must be 4 MB or smaller.")
        if not content or (suffix == ".pdf" and not content.startswith(b"%PDF-")) or (
                suffix == ".docx" and not content.startswith(b"PK")):
            raise HTTPException(422, "The file contents do not match a readable PDF or Word document.")
        try:
            extracted = extract_document(content, suffix)
        except ScreeningError:
            raise HTTPException(422, "Could not read this document. Use an unencrypted PDF (up to 30 pages) or a readable Word (.docx) file.") from None
        text = extracted["text"].strip()
        if len(text) > 20000:
            raise HTTPException(422, "The document exceeds 20,000 characters. Upload a shorter job description.")
        result = generate(request.app.state.settings, "job-import", {"job-document": text}, {})
        return form_fields(result, text)
    finally:
        file.file.close()
