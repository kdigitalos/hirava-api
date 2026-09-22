from sqlalchemy import select, update
from app.agents.models import InterviewQuestionSet
from app.modules.recruiting.models import Requisition
from app.modules.recruiting.pipeline_interviews import interview_table
from app.modules.recruiting.pipeline_feedback import feedback_table
from test_public_intake import setup_job


def test_question_history_scope_duplicates_versions_and_cleanup(api):
    client, app, _, headers = api
    alias = int(setup_job(api).split('/')[-2])
    with app.state.sessions() as db:
        interview_table(db).create(db.bind)
        interview_table(db, True).create(db.bind)
        feedback_table(db).create(db.bind)
    auth = headers['recruiter']
    person = client.post('/api/candidate', headers=auth, json={'jobOpeningId': alias,
        'object': [{'name': 'firstName', 'value': 'Test'}]}).json()['data']
    interview = client.post('/api/interview', headers=auth, json={'jobId': alias,
        'candidateId': person['id'], 'companyName': 'Synthetic', 'interviewDate': '2026-09-21'}).json()['data']
    path = f"/api/recruiter-ai/interviews/{interview['id']}/questions"
    body = {'round': 'Initial', 'text': 'Explain your Python testing project.'}
    assert client.get(path).status_code == 401
    assert client.post(path, json=body, headers=headers['employee']).status_code == 403
    assert client.post(path, json={**body, 'text': '   '}, headers=auth).status_code == 422
    assert client.post(path, json={**body, 'text': 'x' * 20001}, headers=auth).status_code == 422
    first = client.post(path, json=body, headers=auth)
    assert first.status_code == 200, first.text
    assert client.post(path, json=body, headers=auth).json()['id'] == first.json()['id']
    changed = {**body, 'text': 'Describe how you diagnose a failing API test.'}
    assert client.post(path, json=changed, headers=auth).status_code == 200
    rows = client.get(path, headers=auth).json()['data']
    assert len(rows) == 2 and {r['text'] for r in rows} == {body['text'], changed['text']}
    assert client.get(path, headers=headers['outsider']).status_code in (401, 404)
    assert client.post(path, json=body, headers=headers['outsider']).status_code in (401, 404)
    with app.state.sessions.begin() as db:
        db.execute(update(Requisition).values(customer_id='customer-b'))
    assert client.get(path, headers=auth).status_code == 404
    with app.state.sessions.begin() as db:
        db.execute(update(Requisition).values(customer_id='customer-a'))
    assert client.delete(f"/api/interview?ids={interview['id']}", headers=auth).status_code == 200
    with app.state.sessions() as db:
        assert not db.scalars(select(InterviewQuestionSet)).all()
