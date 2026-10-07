from io import BytesIO

import pytest
from sqlalchemy import func, select

from app.modules.organization.models import OrganizationUnit, Position
from app.modules.recruiting.models import Requisition
from app.modules.recruiting.job_import import MAX_BYTES, form_fields
from conftest import post


TEXT = "Platform Engineer\nCompany: Synthetic Co\nLocation: Hyderabad\nPositions: 3\nRequired skills: Python, SQL\nBuild and maintain reliable application services."


def document_bytes(suffix):
    stream = BytesIO()
    if suffix == "docx":
        from docx import Document
        doc = Document()
        for line in TEXT.splitlines():
            doc.add_paragraph(line)
        doc.save(stream)
    else:
        from reportlab.pdfgen.canvas import Canvas
        canvas = Canvas(stream)
        for index, line in enumerate(TEXT.splitlines()):
            canvas.drawString(40, 750 - index * 20, line)
        canvas.save()
    return stream.getvalue()


def result(**values):
    return {"sections": [{"title": name, "text": value, "source_ids": ["job-document"]}
                         for name, value in values.items()], "limitations": []}


@pytest.mark.parametrize("suffix", ["pdf", "docx"])
def test_document_extracts_unsaved_form(api, monkeypatch, suffix):
    def generate(settings, kind, sources, options):
        assert kind == "job-import"
        assert "Platform Engineer" in sources["job-document"]
        return result(title="Platform Engineer", company_name="Synthetic Co", no_of_openings="3",
                      required_skills='["Python", "SQL"]', target_date="2026-12-01")
    monkeypatch.setattr("app.modules.recruiting.job_import.generate", generate)
    response = api[0].post("/api/v1/rms/job-document", headers=api[3]["recruiter"],
                          data={"allow_provider_processing": "true"},
                          files={"file": (f"job.{suffix}", document_bytes(suffix))})
    assert response.status_code == 200, response.text
    fields = response.json()["fields"]
    assert fields["no_of_openings"] == 3
    assert fields["required_skills"] == ["Python", "SQL"]
    assert fields["target_date"] == "2026-12-01"
    assert "Build and maintain" in fields["description"]
    with api[1].state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(Requisition)) == 0
        assert db.scalar(select(func.count()).select_from(Position)) == 0


def test_upload_rejections_never_call_provider(api, monkeypatch):
    monkeypatch.setattr("app.modules.recruiting.job_import.generate", lambda *_: pytest.fail("Provider called"))
    for name, content, consent, role, status in [
        ("job.docx", b"PKbad", "false", "recruiter", 422),
        ("job.doc", b"old document", "true", "recruiter", 422),
        ("job.pdf", b"not a pdf", "true", "recruiter", 422),
        ("job.docx", b"PKbad", "true", "recruiter", 422),
        ("job.pdf", b"%PDF-" + b"x" * MAX_BYTES, "true", "recruiter", 413),
        ("job.pdf", b"%PDF-bad", "true", "employee", 403),
        ("job.pdf", b"%PDF-bad", "true", "outsider", 401),
    ]:
        response = api[0].post("/api/v1/rms/job-document", headers=api[3][role],
                              data={"allow_provider_processing": consent}, files={"file": (name, content)})
        assert response.status_code == status, response.text
    response = api[0].post("/api/v1/rms/job-document", files={"file": ("job.pdf", b"%PDF-bad")})
    assert response.status_code == 401
    api[1].state.settings.rms_enabled = False
    response = api[0].post("/api/v1/rms/job-document", headers=api[3]["recruiter"],
                          files={"file": ("job.pdf", b"%PDF-bad")})
    assert response.status_code == 403


def test_invalid_and_unknown_extracted_values_are_not_applied():
    extracted = form_fields(result(title="Engineer", no_of_openings="3 years", budget="100",
                                  target_date="not a date", recruiter_id="attacker", job_link="javascript:alert(1)"), TEXT)
    assert extracted["fields"] == {"title": "Engineer", "description": TEXT}
    assert len(extracted["warnings"]) == 4
    extracted = form_fields(result(salary_min="200", salary_max="100", currency="INR"), TEXT)
    assert "salary_min" not in extracted["fields"]


def test_import_schema_allows_missing_metadata_without_invention():
    from app.agents.recruiter_tools import draft_format
    schema = draft_format({"job-document": TEXT}, max_sections=20, min_sections=0)
    empty = schema.model_validate({"sections": [], "limitations": ["No clear job metadata found."]})
    extracted = form_fields(empty.model_dump(), TEXT)
    assert extracted["fields"] == {"description": TEXT}
    assert extracted["warnings"] == ["No clear job metadata found."]


