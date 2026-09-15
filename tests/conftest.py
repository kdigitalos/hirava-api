from functools import lru_cache
from pathlib import Path
from uuid import uuid4
import os

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.models import User
from app.core.security import hash_password, issue_token
from app.data.database import Base, session_factory
from sqlalchemy import text
from app.main import create_app

PASSWORD = "Synthetic-test-password-928!"


@pytest.fixture
def tmp_path():
    # Default mkdir permissions also work under Windows restricted-token runners.
    path = Path(__file__).resolve().parents[1] / "test-output" / str(uuid4())
    path.mkdir(parents=True)
    return path


@lru_cache
def password_hash():
    return hash_password(PASSWORD)


@pytest.fixture
def api(tmp_path, monkeypatch):
    database_url = os.environ.get("HIRAVA_TEST_POSTGRES_URL", f"sqlite:///{tmp_path / 'test.db'}")
    settings = Settings(_env_file=None, environment="test", database_url=database_url,
                        customer_id="customer-a", jwt_secret="test-secret-" * 5, aws_bucket_name="synthetic-bucket")
    from io import BytesIO
    from botocore.response import StreamingBody
    from botocore.exceptions import ClientError
    from app.core import object_storage, imported_storage
    objects = {}
    class FakeS3:
        def put_object(self, Bucket, Key, Body, ContentType='application/octet-stream', **kwargs):
            objects[Key] = (Body.read() if hasattr(Body, 'read') else Body, ContentType)
        def upload_fileobj(self, file, bucket, key, ExtraArgs=None):
            self.put_object(bucket, key, file, **(ExtraArgs or {}))
        def get_object(self, Bucket, Key):
            if Key not in objects:
                raise ClientError({'Error': {'Code': 'NoSuchKey'}}, 'GetObject')
            content, mime = objects[Key]
            return {'Body': StreamingBody(BytesIO(content), len(content)), 'ContentType': mime}
        def delete_object(self, Bucket, Key):
            objects.pop(Key, None)
    fake_s3 = FakeS3()
    monkeypatch.setattr(object_storage, 's3_client', lambda settings: fake_s3)
    monkeypatch.setattr(imported_storage, 's3_client', lambda settings: fake_s3)
    app = create_app(settings)
    app.state.test_s3_objects = objects
    if database_url.startswith("postgresql"):
        schema = "test_" + uuid4().hex
        with app.state.engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        app.state.engine = app.state.engine.execution_options(schema_translate_map={None: schema})
        app.state.sessions = session_factory(app.state.engine)
    Base.metadata.create_all(app.state.engine)
    users, headers = {}, {}
    with app.state.sessions.begin() as db:
        for role in ["admin", "hr", "recruiter", "manager", "interviewer", "employee"]:
            record = User(customer_id=settings.customer_id, email=f"{role}@example.com", name=role,
                          role=role, password_hash=password_hash())
            db.add(record)
            db.flush()
            users[role] = record.id
            headers[role] = {"Authorization": f"Bearer {issue_token(record, settings)}"}
        outsider = User(customer_id="customer-b", email="outsider@example.com", name="outsider",
                        role="admin", password_hash=password_hash())
        db.add(outsider)
        db.flush()
        headers["outsider"] = {"Authorization": f"Bearer {issue_token(outsider, settings)}"}
    with TestClient(app) as client:
        yield client, app, users, headers


def post(api, path, body=None, role="admin", status=201, extra_headers=None):
    client, _, _, headers = api
    response = client.post("/api/v1" + path, json=body, headers={**headers[role], **(extra_headers or {})})
    assert response.status_code == status, (path, response.status_code, response.text)
    return response.json() if response.content else None


def get(api, path, role="admin", status=200):
    client, _, _, headers = api
    response = client.get("/api/v1" + path, headers=headers[role])
    assert response.status_code == status, (path, response.status_code, response.text)
    return response.json()


def position(api, capacity=1):
    unit = post(api, "/organization/units", {"name": "Engineering", "kind": "department"})
    return post(api, "/organization/positions", {"title": "Engineer", "unit_id": unit["id"],
                                                 "capacity": capacity, "manager_id": api[2]["manager"]})


def accepted_offer(api, email="employee@example.com", position_id=None):
    from datetime import date
    position_id = position_id or position(api)["id"]
    req = post(api, "/rms/requisitions", {"position_id": position_id, "title": "Engineer", "description": "Synthetic vacancy"}, role="recruiter")
    post(api, f"/rms/requisitions/{req['id']}/submit", role="recruiter", status=200)
    post(api, f"/rms/requisitions/{req['id']}/approve", {"reason": "Headcount approved"}, role="hr", status=200)
    post(api, f"/rms/requisitions/{req['id']}/publish", role="recruiter", status=200)
    candidate = post(api, "/rms/candidates", {"name": "Synthetic Candidate", "email": email,
                                              "consent": True, "consent_notice": "test-v1"}, role="recruiter")
    application = post(api, "/rms/applications", {"candidate_id": candidate["id"], "requisition_id": req["id"]}, role="recruiter")
    for stage in ["screening", "interviewing", "selected"]:
        post(api, f"/rms/applications/{application['id']}/transition", {"status": stage, "reason": "Human reviewed evidence"}, role="recruiter", status=200)
    offer = post(api, "/rms/offers", {"application_id": application["id"], "annual_salary": "60000.00",
                                     "currency": "USD", "start_date": date.today().isoformat()}, role="recruiter")
    post(api, f"/rms/offers/{offer['id']}/submit", role="recruiter", status=200)
    post(api, f"/rms/offers/{offer['id']}/approve", {"reason": "Terms approved"}, role="hr", status=200)
    post(api, f"/rms/offers/{offer['id']}/accept", {"reason": "Synthetic signed acceptance reference"}, role="recruiter", status=200)
    return offer


def active_worker(api):
    from datetime import date
    pos = position(api)
    created = post(api, "/hrms/workers", {"name": "Synthetic Employee", "email": "employee@example.com",
                                          "position_id": pos["id"], "start_date": date.today().isoformat(),
                                          "user_id": api[2]["employee"], "approval_reason": "HR approved direct hire"}, role="hr")
    for task in get(api, "/hrms/tasks", role="hr"):
        post(api, f"/hrms/tasks/{task['id']}/complete", {"reason": "Verified synthetic evidence"}, role="hr", status=200)
    post(api, f"/hrms/lifecycle-cases/{created['onboarding']['id']}/close", {"reason": "Readiness confirmed"}, role="hr", status=200)
    post(api, f"/hrms/employments/{created['employment']['id']}/commence", {"reason": "Commencement confirmed"}, role="hr", status=200)
    return created
