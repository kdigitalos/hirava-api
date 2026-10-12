from app.modules.workforce.imported_organization import update
from test_imported_leave_attendance import setup_people


def test_finances_only_returns_own_saved_compensation(api):
    client, app, _, headers = api
    people = setup_people(api)
    path = '/api/views/employee-finances'
    assert client.get(path).status_code == 401
    assert client.get(path, headers=headers['outsider']).status_code == 401
    assert client.get(path, headers=headers['admin']).json() == {
        'employeeLinked': False, 'compensation': None}
    missing = client.get(path, headers=headers['employee']).json()
    assert missing['employeeLinked']
    assert missing['compensation']['grossSalary'] is None
    assert missing['compensation']['netPay'] is None
    with app.state.sessions.begin() as db:
        update(db, 'Employee', people['employee']['id'], {'payrollJson': {
            'grossSalary': 73125, 'deductionsAmount': 0, 'netPay': None,
            'payFrequency': 'Monthly', 'deductionsDescription': 'Recorded by HR'}})
        update(db, 'Employee', people['manager']['id'], {'payrollJson': {'grossSalary': 99999}})
    response = client.get(path + '?employeeId=' + people['manager']['id'], headers=headers['employee'])
    assert response.status_code == 200, response.text
    saved = response.json()['compensation']
    assert saved['grossSalary'] == 73125
    assert saved['deductionsAmount'] == 0
    assert saved['netPay'] is None  # Never infer payment or a missing amount.
    assert saved['payFrequency'] == 'Monthly'
    assert saved['deductionsDescription'] == 'Recorded by HR'
