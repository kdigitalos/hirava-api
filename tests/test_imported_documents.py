from app.data.imported import table
from app.modules.workforce.imported_assets import insert


def test_document_upload_review_private_preview_and_stats(api):
    client, app, users, headers = api
    with app.state.sessions.begin() as db:
        for model in ('User', 'Employee', 'Department', 'JobTitle', 'EmployeeDocument'):
            table(db, model).create(db.bind)
        bridge = insert(db, 'User', {'auth0Sub': f"local|{users['employee']}", 'email': 'employee@example.com', 'role': 'EMPLOYEE'})
        employee = insert(db, 'Employee', {'employeeCode': 'DOC-1', 'firstName': 'Synthetic', 'lastName': 'Documents', 'status': 'ACTIVE', 'orgSortOrder': 0, 'userId': bridge['id']})
    payload = {'employeeId': employee['id'], 'documentName': 'Synthetic proof', 'documentType': 'Onboarding'}
    response = client.post('/api/documents/upload', data=payload, files={'file': ('proof.pdf', b'%PDF-synthetic', 'application/pdf')}, headers=headers['hr'])
    assert response.status_code == 201, response.text
    document_id = response.json()['id']
    base = f"/api/employees/{employee['id']}/documents/{document_id}"
    assert client.get('/api/documents', headers=headers['hr']).json()[0]['status'] == 'Pending'
    assert client.get('/api/documents/stats', headers=headers['hr']).json()['pendingReviews'] == 1
    assert client.patch(base, json={'status': 'REJECTED'}, headers=headers['hr']).status_code == 422
    assert client.patch(base, json={'status': 'APPROVED'}, headers=headers['hr']).status_code == 200
    assert client.get('/api/documents/stats', headers=headers['hr']).json()['documentsApprovedPercent'] == 100
    response = client.get(base + '/download', headers=headers['hr'])
    assert response.status_code == 200, response.text
    assert response.content == b'%PDF-synthetic'
    assert response.headers['content-disposition'].startswith('inline;')
    assert client.get(base + '/download?download=1', headers=headers['hr']).headers['content-disposition'].startswith('attachment;')
    own = f'/api/employee-documents/{document_id}'
    assert client.get(own + '/download', headers=headers['employee']).content == b'%PDF-synthetic'
    assert client.get(own + '/download', headers=headers['manager']).status_code == 403
    assert client.get('/api/documents', headers=headers['employee']).status_code == 403
    assert client.patch(base, json={'status': 'APPROVED'}, headers=headers['employee']).status_code == 403
    assert len(client.get('/api/employee-documents', headers=headers['employee']).json()) == 1
    assert len(client.get('/api/documents/recent-activity', headers=headers['hr']).json()) == 1
    assert client.get('/api/documents/deadlines', headers=headers['hr']).json() == []
    # The self-service form cannot choose another employee through a body field.
    response = client.post('/api/employee-documents', data={'employeeId': 'someone-else', 'title': 'My upload'}, files={'file': ('self.pdf', b'%PDF-self', 'application/pdf')}, headers=headers['employee'])
    assert response.status_code == 201, response.text
    assert response.json()['employeeId'] == employee['id']
