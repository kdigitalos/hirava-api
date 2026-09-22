"""End-to-end API/queue tests with synthetic documents and a fake AI provider."""
from datetime import timedelta
from io import BytesIO

import pytest
from pydantic import SecretStr
from sqlalchemy import select, update

from app.agents.application import claim, process_one
from app.agents.models import ScreeningJob
from app.agents.screening import Findings, ProviderResult, ScreeningError
from app.core.models import User
from app.data.database import utcnow
from app.modules.recruiting.models import Requisition
from app.modules.recruiting.public_intake import pipeline_table
from test_public_intake import setup_job, submit

JD = "This role requires Python API development and SQL experience. Work with our engineering team."
RESUME = "Developed Python APIs for inventory services. Wrote automated tests and documented the API."
BODY = {"rubric_version": "synthetic-v1", "allow_provider_processing": True, "criteria": [
    {"id": "python", "description": "Python API development", "jd_quote": "Python API development", "weight": 3},
    {"id": "sql", "description": "SQL experience", "jd_quote": "SQL experience", "weight": 1},
]}


@pytest.fixture
def screening(api, monkeypatch):
    client, app, users, headers = api
    path = setup_job(api)
    assert submit(client, path).status_code == 200
    with app.state.sessions.begin() as db:
        db.execute(update(Requisition).values(description=JD))
        row = db.execute(select(pipeline_table(db))).mappings().one()
        candidate_id = row["id"]
    settings = app.state.settings
    settings.ai_screening_enabled = True
    settings.ai_screening_provider = "groq"
    settings.groq_screening_model = "synthetic-only"
    settings.groq_api_key = SecretStr("fake-test-key")
    # Still use the real PDF extractor, with a generated synthetic PDF.
    from reportlab.pdfgen import canvas
    pdf = BytesIO()
    document = canvas.Canvas(pdf)
    document.drawString(40, 750, RESUME)
    document.save()
    monkeypatch.setattr("app.agents.application.object_storage.download", lambda *_: BytesIO(pdf.getvalue()))
    calls = []
    app.state.generation_calls = []

    class Provider:
        def generate_criteria(self, description):
            app.state.generation_calls.append(description)
            return {"criteria": BODY["criteria"], "provider": "groq", "model": "synthetic-only",
                    "response_id": "fake-generation", "input_tokens": 5, "output_tokens": 8}
        def assess(self, source):
            calls.append(source)
            return ProviderResult(provider="groq", model="synthetic-only", response_id="fake-response",
                profile_extraction=getattr(app.state, "test_profile_extraction", None),
                employment_history=getattr(app.state, "test_employment_history", None),
                input_tokens=10, output_tokens=20, assessment=Findings(findings=[
                    {"criterion_id": "python", "status": "evidenced", "resume_quotes": ["Developed Python APIs"], "explanation": "Source describes Python APIs."},
                    {"criterion_id": "sql", "status": "not_evidenced", "resume_quotes": [], "explanation": "SQL is not mentioned."},
                ]))
        def close(self):
            pass
    monkeypatch.setattr("app.agents.application.create_provider", lambda _: Provider())
    return client, app, users, headers, f"/api/candidate/{candidate_id}/assessment", calls


def test_queue_persist_poll_and_duplicate_request(screening):
    client, app, _, headers, path, calls = screening
    assert client.get(path, headers=headers["hr"]).json()["can_run"]
    first = client.post(path, json=BODY, headers=headers["hr"])
    assert first.status_code == 202, first.text
    assert first.json()["status"] == "queued"
    second = client.post(path, json=BODY, headers=headers["hr"])
    assert second.json()["id"] == first.json()["id"]
    assert process_one(app)
    assert not process_one(app)
    saved = client.get(path, headers=headers["recruiter"]).json()["assessment"]
    assert saved["result"]["jd_evidence_score"] == 75
    assert saved["result"]["resume_score"] is None
    assert saved["status"] == "needs_review"
    assert calls[0].resume_text.strip() == RESUME
    assert calls[0].job_description == JD
    assert len(calls) == 1
    # Resubmitting the same successful input doesn't incur another provider request.
    assert client.post(path, json=BODY, headers=headers["hr"]).json()["id"] == saved["id"]
    with app.state.sessions() as db:
        assert db.execute(select(pipeline_table(db).c.status)).scalar_one() == ""
        persisted = db.get(ScreeningJob, saved["id"]).result
        assert len(persisted["candidate_summary"]) == 3
        assert persisted["candidate_summary"] == saved["result"]["candidate_summary"]


