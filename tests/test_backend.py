from datetime import date, timedelta

import jwt
import pytest
from sqlalchemy import func, select

from app.core.config import Settings
from app.core.models import Notification, OutboxEvent, User
from app.core.security import issue_token
from app.modules.workforce.models import Worker
from app.workers.outbox import process_batch
from conftest import PASSWORD, accepted_offer, active_worker, get, position, post


def test_health_and_schema(api):
    client = api[0]
    assert client.get("/api/v1/health").json() == {"status": "ok", "service": "hirava-api"}
    assert client.get("/docs").status_code == 200
    schema = client.get("/openapi.json").json()
    assert "/api/v1/conversion/approve" in schema["paths"]
    assert "HTTPBearer" in schema["components"]["securitySchemes"]
    assert client.get("/api/v1/ready").status_code == 503  # create_all is not a migration


def test_login_logout_and_disabled_users(api):
    token = post(api, "/auth/login", {"email": "employee@example.com", "password": PASSWORD}, status=200)
    client, _, users, headers = api
    auth = {"Authorization": "Bearer " + token["access_token"]}
    assert client.get("/api/v1/auth/me", headers=auth).status_code == 200
    assert "password_hash" not in client.get("/api/v1/auth/me", headers=auth).json()
    assert client.post("/api/v1/auth/logout", headers=auth).status_code == 204
    assert client.get("/api/v1/auth/me", headers=auth).status_code == 401
    response = client.patch(f"/api/v1/users/{users['employee']}", headers=headers["admin"], json={"active": False})
    assert response.status_code == 200
    assert client.get("/api/v1/auth/me", headers=headers["employee"]).status_code == 401


def test_bad_login_counter_persists(api):
    for _ in range(5):
        post(api, "/auth/login", {"email": "employee@example.com", "password": "incorrect"}, status=401)
    post(api, "/auth/login", {"email": "employee@example.com", "password": PASSWORD}, status=401)
    with api[1].state.sessions() as db:
        assert db.get(User, api[2]["employee"]).failed_logins == 5


def test_unauthenticated_and_other_customer_tokens_rejected(api):
    assert api[0].get("/api/v1/hrms/workers").status_code == 401
    get(api, "/hrms/workers", role="outsider", status=401)
    token = jwt.encode({"sub": api[2]["admin"]}, "wrong-secret" * 4, algorithm="HS256")
    assert api[0].get("/api/v1/auth/me", headers={"Authorization": "Bearer " + token}).status_code == 401


@pytest.mark.parametrize("role,path", [
    ("recruiter", "/hrms/workers"), ("recruiter", "/hrms/cases"),
    ("employee", "/rms/candidates"), ("interviewer", "/rms/candidates"),
    ("manager", "/audit"), ("hr", "/users"), ("recruiter", "/reports/hrms"),
])
def test_role_boundaries(api, role, path):
    get(api, path, role=role, status=403)


@pytest.mark.parametrize("module,paths", [
    ("rms", ["/rms/candidates", "/rms/offers", "/rms/interviews", "/conversion", "/reports/rms"]),
    ("hrms", ["/hrms/workers", "/hrms/cases", "/hrms/leave/types", "/conversion", "/reports/hrms"]),
])
def test_module_entitlements_apply_even_to_admin(api, module, paths):
    setattr(api[1].state.settings, module + "_enabled", False)
    for path in paths:
        get(api, path, status=403)


def test_rms_only_keeps_core_references(api):
    api[1].state.settings.hrms_enabled = False
    assert position(api)["occupied"] == 0
    get(api, "/rms/candidates")


def test_hrms_only_direct_hire(api):
    api[1].state.settings.rms_enabled = False
    assert active_worker(api)["worker"]["email"] == "employee@example.com"


def test_requisition_needs_separate_approval(api):
    pos = position(api)
    record = post(api, "/rms/requisitions", {"position_id": pos["id"], "title": "Role", "description": "Description"})
    post(api, f"/rms/requisitions/{record['id']}/publish", status=409)
    post(api, f"/rms/requisitions/{record['id']}/submit", status=200)
    post(api, f"/rms/requisitions/{record['id']}/approve", {"reason": "Approved"}, status=403)
    post(api, f"/rms/requisitions/{record['id']}/approve", {"reason": "Approved"}, role="hr", status=200)


