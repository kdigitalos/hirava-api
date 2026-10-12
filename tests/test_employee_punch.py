from datetime import datetime
from app.data.imported import table
from test_imported_leave_attendance import setup_people


def test_ist_day_checkin_checkout_refresh_and_missing_records(api, monkeypatch):
    client, app, _, headers = api
    setup_people(api)
    with app.state.sessions.begin() as db:
        for model in ('EmployeeTask', 'Announcement'):
            table(db, model).create(db.bind)
    # UTC is still Oct 7, while the employee's work day is Oct 8 in India.
    clock = [datetime(2026, 10, 7, 20)]
    for module in ('imported_attendance', 'imported_attendance_views', 'imported_employee_dashboard'):
        monkeypatch.setattr('app.modules.workforce.' + module + '.now', lambda: clock[0])
    endpoint = '/api/attendance-records'
    auth = headers['employee']
    today = client.get('/api/attendance-today', headers=auth).json()
    assert today == {'workDate': '2026-10-08', 'checkInTime': None, 'checkOutTime': None}
    assert client.post(endpoint, json={'workDate': today['workDate'], 'checkOut': 'now'}, headers=auth).status_code == 422
    assert client.post(endpoint, json={'workDate': '2026-10-07', 'checkIn': 'now'}, headers=auth).status_code == 422
    first = client.post(endpoint, json={'workDate': today['workDate'], 'checkIn': 'now'}, headers=auth)
    assert first.status_code == 200, first.text
    assert first.json()['checkIn'] == '2026-10-07T20:00:00Z'
    assert client.get('/api/attendance-today', headers=auth).json()['checkInTime'] == '1:30 AM IST'
    clock[0] = datetime(2026, 10, 8, 3)
    second = client.post(endpoint, json={'workDate': today['workDate'], 'checkOut': 'now'}, headers=auth)
    assert second.status_code == 200, second.text
    assert second.json()['checkOut'] == '2026-10-08T03:00:00Z'
    clock[0] = datetime(2026, 10, 8, 4)
    repeated = client.post(endpoint, json={'workDate': today['workDate'], 'checkOut': 'now'}, headers=auth)
    assert repeated.json()['checkOut'] == second.json()['checkOut']
    saved = client.get('/api/attendance-today', headers=auth).json()
    assert saved['checkOutTime'] == '8:30 AM IST'
    dashboard = client.get('/api/views/employee-dashboard', headers=auth)
    assert dashboard.status_code == 200, dashboard.text
    assert dashboard.json()['checkInTime'] == saved['checkInTime']
    assert dashboard.json()['checkOutTime'] == saved['checkOutTime']
    assert dashboard.json()['last7'][1]['status'] == 'unrecorded'
    logs = client.get('/api/leave-attendance/logs?days=7', headers=auth).json()['logs']
    assert logs[0]['checkIn'] == '1:30 AM IST' and logs[0]['checkOut'] == '8:30 AM IST'
    assert logs[1]['status'] == 'No attendance recorded'
    assert client.get('/api/attendance-today', headers=headers['manager']).json()['checkInTime'] is None
    assert client.get('/api/attendance-today').status_code == 401
