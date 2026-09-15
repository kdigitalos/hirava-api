from app.data.imported import table


def test_employee_directory_create_edit_and_identity_guard(api, monkeypatch):
    client, app, _, headers = api
    with app.state.sessions.begin() as db:
        for model in ('Employee', 'Department', 'JobTitle', 'User'):
            table(db, model).create(db.bind)
    body = {'employeeCode': 'SYNTHETIC', 'firstName': 'Test', 'lastName': 'Person', 'hireDate': '14-09-2026'}
    response = client.post('/api/employees', json=body, headers=headers['hr'])
    assert response.status_code == 201, response.text
    employee = response.json()
    assert employee['hireDate'] == '2026-09-14'
    assert employee['userId'] is None
    url = f"/api/employees/{employee['id']}"
    assert client.patch(url, json={'userId': 'fake-account'}, headers=headers['hr']).status_code == 409
    assert client.patch(url, json={'lastName': None}, headers=headers['hr']).status_code == 422
    assert client.patch(url, json={'firstName': 'Updated'}, headers=headers['hr']).status_code == 200
    assert client.get('/api/employees', headers=headers['hr']).json()[0]['firstName'] == 'Updated'
    assert client.get(url, headers=headers['employee']).status_code == 403
    assert client.get('/api/employees/peers', headers=headers['employee']).json() == []
    assert client.post('/api/employees', json=body, headers=headers['hr']).status_code == 409
    form = {**body, 'employeeCode': 'PHOTO-TEST', 'contact': '0000000000', 'email': 'test@example.com',
            'userName': 'test', 'address': 'Test address', 'designation': 'Test title', 'location': 'Test',
            'manager': 'Test manager', 'accountHolderName': 'Test', 'accountNumber': '0000', 'bankName': 'Test', 'branchName': 'Test'}
    response = client.post('/api/employees', data=form, files={'employeePhoto': ('test.png', b'synthetic', 'image/png')}, headers=headers['hr'])
    assert response.status_code == 201, response.text
    assert response.json()['jobTitle']['name'] == 'Test title'
    photo = response.json()['employeeDetails']['employeePhoto']
    assert client.get('/api/uploads/' + photo, headers=headers['hr']).content == b'synthetic'