def test_recruiting_to_onboarding_is_idempotent_and_requires_hr(api):
    offer = accepted_offer(api)
    assert get(api, "/hrms/workers", role="hr") == []
    body = {"offer_id": offer["id"], "user_id": api[2]["employee"], "approval_reason": "Reviewed mapping"}
    key = {"Idempotency-Key": "conversion-test-001"}
    post(api, "/conversion/approve", body, role="recruiter", status=403, extra_headers=key)
    preview = get(api, f"/conversion/offers/{offer['id']}/preview", role="hr")
    assert set(preview["mapping"]) == {"name", "email", "position_id", "start_date"}
    first = post(api, "/conversion/approve", body, role="hr", extra_headers=key)
    second = post(api, "/conversion/approve", body, role="hr", extra_headers=key)
    assert first["id"] == second["id"]
    assert len(get(api, "/hrms/workers", role="hr")) == 1
    employment = get(api, "/hrms/employments", role="hr")[0]
    assert employment["status"] == "prehire"
    post(api, f"/hrms/employments/{employment['id']}/commence", {"reason": "Ready"}, role="hr", status=409)
    post(api, "/conversion/approve", {**body, "approval_reason": "Changed"}, role="hr", status=409, extra_headers=key)
    post(api, "/conversion/approve", body, role="hr", status=409, extra_headers={"Idempotency-Key": "different-key-001"})
    assert get(api, "/organization/positions")[0]["occupied"] == 1


def test_capacity_failure_rolls_back_worker_and_conversion(api):
    pos = position(api)
    offer = accepted_offer(api, position_id=pos["id"])
    post(api, "/hrms/workers", {"name": "Other", "email": "other@example.com", "position_id": pos["id"],
                                "start_date": date.today().isoformat(), "approval_reason": "Direct hire approved"}, role="hr")
    post(api, "/conversion/approve", {"offer_id": offer["id"], "approval_reason": "Reviewed"}, role="hr", status=409,
         extra_headers={"Idempotency-Key": "capacity-test-001"})
    assert len(get(api, "/hrms/workers", role="hr")) == 1
    assert get(api, "/conversion", role="hr") == []


def test_duplicate_worker_and_unknown_fields_rejected(api):
    created = active_worker(api)
    post(api, "/hrms/workers", {"name": "Duplicate", "email": "employee@example.com", "position_id": created["employment"]["position_id"],
                                "start_date": date.today().isoformat(), "approval_reason": "Reviewed"}, role="hr", status=409)
    post(api, "/rms/candidates", {"name": "Test", "email": "test@example.com", "consent": False, "consent_notice": "v1"}, role="recruiter", status=422)
    post(api, "/rms/candidates", {"name": "Test", "email": "test@example.com", "consent": True, "consent_notice": "v1", "customer_id": "other"}, role="recruiter", status=422)


def test_employee_scope_and_cross_customer_foreign_key(api):
    created = active_worker(api)
    assert get(api, "/hrms/workers", role="employee")[0]["id"] == created["worker"]["id"]
    with api[1].state.sessions.begin() as db:
        other = Worker(customer_id="customer-b", name="Private", email="private@example.com")
        db.add(other)
        db.flush()
        other_id = other.id
    get(api, f"/hrms/workers/{other_id}", role="hr", status=404)
    assert len(get(api, "/hrms/workers", role="hr")) == 1
    post(api, "/hrms/leave/balances", {"worker_id": other_id, "leave_type_id": "missing", "year": 2026, "granted": 10}, role="hr", status=404)


def next_weekday():
    value = date.today() + timedelta(days=1)
    while value.weekday() >= 5:
        value += timedelta(days=1)
    return value


