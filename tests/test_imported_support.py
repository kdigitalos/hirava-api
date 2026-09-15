from app.data.imported import table
from app.modules.workforce.imported_organization import update
from test_imported_leave_attendance import setup_people


def test_helpdesk_ownership_labels_assignment_and_resolution(api):
    client, app, _, headers = api
    people = setup_people(api)
    with app.state.sessions.begin() as db:
        for model in ('SupportTicket', 'Department'):
            table(db, model).create(db.bind)
    body = {'title': 'Synthetic ticket', 'description': 'Synthetic description', 'category': 'IT', 'priority': 'High'}
    response = client.post('/api/support-tickets', json=body, headers=headers['employee'])
    assert response.status_code == 201, response.text
    id = response.json()['rowId']
    assert response.json()['id'] == 'TKT-001'
    assert client.get('/api/support-tickets', headers=headers['manager']).json()['items'] == []
    assert client.get('/api/ask-me/tickets', headers=headers['employee']).status_code == 403
    assert len(client.get('/api/ask-me/tickets?scope=mine', headers=headers['employee']).json()['tickets']) == 1
    path = '/api/admin/support-tickets/by-id/' + id
    assert client.patch(path, json={'status': 'Resolved'}, headers=headers['employee']).status_code == 403
    response = client.patch(path, json={'assignedToEmployeeId': people['manager']['id'], 'status': 'Resolved'}, headers=headers['hr'])
    assert response.status_code == 200, response.text
    resolved = response.json()['resolvedAt']
    assert resolved
    assert client.get('/api/support-tickets', headers=headers['manager']).json()['items'][0]['status'] == 'Resolved'
    response = client.patch('/api/ask-me/tickets/by-id/' + id, json={'status': 'CLOSED'}, headers=headers['hr'])
    assert response.status_code == 200, response.text
    assert client.get(path, headers=headers['hr']).json()['resolvedAt'] == resolved
    assert client.get('/api/admin/support-tickets/stats', headers=headers['hr']).json()['closed'] == 1
    # Existing title-case rows remain visible under normalized filters.
    with app.state.sessions.begin() as db:
        update(db, 'SupportTicket', id, {'status': 'Closed', 'priority': 'High'})
    assert len(client.get('/api/admin/support-tickets?status=Closed&priority=High', headers=headers['hr']).json()['items']) == 1
    assert client.patch(path, json={'status': 'Open'}, headers=headers['hr']).json()['resolvedAt'] is None
    request = {'employeeId': people['other']['id'], 'subject': 'Other ticket', 'description': 'Synthetic', 'category': 'HR', 'priority': 'LOW'}
    assert client.post('/api/ask-me/tickets', json=request, headers=headers['employee']).status_code == 403
    assert client.post('/api/ask-me/tickets', json=request, headers=headers['hr']).status_code == 201
    assert client.get('/api/ask-me/tickets/agents', headers=headers['employee']).status_code == 403
    assert client.get('/api/ask-me/tickets/agents', headers=headers['hr']).status_code == 200
    assert client.delete('/api/ask-me/tickets/by-id/' + id, headers=headers['employee']).status_code == 403
    assert client.delete('/api/ask-me/tickets/by-id/' + id, headers=headers['hr']).status_code == 204
