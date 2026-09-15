from app.data.imported import table
from app.modules.workforce.imported_assets import insert


def test_onboarding_groups_templates_candidates_and_atomic_bulk(api):
    client, app, _, headers = api
    with app.state.sessions.begin() as db:
        for model in ('Employee', 'OnboardingGroup', 'OnboardingTemplate', 'OnboardingCandidate'):
            table(db, model).create(db.bind)
        employee = insert(db, 'Employee', {'employeeCode': 'ONB-1', 'firstName': 'Synthetic', 'lastName': 'Employee', 'status': 'ACTIVE', 'orgSortOrder': 0})
    root = '/api/onboarding-'
    assert client.post(root + 'groups', json={'status': 'ACTIVE'}, headers=headers['hr']).status_code == 422
    response = client.post(root + 'groups', json={'name': 'Synthetic cohort', 'status': 'ACTIVE', 'windowStart': '2026-10-01', 'windowEnd': '2026-10-31'}, headers=headers['hr'])
    assert response.status_code == 201, response.text
    group = response.json()
    assert len(group['groupCode']) == 8
    assert group['windowStart'] == '2026-10-01T00:00:00.000Z'
    assert client.patch(root + 'groups/' + group['id'], json={'windowEnd': '2026-09-01'}, headers=headers['hr']).status_code == 422
    response = client.post(root + 'templates', json={'name': 'Engineering plan', 'groupId': group['id'], 'stagesJson': {'department': 'Engineering', 'complexity': 'beginner', 'stages': []}}, headers=headers['hr'])
    assert response.status_code == 201, response.text
    template = response.json()
    assert template['category'] == 'Engineering'
    assert len(client.get(root + 'templates?q=plan&department=Engineering', headers=headers['hr']).json()) == 1
    response = client.post(root + 'candidates', json={'name': 'Test Candidate', 'email': 'candidate@example.com', 'groupId': group['id'], 'details': {'template': 'Engineering plan', 'notes': 'Preserve'}}, headers=headers['hr'])
    assert response.status_code == 201, response.text
    candidate = response.json()
    assert candidate['templateId'] == template['id']
    url = root + 'candidates/' + candidate['id']
    response = client.patch(url, json={'name': 'Updated Candidate', 'details': {'displayCandidateId': 'fake'}}, headers=headers['hr'])
    assert response.status_code == 200, response.text
    assert response.json()['details'] == {'template': 'Engineering plan', 'notes': 'Preserve', 'displayCandidateId': candidate['details']['displayCandidateId'], 'fullName': 'Updated Candidate'}
    assert client.delete(root + 'groups/' + group['id'], headers=headers['hr']).status_code == 409
    assert client.delete(root + 'templates/' + template['id'], headers=headers['hr']).status_code == 409
    result = client.get(root + 'groups/' + group['id'] + '?include=candidates', headers=headers['hr']).json()
    assert result['candidates'][0]['name'] == 'Updated Candidate'
    bulk = {'groupId': group['id'], 'candidates': [{'name': 'Duplicate', 'email': 'CANDIDATE@example.com'}, {'name': 'Second', 'email': 'second@example.com'}, {'name': 'Second duplicate', 'email': 'second@example.com'}]}
    response = client.post(root + 'candidates/bulk', json=bulk, headers=headers['hr'])
    assert response.status_code == 201, response.text
    assert len(response.json()['created']) == 1
    assert response.json()['created'][0]['details']['displayCandidateId'] != candidate['details']['displayCandidateId']
    # A later invalid row rolls back the complete import, not just that row.
    response = client.post(root + 'candidates/bulk', json={'groupId': group['id'], 'candidates': [{'name': 'Rollback', 'email': 'rollback@example.com'}, {'name': 'Invalid', 'email': 'invalid-address'}]}, headers=headers['hr'])
    assert response.status_code == 422, response.text
    assert len(client.get(root + 'candidates', headers=headers['hr']).json()) == 2
    assert client.patch(url, json={'employeeId': employee['id'], 'status': 'COMPLETED'}, headers=headers['hr']).status_code == 200
    assert client.delete(url, headers=headers['hr']).status_code == 409
    assert client.patch(url, json={'employeeId': None}, headers=headers['hr']).status_code == 409
    assert client.get(root + 'candidates', headers=headers['employee']).status_code == 403
    assert client.post(root + 'groups', json={'name': 'Denied'}, headers=headers['recruiter']).status_code == 403