def test_access_configuration_and_rubric_validation(screening):
    client, app, _, headers, path, calls = screening
    assert client.get(path).status_code == 401
    for role in ("employee", "manager", "interviewer"):
        assert client.get(path, headers=headers[role]).status_code == 403
        assert client.post(path, json=BODY, headers=headers[role]).status_code == 403
    assert client.get(path, headers=headers["outsider"]).status_code == 401
    assert client.post(path, json={**BODY, "allow_provider_processing": False}, headers=headers["hr"]).status_code == 422
    wrong = {**BODY, "criteria": [{**BODY["criteria"][0], "jd_quote": "Invented requirement"}]}
    assert client.post(path, json=wrong, headers=headers["hr"]).status_code == 422
    app.state.settings.ai_screening_enabled = False
    assert not client.get(path, headers=headers["hr"]).json()["can_run"]
    assert client.post(path, json=BODY, headers=headers["hr"]).status_code == 503
    assert calls == []


def test_foreign_candidate_cannot_be_assessed(screening):
    client, app, _, headers, path, calls = screening
    with app.state.sessions.begin() as db:
        db.execute(update(Requisition).values(customer_id="customer-b"))
    assert client.get(path, headers=headers["admin"]).status_code == 404
    assert client.post(path, json=BODY, headers=headers["admin"]).status_code == 404
    assert calls == []


def test_stale_source_is_not_sent_and_previous_score_is_hidden(screening):
    client, app, _, headers, path, calls = screening
    client.post(path, json=BODY, headers=headers["hr"])
    with app.state.sessions.begin() as db:
        db.execute(update(Requisition).values(description=JD + " Additional requirement."))
    process_one(app)
    saved = client.get(path, headers=headers["hr"]).json()["assessment"]
    assert saved["status"] == "failed" and saved["stale"]
    assert not calls
    client.post(path, json=BODY, headers=headers["hr"])
    process_one(app)
    with app.state.sessions.begin() as db:
        db.execute(update(Requisition).values(description=JD))
    saved = client.get(path, headers=headers["hr"]).json()["assessment"]
    assert saved["stale"] and saved["result"] is None


def test_revoked_actor_is_not_sent(screening):
    client, app, users, headers, path, calls = screening
    client.post(path, json=BODY, headers=headers["hr"])
    with app.state.sessions.begin() as db:
        db.get(User, users["hr"]).active = False
    process_one(app)
    saved = client.get(path, headers=headers["admin"]).json()["assessment"]
    assert saved["status"] == "failed" and saved["result"] is None
    assert not calls


def test_provider_error_has_no_score_and_allows_manual_retry(screening, monkeypatch):
    client, app, _, headers, path, calls = screening
    def fail(_):
        raise ScreeningError("AI provider unavailable; retry later.")
    monkeypatch.setattr("app.agents.application.create_provider", fail)
    first = client.post(path, json=BODY, headers=headers["hr"]).json()
    process_one(app)
    saved = client.get(path, headers=headers["hr"]).json()["assessment"]
    assert saved["status"] == "failed" and saved["result"] is None
    assert saved["error"] == "AI provider unavailable; retry later."
    second = client.post(path, json=BODY, headers=headers["hr"]).json()
    assert second["id"] != first["id"] and second["status"] == "queued"


def test_claim_once_and_crashed_work_is_not_automatically_resent(screening):
    client, app, _, headers, path, calls = screening
    record = client.post(path, json=BODY, headers=headers["hr"]).json()
    assert claim(app.state.sessions, app.state.settings) == record["id"]
    assert claim(app.state.sessions, app.state.settings) is None
    with app.state.sessions.begin() as db:
        db.get(ScreeningJob, record["id"]).started_at = utcnow() - timedelta(minutes=16)
    assert claim(app.state.sessions, app.state.settings) is None
    assert client.get(path, headers=headers["hr"]).json()["assessment"]["status"] == "failed"
    assert not calls


