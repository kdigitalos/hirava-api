from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.workers.vercel_cron import router


@pytest.fixture
def cron(monkeypatch):
    app = FastAPI()
    app.include_router(router)
    app.state.settings = SimpleNamespace(
        vercel=True, cron_secret=SecretStr("test-cron-secret"), customer_id="synthetic",
        imported_storage_cleanup_enabled=True, recruitment_operations_enabled=True,
    )
    app.state.sessions = object()
    mocks = {}
    for name, module, function, result in [
        ("notifications", "app.workers.outbox", "process_batch", 2),
        ("deletions", "app.workers.imported_storage_cleanup", "process_deletions", 1),
        ("operations", "app.agents.operations_worker", "scan_once", None),
        ("screening", "app.agents.application", "process_one", True),
    ]:
        mocks[name] = Mock(return_value=result)
        monkeypatch.setattr(f"{module}.{function}", mocks[name])
    return TestClient(app), app, mocks


@pytest.mark.parametrize("authorization", [None, "Bearer wrong", "Bearer tést", ""])
def test_unauthorized_invocations_never_run_work(cron, authorization):
    client, _, mocks = cron
    headers = {} if authorization is None else {"Authorization": authorization}
    if authorization == "Bearer tést":
        headers = {b"Authorization": authorization.encode()}
    for path in ("maintenance", "screening"):
        assert client.get(f"/api/internal/cron/{path}", headers=headers).status_code == 401
    assert not any(mock.called for mock in mocks.values())


@pytest.mark.parametrize("configured,vercel", [(False, True), (True, False)])
def test_disabled_or_missing_secret_fails_closed(cron, configured, vercel):
    client, app, mocks = cron
    app.state.settings.vercel = vercel
    if not configured:
        app.state.settings.cron_secret = SecretStr("")
    assert client.get("/api/internal/cron/maintenance", headers={
        "Authorization": "Bearer test-cron-secret"}).status_code == 401
    assert not any(mock.called for mock in mocks.values())


def test_authorized_maintenance_uses_bounded_existing_workers(cron):
    client, app, mocks = cron
    response = client.get("/api/internal/cron/maintenance", headers={
        "Authorization": "Bearer test-cron-secret"})
    assert response.status_code == 200
    assert response.json() == {"notifications": 2, "files_deleted": 1}
    mocks["notifications"].assert_called_once_with(app.state.sessions, "synthetic", limit=50)
    mocks["deletions"].assert_called_once_with(app.state.sessions, app.state.settings, limit=5)
    mocks["operations"].assert_called_once_with(app)
    mocks["screening"].assert_not_called()


def test_maintenance_preserves_feature_flags(cron):
    client, app, mocks = cron
    app.state.settings.imported_storage_cleanup_enabled = False
    app.state.settings.recruitment_operations_enabled = False
    assert client.get("/api/internal/cron/maintenance", headers={
        "Authorization": "Bearer test-cron-secret"}).status_code == 200
    mocks["deletions"].assert_not_called()
    mocks["operations"].assert_not_called()


def test_screening_processes_one_claimed_job(cron):
    client, app, mocks = cron
    response = client.get("/api/internal/cron/screening", headers={
        "Authorization": "Bearer test-cron-secret"})
    assert response.status_code == 200
    assert response.json() == {"processed": True}
    mocks["screening"].assert_called_once_with(app)
    mocks["notifications"].assert_not_called()


def test_vercel_lifespan_does_not_start_persistent_workers(monkeypatch):
    from app.core.config import Settings
    from app.main import create_app

    def forbidden(*args, **kwargs):
        raise AssertionError("Vercel must not start persistent work")

    monkeypatch.setattr("app.agents.voice_realtime.recover", forbidden)
    monkeypatch.setattr("app.agents.operations_worker.run_operations", forbidden)
    monkeypatch.setattr("app.agents.application.run_screening", forbidden)
    monkeypatch.setattr("app.workers.imported_storage_cleanup.run_cleanup", forbidden)
    settings = Settings(_env_file=None, environment="local", vercel=True,
        database_url="sqlite:///:memory:", auth_mode="local", jwt_secret="test-secret-" * 5,
        ai_voice_interviews_enabled=True, recruitment_operations_enabled=True,
        ai_screening_enabled=True, imported_storage_cleanup_enabled=True)
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/internal/cron/maintenance").status_code == 401


def test_vercel_live_voice_fails_before_provider_or_session_mutation(api, monkeypatch):
    from app.agents import voice_realtime
    from app.agents.models import VoiceInterview
    from test_voice_interview import setup_voice, ROOT

    client, app, _, _ = api
    _, _, invite, token, _ = setup_voice(api)
    app.state.settings.vercel = True
    create_call = Mock()
    monkeypatch.setattr(voice_realtime, "create_call", create_call)
    response = client.post(ROOT + "/public/live", headers=token,
        json={"sdp": "v=0\r\ns=synthetic-test-offer\r\n", "consent": True})
    assert response.status_code == 503
    create_call.assert_not_called()
    with app.state.sessions() as db:
        record = db.get(VoiceInterview, invite["id"])
        assert record.status == "invited"
        assert record.realtime_attempts == 0
        assert record.realtime_call_id is None