def test_leave_approval_balance_and_cancellation(api):
    worker = active_worker(api)["worker"]
    kind = post(api, "/hrms/leave/types", {"name": "Annual"}, role="hr")
    day = next_weekday()
    post(api, "/hrms/leave/balances", {"worker_id": worker["id"], "leave_type_id": kind["id"], "year": day.year, "granted": 1}, role="hr")
    body = {"worker_id": worker["id"], "leave_type_id": kind["id"], "start_date": day.isoformat(), "end_date": day.isoformat(), "reason": "Personal leave"}
    record = post(api, "/hrms/leave/requests", body, role="employee")
    post(api, "/hrms/leave/requests", body, role="employee", status=409)
    post(api, f"/hrms/leave/requests/{record['id']}/approve", {"reason": "Approved"}, role="employee", status=403)
    post(api, f"/hrms/leave/requests/{record['id']}/approve", {"reason": "Approved"}, role="manager", status=200)
    assert get(api, "/hrms/leave/balances", role="employee")[0]["used"] == 1
    post(api, f"/hrms/leave/requests/{record['id']}/approve", {"reason": "Approved again"}, role="manager", status=409)
    post(api, f"/hrms/leave/requests/{record['id']}/cancel", {"reason": "Plans changed"}, role="employee", status=200)
    assert get(api, "/hrms/leave/balances", role="employee")[0]["used"] == 0


def test_leave_without_balance_is_not_approved(api):
    worker = active_worker(api)["worker"]
    kind = post(api, "/hrms/leave/types", {"name": "Annual"}, role="hr")
    day = next_weekday()
    record = post(api, "/hrms/leave/requests", {"worker_id": worker["id"], "leave_type_id": kind["id"], "start_date": day.isoformat(),
                                               "end_date": day.isoformat(), "reason": "Test"}, role="employee")
    post(api, f"/hrms/leave/requests/{record['id']}/approve", {"reason": "Approved"}, role="manager", status=409)
    assert get(api, "/hrms/leave/requests", role="employee")[0]["status"] == "pending"


def test_restricted_case_notes(api):
    record = post(api, "/hrms/cases", {"subject": "Private question", "description": "Synthetic case description"}, role="employee")
    post(api, f"/hrms/cases/{record['id']}/notes", {"content": "Restricted synthetic HR note"}, role="hr")
    get(api, f"/hrms/cases/{record['id']}/notes", role="employee", status=403)
    get(api, f"/hrms/cases/{record['id']}/notes", role="manager", status=403)
    assert len(get(api, f"/hrms/cases/{record['id']}/notes", role="hr")) == 1
    assert get(api, "/hrms/cases", role="manager") == []


def test_document_boundaries_and_upload_limit(api):
    client, app, _, headers = api
    response = client.post("/api/v1/documents?domain=hrms", headers=headers["hr"], files={"file": ("evidence.txt", b"synthetic")})
    assert response.status_code == 201, response.text
    record = response.json()
    assert "storage_key" not in record
    download = client.get(f"/api/v1/documents/{record['id']}", headers=headers["hr"])
    assert download.content == b"synthetic"
    assert download.headers["content-disposition"].startswith("attachment")
    get(api, f"/documents/{record['id']}", role="recruiter", status=404)
    app.state.settings.max_upload_bytes = 3
    response = client.post("/api/v1/documents?domain=hrms", headers=headers["hr"], files={"file": ("too-big.txt", b"too big")})
    assert response.status_code == 413
    assert len(list((app.state.settings.storage_path / "customer-a").iterdir())) == 1


def test_policy_acknowledgement_is_idempotent(api):
    policy = post(api, "/policies", {"title": "Synthetic policy", "content": "Example policy"}, role="hr")
    first = post(api, f"/policies/{policy['id']}/acknowledge", role="employee", status=200)
    second = post(api, f"/policies/{policy['id']}/acknowledge", role="employee", status=200)
    assert first["id"] == second["id"]


