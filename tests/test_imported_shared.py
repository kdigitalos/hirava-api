from sqlalchemy import select

from app.data.imported import table
from app.modules.workforce.imported_assets import insert


def test_private_upload_and_identity_without_node(api):
    client, app, users, headers = api
    with app.state.sessions.begin() as db:
        table(db, 'User').create(db.bind)
        table(db, 'Employee').create(db.bind)
    response = client.get('/api/users/me', headers=headers['employee'])
    assert response.status_code == 200, response.text
    bridge = response.json()
    assert bridge['role'] == 'EMPLOYEE'
    assert client.get('/api/users/me', headers=headers['employee']).json()['id'] == bridge['id']
    assert client.get('/api/session/employee', headers=headers['employee']).status_code == 401
    with app.state.sessions.begin() as db:
        employee = insert(db, 'Employee', {'employeeCode': 'SELF', 'firstName': 'Synthetic', 'lastName': 'Test',
                     'status': 'ACTIVE', 'orgSortOrder': 0, 'userId': bridge['id']})
    response = client.get('/api/session/employee', headers=headers['employee'])
    assert response.status_code == 200, response.text
    assert response.json()['employee']['id'] == employee['id']
    response = client.post('/api/upload', files={'file': ('test.pdf', b'%PDF-synthetic', 'application/pdf')}, headers=headers['employee'])
    assert response.status_code == 200, response.text
    url = response.json()['fileUrl']
    assert client.get(url, headers=headers['employee']).content == b'%PDF-synthetic'
    assert client.get(url, headers=headers['manager']).status_code == 403
    assert client.get(url, headers=headers['hr']).status_code == 200
    assert client.get(url).status_code == 401
    assert client.get(url, headers=headers['outsider']).status_code == 401
    assert client.post('/api/upload', files={'file': ('test.html', b'<script/>')}, headers=headers['employee']).status_code == 422
    assert client.get('/api/uploads/user-uploads/a/C:/secret', headers=headers['admin']).status_code == 400
    # A same-email row with another subject must never be adopted.
    with app.state.sessions.begin() as db:
        insert(db, 'User', {'email': 'manager@example.com', 'auth0Sub': 'different-subject', 'role': 'EMPLOYEE'})
    assert client.get('/api/users/me', headers=headers['manager']).status_code == 409
