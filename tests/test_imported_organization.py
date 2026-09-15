from app.data.imported import table
from app.modules.workforce.imported_assets import insert


def test_organization_contracts_and_employee_references(api):
    client, app, _, headers = api
    with app.state.sessions.begin() as db:
        for model in ('Employee', 'Department', 'Designation', 'JobTitle', 'Branch'):
            table(db, model).create(db.bind)
        employee = insert(db, 'Employee', {'employeeCode': 'ORG-1', 'firstName': 'Test', 'lastName': 'Head', 'status': 'ACTIVE', 'orgSortOrder': 0})
    body = {'name': 'Engineering', 'code': 'ENG', 'description': 'Test department', 'departmentHeadEmployeeId': employee['id']}
    assert client.post('/api/departments', json=body, headers=headers['employee']).status_code == 403
    response = client.post('/api/departments', json=body, headers=headers['hr'])
    assert response.status_code == 201, response.text
    department = response.json()
    assert department['departmentHead']['id'] == employee['id']
    response = client.post(f"/api/departments/{department['id']}/designations", json={'title': 'Engineer', 'hierarchyLevel': 'L1', 'description': 'Test role'}, headers=headers['hr'])
    assert response.status_code == 201, response.text
    designation = response.json()
    assert client.get('/api/departments', headers=headers['hr']).json()[0]['designations'][0]['id'] == designation['id']
    assert client.delete(f"/api/departments/{department['id']}", headers=headers['hr']).status_code == 409
    response = client.post('/api/job-titles', json={'name': 'Developer'}, headers=headers['hr'])
    assert response.status_code == 201, response.text
    title = response.json()
    branch_body = {'name': 'Test office', 'code': 'TEST', 'street': 'Test street', 'city': 'Hyderabad', 'state': 'Telangana',
                   'zip': '500001', 'country': 'India', 'description': 'Fixture', 'email': 'branch@example.com', 'phone': '0000000000', 'branchHeadEmployeeId': employee['id']}
    response = client.post('/api/branches', json=branch_body, headers=headers['hr'])
    assert response.status_code == 201, response.text
    branch = response.json()
    with app.state.sessions.begin() as db:
        employees = table(db, 'Employee')
        db.execute(employees.update().where(employees.c.id == employee['id']).values(departmentId=department['id'], designationId=designation['id'], jobTitleId=title['id'], branchId=branch['id']))
    for path in (f"/api/designations/{designation['id']}", f"/api/job-titles/{title['id']}", f"/api/branches/{branch['id']}"):
        assert client.delete(path, headers=headers['hr']).status_code == 409
    response = client.get('/api/branches?q=Head', headers=headers['hr'])
    assert response.json()['stats'] == {'total': 1, 'active': 1, 'employees': 1, 'countries': 1}
    assert response.json()['branches'][0]['employees'] == 1
    assert client.get('/api/branches?q=no-match', headers=headers['hr']).json()['branches'] == []
    assert client.get('/api/departments', headers=headers['outsider']).status_code == 401
