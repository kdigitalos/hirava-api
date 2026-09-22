from datetime import timedelta
from sqlalchemy import select, update
from app.agents.models import InterviewPanelFeedback
from app.core.models import User
from app.data.database import utcnow
from app.modules.recruiting.models import Requisition
from app.modules.recruiting.pipeline_interviews import interview_table
from app.modules.recruiting.pipeline_feedback import feedback_table
from test_public_intake import setup_job


def setup_interview(api, reviewer_ids=None):
    client, app, _, headers = api
    alias = int(setup_job(api).split('/')[-2])
    with app.state.sessions() as db:
        interview_table(db).create(db.bind)
        interview_table(db, True).create(db.bind)
        feedback_table(db).create(db.bind)
        with db.begin():
            db.execute(update(Requisition).values(description='Develop Python APIs, write tests and maintain relational SQL databases.'))
    auth = headers['recruiter']
    person = client.post('/api/candidate', headers=auth, json={'jobOpeningId': alias,
        'object': [{'name': 'firstName', 'value': 'Synthetic'}]}).json()['data']
    result = client.post('/api/interview', headers=auth, json={'jobId': alias,
        'candidateId': person['id'], 'companyName': 'Synthetic', 'interviewDate': '2026-09-21',
        **({'reviewer_ids': reviewer_ids} if reviewer_ids is not None else {})})
    assert result.status_code == 201, result.text
    return result.json()['data'], person['id']


def test_individual_tasks_authorization_due_feedback_summary_cleanup(api, monkeypatch):
    client, app, users, headers = api
    interview, person = setup_interview(api)
    base = '/api/interview-panel'
    path = f"{base}/interviews/{interview['id']}"
    payload = {'reviewer_id': users['interviewer'], 'level': 1}
    assert client.post(path, json=payload).status_code == 401
    assert client.post(path, json=payload, headers=headers['employee']).status_code == 403
    assert client.get(path, headers=headers['outsider']).status_code in (401, 404)
    assert client.post(path, json={**payload, 'level': 2}, headers=headers['hr']).status_code == 409
    assert client.post(path, json={**payload, 'due_at': '2026-01-01T12:00:00'}, headers=headers['hr']).status_code == 422
    response = client.post(path, json=payload, headers=headers['hr'])
    assert response.status_code == 200, response.text
    task = response.json()
    assert task['status'] == 'scheduled'
    assert client.post(path, json=payload, headers=headers['hr']).status_code == 409
    second = client.post(path, json={'reviewer_id': users['employee'], 'level': 1}, headers=headers['hr']).json()
    assert len(client.get(base + '/mine', headers=headers['interviewer']).json()['data']) == 1
    assert client.get(base + '/mine', headers=headers['recruiter']).json()['data'] == []
    with app.state.sessions.begin() as db:
        db.execute(update(InterviewPanelFeedback).where(InterviewPanelFeedback.id == task['id']).values(due_at=utcnow()-timedelta(minutes=1)))
    assert client.get(base + '/mine', headers=headers['interviewer']).json()['data'][0]['status'] == 'due'
    change = {'due_at': (utcnow()+timedelta(hours=2)).isoformat(), 'version': task['version']}
    changed = client.patch(f"{base}/assignments/{task['id']}/reminder", json=change, headers=headers['hr'])
    assert changed.status_code == 200, changed.text
    assert changed.json()['status'] == 'scheduled'
    assert client.patch(f"{base}/assignments/{task['id']}/reminder", json=change, headers=headers['hr']).status_code == 409
    feedback = {'notes': 'Explained Python testing and API validation clearly.', 'rating': 4, 'version': changed.json()['version']}
    feedback_path = f"{base}/assignments/{task['id']}/feedback"
    assert client.put(feedback_path, json=feedback, headers=headers['employee']).status_code == 403
    assert client.put(feedback_path, json=feedback, headers=headers['admin']).status_code == 403
    assert client.put(feedback_path, json={**feedback, 'rating': 6}, headers=headers['interviewer']).status_code == 422
    result = client.put(feedback_path, json=feedback, headers=headers['interviewer'])
    assert result.status_code == 200, result.text
    assert result.json()['status'] == 'submitted'
    assert client.put(feedback_path, json=feedback, headers=headers['interviewer']).status_code == 409
    assert client.patch(f"{base}/assignments/{task['id']}/reminder", json={**change, 'version': result.json()['version']}, headers=headers['hr']).status_code == 409
    captured = []
    def fake(settings, kind, sources, options):
        captured.append(sources)
        return {'sections': [], 'limitations': [], 'sources': sources, 'provider': 'test', 'model': 'test', 'tokens': {}, 'kind': kind}
    monkeypatch.setattr('app.agents.recruiter_tools.generate', fake)
    result = client.post(f'/api/recruiter-ai/candidates/{person}/feedback-summary', json={'allow_provider_processing': True}, headers=headers['hr'])
    assert result.status_code == 200, result.text
    assert any('feedback-panel-' in key for key in captured[0])
    assert 'Python testing' in str(captured[0])
    assert client.delete(f"{base}/assignments/{second['id']}", headers=headers['hr']).status_code == 200
    assert client.get(base + '/mine', headers=headers['employee']).json()['data'] == []
    assert client.put(f"{base}/assignments/{second['id']}/feedback", json={**feedback, 'version': 2}, headers=headers['employee']).status_code == 409
    assert client.delete(f"/api/interview?ids={interview['id']}", headers=headers['recruiter']).status_code == 200
    with app.state.sessions() as db:
        assert not db.scalars(select(InterviewPanelFeedback)).all()


