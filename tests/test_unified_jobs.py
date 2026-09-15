from sqlalchemy import select

from app.core.models import AuditEvent
from app.modules.recruiting.models import Requisition
from conftest import get, position, post


def create_job(api, **overrides):
    body = {'position_id': position(api, capacity=2)['id'], 'title': 'Platform Engineer',
            'description': 'Build hiring software', 'job_details': {
                'company_name': 'Synthetic Company', 'department': 'Engineering',
                'location': 'Hyderabad', 'job_type': 'FULL_TIME', 'work_mode': 'Hybrid',
                'recruiter_id': api[2]['recruiter'], 'hiring_due_date': '2026-12-01',
                'target_date': '2026-12-10', 'date_opened': '2026-09-12',
                'budget': '125000.50', 'salary_min': '100000.00', 'salary_max': '120000.00',
                'currency': 'INR', 'no_of_openings': 2, 'required_skills': ['Python', 'PostgreSQL'],
                'hiring_flow': '["Screen", "Panel"]',
                'extra_fields': [{'name': 'cost-center', 'value': 'engineering'}],
            }}
    body.update(overrides)
    return post(api, '/rms/requisitions', body, role='recruiter')


def test_details_persist_on_existing_requisition(api):
    job = create_job(api)
    result = get(api, f"/rms/requisitions/{job['id']}", role='hr')
    assert result['job_details']['budget'] == '125000.50'
    assert result['job_details']['extra_fields'][0]['value'] == 'engineering'
    assert result['job_details']['target_date'] == '2026-12-10'
    assert isinstance(result['legacy_id'], int)
    alias = get(api, f"/rms/job-aliases/{result['legacy_id']}", role='recruiter')
    assert alias['id'] == job['id']
    get(api, f"/rms/job-aliases/{result['legacy_id']}", role='manager', status=404)
    with api[1].state.sessions() as db:
        assert len(db.scalars(select(Requisition)).all()) == 1
        assert db.get(Requisition, job['id']).job_details == result['job_details']


def test_draft_edit_is_versioned_and_audited(api):
    job = create_job(api)
    client, app, _, headers = api
    url = f"/api/v1/rms/requisitions/{job['id']}"
    result = client.patch(url, json={'expected_version': job['version'], 'title': 'Senior Engineer'}, headers=headers['recruiter'])
    assert result.status_code == 200, result.text
    assert result.json()['job_details'] == job['job_details']
    assert result.json()['version'] > job['version']
    stale = client.patch(url, json={'expected_version': job['version'], 'title': 'Stale edit'}, headers=headers['recruiter'])
    assert stale.status_code == 409
    with app.state.sessions() as db:
        event = db.scalar(select(AuditEvent).where(AuditEvent.action == 'requisition.updated'))
        assert event.details['fields'] == ['title']
        assert db.get(Requisition, job['id']).title == 'Senior Engineer'


def test_submitted_terms_cannot_be_changed_or_status_injected(api):
    job = create_job(api)
    client, _, _, headers = api
    url = f"/api/v1/rms/requisitions/{job['id']}"
    injected = client.patch(url, json={'expected_version': job['version'], 'status': 'published'}, headers=headers['recruiter'])
    assert injected.status_code == 422
    post(api, f"/rms/requisitions/{job['id']}/submit", role='recruiter', status=200)
    result = client.patch(url, json={'expected_version': job['version'], 'title': 'Changed after submission'}, headers=headers['recruiter'])
    assert result.status_code == 409


def test_role_scope_and_module_enforced(api):
    job = create_job(api)
    for role, status in [('employee', 403), ('interviewer', 403), ('manager', 404), ('outsider', 401)]:
        get(api, f"/rms/requisitions/{job['id']}", role=role, status=status)
    result = api[0].patch(f"/api/v1/rms/requisitions/{job['id']}",
                         json={'expected_version': job['version'], 'title': 'HR edit'}, headers=api[3]['hr'])
    assert result.status_code == 403
    api[1].state.settings.rms_enabled = False
    get(api, f"/rms/requisitions/{job['id']}", status=403)


def test_invalid_money_capacity_and_assignee_rejected(api):
    pos = position(api)
    for details in [
        {'salary_min': '200', 'salary_max': '100', 'currency': 'INR'},
        {'budget': '10'}, {'budget': '-1', 'currency': 'INR'},
        {'no_of_openings': 2}, {'recruiter_id': api[2]['employee']},
        {'job_link': 'javascript:alert(1)'}, {'extra_fields': 'a' * 65537},
    ]:
        post(api, '/rms/requisitions', {'position_id': pos['id'], 'title': 'Test',
                                      'description': 'Test description', 'job_details': details},
             role='recruiter', status=422)
    assert get(api, '/rms/requisitions', role='recruiter') == []


def test_publication_excludes_private_details(api):
    job = create_job(api)
    post(api, f"/rms/requisitions/{job['id']}/submit", role='recruiter', status=200)
    post(api, f"/rms/requisitions/{job['id']}/approve", {'reason': 'Headcount approved'}, role='hr', status=200)
    post(api, f"/rms/requisitions/{job['id']}/publish", role='recruiter', status=200)
    response = api[0].get('/api/v1/careers/jobs')
    assert response.status_code == 200
    assert set(response.json()[0]) == {'id', 'title', 'description'}
    assert '125000' not in response.text


def test_search_and_status_filter(api):
    job = create_job(api)
    assert len(get(api, '/rms/requisitions?search=platform&status=draft', role='recruiter')) == 1
    assert get(api, '/rms/requisitions?search=%25', role='recruiter') == []
    assert get(api, '/rms/requisitions?status=published', role='recruiter') == []
    assert get(api, f"/rms/requisitions/{job['id']}", role='recruiter')['status'] == 'draft'