@pytest.mark.parametrize("ref", ["https://example.com/resume.pdf", "file:///secret.pdf", "/api/uploads/user-uploads/foreign/" + "a" * 32 + ".pdf"])
def test_untrusted_resume_locations_are_rejected(screening, ref):
    client, app, _, headers, path, calls = screening
    with app.state.sessions.begin() as db:
        table = pipeline_table(db)
        db.execute(update(table).values(object=[{"name": "resume", "value": ref}]))
    assert client.post(path, json=BODY, headers=headers["hr"]).status_code == 422
    assert not calls


def test_automatic_assessment_reuses_job_criteria_and_invalidates_changed_jd(screening):
    client, app, _, headers, path, calls = screening
    body = {"allow_provider_processing": True}
    first = client.post(path, json=body, headers=headers["hr"])
    assert first.status_code == 202
    assert process_one(app)
    saved = client.get(path, headers=headers["hr"]).json()["assessment"]
    assert saved["status"] == "needs_review", saved
    assert saved["result"]["jd_evidence_score"] == 50  # equal weights, not model's weight 3
    assert saved["result"]["criteria_generation"]["response_id"] == "fake-generation"
    assert saved["rubric"]["reused"] is False
    assert client.post(path, json=body, headers=headers["hr"]).json()["id"] == saved["id"]
    assert len(app.state.generation_calls) == 1
    with app.state.sessions() as db:
        table = pipeline_table(db)
        alias = db.execute(select(table.c.job_opening_id)).scalar_one()
    assert submit(client, f"/api/v1/careers/jobs/{alias}/apply", email="second@example.com").status_code == 200
    with app.state.sessions() as db:
        new_id = db.execute(select(table.c.id).order_by(table.c.id.desc())).scalars().first()
    second_path = f"/api/candidate/{new_id}/assessment"
    assert client.post(second_path, json=body, headers=headers["hr"]).status_code == 202
    assert process_one(app)
    second = client.get(second_path, headers=headers["hr"]).json()["assessment"]
    assert second["rubric"]["reused"] is True
    assert len(app.state.generation_calls) == 1 and len(calls) == 2
    with app.state.sessions.begin() as db:
        db.execute(update(Requisition).values(description=JD + " Academic projects are accepted."))
    assert client.get(second_path, headers=headers["hr"]).json()["assessment"]["stale"]
    client.post(second_path, json=body, headers=headers["hr"])
    assert process_one(app)
    assert len(app.state.generation_calls) == 2


def test_invalid_generated_quote_stops_before_resume_assessment(screening, monkeypatch):
    client, app, _, headers, path, calls = screening
    from app.agents import application
    original = application.create_provider
    def invalid(settings):
        provider = original(settings)
        provider.generate_criteria = lambda _: {"criteria": [{**BODY["criteria"][0], "jd_quote": "Invented requirement"}]}
        return provider
    monkeypatch.setattr(application, "create_provider", invalid)
    client.post(path, json={"allow_provider_processing": True}, headers=headers["hr"])
    assert process_one(app)
    saved = client.get(path, headers=headers["hr"]).json()["assessment"]
    assert saved["status"] == "failed" and saved["result"] is None
    assert calls == []


def test_auto_requires_consent_and_real_jd(screening):
    client, app, _, headers, path, calls = screening
    assert client.post(path, json={}, headers=headers["hr"]).status_code == 422
    with app.state.sessions.begin() as db:
        db.execute(update(Requisition).values(description="good"))
    assert client.post(path, json={"allow_provider_processing": True}, headers=headers["hr"]).status_code == 422
    assert not calls and not app.state.generation_calls


def test_access_revoked_during_generation_stops_resume_assessment(screening, monkeypatch):
    client, app, users, headers, path, calls = screening
    from app.agents import application
    original = application.create_provider
    def revoked(settings):
        provider = original(settings)
        generate = provider.generate_criteria
        def run(description):
            with app.state.sessions.begin() as db:
                db.get(User, users["hr"]).active = False
            return generate(description)
        provider.generate_criteria = run
        return provider
    monkeypatch.setattr(application, "create_provider", revoked)
    client.post(path, json={"allow_provider_processing": True}, headers=headers["hr"])
    process_one(app)
    saved = client.get(path, headers=headers["admin"]).json()["assessment"]
    assert saved["status"] == "failed" and not calls
