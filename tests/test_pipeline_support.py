from datetime import datetime, timezone
from sqlalchemy import select

from app.modules.recruiting.models import Requisition
from app.modules.recruiting.pipeline_configuration import SPECS, configuration_table
from app.modules.recruiting.pipeline_interviews import interview_table
from test_public_intake import setup_job


def test_remaining_rms_configuration_and_analytics_without_node(api):
    client, app, _, headers = api
    alias = int(setup_job(api).split('/')[-2])
    with app.state.sessions() as db:
        for kind in SPECS:
            configuration_table(db, kind).create(db.bind)
        interview_table(db).create(db.bind)
        interview_table(db, True).create(db.bind)
    recruiter, hr = headers['recruiter'], headers['hr']
    candidate = client.post('/api/candidate', headers=recruiter, json={'jobOpeningId': alias, 'status': 'Selected',
        'object': [{'name': 'firstName', 'value': 'Synthetic'}]}).json()['data']
    payloads = {'hiringFlow': {'value': 'Screening'}, 'secttionValue': {'value': 'Custom', 'object': {'nested': [1, False]}},
                'template': {'subject': 'Interview', 'body': 'Template content'},
                'question': {'candidateId': candidate['id'], 'question': 'Technical question', 'questionType': 'text'},
                'candidateFormDetails': {'jobOpeningId': alias, 'firstName': 'Synthetic', 'extraField': {'custom': 'kept'}}}
    for kind, payload in payloads.items():
        assert client.post('/api/' + kind, headers=hr, json=payload).status_code == 403
        response = client.post('/api/' + kind, headers=recruiter, json=payload)
        assert response.status_code == 201, (kind, response.text)
        record_id = response.json()['data']['id']
        response = client.get(f'/api/{kind}?id={record_id}', headers=hr)
        assert response.status_code == 200, response.text
        for key, value in payload.items():
            assert response.json()['data'][key] == value
        response = client.put(f'/api/{kind}?id={record_id}', headers=recruiter, json=payload)
        assert response.status_code == 200, response.text
        assert client.put(f'/api/{kind}?id={record_id}', headers=recruiter, json={'badColumn': True}).status_code == 422
    assert client.post('/api/question', headers=recruiter, json={'candidateId': 99999}).status_code == 404
    assert client.post('/api/jobOpenings', headers=recruiter, json={}).status_code == 409
    paths = ['/api/jobOpenings', '/api/jobOpenings/active', '/api/jobOpenings/chart', '/api/candidate/chart',
             '/api/candidate/hiringChart', '/api/dashboard/count', '/api/dashboard/chart', '/api/dashboard/metrics',
             '/api/dashboard/detailPerformanceMetrics', '/api/interview/upcomming']
    for path in paths:
        assert client.get(path).status_code == 401
        assert client.get(path, headers=headers['employee']).status_code == 403
        response = client.get(path, headers=hr)
        assert response.status_code == 200, (path, response.text)
    totals = client.get('/api/dashboard/count?startDate=all', headers=hr).json()
    assert totals['totalJobsCreated'] == totals['totalCandidatesApplied'] == 1
    assert totals['totalInterviewsPending'] == 0
    jobs = client.get('/api/jobOpenings', headers=hr).json()['data']
    assert jobs[0]['candidateIds'] == [str(candidate['id'])]
    assert jobs[0]['status'] == 'Open'
    assert client.get('/api/jobOpenings?searchKey=NO-MATCH', headers=hr).json()['data'] == []
    chart = client.get('/api/candidate/hiringChart?priority=year', headers=hr).json()['data']
    assert len(chart) == 12 and sum(row['count'] for row in chart) == 1
    for path in ('/api/dashboard/count?startDate=bad&endDate=bad', '/api/candidate/chart?priority=invalid',
                 '/api/dashboard/count?startDate=2026-09-20&endDate=2026-09-01'):
        assert client.get(path, headers=hr).status_code == 422
    with app.state.sessions.begin() as db:
        db.scalar(select(Requisition)).customer_id = 'customer-b'
    for path in ('/api/jobOpenings', '/api/question', '/api/candidateFormDetails'):
        assert client.get(path, headers=hr).json()['data'] == []
    assert client.get('/api/dashboard/count', headers=hr).json()['totalCandidatesApplied'] == 0
    # This instance's global presets remain usable; outsiders cannot authenticate.
    assert client.get('/api/template', headers=headers['outsider']).status_code == 401
    record = client.get('/api/template', headers=hr).json()['data'][0]
    assert client.delete(f"/api/template?ids={record['id']}", headers=recruiter).status_code == 200
