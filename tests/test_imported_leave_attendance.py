from datetime import datetime, timezone

from app.data.imported import table
from app.modules.workforce.imported_assets import insert


def setup_people(api):
    _, app, users, _ = api
    result = {}
    with app.state.sessions.begin() as db:
        for model in ('User', 'Employee', 'LeaveType', 'LeaveRequest', 'LeaveBalance', 'AttendanceRecord', 'AttendancePolicy'):
            table(db, model).create(db.bind)
        for role in ('hr', 'manager', 'employee'):
            bridge = insert(db, 'User', {'auth0Sub': f"local|{users[role]}", 'email': role + '@example.com', 'role': role.upper()})
            result[role] = insert(db, 'Employee', {'employeeCode': 'LEAVE-' + role, 'firstName': 'Synthetic', 'lastName': role,
                'status': 'ACTIVE', 'orgSortOrder': 0, 'userId': bridge['id'],
                'reportsToEmployeeId': result['manager']['id'] if role == 'employee' else None})
        result['other'] = insert(db, 'Employee', {'employeeCode': 'LEAVE-other', 'firstName': 'Synthetic', 'lastName': 'Other', 'status': 'ACTIVE', 'orgSortOrder': 0})
    return result


def test_leave_ownership_decisions_overlap_and_balances(api):
    client, app, _, headers = api
    people = setup_people(api)
    response = client.post('/api/leave-types', json={'name': 'Synthetic leave', 'daysPerYear': 12, 'colorHex': '#123456'}, headers=headers['hr'])
    assert response.status_code == 201, response.text
    leave_type = response.json()['id']
    payload = {'leaveTypeId': leave_type, 'startDate': '2026-10-01', 'endDate': '2026-10-02', 'reason': 'Synthetic test'}
    assert client.post('/api/leave-requests', json={**payload, 'employeeId': people['other']['id']}, headers=headers['employee']).status_code == 403
    assert client.post('/api/leave-requests', json={**payload, 'status': 'APPROVED'}, headers=headers['employee']).status_code == 422
    assert client.post('/api/leave-requests', json={**payload, 'endDate': '2026-09-01'}, headers=headers['employee']).status_code == 422
    response = client.post('/api/leave-requests', json=payload, headers=headers['employee'])
    assert response.status_code == 201, response.text
    url = '/api/leave-requests/' + response.json()['id']
    assert response.json()['startDate'] == '2026-10-01T00:00:00.000Z'
    assert client.post('/api/leave-requests', json=payload, headers=headers['employee']).status_code == 409
    assert client.patch(url, json={'status': 'APPROVED'}, headers=headers['employee']).status_code == 403
    assert client.patch(url, json={'reason': 'Manager edit'}, headers=headers['manager']).status_code == 403
    assert client.get('/api/leave-requests?scope=team', headers=headers['manager']).json()['pendingTotal'] == 1
    assert client.patch(url, json={'status': 'APPROVED'}, headers=headers['manager']).status_code == 200
    assert client.patch(url, json={'status': 'APPROVED'}, headers=headers['manager']).status_code == 200
    assert client.patch(url, json={'status': 'REJECTED'}, headers=headers['manager']).status_code == 409
    assert client.delete(url, headers=headers['employee']).status_code == 409
    assert client.delete(url, headers=headers['hr']).json()['status'] == 'CANCELLED'
    # Withdrawal preserves the row and releases the date range.
    assert client.get(url, headers=headers['employee']).status_code == 200
    assert client.post('/api/leave-requests', json=payload, headers=headers['employee']).status_code == 201
    other = client.post('/api/leave-requests', json={**payload, 'employeeId': people['other']['id']}, headers=headers['hr']).json()
    assert client.get('/api/leave-requests/' + other['id'], headers=headers['employee']).status_code == 403
    assert client.patch('/api/leave-requests/' + other['id'], json={'status': 'APPROVED'}, headers=headers['manager']).status_code == 403
    own_hr = client.post('/api/leave-requests', json=payload, headers=headers['hr']).json()
    assert client.patch('/api/leave-requests/' + own_hr['id'], json={'status': 'APPROVED'}, headers=headers['hr']).status_code == 403
    balance = {'employeeId': people['employee']['id'], 'leaveTypeId': leave_type, 'year': 2026, 'balanceDays': 12}
    assert client.post('/api/leave-balances', json=balance, headers=headers['employee']).status_code == 403
    response = client.post('/api/leave-balances', json=balance, headers=headers['hr'])
    assert response.status_code == 201, response.text
    balance_url = '/api/leave-balances/' + response.json()['id']
    assert client.post('/api/leave-balances', json=balance, headers=headers['hr']).status_code == 409
    assert client.get(balance_url, headers=headers['manager']).status_code == 403
    assert client.get(balance_url, headers=headers['employee']).status_code == 200
    assert client.patch(balance_url, json={'balanceDays': -1}, headers=headers['hr']).status_code == 422
    assert client.delete('/api/leave-types/' + leave_type, headers=headers['hr']).status_code == 409
    assert client.get('/api/leave-requests', headers=headers['outsider']).status_code == 401
    assert client.get('/api/leave-requests', headers=headers['recruiter']).status_code == 403