def test_repeat_context_and_no_automatic_retry(api, monkeypatch):
    client, app, users, headers = api
    interview, person = setup_interview(api)
    auth = headers['recruiter']
    history = f"/api/recruiter-ai/interviews/{interview['id']}/questions"
    question = 'How do you test a Python API with a database?'
    assert client.post(history, json={'round': 'Initial', 'text': question}, headers=auth).status_code == 200
    calls = []
    def fake(settings, kind, sources, options):
        calls.append(options)
        return {'sections': [{'title': 'API testing', 'text': question, 'source_ids': ['job']}], 'limitations': [],
                'sources': sources, 'provider': 'test', 'model': 'test', 'tokens': {}, 'kind': kind}
    monkeypatch.setattr('app.agents.recruiter_tools.generate', fake)
    body = {'allow_provider_processing': True, 'round': 'Technical', 'interview_id': interview['id']}
    result = client.post(f'/api/recruiter-ai/candidates/{person}/questions', json=body, headers=auth)
    assert result.status_code == 200, result.text
    assert len(calls) == 1 and calls[0]['previous_questions'][0]['text'] == question
    assert result.json()['repeat_check'] == {'saved_versions_checked': 1, 'possible_repeats': ['API testing']}
    assert result.json()['limitations']
    with app.state.sessions.begin() as db:
        db.execute(update(Requisition).values(customer_id='customer-b'))
    assert client.get(history, headers=auth).status_code == 404
    assert client.get(f"/api/interview-panel/interviews/{interview['id']}", headers=auth).status_code == 404


