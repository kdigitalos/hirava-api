"""Profile grounding, non-destructive merging and worker persistence."""
from copy import deepcopy

import pytest
from sqlalchemy import select, update

from app.agents.profile_extraction import ExtractedField, grounded_fields, fill_blank_fields
from app.agents.application import process_one
from app.core.models import AuditEvent
from app.agents.models import ScreeningJob
from app.modules.recruiting.public_intake import pipeline_table
from test_screening_application import screening, BODY  # noqa: F401


def extracted(name, value, refs=None):
    return ExtractedField(name=name, value=value, resume_passage_ids=refs or ["p1"])


def test_grounding_accepts_source_values_only():
    result = grounded_fields([
        extracted("skills", "Python"), extracted("education", "PhD"),
        extracted("skills", "SQL", ["missing"]), extracted("skills", "Python")],
        {"p1": "Built Python APIs"})
    assert [item["value"] for item in result["fields"]] == ["Python"]
    assert result["fields"][0]["resume_quotes"] == ["Built Python APIs"]
    assert result["rejected_count"] == 2


@pytest.mark.parametrize("name,value", [("email", "not-an-email"), ("mobile", "12345"),
                                       ("mobile", "abc1234567890")])
def test_invalid_contacts_are_not_filled(name, value):
    result = grounded_fields([extracted(name, value)], {"p1": value})
    assert result["fields"] == [] and result["rejected_count"] == 1


def test_blank_fill_preserves_existing_and_rejects_ambiguous_identity():
    original = [{"name": "email", "value": "entered@example.com"},
                {"name": "skills", "value": " ", "label": "My skills"}]
    fields = [dict(name="email", value="resume@example.com"), dict(name="skills", value="Python"),
              dict(name="skills", value="SQL"), dict(name="firstName", value="Asha"),
              dict(name="firstName", value="Maya")]
    before = deepcopy(original)
    merged, filled, preserved = fill_blank_fields(original, fields, "test")
    assert original == before
    assert merged[0] == before[0]
    assert merged[1]["value"] == "Python, SQL" and merged[1]["label"] == "My skills"
    assert merged[1]["aiExtraction"]["review_required"]
    assert filled == ["skills"] and preserved == ["email", "firstName"]
    assert fill_blank_fields(merged, fields, "next")[1] == []


def test_autofill_persists_without_staling_result_or_repeating_provider(screening):
    client, app, _, headers, path, calls = screening
    app.state.test_profile_extraction = grounded_fields([extracted("skills", "Python")],
                                                       {"p1": "Developed Python APIs"})
    queued = client.post(path, json=BODY, headers=headers["hr"]).json()
    assert process_one(app)
    result = client.get(path, headers=headers["hr"]).json()["assessment"]
    assert not result["stale"]
    assert result["result"]["profile_extraction"]["filled_fields"] == ["skills"]
    with app.state.sessions() as db:
        row = db.execute(select(pipeline_table(db))).mappings().one()
        fields = {item["name"]: item for item in row["object"]}
        assert fields["skills"]["value"] == "Python"
        assert fields["skills"]["aiExtraction"]["assessment_id"] == queued["id"]
        assert row["status"] == ""
        event = db.scalar(select(AuditEvent).where(AuditEvent.action == "candidate.profile_autofilled"))
        assert event.actor_id is None and event.details["filled_fields"] == ["skills"]
    assert client.post(path, json=BODY, headers=headers["hr"]).json()["id"] == queued["id"]
    assert len(calls) == 1
    with app.state.sessions.begin() as db:
        table = pipeline_table(db)
        changed = deepcopy(row["object"])
        next(item for item in changed if item["name"] == "skills")["value"] = "Recruiter edit"
        db.execute(table.update().values(object=changed))
    assert client.get(path, headers=headers["hr"]).json()["assessment"]["stale"]


def test_edit_during_inference_prevents_autofill(screening, monkeypatch):
    client, app, _, headers, path, _ = screening
    from app.agents import application
    original_factory = application.create_provider
    def factory(settings):
        provider = original_factory(settings)
        assess = provider.assess
        def changed(source):
            response = assess(source)
            response.profile_extraction = grounded_fields([extracted("skills", "Python")],
                                                         {"p1": "Developed Python APIs"})
            with app.state.sessions.begin() as db:
                table = pipeline_table(db)
                fields = deepcopy(db.execute(select(table.c.object)).scalar_one())
                fields.append({"name": "skills", "value": "Recruiter edit"})
                db.execute(table.update().values(object=fields))
            return response
        provider.assess = changed
        return provider
    monkeypatch.setattr(application, "create_provider", factory)
    client.post(path, json=BODY, headers=headers["hr"])
    assert process_one(app)
    result = client.get(path, headers=headers["hr"]).json()["assessment"]
    assert result["status"] == "failed" and result["result"] is None
    with app.state.sessions() as db:
        assert next(item for item in db.execute(select(pipeline_table(db).c.object)).scalar_one()
                    if item["name"] == "skills")["value"] == "Recruiter edit"
        assert db.scalar(select(AuditEvent).where(AuditEvent.action == "candidate.profile_autofilled")) is None


def test_older_successful_assessment_can_be_upgraded(screening):
    client, app, _, headers, path, _ = screening
    first = client.post(path, json=BODY, headers=headers["hr"]).json()
    assert process_one(app)
    with app.state.sessions.begin() as db:
        record = db.get(ScreeningJob, first["id"])
        record.result = {key: value for key, value in record.result.items() if key != "employment_history"}
    assert client.post(path, json=BODY, headers=headers["hr"]).json()["id"] != first["id"]


def test_intake_autofill_preserves_consent_and_result_freshness(screening):
    from test_intake_screening import configure
    from test_public_intake import submit
    client, app, _, headers, calls, url, offer = configure(screening)
    app.state.test_profile_extraction = grounded_fields([extracted("skills", "Python")],
                                                       {"p1": "Developed Python APIs"})
    assert submit(client, url + "/apply", email="autofill@example.com", ai_consent=offer["consent_token"]).status_code == 200
    assert process_one(app)
    with app.state.sessions() as db:
        record = db.scalar(select(ScreeningJob))
        candidate_id = record.candidate_id
        table = pipeline_table(db)
        fields = db.execute(select(table.c.object).where(table.c.id == candidate_id)).scalar_one()
        assert any(item["name"] == "aiConsent" and "Agreed" in item["value"] for item in fields)
    result = client.get(f"/api/candidate/{candidate_id}/assessment", headers=headers["hr"]).json()["assessment"]
    assert not result["stale"] and result["status"] == "needs_review"
    assert result["result"]["profile_extraction"]["filled_fields"] == ["skills"]
    assert len(calls) == 1