def test_learning_and_performance(api):
    worker = active_worker(api)["worker"]
    goal = post(api, "/hrms/performance/goals", {"worker_id": worker["id"], "title": "Complete onboarding", "due_date": date.today().isoformat()}, role="manager")
    post(api, f"/hrms/performance/goals/{goal['id']}/complete", role="employee", status=200)
    review = post(api, "/hrms/performance/reviews", {"worker_id": worker["id"], "period": "First month", "feedback": "Human authored feedback"}, role="manager")
    post(api, f"/hrms/performance/reviews/{review['id']}/acknowledge", role="manager", status=403)
    post(api, f"/hrms/performance/reviews/{review['id']}/acknowledge", role="employee", status=200)
    course = post(api, "/hrms/learning/courses", {"title": "Orientation", "reference_url": "https://example.com/orientation"}, role="hr")
    assignment = post(api, "/hrms/learning/assignments", {"worker_id": worker["id"], "course_id": course["id"]}, role="manager")
    post(api, f"/hrms/learning/assignments/{assignment['id']}/complete", {"reason": "Completed synthetic course"}, role="employee", status=200)


def test_offboarding_requires_evidence_then_revokes_local_access(api):
    created = active_worker(api)
    case = post(api, f"/hrms/employments/{created['employment']['id']}/offboard", {"reason": "Approved synthetic exit"}, role="hr")
    post(api, f"/hrms/lifecycle-cases/{case['id']}/close", {"reason": "Done"}, role="hr", status=409)
    for task in get(api, "/hrms/tasks", role="hr"):
        if task["case_id"] == case["id"]:
            post(api, f"/hrms/tasks/{task['id']}/complete", {"reason": "Verified synthetic provider reconciliation"}, role="hr", status=200)
    post(api, f"/hrms/lifecycle-cases/{case['id']}/close", {"reason": "Exit reconciled"}, role="hr", status=200)
    get(api, "/auth/me", role="employee", status=401)
    assert get(api, "/organization/positions")[0]["occupied"] == 0


def test_outbox_deduplication_and_failed_event_repair(api):
    active_worker(api)
    app = api[1]
    assert process_batch(app.state.sessions, "customer-a") == 1
    assert process_batch(app.state.sessions, "customer-a") == 0
    assert len(get(api, "/notifications", role="hr")) == 1
    with app.state.sessions.begin() as db:
        event = OutboxEvent(customer_id="customer-a", topic="unsupported", payload={})
        db.add(event)
        db.flush()
        event_id = event.id
    process_batch(app.state.sessions, "customer-a")
    with app.state.sessions() as db:
        assert db.get(OutboxEvent, event_id).status == "failed"
    post(api, f"/outbox/{event_id}/retry", status=200)


def test_audit_records_have_actor_and_correlation(api):
    position(api)
    records = get(api, "/audit")
    assert len(records) == 2
    assert all(row["actor_id"] == api[2]["admin"] and row["correlation_id"] for row in records)


def test_production_config_and_customer_path_validation():
    with pytest.raises(ValueError):
        Settings(_env_file=None, environment="production", auth_mode="local", jwt_secret="s" * 40)
    with pytest.raises(ValueError):
        Settings(_env_file=None, customer_id="../other", jwt_secret="s" * 40)


def test_candidate_self_service_and_record_isolation(api):
    client, _, _, headers = api
    pos = position(api)
    requisition = post(api, "/rms/requisitions", {"position_id": pos["id"], "title": "Public Engineer", "description": "Public vacancy"}, role="recruiter")
    assert client.get("/api/v1/careers/jobs").json() == []
    post(api, f"/rms/requisitions/{requisition['id']}/submit", role="recruiter", status=200)
    post(api, f"/rms/requisitions/{requisition['id']}/approve", {"reason": "Approved"}, role="hr", status=200)
    post(api, f"/rms/requisitions/{requisition['id']}/publish", role="recruiter", status=200)
    jobs = client.get("/api/v1/careers/jobs").json()
    assert set(jobs[0]) == {"id", "title", "description"}
    for name in ("alice", "bob"):
        token = post(api, "/careers/register", {"name": name, "email": f"{name}@example.com", "password": PASSWORD,
                                               "consent": True, "consent_notice": "test-v1"})
        headers[name] = {"Authorization": "Bearer " + token["access_token"]}
    application = post(api, "/careers/applications", {"requisition_id": requisition["id"]}, role="alice")
    assert get(api, "/careers/applications", role="bob") == []
    assert "disposition_reason" not in get(api, "/careers/applications", role="alice")[0]
    post(api, f"/careers/applications/{application['id']}/withdraw", {"reason": "Withdraw"}, role="bob", status=404)
    get(api, "/rms/candidates", role="alice", status=403)
    get(api, "/hrms/workers", role="alice", status=403)
    get(api, "/policies", role="alice", status=403)
    for stage in ["screening", "interviewing", "selected"]:
        post(api, f"/rms/applications/{application['id']}/transition", {"status": stage, "reason": "Reviewed"}, role="recruiter", status=200)
    offer = post(api, "/rms/offers", {"application_id": application["id"], "annual_salary": "50000", "currency": "USD", "start_date": date.today().isoformat()}, role="recruiter")
    assert get(api, "/careers/offers", role="alice") == []
    post(api, f"/rms/offers/{offer['id']}/submit", role="recruiter", status=200)
    post(api, f"/rms/offers/{offer['id']}/approve", {"reason": "Approved"}, role="hr", status=200)
    post(api, f"/careers/offers/{offer['id']}/accept", {"reason": "I accept the approved terms"}, role="bob", status=404)
    post(api, f"/careers/offers/{offer['id']}/accept", {"reason": "I accept the approved terms"}, role="alice", status=200)
    assert get(api, "/hrms/workers", role="hr") == []
    api[1].state.settings.rms_enabled = False
    assert client.get("/api/v1/careers/jobs").status_code == 404


