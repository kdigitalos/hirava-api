from app.data.imported import table
from test_imported_leave_attendance import setup_people
from test_claims import draft, act


def inbox(client, headers, role='employee'):
    response = client.get('/api/v1/notification-inbox', headers=headers[role])
    assert response.status_code == 200, response.text
    return response.json()


def test_leave_decision_inbox_ownership_read_and_no_duplicates(api):
    client, app, _, headers = api
    people = setup_people(api)
    kind = client.post('/api/leave-types', json={'name': 'Annual', 'daysPerYear': 12}, headers=headers['hr']).json()
    leave = client.post('/api/leave-requests', json={'leaveTypeId': kind['id'],
        'startDate': '2026-11-05', 'endDate': '2026-11-06', 'reason': 'Synthetic'},
        headers=headers['employee']).json()
    url = '/api/leave-requests/' + leave['id']
    for role in ('admin', 'hr'):
        review = inbox(client, headers, role)
        assert review['unread_count'] == 1
        assert review['items'][0]['href'] == '/HRMS/Admin/AttendanceLeave/leave-manager'
    assert inbox(client, headers)['unread_count'] == 0
    for _ in range(2):
        response = client.patch(url, json={'status': 'APPROVED'}, headers=headers['hr'])
        assert response.status_code == 200, response.text
    received = inbox(client, headers)
    assert received['unread_count'] == 1 and len(received['items']) == 1
    item = received['items'][0]
    assert 'approved' in item['message']
    assert item['href'] == '/HRMS/Employee/leaves-management'
    assert inbox(client, headers, 'manager')['items'] == []
    read_url = '/api/v1/notifications/' + item['id'] + '/read'
    assert client.post(read_url, headers=headers['manager']).status_code == 404
    assert client.post(read_url, headers=headers['outsider']).status_code == 401
    assert client.post(read_url, headers=headers['employee']).status_code == 200
    assert client.post(read_url, headers=headers['employee']).status_code == 200
    assert inbox(client, headers)['unread_count'] == 0
    assert client.get('/api/v1/notification-inbox').status_code == 401


def test_task_assignment_and_hr_document_upload(api):
    client, app, _, headers = api
    people = setup_people(api)
    with app.state.sessions.begin() as db:
        for model in ('EmployeeTask', 'EmployeeDocument'):
            table(db, model).create(db.bind)
    response = client.post('/api/admin/employee-tasks', json={'employeeId': people['employee']['id'],
        'title': 'Synthetic assigned task', 'description': 'Synthetic task details',
        'dueDate': '2026-11-05', 'source': 'ONBOARDING'}, headers=headers['hr'])
    assert response.status_code == 201, response.text
    task_id = response.json()['id']
    response = client.post('/api/documents/upload',
        data={'employeeId': people['employee']['id'], 'documentName': 'HR letter', 'documentType': 'Onboarding'},
        files={'file': ('proof.pdf', b'%PDF-synthetic', 'application/pdf')}, headers=headers['hr'])
    assert response.status_code == 201, response.text
    received = inbox(client, headers)
    assert received['unread_count'] == 2
    assert {item['href'] for item in received['items']} == {
        '/HRMS/Employee/my-tasks/' + task_id, '/HRMS/Employee/my-profile?tab=Document'}
    assert inbox(client, headers, 'manager')['items'] == []
    response = client.post('/api/employee-documents', data={'title': 'Self upload'},
        files={'file': ('self.pdf', b'%PDF-self', 'application/pdf')}, headers=headers['employee'])
    assert response.status_code == 201, response.text
    assert inbox(client, headers)['unread_count'] == 2
    for role in ('admin', 'hr'):
        review = inbox(client, headers, role)
        assert review['unread_count'] == 1
        assert review['items'][0]['href'] == '/HRMS/Admin/EmployeeManagement/document-repository'


def test_claim_decision_notifies_only_requester(api):
    client, _, _, headers = api
    claim = act(api, draft(api), 'submit')
    for role in ('admin', 'hr'):
        review = inbox(client, headers, role)
        assert review['unread_count'] == 1
        assert review['items'][0]['href'] == '/HRMS/Admin/EmployeeSelfService/reimbursements-claims'
    act(api, claim, 'reject', role='hr')
    received = inbox(client, headers)
    assert received['unread_count'] == 1
    assert received['items'][0]['message'] == 'Your expense claim was rejected.'
    assert received['items'][0]['href'] == '/HRMS/Employee/reimbursements-claims'
    assert inbox(client, headers, 'manager')['items'] == []
    act(api, claim, 'approve', role='hr', status=409)
    assert inbox(client, headers)['unread_count'] == 1


def test_delivery_rolls_back_with_action_and_worker_does_not_duplicate(api):
    from app.core.models import User
    from app.core.notifications import deliver
    from app.workers.outbox import process_batch
    client, app, users, headers = api
    with app.state.sessions() as db:
        actor = db.get(User, users['hr'])
        deliver(db, actor, users['employee'], 'Rolled back', '/HRMS/Employee/my-tasks')
        db.rollback()
    assert inbox(client, headers)['items'] == []
    claim = act(api, draft(api), 'submit')
    act(api, claim, 'approve', role='hr')
    process_batch(app.state.sessions, app.state.settings.customer_id)
    assert len(inbox(client, headers)['items']) == 1


def test_review_notifications_exclude_self_inactive_and_other_customers(api):
    from sqlalchemy import select
    from app.core.models import Notification, User
    client, app, users, headers = api
    with app.state.sessions.begin() as db:
        inactive = User(customer_id=app.state.settings.customer_id, email='inactive@example.com',
                        name='Inactive HR', role='hr', active=False)
        db.add(inactive)
        db.flush()
        inactive_id = inactive.id
    pending = act(api, draft(api, role='hr'), 'submit', role='hr')
    assert inbox(client, headers, 'hr')['items'] == []
    assert inbox(client, headers, 'admin')['unread_count'] == 1
    assert inbox(client, headers, 'employee')['items'] == []
    act(api, pending, 'submit', role='hr', status=409)
    assert inbox(client, headers, 'admin')['unread_count'] == 1
    with app.state.sessions() as db:
        all_rows = db.scalars(select(Notification)).all()
        assert all_rows and all(row.user_id == users['admin'] for row in all_rows)
        assert all(row.user_id != inactive_id for row in all_rows)