def test_document_dropdown_values_and_experience():
    fields = form_fields(result(job_type="FULL_TIME", work_mode="Remote", experience_years="0", currency="INR"), TEXT)["fields"]
    assert fields["job_type"] == "Full-Time"
    assert fields["work_mode"] == "Work from Home"
    assert fields["experience_years"] == 0
    fields = form_fields(result(job_type="freelance", work_mode="on-site", experience_years="3"), TEXT)["fields"]
    assert fields["job_type"] == "Free-lancing" and fields["work_mode"] == "Work from Office"
    assert fields["experience_years"] == 3
    fields = form_fields(result(job_type="internship", experience_years="3.5"), TEXT)["fields"]
    assert "job_type" not in fields and "experience_years" not in fields


def test_experience_persists_on_create_edit_and_read(api):
    job = post(api, "/rms/requisitions", {"title": "Engineer", "description": TEXT,
        "job_details": {"experience_years": 3, "job_type": "Contract", "work_mode": "Hybrid", "currency": "USD"}})
    url = f"/api/v1/rms/requisitions/{job['id']}"
    assert job["job_details"]["experience_years"] == 3
    updated = api[0].patch(url, headers=api[3]["admin"], json={"expected_version": job["version"],
        "job_details": {**job["job_details"], "experience_years": 0}})
    assert updated.status_code == 200, updated.text
    saved = api[0].get(url, headers=api[3]["admin"]).json()["job_details"]
    assert saved["experience_years"] == 0 and saved["job_type"] == "Contract"
    assert saved["work_mode"] == "Hybrid" and saved["currency"] == "USD"
    for invalid in (-1, 51, 1.5):
        post(api, "/rms/requisitions", {"title": "Engineer", "description": TEXT,
             "job_details": {"experience_years": invalid}}, status=422)


@pytest.mark.parametrize("role", ["admin", "recruiter", "manager"])
def test_number_of_positions_creates_linked_headcount_and_requires_approval(api, role):
    job = post(api, "/rms/requisitions", {"title": "Engineer", "description": TEXT,
               "job_details": {"no_of_openings": 3, "department": "Engineering"}}, role=role)
    assert job["status"] == "draft"
    assert job["job_details"]["no_of_openings"] == 3
    with api[1].state.sessions() as db:
        position = db.get(Position, job["position_id"])
        assert position.capacity == 3 and position.occupied == 0
        assert position.customer_id == "customer-a"
        assert position.manager_id == (api[2][role] if role == "manager" else None)
    post(api, f"/rms/requisitions/{job['id']}/publish", role="recruiter", status=409)
    response = api[0].patch(f"/api/v1/rms/requisitions/{job['id']}", headers=api[3][role],
                           json={"expected_version": job["version"], "job_details": {"no_of_openings": 5}})
    assert response.status_code == 200, response.text
    with api[1].state.sessions() as db:
        assert db.get(Position, job["position_id"]).capacity == 5
    post(api, f"/rms/requisitions/{job['id']}/submit", role=role, status=200)
    if role == "admin":
        post(api, f"/rms/requisitions/{job['id']}/approve", {"reason": "Self approval"}, role=role, status=403)
    post(api, f"/rms/requisitions/{job['id']}/approve", {"reason": "Approved headcount"}, role="hr", status=200)


def test_invalid_job_rolls_back_automatic_position(api):
    post(api, "/rms/requisitions", {"title": "Engineer", "description": TEXT,
         "job_details": {"no_of_openings": 3, "recruiter_id": api[2]["employee"]}}, role="recruiter", status=422)
    with api[1].state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(Position)) == 0
        assert db.scalar(select(func.count()).select_from(OrganizationUnit)) == 0


def test_shared_managed_headcount_cannot_be_resized(api):
    job = post(api, "/rms/requisitions", {"title": "Engineer", "description": TEXT})
    post(api, "/rms/requisitions", {"title": "Second job", "description": TEXT, "position_id": job["position_id"]})
    response = api[0].patch(f"/api/v1/rms/requisitions/{job['id']}", headers=api[3]["admin"],
                           json={"expected_version": job["version"], "job_details": {"no_of_openings": 5}})
    assert response.status_code == 409