def test_profile_change_requires_hr_review(api):
    worker = active_worker(api)["worker"]
    change = post(api, "/hrms/profile-changes", {"worker_id": worker["id"], "proposed_name": "Updated Name", "reason": "Correction"}, role="employee")
    assert get(api, f"/hrms/workers/{worker['id']}", role="employee")["name"] != "Updated Name"
    post(api, f"/hrms/profile-changes/{change['id']}/approve", {"reason": "Verified"}, role="employee", status=403)
    post(api, f"/hrms/profile-changes/{change['id']}/approve", {"reason": "Verified"}, role="hr", status=200)
    assert get(api, f"/hrms/workers/{worker['id']}", role="employee")["name"] == "Updated Name"


def test_concurrent_conversion_retries_produce_one_worker(api):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    offer = accepted_offer(api)
    body = {"offer_id": offer["id"], "approval_reason": "Concurrent retry verification"}
    headers = {**api[3]["hr"], "Idempotency-Key": "concurrent-key-001"}
    barrier = threading.Barrier(2)

    def invoke():
        barrier.wait(timeout=10)
        return api[0].post("/api/v1/conversion/approve", json=body, headers=headers)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: invoke(), range(2)))
    assert all(result.status_code in {201, 409, 503} for result in results), [r.text for r in results]
    replay = api[0].post("/api/v1/conversion/approve", json=body, headers=headers)
    assert replay.status_code == 201, replay.text
    assert len(get(api, "/hrms/workers", role="hr")) == 1
    assert len(get(api, "/conversion", role="hr")) == 1
    assert get(api, "/organization/positions")[0]["occupied"] == 1


def test_optimistic_lock_rejects_stale_updates(api):
    from sqlalchemy.orm.exc import StaleDataError
    from app.modules.organization.models import Position
    created = position(api)
    sessions = api[1].state.sessions
    with sessions() as first, sessions() as second:
        left = first.get(Position, created["id"])
        right = second.get(Position, created["id"])
        left.title = "First update"
        first.commit()
        right.title = "Stale update"
        with pytest.raises(StaleDataError):
            second.commit()