def test_deleted_round_and_inactive_reviewer_cannot_submit(api):
    client, app, users, headers = api
    interview, person = setup_interview(api)
    auth = headers['recruiter']
    schedule = {'interviewId': interview['id'], 'jobId': interview['jobId'],
                'candidateId': person, 'interviewDate': '2026-09-22'}
    response = client.post('/api/interviewSchedule', json=schedule, headers=auth)
    assert response.status_code == 201, response.text
    slot = response.json()['data']['id']
    path = f"/api/interview-panel/interviews/{interview['id']}"
    assignment = {'reviewer_id': users['interviewer'], 'level': 2}
    response = client.post(path, json=assignment, headers=auth)
    assert response.status_code == 200, response.text
    old = response.json()
    assert client.delete(f'/api/interviewSchedule?ids={slot}', headers=auth).status_code == 200
    assert client.get(path, headers=auth).json()['data'][0]['status'] == 'unavailable'
    feedback = {'version': old['version'], 'notes': 'A response for a round that has been removed.'}
    assert client.put(f"/api/interview-panel/assignments/{old['id']}/feedback", json=feedback,
                      headers=headers['interviewer']).status_code == 409
    assert client.post('/api/interviewSchedule', json=schedule, headers=auth).status_code == 201
    # Recreating a round must not revive its previous assignment.
    assert client.get(path, headers=auth).json()['data'][0]['status'] == 'unavailable'
    assert client.post(path, json=assignment, headers=auth).status_code == 200
    with app.state.sessions.begin() as db:
        db.execute(update(User).where(User.id == users['interviewer']).values(active=False))
    assert client.get('/api/interview-panel/mine', headers=headers['interviewer']).status_code in (401, 403)
    assert client.post(path, json={**assignment, 'level': 1}, headers=auth).status_code == 422


def test_scheduling_creates_feedback_once_and_preserves_submitted_responses(api):
    client, app, users, headers = api
    parent, person = setup_interview(api, [users['interviewer'], users['employee']])
    auth = headers['recruiter']
    path = f"/api/interview-panel/interviews/{parent['id']}"
    tasks = client.get(path, headers=auth).json()['data']
    assert len(tasks) == 2 and all(t['level'] == 1 for t in tasks)
    mine = next(t for t in tasks if t['reviewer_id'] == users['interviewer'])
    assert client.put(f"/api/interview-panel/assignments/{mine['id']}/feedback", headers=headers['interviewer'],
        json={'version': mine['version'], 'notes': 'Explained debugging and SQL transactions clearly.'}).status_code == 200
    # Changing the panel cancels only pending tasks; submitted responses survive.
    assert client.put(path + '/rounds/1', headers=auth, json={'reviewer_ids': [users['admin']]}).status_code == 200
    tasks = client.get(path, headers=auth).json()['data']
    assert next(t for t in tasks if t['reviewer_id'] == users['interviewer'])['status'] == 'submitted'
    assert next(t for t in tasks if t['reviewer_id'] == users['employee'])['status'] == 'cancelled'
    assert client.put(path + '/rounds/1', headers=auth, json={'reviewer_ids': [users['admin']]}).status_code == 200
    assert len(client.get(path, headers=auth).json()['data']) == 3
    schedule = {'interviewId': parent['id'], 'jobId': parent['jobId'], 'candidateId': person,
        'interviewDate': '2026-09-22', 'reviewer_ids': [users['interviewer']],
        'feedback_due_at': (utcnow() + timedelta(days=3)).isoformat()}
    # Wrong-tenant reviewer cannot leave a partially saved round behind.
    with app.state.sessions() as db:
        outsider = db.scalar(select(User.id).where(User.customer_id == 'customer-b'))
    assert outsider
    assert client.post('/api/interviewSchedule', headers=auth,
        json={**schedule, 'reviewer_ids': [outsider]}).status_code == 422
    assert client.get(f"/api/interview?id={parent['id']}", headers=auth).json()['data']['S2'] is None
    created = client.post('/api/interviewSchedule', headers=auth, json=schedule)
    assert created.status_code == 201, created.text
    tasks = client.get(path, headers=auth).json()['data']
    next_round = [t for t in tasks if t['level'] == 2]
    assert len(next_round) == 1 and next_round[0]['reviewer_id'] == users['interviewer']
    from datetime import datetime
    assert datetime.fromisoformat(next_round[0]['due_at'].replace('Z', '+00:00')) == datetime.fromisoformat(schedule['feedback_due_at'])
