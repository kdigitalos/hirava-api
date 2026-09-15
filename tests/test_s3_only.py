import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.core import imported_storage, object_storage
from app.core.models import Document, OutboxEvent


def test_missing_or_failed_s3_never_saves_document_locally(api, monkeypatch):
    client, app, _, headers = api
    settings = app.state.settings
    settings.aws_bucket_name = ''
    response = client.post('/api/v1/documents?domain=hrms', headers=headers['hr'],
                           files={'file': ('synthetic.txt', b'Synthetic')})
    assert response.status_code == 503
    for operation in (lambda: imported_storage.save(settings, 'test.pdf', b'test', 'application/pdf'),
                      lambda: imported_storage.open_file(settings, 'test.pdf'),
                      lambda: imported_storage.remove(settings, 'test.pdf')):
        with pytest.raises(HTTPException) as error:
            operation()
        assert error.value.status_code == 503
    settings.aws_bucket_name = 'synthetic-bucket'
    def unavailable(*args, **kwargs):
        raise OSError('Synthetic provider failure')
    monkeypatch.setattr(object_storage, 's3_client', unavailable)
    monkeypatch.setattr(imported_storage, 's3_client', unavailable)
    assert client.post('/api/v1/documents?domain=hrms', headers=headers['hr'],
                       files={'file': ('synthetic.txt', b'Synthetic')}).status_code == 503
    with pytest.raises(HTTPException) as error:
        imported_storage.open_file(settings, 'test.pdf')
    assert error.value.status_code == 503
    assert app.state.test_s3_objects == {}
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(Document)) == 0


def test_native_document_database_failure_queues_s3_cleanup(api, monkeypatch):
    client, app, _, headers = api
    def fail_audit(*args, **kwargs):
        raise HTTPException(503, 'Synthetic database write failure')
    monkeypatch.setattr('app.core.router.audit', fail_audit)
    response = client.post('/api/v1/documents?domain=hrms', headers=headers['hr'],
                           files={'file': ('synthetic.txt', b'Synthetic')})
    assert response.status_code == 503
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(Document)) == 0
        event = db.scalar(select(OutboxEvent).where(OutboxEvent.topic == 'imported.storage.delete'))
        assert event.payload['key'] in app.state.test_s3_objects
