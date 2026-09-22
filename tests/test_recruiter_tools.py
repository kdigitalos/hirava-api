from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from pydantic import SecretStr
from sqlalchemy import select, update
from app.agents.recruiter_tools import Draft, generate
from app.core.config import Settings
from app.core.models import AuditEvent
from app.modules.recruiting.public_intake import pipeline_table
from app.modules.recruiting.pipeline_feedback import feedback_table
from app.modules.recruiting.models import Requisition
from test_public_intake import setup_job, submit


@pytest.mark.parametrize("provider", ["openai", "groq"])
def test_provider_contract_and_source_rejection(monkeypatch, provider):
    captured = {}
    draft = Draft(sections=[{"title": "Draft", "text": "Synthetic output", "source_ids": ["brief"]}], limitations=[])
    def parse(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(status="completed", output_parsed=draft, usage=None)
    def create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(
            refusal=None, content=draft.model_dump_json()))], usage=None)
    closed = []
    fake = SimpleNamespace(responses=SimpleNamespace(parse=parse), chat=SimpleNamespace(completions=SimpleNamespace(create=create)), close=lambda: closed.append(True))
    monkeypatch.setattr("app.agents.recruiter_tools.create_client", lambda *_: fake)
    settings = Settings(_env_file=None, jwt_secret="x" * 32, ai_recruiter_tools_enabled=True,
        ai_provider=provider, openai_model="test", groq_model="test", openai_api_key="fake", groq_api_key="fake")
    result = generate(settings, "job-description", {"brief": "Synthetic job brief"}, {})
    assert result["provider"] == provider and closed == [True]
    assert captured["model"] == "test"
    if provider == "openai":
        assert captured["store"] is False and captured["max_output_tokens"] == 4000
    else:
        assert captured["response_format"]["json_schema"]["strict"] is True
    draft.sections[0].source_ids = ["invented"]
    with pytest.raises(HTTPException) as error:
        generate(settings, "job-description", {"brief": "Synthetic job brief"}, {})
    assert error.value.status_code == 502 and len(closed) == 2


def test_routes_scope_consent_feedback_and_audit(api, monkeypatch):
    client, app, users, headers = api
    public_path = setup_job(api)
    submit(client, public_path)
    with app.state.sessions.begin() as db:
        row = db.execute(select(pipeline_table(db))).mappings().one()
        person_id, job_id = row["id"], row["job_opening_id"]
        table = feedback_table(db)
        table.create(db.bind, checkfirst=True)
        from app.modules.recruiting.pipeline_interviews import interview_table
        interview_table(db).create(db.bind, checkfirst=True)
    calls = []
    def fake(settings, kind, sources, options):
        calls.append((kind, sources, options))
        return {"sections": [], "sources": sources, "limitations": [], "provider": "test", "model": "test", "tokens": {"input": 1, "output": 2}, "kind": kind}
    monkeypatch.setattr("app.agents.recruiter_tools.generate", fake)
    base = "/api/recruiter-ai"
    body = {"title": "Developer", "brief": "Build Python APIs with SQL databases.", "allow_provider_processing": True}
    assert client.post(base + "/job-description", json=body).status_code == 401
    assert client.post(base + "/job-description", json=body, headers=headers["employee"]).status_code == 403
    assert client.post(base + "/job-description", json={**body, "allow_provider_processing": False}, headers=headers["hr"]).status_code == 422
    assert client.post(base + "/job-description", json=body, headers=headers["hr"]).status_code == 200
    assert client.post(f"{base}/candidates/99999/questions", json=body, headers=headers["hr"]).status_code == 404
    with app.state.sessions.begin() as db:
        db.execute(update(Requisition).values(description="Build Python APIs with SQL databases and write automated tests for reliable services."))
    assert client.post(f"{base}/candidates/{person_id}/questions", json=body, headers=headers["hr"]).status_code == 200
    assert calls[-1][0] == "questions" and "job" in calls[-1][1]
    path = f"{base}/candidates/{person_id}/feedback-summary"
    before = len(calls)
    assert client.post(path, json=body, headers=headers["hr"]).status_code == 422
    assert len(calls) == before
    with app.state.sessions.begin() as db:
        db.execute(feedback_table(db).insert().values(candidateId=person_id, jobId=job_id,
            interviewerName="Synthetic reviewer", description="Explained Python testing well.", level=1))
    assert client.post(path, json=body, headers=headers["hr"]).status_code == 200
    assert next(iter(calls[-1][1])).startswith("feedback-")
    assert client.post(path, json=body, headers=headers["outsider"]).status_code in (401, 404)
    with app.state.sessions() as db:
        audits = db.scalars(select(AuditEvent).where(AuditEvent.action == "ai.draft_generated")).all()
        assert len(audits) == 3
        assert all("Synthetic reviewer" not in str(a.details) for a in audits)


def test_disabled_tools_never_create_client(monkeypatch):
    monkeypatch.setattr("app.agents.recruiter_tools.create_client", lambda *_: pytest.fail("No request allowed"))
    with pytest.raises(HTTPException) as error:
        generate(Settings(_env_file=None, jwt_secret="x" * 32), "job-description", {}, {})
    assert error.value.status_code == 503


def test_email_draft_scope_missing_details_and_no_send(api, monkeypatch):
    client, app, _, headers = api
    path = setup_job(api)
    submit(client, path)
    with app.state.sessions() as db:
        person = db.execute(select(pipeline_table(db))).mappings().one()
        candidate_id, job_id = person["id"], person["job_opening_id"]
    calls = []
    def fake(settings, kind, sources, options):
        calls.append((kind, sources))
        return {"kind": kind, "sections": [{"title": "Email", "text": "Dear candidate, please join us.", "source_ids": ["interview-details"]}],
                "sources": sources, "limitations": [], "provider": "test", "model": "test", "tokens": {}}
    monkeypatch.setattr("app.agents.recruiter_tools.generate", fake)
    body = {"candidate_id": candidate_id, "job_id": job_id, "allow_provider_processing": True,
            "date": "21 September 2026", "time": "12:45 pm", "timezone": "Asia/Calcutta"}
    endpoint = "/api/recruiter-ai/interview-email"
    assert client.post(endpoint, json=body).status_code == 401
    assert client.post(endpoint, json=body, headers=headers['employee']).status_code == 403
    assert client.post(endpoint, json={**body, 'allow_provider_processing': False}, headers=headers['hr']).status_code == 422
    assert client.post(endpoint, json={**body, 'job_id': job_id + 1000}, headers=headers['hr']).status_code == 409
    assert client.post(endpoint, json=body, headers=headers['outsider']).status_code in (401, 404)
    assert not calls
    response = client.post(endpoint, json=body, headers=headers['hr'])
    assert response.status_code == 200, response.text
    assert calls[0][0] == 'interview-email'
    assert '12:45 pm' in calls[0][1]['interview-details']
    assert 'meeting link or location' in response.json()['limitations'][-1]
    with app.state.sessions() as db:
        audits = db.scalars(select(AuditEvent).where(AuditEvent.action == 'ai.draft_generated')).all()
        assert len(audits) == 1
        assert 'Dear candidate' not in str(audits[0].details)
