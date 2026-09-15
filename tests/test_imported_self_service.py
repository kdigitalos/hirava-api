from app.data.imported import find, table
from app.modules.workforce.imported_assets import insert
from test_imported_leave_attendance import setup_people


def test_profile_proposals_supersede_and_apply_only_after_independent_review(api):
    client, app, _, headers = api
    people = setup_people(api)
    with app.state.sessions.begin() as db:
        for model in ('Department', 'JobTitle', 'EmployeeProfile', 'EmployeeSelfServiceRequest'):
            table(db, model).create(db.bind)
        insert(db, 'EmployeeProfile', {'employeeId': people['employee']['id'], 'nationality': 'Preserved'})
    response = client.patch('/api/my-profile', json={'displayName': 'Proposed', 'firstName': 'Updated', 'dateOfBirth': '1995-01-03'}, headers=headers['employee'])
    assert response.status_code == 202, response.text
    first = response.json()['request']['id']
    assert client.get('/api/my-profile', headers=headers['employee']).json()['employee']['firstName'] == 'Synthetic'
    assert client.patch('/api/my-profile', json={'role': 'admin'}, headers=headers['employee']).status_code == 422
    assert client.patch('/api/my-profile', json={'dateOfBirth': '2026-02-30'}, headers=headers['employee']).status_code == 422
    response = client.patch('/api/my-profile', json={'displayName': 'Replacement', 'firstName': 'Updated', 'dateOfBirth': '1995-01-03', 'benefits': ['Test']}, headers=headers['employee'])
    assert response.status_code == 202, response.text
    second = response.json()['request']['id']
    pending = client.get('/api/my-profile/pending-request', headers=headers['employee']).json()['pending']
    assert pending['id'] == second
    root = '/api/admin/self-service-requests/'
    assert client.patch(root + first, json={'status': 'APPROVED'}, headers=headers['hr']).status_code == 409
    assert client.patch(root + second, json={'status': 'APPROVED'}, headers=headers['employee']).status_code == 403
    detail = client.get(root + second, headers=headers['hr']).json()
    assert detail['current']['firstName'] == 'Synthetic'
    assert detail['payload']['firstName'] == 'Updated'
    response = client.patch(root + second, json={'status': 'Approved', 'reviewNote': 'Synthetic review'}, headers=headers['hr'])
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'Approved'
    profile = client.get('/api/my-profile', headers=headers['employee']).json()
    assert profile['employee']['firstName'] == 'Updated'
    assert profile['profile']['displayName'] == 'Replacement'
    assert profile['profile']['nationality'] == 'Preserved'
    assert profile['profile']['dateOfBirth'] == '1995-01-03'
    assert client.get('/api/my-profile/pending-request', headers=headers['employee']).json()['pending'] is None
    assert client.patch(root + second, json={'status': 'REJECTED'}, headers=headers['hr']).status_code == 409
    own = client.patch('/api/my-profile', json={'displayName': 'HR proposal'}, headers=headers['hr']).json()['request']['id']
    assert client.patch(root + own, json={'status': 'APPROVED'}, headers=headers['hr']).status_code == 403
    assert client.patch(root + own, json={'status': 'REJECTED', 'reviewNote': 'Test rejection'}, headers=headers['admin']).status_code == 200
    assert client.get('/api/my-profile', headers=headers['hr']).json()['profile'] == {}
    response = client.get('/api/admin/self-service-requests?search=Updated&type=Profile%20Update&status=Approved', headers=headers['hr'])
    assert response.status_code == 200, response.text
    assert len(response.json()['requests']) == 1
    assert client.get(root + second, headers=headers['outsider']).status_code == 401
    assert client.delete('/api/my-profile', headers=headers['employee']).status_code == 409