def test_attendance_server_time_idempotency_corrections_and_policy_validation(api):
    client, _, _, headers = api
    people = setup_people(api)
    today = datetime.now(timezone.utc).date().isoformat()
    payload = {'workDate': today, 'checkIn': '2001-01-01T00:00:00Z'}
    response = client.post('/api/attendance-records', json=payload, headers=headers['employee'])
    assert response.status_code == 200, response.text
    record = response.json()
    assert record['checkIn'].startswith(today)
    again = client.post('/api/attendance-records', json=payload, headers=headers['employee']).json()
    assert again['id'] == record['id'] and again['checkIn'] == record['checkIn']
    assert client.post('/api/attendance-records', json={'workDate': '2001-01-01', 'checkIn': 'now'}, headers=headers['employee']).status_code == 422
    assert client.post('/api/attendance-records', json={**payload, 'employeeId': people['other']['id']}, headers=headers['employee']).status_code == 403
    url = '/api/attendance-records/' + record['id']
    assert client.get(url, headers=headers['manager']).status_code == 403
    assert client.patch(url, json={'checkIn': None}, headers=headers['employee']).status_code == 403
    assert client.patch(url, json={'checkIn': '2026-09-01T10:00:00'}, headers=headers['hr']).status_code == 422
    assert client.patch(url, json={'checkIn': '2026-09-01T10:00:00+05:30', 'checkOut': '2026-09-01T09:00:00+05:30'}, headers=headers['hr']).status_code == 422
    response = client.patch(url, json={'checkIn': '2026-09-01T10:00:00+05:30', 'checkOut': '2026-09-01T18:00:00+05:30', 'workDate': '2026-09-01'}, headers=headers['hr'])
    assert response.status_code == 200, response.text
    assert response.json()['checkIn'] == '2026-09-01T04:30:00Z'
    assert client.get('/api/attendance-records?scope=self', headers=headers['hr']).json() == []
    assert client.delete(url, headers=headers['employee']).status_code == 403
    policy = {'category': 'LEAVE_TYPE', 'name': 'Synthetic', 'config': {'days': 12, 'carryForward': True}}
    assert client.post('/api/attendance-policies', json=policy, headers=headers['employee']).status_code == 403
    assert client.post('/api/attendance-policies', json={**policy, 'config': {'days': -1}}, headers=headers['hr']).status_code == 422
    response = client.post('/api/attendance-policies', json=policy, headers=headers['hr'])
    assert response.status_code == 201, response.text
    assert '12 days' in response.json()['detail']
    policy_url = '/api/attendance-policies/' + response.json()['id']
    assert client.patch(policy_url, json={'status': 'INACTIVE'}, headers=headers['hr']).status_code == 200
    assert client.get('/api/attendance-policies?category=LEAVE_TYPE', headers=headers['hr']).json()[0]['status'] == 'INACTIVE'
    assert client.delete(policy_url, headers=headers['hr']).status_code == 204


