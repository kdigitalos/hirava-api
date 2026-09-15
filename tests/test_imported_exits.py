from app.data.imported import find, table
from test_imported_leave_attendance import setup_people


def test_exit_ownership_independent_clearance_and_template_snapshot(api):
    client, app, _, headers = api
    people = setup_people(api)
    with app.state.sessions.begin() as db:
        for model in ('Department', 'JobTitle', 'ExitRequest', 'FnfSettlement', 'ExitOffboardingTemplate'):
            table(db, model).create(db.bind)
    payload = {'employeeId': people['hr']['id'], 'resignationDate': '2026-10-01', 'lastWorkingDate': '2026-10-31', 'reason': 'Synthetic resignation', 'exitType': 'Resignation'}
    assert client.post('/api/exit-requests', json={**payload, 'status': 'COMPLETED'}, headers=headers['admin']).status_code == 422
    response = client.post('/api/exit-requests', json=payload, headers=headers['admin'])
    assert response.status_code == 201, response.text
    url = '/api/exit-requests/' + response.json()['id']
    assert client.get(url, headers=headers['employee']).status_code == 403
    assert client.get('/api/exit-requests', headers=headers['employee']).json() == []
    assert client.patch(url, json={'status': 'APPROVED'}, headers=headers['hr']).status_code == 403
    assert client.patch(url, json={'status': 'COMPLETED'}, headers=headers['admin']).status_code == 409
    assert client.patch(url, json={'status': 'APPROVED'}, headers=headers['admin']).status_code == 200
    template_body = {'name': 'Synthetic exit plan', 'stages': [{'id': 'stage-1', 'title': 'Handover', 'days': 1, 'stageDescription': '', 'taskItems': [{'id': 'task-1', 'title': 'Handover notes', 'owner': 'HR', 'dueLabel': 'Today'}]}]}
    response = client.post('/api/exit-offboarding-templates', json=template_body, headers=headers['hr'])
    assert response.status_code == 201, response.text
    template_id = response.json()['template']['id']
    assert len(client.get('/api/exit-offboarding-templates', headers=headers['hr']).json()['templates']) == 1
    applied = client.post('/api/exit-offboarding-templates/' + template_id + '/apply', json={'exitRequestId': url.rsplit('/', 1)[1]}, headers=headers['admin'])
    assert applied.status_code == 201, applied.text
    assert applied.json()['snapshot']['stages'][0]['taskItems'][0]['done'] is False
    clearance = client.get(url + '/clearance', headers=headers['admin']).json()
    assert client.patch(url + '/clearance', json={**clearance, 'complete': True}, headers=headers['admin']).status_code == 409
    for department in clearance['departments']:
        department['status'] = 'Approved'
        department['decidedBy'] = 'Spoofed'
        for item in department['items']:
            item['done'] = True
    assert client.patch(url + '/clearance', json=clearance, headers=headers['hr']).status_code == 403
    response = client.patch(url + '/clearance', json={**clearance, 'complete': True}, headers=headers['admin'])
    assert response.status_code == 200, response.text
    assert response.json()['departments'][0]['decidedBy'] == 'admin'
    assert client.patch(url, json={'status': 'COMPLETED'}, headers=headers['admin']).status_code == 200
    assert client.patch(url + '/clearance', json=clearance, headers=headers['admin']).status_code == 409
    assert client.delete(url, headers=headers['admin']).status_code == 409
    # Own filing ignores a supplied foreign employee and keeps files private.
    response = client.post('/api/exit-requests', data={'employeeId': people['other']['id'], 'draft': 'true'}, files={'attachments': ('synthetic.pdf', b'%PDF-synthetic', 'application/pdf')}, headers=headers['employee'])
    assert response.status_code == 201, response.text
    own = response.json()
    assert own['employeeId'] == people['employee']['id']
    path = '/api/uploads/' + own['attachmentsJson'][0]['relativePath']
    assert client.get(path, headers=headers['employee']).content == b'%PDF-synthetic'
    assert client.get(path, headers=headers['manager']).status_code == 403
    assert client.delete('/api/exit-requests/' + own['id'], headers=headers['admin']).status_code == 204
    assert client.get(path, headers=headers['admin']).status_code == 404
