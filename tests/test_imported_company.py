from sqlalchemy import func, select
from app.data.imported import table
from app.core import imported_storage


def test_company_profile_read_validation_and_logo_cleanup(api, monkeypatch):
    client, app, _, headers = api
    with app.state.sessions.begin() as db:
        table(db, 'OrganizationCompanyProfile').create(db.bind)
    path = '/api/organization/company-profile'
    assert client.get(path, headers=headers['hr']).json()['companyName'] == ''
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(table(db, 'OrganizationCompanyProfile'))) == 0
    payload = dict(companyName='Synthetic', industry='Software', email='synthetic@example.com', phone='1234567890',
        website='example.com', taxId='TEST', description='Synthetic company', streetAddress='Test street', city='Test', defaultCurrency='INR')
    assert client.patch(path, json=payload, headers=headers['employee']).status_code == 403
    assert client.patch(path, json={**payload, 'defaultCurrency': 'rupees'}, headers=headers['hr']).status_code == 422
    response = client.patch(path, json=payload, headers=headers['hr'])
    assert response.status_code == 200, response.text
    assert response.json()['website'] == 'https://example.com'
    saved = []
    monkeypatch.setattr(imported_storage, 'save', lambda settings, key, content, mime: saved.append(key))
    response = client.post(path, files={'logo': ('test.png', b'synthetic', 'image/png')}, headers=headers['hr'])
    assert response.status_code == 200, response.text
    assert response.json()['logoUrl'] == '/api/uploads/' + saved[0] + '?view=1'
    assert client.patch(path, json={'clearLogo': True}, headers=headers['hr']).json()['logoUrl'] is None
    assert client.get(path, headers=headers['hr']).json()['companyName'] == 'Synthetic'
    events = client.get('/api/v1/outbox', headers=headers['admin']).json()
    assert any(event['topic'] == 'imported.storage.delete' and event['payload']['key'] == saved[0] for event in events)
