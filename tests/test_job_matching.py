from sqlalchemy import select, update

from conftest import position, post
from test_public_intake import setup_job
from app.core.models import AuditEvent
from app.data.database import utcnow
from app.modules.recruiting.models import JobReference, Requisition
from app.modules.recruiting.public_intake import pipeline_table


def setup(api):
    _, app, _, _ = api
    old_path = setup_job(api)
    old_alias = int(old_path.split("/")[-2])
    target = post(api, '/rms/requisitions', {'position_id': position(api)['id'],
        'title': 'Python developer', 'description': 'Build Python services and SQL databases.',
        'job_details': {'required_skills': ['Python', 'SQL', 'Git']}}, role='recruiter')
    with app.state.sessions.begin() as db:
        table = pipeline_table(db)
        for email, skills in [('same@example.com', 'Python'), ('same@example.com', 'Python, SQL'),
                              ('other@example.com', 'JavaScript'), ('noskills@example.com', '')]:
            db.execute(table.insert().values(job_opening_id=old_alias, object=[
                {'name': 'firstName', 'value': 'Test'}, {'name': 'email', 'value': email},
                {'name': 'skills', 'value': skills}], status='', created_at=utcnow(), updated_at=utcnow()))
    return target, old_alias


def test_draft_preview_publish_and_freshness(api):
    client, app, _, headers = api
    target, _ = setup(api)
    url = f"/api/v1/rms/requisitions/{target['id']}/recommendations"
    result = client.get(url, headers=headers['hr']).json()
    assert len(result['candidates']) == 1
    match = result['candidates'][0]
    assert match['matched_skills'] == ['Python', 'SQL']
    assert match['missing_skills'] == ['Git'] and result['profiles_without_skills'] == 1
    post(api, f"/rms/requisitions/{target['id']}/submit", role='recruiter', status=200)
    post(api, f"/rms/requisitions/{target['id']}/approve", {'reason': 'Approved'}, role='hr', status=200)
    published = post(api, f"/rms/requisitions/{target['id']}/publish", role='recruiter', status=200)
    assert published['candidate_recommendations']['candidates'][0]['candidate_id'] == match['candidate_id']
    with app.state.sessions.begin() as db:
        assert db.scalar(select(AuditEvent).where(AuditEvent.action == 'requisition.candidates_matched', AuditEvent.resource_id == target['id']))
        table = pipeline_table(db)
        # Applying to the target excludes all older records for the same person.
        db.execute(table.insert().values(job_opening_id=target['legacy_id'], object=[
            {'name': 'email', 'value': 'SAME@example.com'}], status=''))
    assert client.get(url, headers=headers['hr']).json()['candidates'] == []


def test_matching_tenant_and_role_boundaries(api):
    client, app, _, headers = api
    target, old_alias = setup(api)
    url = f"/api/v1/rms/requisitions/{target['id']}/recommendations"
    assert client.get(url).status_code == 401
    for role in ('employee', 'manager', 'interviewer'):
        assert client.get(url, headers=headers[role]).status_code == 403
    with app.state.sessions.begin() as db:
        old_id = db.scalar(select(JobReference.requisition_id).where(JobReference.id == old_alias))
        db.execute(update(Requisition).where(Requisition.id == old_id).values(customer_id='customer-b'))
    assert client.get(url, headers=headers['hr']).json()['candidates'] == []
    with app.state.sessions.begin() as db:
        db.execute(update(Requisition).where(Requisition.id == target['id']).values(customer_id='customer-b'))
    assert client.get(url, headers=headers['hr']).status_code == 404


def test_skill_boundaries_aliases_and_empty_requirements(api):
    from app.agents.job_matching import contains, recommendations
    assert not contains('JavaScript', 'Java')
    assert not contains('C++', 'C')
    assert contains('C++, SQL', 'C++')
    target, _ = setup(api)
    _, app, _, _ = api
    with app.state.sessions.begin() as db:
        job = db.get(Requisition, target['id'])
        job.job_details = {'required_skills': ['Python', 'python', 'SQL']}
        assert len(recommendations(db, job)['required_skills']) == 2
        job.job_details = {}
        assert recommendations(db, job)['method'] == 'description_skill_mentions'
        job.description = 'A vacancy with no recognized technical requirements.'
        assert recommendations(db, job)['required_skills'] == []
