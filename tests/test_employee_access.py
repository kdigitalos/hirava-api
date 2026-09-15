from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.employee_access import employee_link, set_employee_link
from conftest import get, post


def test_employee_link_preserves_identity_and_rejects_takeover():
    engine = create_engine('sqlite://')
    with engine.begin() as c:
        c.exec_driver_sql("ATTACH DATABASE ':memory:' AS public")
        c.exec_driver_sql('CREATE TABLE public."User" (id TEXT PRIMARY KEY, auth0_sub TEXT UNIQUE, email TEXT UNIQUE, name TEXT, role TEXT, created_at TEXT, updated_at TEXT)')
        c.exec_driver_sql('CREATE TABLE public."Employee" (id TEXT PRIMARY KEY, employee_code TEXT, first_name TEXT, last_name TEXT, user_id TEXT UNIQUE, status TEXT, updated_at TEXT)')
        c.exec_driver_sql("INSERT INTO public.Employee VALUES ('e1','TEST1','Test','One',NULL,'ACTIVE',NULL),('e2','TEST2','Test','Two',NULL,'ACTIVE',NULL),('e3','TEST3','Test','Three',NULL,'TERMINATED',NULL)")
    account = SimpleNamespace(id='u1', auth_subject=None, email='one@example.com', name='One', role='employee', active=True)
    other = SimpleNamespace(id='u2', auth_subject=None, email='two@example.com', name='Two', role='employee', active=True)
    with Session(engine) as db:
        assert employee_link(db, account) is None
        assert set_employee_link(db, account, 'e1')['id'] == 'e1'
        assert set_employee_link(db, account, 'e1')['id'] == 'e1'
        assert db.scalar(text('SELECT count(*) FROM public."User"')) == 1
        with pytest.raises(HTTPException) as err: set_employee_link(db, other, 'e1')
        assert err.value.status_code == 409
        with pytest.raises(HTTPException): set_employee_link(db, account, 'e2')
        assert set_employee_link(db, account, None) is None
        assert set_employee_link(db, account, 'e2')['id'] == 'e2'
        with pytest.raises(HTTPException): set_employee_link(db, other, 'e3')
        with pytest.raises(HTTPException): set_employee_link(db, other, 'missing')
        db.rollback()
        assert db.scalar(text('SELECT count(*) FROM public."User"')) == 0
        assert db.scalar(text('SELECT count(*) FROM public.Employee WHERE user_id IS NOT NULL')) == 0


def test_link_api_permissions_versions_and_revocation(api, monkeypatch):
    import app.core.employee_access as service
    client, app, users, headers = api
    app.state.settings.legacy_api_url = ''
    monkeypatch.setattr(service, 'employee_link', lambda db, account: None)
    writes = []
    monkeypatch.setattr(service, 'set_employee_link', lambda db, account, employee_id: writes.append(employee_id))
    target = users['employee']
    path = f'/api/v1/users/{target}/employee-link'
    for role in ['employee', 'hr', 'manager', 'recruiter', 'interviewer']:
        assert client.get(path, headers=headers[role]).status_code == 403
        assert client.put(path, json={'employee_id': 'e1', 'expected_version': 1}, headers=headers[role]).status_code == 403
    assert client.get(path, headers=headers['outsider']).status_code == 401
    result = client.get(path, headers=headers['admin']).json()
    assert client.put(path, json={'employee_id': 'e1', 'expected_version': result['version'] + 1}, headers=headers['admin']).status_code == 409
    assert writes == []
    response = client.put(path, json={'employee_id': 'e1', 'expected_version': result['version']}, headers=headers['admin'])
    assert response.status_code == 200
    assert writes == ['e1']
    assert client.get('/api/v1/auth/me', headers=headers['employee']).status_code == 401
    assert client.put(path, json={'employee_id': 'e2', 'expected_version': result['version']}, headers=headers['admin']).status_code == 409
    assert any(e['action'] == 'user.employee_link_changed' for e in get(api, '/audit'))


def test_local_account_cannot_supply_auth0_subject(api):
    post(api, '/users', {'name': 'Test', 'email': 'new@example.com', 'role': 'employee',
         'password': 'Synthetic-password-123', 'auth_subject': 'auth0|other'}, status=422)
