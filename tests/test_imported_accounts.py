from app.modules.workforce import imported_accounts
from app.data.imported import table
from tests.test_imported_leave_attendance import setup_people


def test_account_compatibility_uses_native_invitation_and_permissions(api, monkeypatch):
    client, app, _, headers = api
    people = setup_people(api)
    app.state.settings.legacy_api_url = ''
    with app.state.sessions.begin() as db:
        employees = table(db, 'Employee')
        db.execute(employees.update().where(employees.c.id == people['other']['id']).values(email='synthetic@example.com'))
    path = '/api/admin/employees-pending-access'
    assert client.get(path, headers=headers['hr']).status_code == 403
    assert [r['id'] for r in client.get(path, headers=headers['admin']).json()] == [people['other']['id']]
    payload = {'name': 'Synthetic invite', 'email': 'invite@example.com', 'role': 'hr_manager'}
    assert client.post('/api/admin/create-user', json=payload, headers=headers['hr']).status_code == 403
    assert client.post('/api/admin/create-user', json=payload, headers=headers['admin']).status_code == 503
    calls = []
    def invite(body, request, actor, db):
        calls.append(body)
        return {'account': {'id': 'synthetic', 'email': str(body.email), 'role': body.role},
                'invitation': {'status': 'accepted_by_provider'}}
    monkeypatch.setattr(imported_accounts, 'invite', invite)
    response = client.post('/api/admin/create-user', json=payload, headers=headers['admin'])
    assert response.status_code == 201, response.text
    assert calls[-1].role == 'hr'
    assert response.json()['success'] and 'not confirmed' in response.json()['message']
    response = client.post('/api/admin/provision-employee-access', json={'employeeId': people['other']['id'], 'role': 'EMPLOYEE'}, headers=headers['admin'])
    assert response.status_code == 201, response.text
    assert calls[-1].employee_id == people['other']['id']
    assert calls[-1].email == 'synthetic@example.com'
    assert client.post('/api/admin/provision-employee-access', json={'employeeId': people['employee']['id'], 'role': 'ADMIN'}, headers=headers['admin']).status_code == 409
    assert len(calls) == 2


def test_account_role_changes_are_authoritative_and_revoke_sessions(api):
    client, app, users, headers = api
    setup_people(api)
    path = '/api/users/' + users['employee']
    assert client.get('/api/users', headers=headers['employee']).status_code == 403
    assert client.patch(path, json={'role': 'ADMIN'}, headers=headers['hr']).status_code == 403
    assert client.patch('/api/users/' + users['admin'], json={'role': 'HR'}, headers=headers['admin']).status_code == 409
    assert client.patch(path, json={'role': 'CANDIDATE'}, headers=headers['admin']).status_code == 409
    response = client.patch(path, json={'role': 'HR'}, headers=headers['admin'])
    assert response.status_code == 200, response.text
    assert response.json()['role'] == 'HR'
    assert client.get('/api/v1/auth/me', headers=headers['employee']).status_code == 401
    data = client.get(path, headers=headers['admin']).json()
    assert not any(key in data for key in ('password_hash', 'token_version', 'auth_subject'))
