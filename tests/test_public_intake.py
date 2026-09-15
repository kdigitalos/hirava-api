from io import BytesIO
from sqlalchemy import select
from conftest import position, post
from app.modules.recruiting.public_intake import pipeline_table

PDF = b"%PDF-1.4\nSynthetic test resume\n%%EOF"


def setup_job(api):
    client, app, _, _ = api
    with app.state.sessions() as db:
        pipeline_table(db).create(db.bind, checkfirst=True)
    job = post(api, '/rms/requisitions', {'position_id': position(api)['id'],
        'title': 'Public intake test', 'description': 'Synthetic role'}, role='recruiter')
    post(api, f"/rms/requisitions/{job['id']}/submit", role='recruiter', status=200)
    post(api, f"/rms/requisitions/{job['id']}/approve", {'reason': 'Approved'}, role='hr', status=200)
    post(api, f"/rms/requisitions/{job['id']}/publish", role='recruiter', status=200)
    return f"/api/v1/careers/jobs/{job['legacy_id']}/apply"


def submit(client, path, **changes):
    data = {'name': 'Test Applicant', 'email': 'applicant@example.com', 'phone': '+91 9876543210', 'consent': 'on'}
    data.update(changes)
    return client.post(path, data=data, files={'resume': ('resume.pdf', PDF, 'application/pdf')})


def test_guest_intake_pipeline_duplicate_and_private_resume(api, monkeypatch):
    client, app, _, headers = api
    path = setup_job(api)
    app.state.settings.aws_bucket_name = 'synthetic-bucket'
    uploads = []
    monkeypatch.setattr('app.core.object_storage.upload', lambda settings, key, file: uploads.append((key, file.read())))
    monkeypatch.setattr('app.core.object_storage.download', lambda settings, key: BytesIO(PDF))
    assert submit(client, path).status_code == 200
    assert submit(client, path, name='Do not overwrite').status_code == 200
    assert len(uploads) == 1
    with app.state.sessions() as db:
        table = pipeline_table(db)
        rows = db.execute(select(table)).mappings().all()
        assert len(rows) == 1
        profile = {f['name']: f['value'] for f in rows[0]['object']}
        assert profile['firstName'] == 'Test'
        assert profile['email'] == 'applicant@example.com'
        assert profile['mobile'] == '+91 9876543210'
        assert rows[0]['status'] == ''  # Existing pipeline's Unassessed stage.
    url = profile['resume']
    assert client.get(url).status_code == 401
    assert client.get(url, headers=headers['employee']).status_code == 403
    assert client.get(url, headers=headers['outsider']).status_code == 401
    response = client.get(url, headers=headers['recruiter'])
    assert response.status_code == 200
    assert response.content == PDF
    assert 'attachment' in response.headers['content-disposition']
    preview = client.get(url + '?preview=true', headers=headers['recruiter'])
    assert preview.status_code == 200
    assert preview.content == PDF
    assert preview.headers['content-disposition'].startswith('inline;')
    assert client.get(url + '?preview=true').status_code == 401


def test_guest_intake_validation_and_unavailable_job(api, monkeypatch):
    client, app, _, _ = api
    path = setup_job(api)
    monkeypatch.setattr('app.core.object_storage.upload', lambda *args: (_ for _ in ()).throw(AssertionError('Must not upload')))
    for changes in ({'name': ' '}, {'email': 'invalid'}, {'phone': 'abc'}, {'consent': 'off'}):
        assert submit(client, path, **changes).status_code == 422
    response = client.post(path, data={'name': 'Test Applicant', 'email': 'a@example.com', 'phone': '9876543210', 'consent': 'on'},
        files={'resume': ('resume.pdf', b'<html>invalid</html>', 'application/pdf')})
    assert response.status_code == 422
    app.state.settings.aws_bucket_name = ""
    assert submit(client, path).status_code == 503  # storage must be configured
    app.state.settings.customer_id = 'customer-b'
    assert submit(client, path).status_code == 404
    app.state.settings.customer_id = 'customer-a'
    app.state.settings.rms_enabled = False
    assert submit(client, path).status_code == 404