def test_attendance_views_use_saved_records_and_keep_employee_scope(api, monkeypatch):
    from datetime import date
    from app.modules.workforce import imported_attendance_views as views, imported_leave_calendar as calendar
    client, app, _, headers = api
    people = setup_people(api)
    instant = datetime(2026, 9, 14, 18)
    monkeypatch.setattr(views, 'now', lambda: instant)
    monkeypatch.setattr(calendar, 'now', lambda: instant)
    with app.state.sessions.begin() as db:
        for model in ('Department', 'EmployeeShift', 'PublicHoliday'):
            table(db, model).create(db.bind)
        kind = insert(db, 'LeaveType', {'name': 'Sick leave', 'daysPerYear': 12})
        insert(db, 'LeaveRequest', {'employeeId': people['other']['id'], 'leaveTypeId': kind['id'], 'status': 'APPROVED',
            'startDate': date(2026, 9, 14), 'endDate': date(2026, 9, 14)})
        insert(db, 'AttendanceRecord', {'employeeId': people['employee']['id'], 'workDate': date(2026, 9, 14),
            'checkIn': datetime(2026, 9, 14, 9), 'checkOut': datetime(2026, 9, 14, 18)})
        insert(db, 'AttendanceRecord', {'employeeId': people['manager']['id'], 'workDate': date(2026, 9, 14),
            'checkIn': datetime(2026, 9, 14, 10), 'checkOut': datetime(2026, 9, 14, 18)})
    response = client.get('/api/attendance-tracker?workDate=2026-09-14', headers=headers['hr'])
    assert response.status_code == 200, response.text
    assert response.json()['stats'] == {'presentToday': '2/4', 'lateArrivals': 1, 'absent': 1, 'onLeave': 1}
    assert client.get('/api/attendance-tracker?format=csv&workDate=2026-09-14', headers=headers['hr']).headers['content-type'].startswith('text/csv')
    assert client.get('/api/attendance-tracker', headers=headers['employee']).status_code == 403
    response = client.get('/api/leave-attendance/overview', headers=headers['employee'])
    assert response.status_code == 200, response.text
    assert response.json()['stats']['daysPresent'] == 1
    assert response.json()['recentAttendance'][0]['status'] == 'Present'
    assert client.get('/api/leave-attendance/logs?days=7', headers=headers['employee']).json()['logs'][0]['checkIn'] == '9:00 AM UTC'
    url = f"/api/employees/{people['employee']['id']}/attendance?period=monthly&year=2026&month=9"
    response = client.get(url, headers=headers['hr'])
    assert response.status_code == 200, response.text
    assert response.json()['overview']['presentDays'] == 1
    assert response.json()['leaveSummary'] == []
    response = client.get('/api/leave-manager?year=2026&month=9', headers=headers['hr'])
    assert response.status_code == 200, response.text
    assert response.json()['summary']['daysTaken'] == 1
    assert len(response.json()['calendarWeeks']) == 6
    assert response.json()['onLeaveToday'][0]['employeeId'] == people['other']['id']
    response = client.get('/api/attendance-policy-stats', headers=headers['hr'])
    assert response.status_code == 200, response.text
    assert response.json()['kpi']['presentToday'] == '2/4'
    report = '/api/attendance-tracker/reports?startDate=2026-09-14&endDate=2026-09-14'
    response = client.get(report, headers=headers['hr'])
    assert response.status_code == 200, response.text
    assert response.json()['kpis']['totalEmployeesFraction'] == '2/4'
    assert response.json()['kpis']['averageAttendancePct'] == 66.7
    assert response.json()['kpis']['totalOvertimeHours'] == 1
    assert response.json()['distribution'] == {'presentPct': 25, 'latePct': 25, 'leaveEarlyPct': 25, 'absentPct': 25}
    assert client.get(report, headers=headers['manager']).status_code == 403
    pdf_url = report.replace('/reports?', '/reports/pdf?')
    response = client.get(pdf_url, headers=headers['hr'])
    assert response.status_code == 200, response.text
    assert response.content.startswith(b'%PDF-')
    assert response.headers['content-type'] == 'application/pdf'
    assert client.get(pdf_url, headers=headers['employee']).status_code == 403
    assert client.get('/api/attendance-tracker/reports?startDate=2020-01-01&endDate=2026-01-01', headers=headers['hr']).status_code == 422
    response = client.get('/api/admin/attendance-records?date=2026-09-14', headers=headers['hr'])
    assert response.status_code == 200, response.text
    assert len(response.json()['rows']) == 2
