from app.data.imported import table
from test_imported_leave_attendance import setup_people


def test_task_ownership_calendar_and_policy_roles(api):
    client, app, _, headers = api
    people = setup_people(api)
    with app.state.sessions.begin() as db:
        for model in ('EmployeeTask', 'SupportTicket', 'AdminScheduleItem', 'PrivacyPolicy'):
            table(db, model).create(db.bind)
    task = {'employeeId': people['employee']['id'], 'title': 'Synthetic onboarding', 'description': 'Complete a synthetic task', 'source': 'ONBOARDING', 'dueDate': '2026-10-01'}
    response = client.post('/api/admin/employee-tasks', json=task, headers=headers['hr'])
    assert response.status_code == 201, response.text
    id = response.json()['id']
    own = '/api/employee-tasks/' + id
    assert client.patch(own, json={'completed': True}, headers=headers['manager']).status_code == 404
    assert client.patch(own, json={'completed': True}, headers=headers['employee']).status_code == 200
    assert client.get('/api/employee-tasks', headers=headers['employee']).json()['items'][0]['status'] == 'Completed'
    assert client.get('/api/employee-tasks', headers=headers['manager']).json()['items'] == []
    assert client.post('/api/admin/employee-tasks', json=task, headers=headers['employee']).status_code == 403
    schedule = {'type': 'meetings', 'title': 'Synthetic meeting', 'location': 'Test', 'startAt': '2026-10-01T10:00:00+05:30', 'endAt': '2026-10-01T11:00:00+05:30'}
    response = client.post('/api/admin/schedule-items', json=schedule, headers=headers['hr'])
    assert response.status_code == 201, response.text
    assert response.json()['item']['startAt'].startswith('2026-10-01T04:30:00')
    assert client.post('/api/admin/schedule-items', json={**schedule, 'endAt': schedule['startAt']}, headers=headers['hr']).status_code == 422
    assert len(client.get('/api/admin/schedule-items', headers=headers['hr']).json()['items']) == 1
    policy = {'title': 'Synthetic policy', 'policyType': 'Test', 'applicableTo': 'All', 'description': 'Synthetic only', 'status': 'active'}
    response = client.post('/api/privacy-policies', json=policy, headers=headers['hr'])
    assert response.status_code == 201, response.text
    path = '/api/privacy-policies/' + response.json()['id']
    assert client.get(path, headers=headers['employee']).json()['status'] == 'ACTIVE'
    assert client.patch(path, json={'content': 'Updated'}, headers=headers['employee']).status_code == 403
    assert client.patch(path, json={'content': 'Updated'}, headers=headers['hr']).status_code == 200
    assert client.delete(path, headers=headers['employee']).status_code == 403
    assert client.delete(path, headers=headers['hr']).status_code == 204
