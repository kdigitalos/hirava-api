from datetime import timedelta
from app.data.imported import table
from app.modules.workforce.imported_assets import insert, now
from tests.test_imported_leave_attendance import setup_people


def test_named_views_ownership_empty_states_and_role_metadata(api):
    client, app, users, headers = api
    people = setup_people(api)
    with app.state.sessions.begin() as db:
        for model in ('Department', 'JobTitle', 'EmployeeProfile', 'EmployeeDocument', 'AssetAssignment', 'PrivacyPolicy', 'EmployeeTask', 'Announcement', 'OrganizationRoleSetting'):
            table(db, model).create(db.bind)
        task = insert(db, 'EmployeeTask', {'employeeId': people['employee']['id'], 'title': 'Own task', 'description': 'Synthetic',
            'source': 'ONBOARDING', 'dueDate': now() - timedelta(days=1), 'status': 'IN_PROGRESS', 'detailKind': 'generic'})
    base = '/api/views/'
    profile = client.get(base + 'employee-profile', headers=headers['employee'])
    assert profile.status_code == 200, profile.text
    assert profile.json()['employeeId'] == people['employee']['id']
    assert profile.json()['myDocuments'] == [] and profile.json()['bankName'] == ''
    assert profile.json()['assignedAssets'] == [] and profile.json()['recentlyViewedPolicies'] == []
    assert client.get(base + 'my-task?id=' + task['id'], headers=headers['manager']).json() is None
    assert client.get(base + 'my-task?id=' + task['id'], headers=headers['employee']).json()['status'] == 'Overdue'
    dashboard = client.get(base + 'employee-dashboard', headers=headers['employee'])
    assert dashboard.status_code == 200, dashboard.text
    assert dashboard.json()['myTasks'] == 1 and len(dashboard.json()['last7']) == 7
    assert dashboard.json()['netPayStr'] is None
    assert client.get(base + 'policy-stats', headers=headers['employee']).status_code == 403
    assert client.get(base + 'ess-profile', headers=headers['admin']).json()['employee'] is None
    role_path = '/api/organization/roles'
    response = client.post(role_path, json={'name': 'Configuration test', 'description': 'Reference only'}, headers=headers['admin'])
    assert response.status_code == 201, response.text
    assert response.json()['permissionsEnforced'] is False
    record_id = response.json()['id']
    assert client.patch(role_path + '/' + record_id, json={'permissions': {'settings': {'read': True}}}, headers=headers['admin']).status_code == 422
    listing = client.get(base + 'organization-roles', headers=headers['admin']).json()
    assert listing['roles'][0]['userCount'] == 0
    assert client.get(base + 'organization-roles', headers=headers['hr']).status_code == 403
    assert client.delete(role_path + '/' + record_id, headers=headers['admin']).status_code == 200
