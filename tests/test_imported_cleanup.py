from sqlalchemy import select

from app.core import imported_storage
from app.core.models import OutboxEvent
from app.data.imported import find, table
from app.modules.workforce.imported_assets import insert
from app.modules.workforce.imported_organization import update
from app.workers.imported_storage_cleanup import TOPIC, process_deletions, queue_delete
from app.workers.outbox import process_batch
from test_imported_leave_attendance import setup_people


def test_document_delete_retries_without_exposing_deleted_file(api, monkeypatch):
    client, app, _, headers = api
    people = setup_people(api)
    settings = app.state.settings
    with app.state.sessions.begin() as db:
        table(db, 'EmployeeDocument').create(db.bind)
    response = client.post('/api/employee-documents', data={'title': 'Synthetic'}, files={'file': ('test.pdf', b'%PDF-test', 'application/pdf')}, headers=headers['employee'])
    assert response.status_code == 201, response.text
    record = response.json()
    key = record['storagePath']
    own = '/api/employee-documents/' + record['id']
    assert client.delete(own, headers=headers['manager']).status_code == 404
    assert client.delete(own, headers=headers['employee']).status_code == 204
    assert key in app.state.test_s3_objects
    assert client.get('/api/uploads/' + key, headers=headers['hr']).status_code == 404
    assert client.get(own + '/download', headers=headers['employee']).status_code == 404
    assert process_batch(app.state.sessions, settings.customer_id) == 0
    original = imported_storage.remove
    def failed(*args):
        raise OSError('Synthetic storage failure')
    monkeypatch.setattr(imported_storage, 'remove', failed)
    assert process_deletions(app.state.sessions, settings) == 0
    with app.state.sessions() as db:
        event = db.scalar(select(OutboxEvent).where(OutboxEvent.topic == TOPIC))
        assert event.status == 'pending' and event.attempts == 1
    monkeypatch.setattr(imported_storage, 'remove', original)
    assert process_deletions(app.state.sessions, settings) == 1
    assert key not in app.state.test_s3_objects
    assert process_deletions(app.state.sessions, settings) == 0
    # A rolled-back business transaction cannot trigger object deletion.
    with app.state.sessions() as db:
        queue_delete(db, settings.customer_id, 'employees/test/rollback.png')
        db.rollback()
    assert process_deletions(app.state.sessions, settings) == 0


def test_photo_replacement_preserves_metadata_and_queues_only_previous_photo(api):
    client, app, _, headers = api
    people = setup_people(api)
    employee = people['employee']
    with app.state.sessions.begin() as db:
        update(db, 'Employee', employee['id'], {'employeeDetails': {'preserved': 'value'}})
    url = '/api/my-profile/photo'
    first = client.post(url, files={'file': ('photo.png', b'Synthetic png', 'image/png')}, headers=headers['employee'])
    assert first.status_code == 200, first.text
    key = first.json()['employeePhoto']
    assert client.post(url, files={'file': ('bad.svg', b'<svg/>', 'image/svg+xml')}, headers=headers['employee']).status_code == 422
    second = client.post(url, files={'file': ('photo.png', b'Synthetic replacement', 'image/png')}, headers=headers['employee'])
    assert second.status_code == 200, second.text
    assert client.get('/api/uploads/' + key, headers=headers['employee']).status_code == 404
    assert client.get(second.json()['photoUrl'], headers=headers['employee']).content == b'Synthetic replacement'
    assert process_deletions(app.state.sessions, app.state.settings) == 1
    with app.state.sessions() as db:
        metadata = find(db, 'Employee', employee['id'])['employeeDetails']
        assert metadata['preserved'] == 'value'
        assert metadata['employeePhoto'] == second.json()['employeePhoto']
    assert client.delete(url, headers=headers['employee']).status_code == 204
    assert process_deletions(app.state.sessions, app.state.settings) == 1
    assert client.get(second.json()['photoUrl'], headers=headers['employee']).status_code == 404
