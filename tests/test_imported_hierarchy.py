from io import BytesIO

from openpyxl import Workbook

from app.data.imported import table
from test_imported_leave_attendance import setup_people


def test_hierarchy_cycles_roles_reordering_and_import(api):
    client, app, _, headers = api
    people = setup_people(api)
    with app.state.sessions.begin() as db:
        for model in ('Department', 'Designation', 'JobTitle'):
            table(db, model).create(db.bind)
    response = client.get('/api/manager-mapping', headers=headers['hr'])
    assert response.status_code == 200, response.text
    assert response.json()['stats']['mapped'] == 1
    body = {'employeeIds': [people['manager']['id']], 'managerId': people['employee']['id']}
    assert client.post('/api/manager-mapping/bulk', json=body, headers=headers['employee']).status_code == 403
    response = client.post('/api/manager-mapping/bulk', json=body, headers=headers['hr'])
    assert response.json()['results'][0]['error'] == 'reporting_cycle'
    response = client.post('/api/reporting-hierarchy/employees', json={'managerId': people['manager']['id'], 'firstName': 'New', 'title': 'Synthetic title'}, headers=headers['hr'])
    assert response.status_code == 201, response.text
    new_id = response.json()['id']
    body = {'parentId': people['manager']['id'], 'orderedIds': [new_id, new_id]}
    assert client.post('/api/reporting-hierarchy/reorder', json=body, headers=headers['hr']).status_code == 422
    body['orderedIds'] = [new_id, people['employee']['id']]
    assert client.post('/api/reporting-hierarchy/reorder', json=body, headers=headers['hr']).status_code == 200
    response = client.get('/api/reporting-hierarchy', headers=headers['hr'])
    assert response.status_code == 200, response.text
    assert response.json()['stats']['hierarchyLevels'] == 2
    assert client.delete('/api/reporting-hierarchy/employees/' + new_id, headers=headers['hr']).status_code == 409
    workbook = Workbook()
    workbook.active.append(['employee_code', 'manager_employee_code'])
    workbook.active.append([people['other']['employeeCode'], people['manager']['employeeCode']])
    workbook.active.append([people['manager']['employeeCode'], people['other']['employeeCode']])
    stream = BytesIO()
    workbook.save(stream)
    response = client.post('/api/manager-mapping/import', files={'file': ('mapping.xlsx', stream.getvalue())}, headers=headers['hr'])
    assert response.status_code == 200, response.text
    assert response.json()['updated'] == 1 and response.json()['failed'] == 1
    assert response.json()['results'][1]['error'] == 'reporting_cycle'