def test_auth0_rs256_validation_and_local_account_mapping(api, monkeypatch):
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from cryptography.hazmat.primitives.asymmetric import rsa
    import app.core.security as security
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    settings = api[1].state.settings
    settings.auth_mode, settings.auth0_domain, settings.auth0_audience = "auth0", "test.example.com", "hirava-test-api"
    with api[1].state.sessions.begin() as db:
        db.get(User, api[2]["hr"]).auth_subject = "auth0|test-hr"
    monkeypatch.setattr(security, "jwks_client", lambda _: SimpleNamespace(
        get_signing_key_from_jwt=lambda _: SimpleNamespace(key=private.public_key())))
    claims = {"sub": "auth0|test-hr", "iss": "https://test.example.com/", "aud": "hirava-test-api",
              "iat": datetime.now(timezone.utc), "exp": datetime.now(timezone.utc) + timedelta(minutes=5)}
    token = jwt.encode(claims, private, algorithm="RS256")
    headers = {"Authorization": "Bearer " + token}
    assert api[0].get("/api/v1/auth/me", headers=headers).status_code == 200
    wrong_audience = jwt.encode({**claims, "aud": "wrong-api"}, private, algorithm="RS256")
    assert api[0].get("/api/v1/auth/me", headers={"Authorization": "Bearer " + wrong_audience}).status_code == 401
    unknown = jwt.encode({**claims, "sub": "auth0|unprovisioned"}, private, algorithm="RS256")
    assert api[0].get("/api/v1/auth/me", headers={"Authorization": "Bearer " + unknown}).status_code == 401
    post(api, "/auth/login", {"email": "hr@example.com", "password": PASSWORD}, status=404)


def test_migrations_upgrade_downgrade_and_readiness(tmp_path, monkeypatch):
    from pathlib import Path
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect
    from fastapi.testclient import TestClient
    from app.data.database import Base, build_engine
    from app.main import create_app
    url = f"sqlite:///{tmp_path / 'migration.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(config, "head")
    engine = build_engine(url)
    assert set(Base.metadata.tables).issubset(inspect(engine).get_table_names())
    settings = Settings(_env_file=None, database_url=url, jwt_secret="s" * 48, environment="test")
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/ready").status_code == 200
    command.check(config)
    command.downgrade(config, "base")
    assert inspect(engine).get_table_names() == ["alembic_version"]
    command.upgrade(config, "head")
    engine.dispose()


def test_interview_assignment_packets_and_scorecards(api):
    from datetime import datetime, timezone
    from app.modules.interviews.models import Interview
    from app.modules.recruiting.models import Application, Candidate, Requisition
    # Seed an interviewing application, then exercise scheduling and evidence over HTTP.
    pos = position(api)
    with api[1].state.sessions.begin() as db:
        req = Requisition(customer_id="customer-a", position_id=pos["id"], title="Role", description="Public job description",
                          requested_by=api[2]["recruiter"], approved_by=api[2]["hr"], status="published")
        candidate = Candidate(customer_id="customer-a", name="Interview Candidate", email="interview@example.com",
                              consent_at=datetime.now(timezone.utc), consent_notice="test-v1")
        db.add_all([req, candidate])
        db.flush()
        application = Application(customer_id="customer-a", candidate_id=candidate.id, requisition_id=req.id, status="interviewing")
        db.add(application)
        db.flush()
        application_id = application.id
    scheduled = datetime.now(timezone(timedelta(hours=5, minutes=30))) + timedelta(days=1)
    record = post(api, "/rms/interviews", {"application_id": application_id, "interviewer_id": api[2]["interviewer"],
                                          "scheduled_at": scheduled.isoformat()}, role="recruiter")
    packet = get(api, f"/rms/interviews/{record['id']}/packet", role="interviewer")
    assert set(packet["packet"]) == {"candidate_name", "job_title", "job_description"}
    get(api, f"/rms/interviews/{record['id']}/packet", role="manager", status=404)
    score = {"competency": "Problem solving", "score": 4, "evidence": "Specific synthetic evidence"}
    post(api, f"/rms/interviews/{record['id']}/scorecard", score, role="manager", status=403)
    post(api, f"/rms/interviews/{record['id']}/scorecard", score, role="interviewer", status=409)
    with api[1].state.sessions.begin() as db:
        interview = db.get(Interview, record["id"])
        assert interview.scheduled_at.replace(tzinfo=timezone.utc) == scheduled.astimezone(timezone.utc)
        interview.scheduled_at = datetime.now(timezone.utc) - timedelta(hours=1)
    post(api, f"/rms/interviews/{record['id']}/scorecard", score, role="interviewer")
    post(api, f"/rms/interviews/{record['id']}/scorecard", score, role="interviewer", status=409)
    assert get(api, f"/rms/interviews/{record['id']}/scorecard", role="recruiter")["score"] == 4
