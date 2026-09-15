from app.data.imported import find, table
from app.modules.workforce.imported_assets import insert


def test_profile_metadata_merges_reporting_cycles_and_event_ownership(api):
    client, app, _, headers = api
    with app.state.sessions.begin() as db:
        for model in ('Employee', 'Department', 'JobTitle', 'User', 'EmployeeLifecycleEvent', 'OnboardingCandidate', 'ProbationRecord'):
            table(db, model).create(db.bind)
        employees = [insert(db, 'Employee', {'employeeCode': f'PROFILE-{number}', 'firstName': 'Synthetic', 'lastName': str(number),
                     'status': 'ACTIVE', 'orgSortOrder': 0, 'employeeDetails': {'preserved': True},
                     'payrollJson': {'sourceMetadata': 'preserved'}}) for number in (1, 2)]
    first, second = [f"/api/employees/{employee['id']}" for employee in employees]
    response = client.patch(first + '/job-details', json={'reportsToEmployeeId': employees[1]['id'], 'workLocation': 'Test office'}, headers=headers['hr'])
    assert response.status_code == 200, response.text
    assert response.json()['position']['reportsToName'] == 'Synthetic 2'
    assert client.patch(second + '/job-details', json={'reportsToEmployeeId': employees[0]['id']}, headers=headers['hr']).status_code == 409
    response = client.patch(first + '/payroll', json={'grossSalary': 50000, 'benefits': ['Health Insurance']}, headers=headers['hr'])
    assert response.status_code == 200, response.text
    assert response.json()['payroll']['grossSalary'] == 50000
    assert response.json()['payroll']['netPay'] is None
    assert client.patch(first + '/payroll', json={'netPay': -1}, headers=headers['hr']).status_code == 422
    assert client.patch(first + '/payroll', json={'grossSalary': '50000'}, headers=headers['hr']).status_code == 422
    assert client.patch(first + '/payroll', json={'taxRegime': 'Synthetic'}, headers=headers['hr']).status_code == 200
    with app.state.sessions() as db:
        record = find(db, 'Employee', employees[0]['id'])
        assert record['employeeDetails']['preserved']
        assert record['payrollJson']['sourceMetadata'] == 'preserved'
        assert record['payrollJson']['grossSalary'] == 50000
    response = client.post(first + '/lifecycle', json={'title': 'Synthetic event', 'occurredOn': '2026-09-14', 'kind': 'OTHER', 'bullets': ['Human recorded']}, headers=headers['hr'])
    assert response.status_code == 201, response.text
    event = response.json()
    response = client.get(first + '/lifecycle', headers=headers['hr'])
    assert response.status_code == 200, response.text
    assert response.json()['timeline'][0]['id'] == event['id']
    assert client.delete(second + '/lifecycle/' + event['id'], headers=headers['hr']).status_code == 404
    assert client.patch(first + '/lifecycle/' + event['id'], json={'title': 'Updated event'}, headers=headers['hr']).status_code == 200
    for suffix in ('/payroll', '/job-details', '/lifecycle'):
        assert client.get(first + suffix, headers=headers['employee']).status_code == 403
