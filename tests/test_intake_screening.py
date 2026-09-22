"""Synthetic public intake through the durable screening worker; no live provider calls."""
import pytest
from sqlalchemy import select, update

from app.agents.application import process_one
from app.agents.models import ScreeningJob
from app.core.models import AuditEvent, User
from app.modules.recruiting.models import Requisition
from app.modules.recruiting.public_intake import pipeline_table
from test_public_intake import submit
from test_screening_application import screening  # noqa: F401


def configure(screening):
    client, app, users, headers, _, calls = screening
    settings = app.state.settings
    settings.ai_screening_on_intake = True
    settings.ai_screening_intake_actor_id = users["admin"]
    with app.state.sessions() as db:
        alias = db.execute(select(pipeline_table(db).c.job_opening_id)).scalar_one()
    url = f"/api/v1/careers/jobs/{alias}"
    offer = client.get(url).json()["ai_screening"]
    return client, app, users, headers, calls, url, offer


def records(app):
    with app.state.sessions() as db:
        return db.scalars(select(ScreeningJob)).all()


def test_opt_in_queues_atomically_and_duplicate_does_not_resubmit(screening):
    client, app, _, headers, calls, url, offer = configure(screening)
    data = {"email": "automatic@example.com", "ai_consent": offer["consent_token"]}
    response = submit(client, url + "/apply", **data)
    assert response.status_code == 200
    assert not calls  # No inference in the submission request.
    assert len(records(app)) == 1
    queued = records(app)[0]
    assert queued.status == "queued" and queued.rubric["trigger"] == "public_intake"
    assert submit(client, url + "/apply", **data).json() == response.json()
    assert len(records(app)) == 1
    assert process_one(app)
    result = client.get(f"/api/candidate/{queued.candidate_id}/assessment", headers=headers["hr"]).json()["assessment"]
    assert result["status"] == "needs_review", result
    assert result["result"]["jd_evidence_score"] == 50
    assert len(calls) == 1
    assert submit(client, url + "/apply", **data).status_code == 200
    assert len(records(app)) == 1 and not process_one(app)
    with app.state.sessions() as db:
        table = pipeline_table(db)
        assert db.execute(select(table.c.status).where(table.c.id == queued.candidate_id)).scalar_one() == ""
        event = db.scalar(select(AuditEvent).where(AuditEvent.action == "screening.intake_requested"))
        assert event.actor_id is None and event.details["trigger"] == "public_intake"


@pytest.mark.parametrize("consent", [None, "on", "old-provider-token"])
def test_missing_or_invalid_ai_consent_still_accepts_application(screening, consent):
    client, app, _, _, calls, url, offer = configure(screening)
    data = {"email": "manual@example.com"}
    if consent is not None:
        data["ai_consent"] = consent
    assert submit(client, url + "/apply", **data).status_code == 200
    assert not records(app) and not calls
    # Anonymous retry cannot upgrade somebody else's application to AI consent.
    assert submit(client, url + "/apply", **{**data, "ai_consent": offer["consent_token"]}).status_code == 200
    assert not records(app)


@pytest.mark.parametrize("change", ["disabled", "actor", "model", "jd"])
def test_configuration_changes_do_not_queue_unconsented_processing(screening, change):
    client, app, users, _, calls, url, offer = configure(screening)
    if change == "disabled":
        app.state.settings.ai_screening_on_intake = False
    elif change == "model":
        app.state.settings.groq_screening_model = "different-model"
    else:
        with app.state.sessions.begin() as db:
            if change == "actor":
                db.get(User, users["admin"]).active = False
            else:
                db.execute(update(Requisition).values(description="good"))
    assert submit(client, url + "/apply", email="changed@example.com", ai_consent=offer["consent_token"]).status_code == 200
    assert not records(app) and not calls


def test_disabled_after_queue_stops_provider_processing(screening):
    client, app, _, _, calls, url, offer = configure(screening)
    submit(client, url + "/apply", email="queued@example.com", ai_consent=offer["consent_token"])
    app.state.settings.ai_screening_on_intake = False
    assert process_one(app)
    assert records(app)[0].status == "failed" and not calls


def test_queue_failure_preserves_candidate_and_resume(screening, monkeypatch):
    client, app, _, _, calls, url, offer = configure(screening)
    before = len(app.state.test_s3_objects)
    def fail(*args):
        raise RuntimeError("synthetic queue outage")
    monkeypatch.setattr("app.agents.intake.queue_intake", fail)
    assert submit(client, url + "/apply", email="outage@example.com", ai_consent=offer["consent_token"]).status_code == 200
    with app.state.sessions() as db:
        assert len(db.execute(select(pipeline_table(db))).all()) == 2
        assert db.scalar(select(AuditEvent).where(AuditEvent.action == "screening.intake_queue_failed"))
    assert len(app.state.test_s3_objects) == before + 1
    assert not records(app) and not calls
