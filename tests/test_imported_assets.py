from datetime import datetime

from app.data.imported import table
from app.modules.workforce.imported_assets import insert


def setup_inventory(api):
    client, app, _, headers = api
    with app.state.sessions.begin() as db:
        for model in ('AssetCategory', 'AssetVendor', 'Asset', 'AssetPhoto', 'AssetAssignment', 'Employee', 'Department'):
            table(db, model).create(db.bind)
        employee = insert(db, 'Employee', {'employeeCode': 'TEST-1', 'firstName': 'Synthetic', 'lastName': 'Employee',
                                         'status': 'ACTIVE', 'orgSortOrder': 0})
    category = client.post('/api/asset-categories', headers=headers['hr'], json={'name': 'Laptop', 'idPrefix': 'lap', 'description': 'Testing'})
    assert category.status_code == 201, category.text
    vendor = client.post('/api/vendors', headers=headers['hr'], json={'name': 'Synthetic vendor'})
    assert vendor.status_code == 201, vendor.text
    body = {'assetTag': 'TEST-LAP-1', 'name': 'Test laptop', 'model': 'Synthetic', 'serialNumber': 'TEST-SERIAL',
            'categoryId': category.json()['id'], 'vendorId': vendor.json()['id'], 'condition': 'NEW',
            'purchaseOrder': 'TEST-PO', 'invoiceNumber': 'TEST-INV', 'purchaseDate': '2026-09-01',
            'purchaseValue': '65,000.50', 'usefulLifeMonths': 36, 'warrantyEndDate': '2027-09-01',
            'location': 'Test office', 'notes': 'Synthetic fixture'}
    return body, employee


def test_inventory_allocation_and_return_without_node(api):
    client, app, _, headers = api
    body, employee = setup_inventory(api)
    assert not app.state.settings.legacy_api_url
    for role in ('employee', 'manager', 'recruiter'):
        assert client.get('/api/assets', headers=headers[role]).status_code == 403
        assert client.post('/api/assets', json=body, headers=headers[role]).status_code == 403
    response = client.post('/api/assets', json=body, headers=headers['hr'])
    assert response.status_code == 201, response.text
    asset = response.json()
    assert asset['purchaseValue'] == '65000.50'
    assert asset['category']['name'] == 'Laptop'
    assert client.post('/api/assets', json=body, headers=headers['hr']).status_code == 409
    assert client.get('/api/asset-categories', headers=headers['hr']).json()[0]['assetCount'] == 1
    assert len(client.get('/api/assets/available', headers=headers['hr']).json()) == 1
    assert client.patch(f"/api/assets/{asset['id']}", json={'status': 'ALLOCATED'}, headers=headers['hr']).status_code == 409
    allocation = {'assetId': asset['id'], 'employeeId': employee['id'], 'assignedAt': '2026-09-14'}
    response = client.post('/api/asset-assignments', json=allocation, headers=headers['hr'])
    assert response.status_code == 201, response.text
    assigned = response.json()
    assert assigned['employee']['firstName'] == 'Synthetic'
    assert assigned['asset']['status'] == 'ALLOCATED'
    assert client.post('/api/asset-assignments', json=allocation, headers=headers['hr']).status_code == 409
    assert client.get('/api/assets/available', headers=headers['hr']).json() == []
    response = client.get('/api/assets', headers=headers['hr'])
    assert response.status_code == 200, response.text
    assert response.json()[0]['assignedTo'] == 'Synthetic Employee'
    assert client.delete(f"/api/assets/{asset['id']}", headers=headers['hr']).status_code == 409
    url = f"/api/asset-assignments/{assigned['id']}"
    assert client.patch(url, json={'returnedAt': None}, headers=headers['hr']).status_code == 409
    assert client.patch(url, json={'returnedAt': '2026-09-01'}, headers=headers['hr']).status_code == 422
    response = client.patch(url, json={'returnedAt': '2026-09-15'}, headers=headers['hr'])
    assert response.status_code == 200, response.text
    assert len(client.get('/api/assets/available', headers=headers['hr']).json()) == 1
    assert client.patch(url, json={'returnedAt': '2026-09-16'}, headers=headers['hr']).status_code == 409
    assert client.delete(url, headers=headers['hr']).status_code == 409
    assert client.get('/api/asset-assignments?activeOnly=true', headers=headers['hr']).json() == []


def test_asset_photo_failure_rolls_back_asset_and_cleans_saved_files(api, monkeypatch):
    from sqlalchemy import func, select
    client, app, _, headers = api
    body, _ = setup_inventory(api)
    saved, cleaned = [], []
    def save(settings, key, content, mime):
        if saved:
            raise RuntimeError('Synthetic storage failure')
        saved.append(key)
    monkeypatch.setattr('app.core.imported_storage.save', save)
    monkeypatch.setattr('app.core.imported_storage.remove', lambda settings, key: cleaned.append(key))
    import pytest
    with pytest.raises(RuntimeError, match='Synthetic storage failure'):
        client.post('/api/assets', data=body, files=[('photos', ('a.png', b'synthetic', 'image/png')),
                     ('photos', ('b.png', b'synthetic', 'image/png'))], headers=headers['hr'])
    assert saved == cleaned
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(table(db, 'Asset'))) == 0
        assert db.scalar(select(func.count()).select_from(table(db, 'AssetPhoto'))) == 0


def test_employee_return_ownership_review_and_timeline(api):
    client, app, users, headers = api
    body, employee = setup_inventory(api)
    with app.state.sessions.begin() as db:
        table(db, 'User').create(db.bind)
        table(db, 'AssetReturnRequest').create(db.bind)
        bridge = insert(db, 'User', {'auth0Sub': f"local|{users['employee']}", 'email': 'employee@example.com',
                                    'name': 'Synthetic', 'role': 'EMPLOYEE'})
        employees = table(db, 'Employee')
        db.execute(employees.update().where(employees.c.id == employee['id']).values(userId=bridge['id']))
    asset = client.post('/api/assets', json=body, headers=headers['hr']).json()
    allocation = client.post('/api/asset-assignments', json={'assetId': asset['id'], 'employeeId': employee['id']}, headers=headers['hr']).json()
    payload = {'assetAssignmentId': allocation['id'], 'reason': 'Return test', 'expectedReturnDate': '2026-10-01'}
    assert client.post('/api/asset-return-requests', json=payload, headers=headers['manager']).status_code == 403
    response = client.post('/api/asset-return-requests', json=payload, headers=headers['employee'])
    assert response.status_code == 201, response.text
    request = response.json()
    assert request['status'] == 'Pending Approval'
    assert client.post('/api/asset-return-requests', json=payload, headers=headers['employee']).status_code == 409
    review = {'id': request['id'], 'status': 'APPROVED'}
    assert client.patch('/api/asset-return-requests', json=review, headers=headers['employee']).status_code == 403
    assert client.patch('/api/asset-return-requests', json=review, headers=headers['hr']).status_code == 200
    assert client.patch('/api/asset-return-requests', json=review, headers=headers['hr']).status_code == 409
    assert client.get('/api/assets/available', headers=headers['hr']).json() == []
    assert client.get('/api/asset-return-requests', headers=headers['employee']).json()[0]['status'] == 'Approved'
    response = client.get('/api/asset-assignments/timeline', headers=headers['hr'])
    assert response.status_code == 200, response.text
    assert {row['event'] for row in response.json()} == {'Asset Allocated', 'Return Requested', 'Return Approved'}
