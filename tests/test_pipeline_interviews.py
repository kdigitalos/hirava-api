from app.modules.recruiting.pipeline_interviews import interview_table
from test_public_intake import setup_job


def test_pipeline_interview_stages_without_node(api):
    client, app, _, headers = api
    alias = int(setup_job(api).split('/')[-2])
    with app.state.sessions() as db:
        interview_table(db).create(db.bind)
        interview_table(db, True).create(db.bind)
        from app.modules.recruiting.pipeline_feedback import feedback_table
        feedback_table(db).create(db.bind)
    recruiter = headers['recruiter']
    person = client.post('/api/candidate', headers=recruiter, json={'jobOpeningId': alias,
        'object': [{'name': 'firstName', 'value': 'Test'}]}).json()['data']
    body = {'jobId': alias, 'candidateId': person['id'], 'companyName': 'Synthetic',
            'interviewDate': '2026-09-20', 'panelMembers': ['Panel A', 'Panel B']}
    assert client.post('/api/interview', headers=headers['hr'], json=body).status_code == 403
    response = client.post('/api/interview', headers=recruiter, json=body)
    assert response.status_code == 201, response.text
    parent = response.json()['data']
    assert parent['panelMembers'] == 'Panel A,Panel B'
    assert parent['S2'] is None
    assert client.post('/api/interview', headers=recruiter, json=body).status_code == 409
    response = client.get(f"/api/interview?id={parent['id']}", headers=headers['hr'])
    assert response.json()['data']['candidateName'] == 'Test'
    slot = {key: body[key] for key in ('jobId', 'candidateId', 'interviewDate')}
    slot['interviewId'] = parent['id']
    slots = []
    for stage in ('S2', 'S3', 'S4'):
        response = client.post('/api/interviewSchedule', json=slot, headers=recruiter)
        assert response.status_code == 201, response.text
        created = response.json()['data']
        slots.append(created['id'])
        assert response.json()['updatedInterview'][stage] == str(created['id'])
    assert client.post('/api/interviewSchedule', json=slot, headers=recruiter).status_code == 409
    assert client.put(f"/api/interview?id={parent['id']}", json={'jobId': alias + 1}, headers=recruiter).status_code == 409
    assert client.put(f"/api/interview?id={parent['id']}", json={'S2': '999'}, headers=recruiter).status_code == 422
    assert client.put(f'/api/interviewSchedule?id={slots[0]}', json={'candidateId': 999}, headers=recruiter).status_code == 409
    response = client.put(f'/api/interviewSchedule?id={slots[0]}', json={'interviewDate': '2026-09-21T12:00:00+05:30'}, headers=recruiter)
    assert response.status_code == 200, response.text
    assert response.json()['data']['interviewDate'].startswith('2026-09-21T06:30')
    counts = client.get(f'/api/interview/levelCounts?jobId={alias}', headers=headers['hr']).json()['levelCounts']
    assert counts == {'totalL1': 1, 'totalL2': 1, 'totalL3': 1, 'totalL4': 1}
    response = client.delete(f'/api/interviewSchedule?ids={slots[1]}', headers=recruiter)
    assert response.status_code == 200, response.text
    response = client.post('/api/interviewSchedule', json=slot, headers=recruiter)
    assert response.status_code == 201, response.text
    assert response.json()['updatedInterview']['S3'] == str(response.json()['data']['id'])
    assert client.get('/api/interviewSchedule', headers=headers['employee']).status_code == 403
    assert client.get('/api/interview').status_code == 401
    assert client.delete('/api/interviewSchedule?ids=bad', headers=recruiter).status_code == 422
    feedback_body = {'interviewId': parent['id'], 'candidateId': person['id'], 'jobId': alias,
                     'level': 1, 'description': 'Human interview notes', 'overallRating': 4}
    response = client.post('/api/feedback', json=feedback_body, headers=recruiter)
    assert response.status_code == 201, response.text
    feedback_id = response.json()['data']['id']
    assert client.post('/api/feedback', json=feedback_body, headers=recruiter).status_code == 409
    response = client.put(f'/api/feedback?id={feedback_id}', json={'description': 'Updated notes'}, headers=recruiter)
    assert response.status_code == 200, response.text
    assert client.put(f'/api/feedback?id={feedback_id}', json={'level': 2}, headers=recruiter).status_code == 409
    assert client.delete(f"/api/interview?ids={parent['id']}", headers=recruiter).status_code == 409
    assert client.delete(f"/api/candidate?ids={person['id']}", headers=recruiter).status_code == 409
    response = client.delete(f'/api/feedback?ids={feedback_id}', headers=recruiter)
    assert response.status_code == 200, response.text
    assert client.get(f"/api/interview?id={parent['id']}", headers=recruiter).json()['data']['F1'] is None
    assert client.post('/api/feedback', json=feedback_body, headers=recruiter).status_code == 201
    from sqlalchemy import select
    from app.modules.recruiting.models import Requisition
    with app.state.sessions.begin() as db:
        db.scalar(select(Requisition)).customer_id = 'customer-b'
    assert client.get('/api/interview', headers=recruiter).json()['data'] == []
    assert client.get('/api/interviewSchedule', headers=recruiter).json()['data'] == []
    assert client.post('/api/interviewSchedule', json=slot, headers=recruiter).status_code == 404
    assert client.delete(f'/api/interviewSchedule?ids={slots[0]}', headers=recruiter).status_code == 404
