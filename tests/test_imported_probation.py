from app.data.imported import table
from app.modules.workforce.imported_probation import DEFAULTS
from test_imported_leave_attendance import setup_people


def test_probation_independent_review_extension_confirmation_and_policy(api):
    client, app, _, headers = api
    people = setup_people(api)
    with app.state.sessions.begin() as db:
        for model in ('Department', 'JobTitle', 'Branch', 'ProbationRecord', 'ProbationPolicySettings'):
            table(db, model).create(db.bind)
    body = {'employeeId': people['hr']['id'], 'reportingManager': 'Synthetic manager', 'joiningDate': '2026-01-01', 'probationStart': '2026-01-01', 'probationEnd': '2026-01-31'}
    assert client.post('/api/probation-records', json={**body, 'status': 'CONFIRMED'}, headers=headers['hr']).status_code == 403
    response = client.post('/api/probation-records', json=body, headers=headers['admin'])
    assert response.status_code == 201, response.text
    url = '/api/probation-records/' + response.json()['id']
    assert client.post('/api/probation-records', json=body, headers=headers['admin']).status_code == 409
    assert client.patch(url, json={'action': 'confirm'}, headers=headers['hr']).status_code == 403
    response = client.patch(url, json={'action': 'extend', 'monthsAdded': 1, 'note': 'Synthetic extension', 'notifyEmployee': False}, headers=headers['admin'])
    assert response.status_code == 200, response.text
    assert response.json()['probationEnd'] == '28 Feb 2026'
    assert response.json()['extensions'] == 1
    review = {'action': 'add-review', 'title': 'Final Review', 'description': 'Synthetic evidence', 'performanceRating': 4, 'attendanceRating': 'Good', 'skills': ['Python'], 'recommendation': 'CONFIRM', 'reviewedBy': 'Spoofed reviewer'}
    response = client.patch(url, json=review, headers=headers['admin'])
    assert response.status_code == 200, response.text
    assert response.json()['status'] != 'Confirmed'
    assert response.json()['reviews'][0]['reviewedBy'] == 'admin'
    assert next(step for step in response.json()['timeline'] if step['label'] == 'Mid Review')['state'] != 'completed'
    response = client.patch(url, json={'action': 'confirm'}, headers=headers['admin'])
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'Confirmed'
    assert client.patch(url, json=review, headers=headers['admin']).status_code == 409
    assert client.get('/api/probation-records/filter-options', headers=headers['hr']).status_code == 200
    assert client.get('/api/probation-records', headers=headers['employee']).status_code == 403
    settings = client.get('/api/probation-settings', headers=headers['hr']).json()
    assert settings['updatedAt'] is None
    payload = {key: value for key, value in DEFAULTS.items() if key != 'id'}
    response = client.put('/api/probation-settings', json={**payload, 'maxExtensions': 3}, headers=headers['hr'])
    assert response.status_code == 200, response.text
    assert client.get('/api/probation-settings', headers=headers['hr']).json()['maxExtensions'] == 3
