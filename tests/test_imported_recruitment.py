from app.data.imported import table
from conftest import position, post
from test_imported_leave_attendance import setup_people


def test_employee_board_uses_canonical_jobs_and_scopes_applications(api):
    client, app, _, headers = api
    setup_people(api)
    with app.state.sessions.begin() as db:
        for model in ('JobApplication', 'JobReferral'):
            table(db, model).create(db.bind)
    pos = position(api)
    job = post(api, '/rms/requisitions', {'position_id': pos['id'], 'title': 'Synthetic vacancy', 'description': 'Synthetic only'}, role='recruiter')
    assert client.get('/api/job-openings', headers=headers['employee']).json()['jobs'] == []
    assert client.post('/api/job-applications', json={'jobOpeningId': job['id']}, headers=headers['employee']).status_code == 404
    post(api, f"/rms/requisitions/{job['id']}/submit", role='recruiter', status=200)
    post(api, f"/rms/requisitions/{job['id']}/approve", {'reason': 'Synthetic approval'}, role='hr', status=200)
    post(api, f"/rms/requisitions/{job['id']}/publish", role='recruiter', status=200)
    jobs = client.get('/api/job-openings', headers=headers['employee']).json()['jobs']
    assert jobs[0]['id'] == job['id']
    response = client.post('/api/job-applications', json={'jobOpeningId': job['id']}, headers=headers['employee'])
    assert response.status_code == 201, response.text
    id = response.json()['id']
    assert client.post('/api/job-applications', json={'jobOpeningId': job['id']}, headers=headers['employee']).status_code == 409
    assert client.get('/api/job-applications', headers=headers['manager']).json()['applications'] == []
    assert client.get('/api/admin/job-applications', headers=headers['employee']).status_code == 403
    assert client.patch('/api/admin/job-applications/' + id, json={'status': 'IN_REVIEW'}, headers=headers['hr']).status_code == 200
    assert client.get('/api/job-applications', headers=headers['employee']).json()['applications'][0]['status'] == 'In Review'
    referral = {'candidateName': 'Synthetic referral', 'candidateEmail': 'referral@example.com', 'role': 'Developer', 'jobOpeningId': job['id']}
    response = client.post('/api/job-referrals', json=referral, headers=headers['employee'])
    assert response.status_code == 201, response.text
    id = response.json()['id']
    assert client.get('/api/job-referrals', headers=headers['manager']).json()['referrals'] == []
    assert client.patch('/api/admin/job-referrals/' + id, json={'status': 'HIRED'}, headers=headers['hr']).status_code == 200
    counts = client.get('/api/admin/job-openings', headers=headers['hr']).json()['jobs'][0]
    assert counts['applicationsCount'] == 1 and counts['referralsCount'] == 1
    assert client.post('/api/admin/job-openings', json={}, headers=headers['hr']).status_code == 409
