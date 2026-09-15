import httpx
from pydantic import SecretStr
from sqlalchemy import select
from app.core import imported_mail
from app.data.imported import table


def test_subscription_public_validation_and_server_owned_review_state(api):
    client, app, _, _ = api
    with app.state.sessions.begin() as db:
        table(db, 'ClientSubscriptionRequest').create(db.bind)
    path = '/api/subscription-requests'
    payload = {'companyName': 'Synthetic lead', 'primaryContactName': 'Test', 'primaryContactEmail': 'test@example.com',
        'primaryContactMobile': '9876543210', 'productRequired': 'RMS', 'subscriptionPlan': 'ANNUAL', 'rmsUserCount': '2',
        'corporateSameAsRegistered': True, 'corporateAddress': 'Ignored address', 'status': 'CONVERTED', 'internalNotes': 'forged'}
    response = client.post(path, json={**payload, 'subscriptionPlan': 'QUARTERLY', 'numberOfEmployees': '500'})
    assert response.status_code == 422 and 'subscriptionPlan' in response.json()['fieldErrors']
    response = client.post(path, json=payload)
    assert response.status_code == 201, response.text
    assert response.json()['emailStatus'] == 'not_configured'
    with app.state.sessions() as db:
        tbl = table(db, 'ClientSubscriptionRequest')
        row = db.execute(select(tbl)).mappings().one()
        assert row[tbl.c.status] == 'NEW' and row[tbl.c.internalNotes] is None
        assert row[tbl.c.corporateAddress] is None
    assert client.post(path, json={**payload, 'expectedGoLiveDate': '2026-02-30'}).status_code == 422


def test_interview_email_provider_acceptance_and_errors(api, monkeypatch):
    client, app, _, headers = api
    path = '/api/sendEmails'
    payload = {'companyName': 'Synthetic', 'duration': 30, 'interviewDate': '2026-10-01', 'interviewTime': '10:00',
               'participants': ['test@example.com'], 'emailDes': '<script>plain text</script>'}
    assert client.post(path, json=payload, headers=headers['employee']).status_code == 403
    assert client.post(path, json=payload, headers=headers['recruiter']).status_code == 503
    app.state.settings.sendgrid_api_key = SecretStr('synthetic-key')
    app.state.settings.sendgrid_verified_sender = 'sender@example.com'
    calls = []
    def post(url, **kwargs):
        calls.append(kwargs['json'])
        return httpx.Response(202, request=httpx.Request('POST', url))
    monkeypatch.setattr(imported_mail.httpx, 'post', post)
    response = client.post(path, json=payload, headers=headers['recruiter'])
    assert response.status_code == 202, response.text
    assert 'not confirmed' in response.json()['message']
    assert calls[0]['content'][0]['type'] == 'text/plain'
    def failed(*args, **kwargs):
        raise httpx.ConnectError('synthetic')
    monkeypatch.setattr(imported_mail.httpx, 'post', failed)
    assert client.post(path, json=payload, headers=headers['recruiter']).status_code == 503
