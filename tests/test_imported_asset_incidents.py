from app.data.imported import table
from app.modules.workforce.imported_assets import insert
from test_imported_assets import setup_inventory


def test_incidents_and_profile_asset_returns(api):
    client, app, users, headers = api
    body, employee = setup_inventory(api)
    with app.state.sessions.begin() as db:
        for model in ('User', 'JobTitle', 'Designation', 'LostDamageIncident', 'LostDamagePolicyGuideline', 'LostDamageWorkflowStep'):
            table(db, model).create(db.bind)
        bridge = insert(db, 'User', {'auth0Sub': f"local|{users['employee']}", 'email': 'employee@example.com', 'role': 'EMPLOYEE'})
        employees = table(db, 'Employee')
        db.execute(employees.update().where(employees.c.id == employee['id']).values(userId=bridge['id']))
    base = f"/api/employees/{employee['id']}/assets"
    response = client.post(base, json={'assetName': 'Test asset', 'originalPrice': 1000, 'dateHandedToEmployee': '2026-01-01'}, headers=headers['hr'])
    assert response.status_code == 201, response.text
    allocation = response.json()
    assert client.get(base, headers=headers['hr']).json()['assignments'][0]['id'] == allocation['id']
    payload = {'assetId': allocation['asset']['id'], 'reporterEmployeeId': 'ignored-body-owner', 'incidentType': 'DAMAGED',
               'incidentDate': '2026-09-01', 'location': 'Test', 'description': 'Synthetic incident', 'estimatedCost': '1,000.50'}
    response = client.post('/api/lost-damage-incidents', data=payload, files={'attachments': ('test.pdf', b'%PDF-test', 'application/pdf')}, headers=headers['employee'])
    assert response.status_code == 201, response.text
    incident = response.json()
    assert incident['employeeName'] == 'Synthetic Employee'
    assert incident['status'] == 'UNDER_REVIEW'
    assert incident['estimatedCostFormatted'] == '₹1,001'
    url = '/api/lost-damage-incidents/' + incident['id']
    assert client.patch(url, json={'status': 'RESOLVED'}, headers=headers['employee']).status_code == 403
    assert client.patch(url, json={'status': 'RESOLVED'}, headers=headers['hr']).status_code == 200
    assert client.get(url, headers=headers['employee']).status_code == 200
    assert client.get('/api/lost-damage-incidents', headers=headers['employee']).json()['stats']['resolvedThisMonth'] == 1
    assert client.get('/api/lost-damage-policy', headers=headers['hr']).json() == {'policyGuidelines': [], 'workflowSteps': []}
    release = base + '/' + allocation['id']
    assert client.delete(release, headers=headers['hr']).status_code == 204
    assert client.delete(release, headers=headers['hr']).status_code == 204
    assert client.post('/api/lost-damage-incidents', data=payload, headers=headers['employee']).status_code == 415
    # A returned asset is no longer owned for incident submission.
    assert client.post('/api/lost-damage-incidents', data=payload, files={'attachments': ('test.pdf', b'%PDF-test')}, headers=headers['employee']).status_code == 403
