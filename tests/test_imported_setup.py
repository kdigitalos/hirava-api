from app.data.imported import table


def test_structure_import_atomic_and_no_invented_head_or_history(api):
    client, app, _, headers = api
    with app.state.sessions.begin() as db:
        for model in ('Department', 'Branch', 'Designation', 'Employee', 'OrganizationCompanyProfile', 'SupportTicket'):
            table(db, model).create(db.bind)
    path = '/api/organization/setup-dashboard'
    payload = {'action': 'importStructure', 'structure': {'departments': [{'name': 'Synthetic', 'code': 'TEST'}],
        'locations': [{'name': 'Test location', 'city': 'Test', 'state': 'Test', 'country': 'India'}],
        'designations': [{'departmentCodeOrName': 'TEST', 'title': 'Developer'}]}}
    assert client.post(path + '/actions', json=payload, headers=headers['employee']).status_code == 403
    response = client.post(path + '/actions', json=payload, headers=headers['hr'])
    assert response.status_code == 200, response.text
    dashboard = client.get(path, headers=headers['hr']).json()
    assert dashboard['hierarchy']['children'][0]['title'] == 'No head assigned'
    assert dashboard['recentChanges'] == []
    broken = {'action': 'importStructure', 'structure': {'departments': [{'name': 'Must roll back', 'code': 'ROLLBACK'}],
        'designations': [{'departmentCodeOrName': 'missing', 'title': 'Invalid'}]}}
    assert client.post(path + '/actions', json=broken, headers=headers['hr']).status_code == 422
    assert client.get(path, headers=headers['hr']).json()['stats'][1]['value'] == '1'
    assert client.get('/api/search?q=Synthetic', headers=headers['employee']).status_code == 403
    assert client.get('/api/search?q=nonexistent', headers=headers['hr']).json()['results'] == []
    assert client.get('/api/health').json()['database'] == 'up'
