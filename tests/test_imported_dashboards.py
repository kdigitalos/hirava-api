from datetime import timedelta

from app.data.imported import table
from app.modules.workforce.imported_assets import insert, now
from app.modules.workforce.imported_organization import update
from test_imported_leave_attendance import setup_people


def test_dashboard_counts_drafts_and_compensation_are_not_payments(api):
    client, app, _, headers = api
    people = setup_people(api)
    with app.state.sessions.begin() as db:
        for model in ('Department', 'Designation', 'JobTitle', 'ExitRequest', 'EmployeeDocument', 'SupportTicket', 'PublicHoliday', 'OnboardingGroup', 'OnboardingCandidate', 'ProbationRecord'):
            table(db, model).create(db.bind)
        update(db, 'Employee', people['employee']['id'], {'hireDate': now().date(), 'payrollJson': {'grossSalary': 50000, 'netPay': 40000}})
        for draft in (False, True):
            insert(db, 'ExitRequest', {'employeeId': people['employee']['id'], 'status': 'PENDING', 'isDraft': draft,
                'noticeWaived': False, 'policyAccepted': True, 'lastWorkingDate': now().date() + timedelta(days=30)})
    response = client.get('/api/admin/dashboard', headers=headers['hr'])
    assert response.status_code == 200, response.text
    summary = response.json()['summary']
    assert summary['totalEmployees'] == 4 and summary['newHires30d'] == 1 and summary['pendingApprovals'] == 1
    assert all(row['status'] == 'Pending' and row['paymentVerified'] is False for row in response.json()['payroll'])
    assert client.get('/api/admin/dashboard', headers=headers['employee']).status_code == 403
    response = client.get('/api/admin/exit-dashboard', headers=headers['hr'])
    assert response.status_code == 200, response.text
    assert response.json()['stats']['totalExits'] == 1
    assert response.json()['reasons'][0]['pct'] == 100
    response = client.get('/api/employee-self-service/dashboard', headers=headers['employee'])
    assert response.status_code == 200, response.text
    assert response.json()['payslip']['hasDownload'] is False
    assert response.json()['payslip']['periodLabel'] == 'Recorded compensation'
    response = client.get('/api/admin/onboarding-dashboard', headers=headers['hr'])
    assert response.status_code == 200, response.text
    assert response.json()['stats']['openOffboardingCases'] == 1
    assert response.json()['candidatesInProgressList'] == []
    assert client.post('/api/admin/onboarding-dashboard', json={'action': 'complete-task', 'taskId': 'candidate-test'}, headers=headers['hr']).status_code == 409
