from app.data.imported import table
from test_imported_leave_attendance import setup_people


def test_settlement_amounts_ownership_and_review_transitions(api):
    client, app, _, headers = api
    people = setup_people(api)
    with app.state.sessions.begin() as db:
        for model in ('ExitRequest', 'FnfSettlement'):
            table(db, model).create(db.bind)
    body = {'employeeId': people['hr']['id'], 'exitDate': '2026-10-31', 'departmentLabel': 'Synthetic', 'netAmount': '1,23,456.78', 'companyPayout': '123456.78'}
    response = client.post('/api/fnf-settlements', json=body, headers=headers['admin'])
    assert response.status_code == 201, response.text
    record = response.json()['settlement']
    assert record['netAmountPaise'] == 12345678
    assert record['netAmountDisplay'] == '₹1,23,456.78'
    url = '/api/fnf-settlements/' + record['id']
    assert client.patch(url, json={'status': 'Approved'}, headers=headers['admin']).status_code == 409
    assert client.patch(url, json={'employeeId': people['other']['id']}, headers=headers['admin']).status_code == 409
    assert client.patch(url, json={'netAmount': 'NaN'}, headers=headers['admin']).status_code == 422
    assert client.patch(url, json={'status': 'Under Review'}, headers=headers['admin']).status_code == 200
    assert client.patch(url, json={'status': 'Approved'}, headers=headers['hr']).status_code == 403
    assert client.patch(url, json={'status': 'Approved'}, headers=headers['admin']).status_code == 200
    assert client.patch(url, json={'netAmount': '100'}, headers=headers['admin']).status_code == 409
    assert client.delete(url, headers=headers['admin']).status_code == 409
    assert client.patch(url, json={'status': 'Completed'}, headers=headers['admin']).status_code == 200
    assert client.patch(url, json={'notes': 'Edited'}, headers=headers['admin']).status_code == 409
    assert client.get(url, headers=headers['employee']).status_code == 403
