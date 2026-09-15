from sqlalchemy import select

from app.modules.recruiting.models import Requisition
from app.modules.recruiting.public_intake import pipeline_table
from test_public_intake import setup_job


def test_pipeline_without_legacy_service_and_role_boundaries(api):
    client, app, users, headers = api
    alias = int(setup_job(api).split('/')[-2])
    assert not app.state.settings.legacy_api_url
    payload = {"jobOpeningId": alias, "object": [
        {"name": "firstName", "value": "SingleName"},
        {"name": "email", "value": "synthetic@example.com"}], "updatedBy": "spoofed"}
    assert client.post('/api/candidate', json=payload).status_code == 401
    assert client.post('/api/candidate', json={**payload, 'object': 'x' * (1024 * 1024)}, headers=headers['admin']).status_code == 413
    for role in ('hr', 'employee', 'manager', 'interviewer'):
        assert client.post('/api/candidate', json=payload, headers=headers[role]).status_code == 403
    response = client.post('/api/candidate', json=payload, headers=headers['recruiter'])
    assert response.status_code == 201, response.text
    saved = response.json()['data']
    assert saved['updatedBy'] == users['recruiter']
    candidate_id = saved['id']
    assert client.get('/api/candidate', headers=headers['employee']).status_code == 403
    assert client.get('/api/candidate', headers=headers['outsider']).status_code == 401
    assert client.get('/api/candidate', headers=headers['hr']).json()['data'][0]['id'] == candidate_id
    detail = client.get(f'/api/candidate?id={candidate_id}', headers=headers['hr']).json()['data']
    assert detail['object'] == payload['object']
    assert 'hiringFlow' in detail
    paths = ['/api/jobOpenings/interview', '/api/candidate/jobOpenings', '/api/jobOpenings/drops',
             '/api/candidate/count', '/api/candidate/recent', '/api/candidate/candidateNames']
    for path in paths:
        response = client.get(path, headers=headers['hr'])
        assert response.status_code == 200, (path, response.text)
        assert len(response.json()['data']) == 1
    counts = client.get('/api/jobOpenings/interview', headers=headers['hr']).json()['data'][0]
    assert counts['noOfInterviewApp'] == 1  # No interview record exists.
    names = client.get('/api/candidate/candidateNames', headers=headers['hr']).json()['data']
    assert names[0]['candidateName'] == 'SingleName'
    response = client.get(f'/api/jobOpenings/candidate?id={alias}&interviewStatus=Unassessed', headers=headers['hr'])
    assert len(response.json()['data']['candidates']) == 1
    response = client.put(f'/api/candidate?id={candidate_id}', json={'status': 'Shortlisted'}, headers=headers['recruiter'])
    assert response.status_code == 200, response.text
    assert response.json()['data']['status'] == 'Shortlisted'
    assert client.get(f'/api/jobOpenings/candidate?id={alias}&interviewStatus=unassessed', headers=headers['hr']).json()['data']['candidates'] == []
    assert client.put(f'/api/candidate?id={candidate_id}', json={'jobOpeningId': alias + 1}, headers=headers['admin']).status_code == 409
    assert client.put(f'/api/candidate?id={candidate_id}', json={'jobOpeningId': None}, headers=headers['admin']).status_code == 422
    assert client.put(f'/api/candidate?id={candidate_id}', json={'customer_id': 'other'}, headers=headers['admin']).status_code == 422
    assert client.get('/api/candidate?id=bad', headers=headers['admin']).status_code == 422
    assert client.get('/api/candidate/recent?priority=bad', headers=headers['admin']).status_code == 422
    with app.state.sessions.begin() as db:
        parent = db.scalar(select(Requisition))
        parent.status = 'closed'
    assert client.post('/api/candidate', json=payload, headers=headers['admin']).status_code == 409


def test_pipeline_does_not_expose_other_customer_or_orphans(api):
    client, app, _, headers = api
    alias = int(setup_job(api).split('/')[-2])
    payload = {'jobOpeningId': alias, 'object': []}
    saved = client.post('/api/candidate', json=payload, headers=headers['admin']).json()['data']
    with app.state.sessions.begin() as db:
        parent = db.scalar(select(Requisition))
        parent.customer_id = 'customer-b'
        table = pipeline_table(db)
        db.execute(table.insert().values(job_opening_id=999999, object=[], questions={}, status=''))
    for path in ('/api/candidate', '/api/candidate/count', '/api/candidate/jobOpenings',
                 '/api/jobOpenings/interview', '/api/jobOpenings/drops', '/api/candidate/recent',
                 '/api/candidate/candidateNames', '/api/jobOpenings/candidate'):
        response = client.get(path, headers=headers['admin'])
        assert response.status_code == 200, response.text
        assert response.json()['data'] == [], path
    for method, path, kwargs in (
        ('get', f"/api/candidate?id={saved['id']}", {}),
        ('put', f"/api/candidate?id={saved['id']}", {'json': {'status': 'Selected'}}),
        ('get', f'/api/jobOpenings/candidate?id={alias}', {}),
        ('post', '/api/candidate', {'json': payload}),
    ):
        assert getattr(client, method)(path, headers=headers['admin'], **kwargs).status_code == 404
    app.state.settings.rms_enabled = False
    assert client.get('/api/candidate', headers=headers['admin']).status_code == 403
