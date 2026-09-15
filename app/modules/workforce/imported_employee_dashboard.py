"""Employee dashboard uses own records; no inferred payroll payment."""
from datetime import timedelta
from app.core.imported_identity import linked_employee
from app.data.imported import find, table
from app.modules.workforce.imported_assets import now, rows
from app.modules.workforce.imported_employee_profile import details, full_name
from app.modules.workforce.imported_profile_view import initials


def employee_dashboard(db, user):
    name = user.name or user.email
    result = {'avatarUrl': None, 'jobTitle': '', 'department': '', 'managerName': '', 'netPayStr': None,
        'leaveBalances': [], 'announcements': [], 'myTasks': 0, 'pendingApprovals': 0, 'leaveRequests': 0,
        'openClaims': 0, 'checkedInToday': False, 'checkInTime': None, 'employeeFound': False,
        'firstName': name.split()[0].split('@')[0], 'initials': initials(name), 'last7': [], 'timezone': 'UTC', 'paymentVerified': False}
    employee = linked_employee(db, user, required=False)
    if not employee:
        return result
    result['employeeFound'] = True
    for model, foreign_key, source, target in (('Department', 'departmentId', 'name', 'department'), ('JobTitle', 'jobTitleId', 'name', 'jobTitle')):
        related = find(db, model, employee[foreign_key], required=False) if employee[foreign_key] else None
        result[target] = related[source] if related else ''
    if not result['jobTitle'] and employee['designationId']:
        result['jobTitle'] = (find(db, 'Designation', employee['designationId'], required=False) or {}).get('title', '')
    if employee['reportsToEmployeeId']:
        manager = find(db, 'Employee', employee['reportsToEmployeeId'], required=False)
        result['managerName'] = full_name(manager) if manager else ''
    photo = details(employee).get('employeePhoto')
    if isinstance(photo, str) and photo:
        result['avatarUrl'] = '/api/uploads/' + photo.lstrip('/')
    today = now().replace(hour=0, minute=0, second=0, microsecond=0)
    attendance = table(db, 'AttendanceRecord')
    records = rows(db, 'AttendanceRecord', attendance.c.employeeId == employee['id'], attendance.c.workDate >= today.date() - timedelta(days=6), attendance.c.workDate <= today.date())
    by_day = {record['workDate']: record for record in records}
    for i in range(7):
        day = today - timedelta(days=i)
        record = by_day.get(day.date())
        check_in = record['checkIn'].strftime('%I:%M %p') if record and record['checkIn'] else None
        check_out = record['checkOut'].strftime('%I:%M %p') if record and record['checkOut'] else None
        # Actual recorded work takes precedence over the default weekend display.
        result['last7'].append({'key': day.date().isoformat(), 'label': day.strftime('%a, %b %d'),
            'status': 'checked' if check_in else 'weekly-off' if day.weekday() >= 5 else 'absent', 'checkIn': check_in, 'checkOut': check_out})
        if i == 0:
            result.update(checkedInToday=bool(check_in), checkInTime=check_in)
    for balance in rows(db, 'LeaveBalance', table(db, 'LeaveBalance').c.employeeId == employee['id'], table(db, 'LeaveBalance').c.year == today.year):
        kind = find(db, 'LeaveType', balance['leaveTypeId'])
        total, remaining = kind['daysPerYear'], float(balance['balanceDays'])
        result['leaveBalances'].append({'type': kind['name'], 'used': max(0, total - remaining), 'total': total,
            'remaining': max(0, remaining), 'color': kind['colorHex'] or '#4A6CF7'})
    tasks = rows(db, 'EmployeeTask', table(db, 'EmployeeTask').c.employeeId == employee['id'])
    leaves = rows(db, 'LeaveRequest', table(db, 'LeaveRequest').c.employeeId == employee['id'])
    result['myTasks'] = sum(task['status'] == 'IN_PROGRESS' for task in tasks)
    result['pendingApprovals'] = sum(leave['status'] == 'PENDING' for leave in leaves)
    result['leaveRequests'] = sum(leave['startDate'].year == today.year for leave in leaves)
    announcements = table(db, 'Announcement')
    for row in rows(db, 'Announcement', announcements.c.isActive.is_(True), announcements.c.publishedAt <= now(), order=announcements.c.publishedAt.desc())[:5]:
        result['announcements'].append({'id': row['id'], 'title': row['title'], 'tag': row['tag'], 'description': row['body'],
            'dept': row['department'] or 'Company', 'date': row['publishedAt'].strftime('%m/%d/%Y')})
    return result
