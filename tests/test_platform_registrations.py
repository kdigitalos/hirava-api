from app.data.imported import table


def test_platform_registrations_explicit_access_and_search(api):
    client, app, users, headers = api
    with app.state.sessions.begin() as db:
        table(db, 'ClientSubscriptionRequest').create(db.bind)
    path = '/api/platform/registrations'
    assert client.get(path).status_code == 401
    for role in ('admin', 'hr', 'recruiter', 'employee'):
        assert client.get(path, headers=headers[role]).status_code == 403
    app.state.settings.platform_admin_user_ids = users['admin']
    app.state.settings.rms_enabled = False
    app.state.settings.hrms_enabled = False
    assert client.get('/api/platform/access', headers=headers['admin']).status_code == 200
    payload = {'companyName': 'Synthetic Company', 'primaryContactName': 'Test',
               'primaryContactEmail': 'test@example.com', 'primaryContactMobile': '9876543210',
               'productRequired': 'RMS', 'subscriptionPlan': 'ANNUAL', 'rmsUserCount': 2}
    assert client.post('/api/subscription-requests', json=payload).status_code == 201
    response = client.get(path + '?q=synthetic', headers=headers['admin'])
    assert response.status_code == 200, response.text
    assert response.headers['cache-control'] == 'no-store'
    assert response.json()['total'] == 1
    assert response.json()['items'][0]['companyName'] == 'Synthetic Company'
    assert response.json()['items'][0]['primaryContactEmail'] == 'test@example.com'
    assert client.get(path + '?q=absent', headers=headers['admin']).json()['total'] == 0
    assert client.get(path + '?page=2', headers=headers['admin']).json()['items'] == []
    assert client.get(path + '?page=0', headers=headers['admin']).status_code == 422
    assert client.get(path, headers=headers['outsider']).status_code == 401
    app.state.settings.platform_admin_user_ids = ''
    assert client.get(path, headers=headers['admin']).status_code == 403


def test_owner_review_audited_and_does_not_activate_accounts(api):
    from sqlalchemy import select, func
    from app.core.models import User, AuditEvent, CompanyRegistrationReview
    client, app, users, headers = api
    with app.state.sessions.begin() as db:
        table(db, 'ClientSubscriptionRequest').create(db.bind)
    payload = {'companyName': 'Review Test', 'primaryContactName': 'Test',
               'primaryContactEmail': 'review@example.com', 'primaryContactMobile': '9876543210',
               'productRequired': 'RMS', 'subscriptionPlan': 'ANNUAL', 'rmsUserCount': 2}
    record_id = client.post('/api/subscription-requests', json=payload).json()['request']['id']
    path = f'/api/platform/registrations/{record_id}/review'
    body = {'decision': 'APPROVED', 'note': 'Reviewed', 'expected_version': 0}
    assert client.post(path, json=body).status_code == 401
    assert client.post(path, json=body, headers=headers['admin']).status_code == 403
    app.state.settings.platform_admin_user_ids = users['admin']
    assert client.post(path, json={**body, 'decision': 'REJECTED', 'note': '  '}, headers=headers['admin']).status_code == 422
    assert client.post(path, json={**body, 'decision': 'ACTIVE'}, headers=headers['admin']).status_code == 422
    response = client.post(path, json=body, headers=headers['admin'])
    assert response.status_code == 200, response.text
    review = response.json()['review']
    assert review['decision'] == 'APPROVED' and review['requested_terms']['rmsUserCount'] == 2
    assert client.post(path, json=body, headers=headers['admin']).status_code == 409
    rejected = client.post(path, json={**body, 'decision': 'REJECTED', 'expected_version': review['version']}, headers=headers['admin'])
    assert rejected.status_code == 200
    assert client.get('/api/platform/registrations', headers=headers['admin']).json()['items'][0]['review']['decision'] == 'REJECTED'
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(CompanyRegistrationReview)) == 1
        assert db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.action == 'company_registration.reviewed')) == 2
        assert db.scalar(select(User).where(User.email == 'review@example.com')) is None
    assert client.post('/api/platform/registrations/missing/review', json=body, headers=headers['admin']).status_code == 404
