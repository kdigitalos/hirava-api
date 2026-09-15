"""Attendance read models over saved imported HRMS records."""
import calendar
import csv
import io
import math
from collections import Counter
from datetime import date, datetime, time, timedelta

from fastapi import Depends, HTTPException, Query, Response
from sqlalchemy import select

from app.core.compatibility_routing import APIRouter
from app.data.database import get_db
from app.data.imported import dto, find, table
from app.modules.workforce.imported_assets import admin, now, rows
from app.modules.workforce.imported_attendance import Punch, calendar_date, punch
from app.modules.workforce.imported_leave import employee_id, output, staff

router = APIRouter(prefix='/api', tags=['HRMS attendance views'])


def rounded(value, digits=0):
    return math.floor(value * 10 ** digits + 0.5) / 10 ** digits


def month_bounds(year, month):
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def days_between(start, end):
    return (start + timedelta(days=offset) for offset in range(max(0, (end - start).days + 1)))


def intersect(start, end, lo, hi):
    return max(0, (min(end, hi) - max(start, lo)).days + 1)


def nice_date(value):
    return f'{value:%b} {value.day}, {value.year}'


def display_time(value):
    # Explicit UTC avoids the old server-local timezone changing between deployments.
    return value.strftime('%I:%M %p').lstrip('0') + ' UTC' if value else None


def late(record):
    return bool(record and record['checkIn'] and record['checkIn'] > datetime.combine(record['workDate'], time(9, 30)))


def display_name(employee):
    return ' '.join(filter(None, (employee['firstName'], employee['lastName']))).strip() or '—'


def avatar(employee):
    details = employee.get('employeeDetails')
    path = details.get('employeePhoto') if isinstance(details, dict) else None
    return '/api/uploads/' + path.lstrip('/') if isinstance(path, str) and path else None


def attendance_window(db, owner, start, end):
    tbl = table(db, 'AttendanceRecord')
    criteria = [tbl.c.workDate >= start, tbl.c.workDate <= end]
    if owner:
        criteria.append(tbl.c.employeeId == owner)
    return rows(db, 'AttendanceRecord', *criteria, order=tbl.c.workDate.desc())


def leave_window(db, start, end, owner=None):
    tbl = table(db, 'LeaveRequest')
    criteria = [tbl.c.status == 'APPROVED', tbl.c.startDate <= end, tbl.c.endDate >= start]
    if owner:
        criteria.append(tbl.c.employeeId == owner)
    return rows(db, 'LeaveRequest', *criteria)


def day_status(employee_id, record, on_leave):
    if employee_id in on_leave:
        return 'ON_LEAVE'
    if not record or not record['checkIn']:
        return 'ABSENT'
    return 'LATE' if late(record) else 'PRESENT'


@router.get('/attendance-tracker')
def tracker(workDate: str = '', departmentId: str = '', status: str = 'all', q: str = Query('', max_length=200),
            take: int = Query(200, ge=1, le=500), format: str = '', user=Depends(admin), db=Depends(get_db)):
    day = calendar_date(workDate) if workDate else now().date()
    employees = rows(db, 'Employee', table(db, 'Employee').c.status == 'ACTIVE')
    records = {record['employeeId']: record for record in attendance_window(db, None, day, day)}
    on_leave = {record['employeeId'] for record in leave_window(db, day, day)}
    states = {employee['id']: day_status(employee['id'], records.get(employee['id']), on_leave) for employee in employees}
    counts = Counter(states.values())
    departments = rows(db, 'Department', order=table(db, 'Department').c.name)
    department_names = {item['id']: item['name'] for item in departments}
    selected = [employee for employee in employees if (not departmentId or employee['departmentId'] == departmentId)
                and (not q.strip() or any(q.strip().casefold() in str(employee[key] or '').casefold() for key in ('firstName', 'lastName', 'employeeCode')))]
    selected.sort(key=lambda e: (e['lastName'] or '', e['firstName'] or ''))
    filter_status = status.upper().replace('ONLEAVE', 'ON_LEAVE')
    data = []
    for employee in selected[:take]:
        state = states[employee['id']]
        if filter_status in ('PRESENT', 'LATE', 'ABSENT', 'ON_LEAVE') and filter_status != state:
            continue
        record = records.get(employee['id']) or {}
        start, end = record.get('checkIn'), record.get('checkOut')
        hours = rounded(max(0, (end - start).total_seconds() / 3600), 1) if start and end else None
        data.append({'employeeId': employee['id'], 'employeeName': display_name(employee), 'department': department_names.get(employee['departmentId'], '—'),
                     'recordId': record.get('id'), 'checkIn': display_time(start), 'checkOut': display_time(end),
                     'totalHours': f'{hours:g}h' if hours is not None else None, 'status': state, 'avatarUrl': avatar(employee)})
    if format == 'csv':
        stream = io.StringIO(newline='')
        writer = csv.writer(stream)
        writer.writerow(['Employee Name', 'Department', 'Check in', 'Check out', 'Total Hours', 'Status'])
        for record in data:
            # Quoting alone does not prevent spreadsheet formula execution.
            values = [record[key] or '' for key in ('employeeName', 'department', 'checkIn', 'checkOut', 'totalHours', 'status')]
            writer.writerow(["'" + value if value.lstrip().startswith(('=', '+', '-', '@')) else value for value in values])
        return Response(stream.getvalue(), media_type='text/csv', headers={'Content-Disposition': f'attachment; filename="attendance-{day.isoformat()}.csv"'})
    return {'workDate': day.isoformat(), 'stats': {'presentToday': f"{counts['PRESENT'] + counts['LATE']}/{len(employees)}",
            'lateArrivals': counts['LATE'], 'absent': counts['ABSENT'], 'onLeave': counts['ON_LEAVE']}, 'rows': data,
            'departments': [{key: item[key] for key in ('id', 'name')} for item in departments]}


@router.post('/attendance-tracker')
def tracker_punch(body: Punch, user=Depends(admin), db=Depends(get_db)):
    return punch(body, user, db)


@router.get('/attendance-policy-stats')
def policy_stats(user=Depends(admin), db=Depends(get_db)):
    today = now().date()
    active = rows(db, 'Employee', table(db, 'Employee').c.status == 'ACTIVE')
    records = [r for r in attendance_window(db, None, today, today) if r['checkIn']]
    leave_tbl = table(db, 'LeaveRequest')
    leaves = rows(db, 'LeaveRequest')
    balances = rows(db, 'LeaveBalance')
    shifts = rows(db, 'EmployeeShift', table(db, 'EmployeeShift').c.shiftDate == today)
    policies = rows(db, 'AttendancePolicy', table(db, 'AttendancePolicy').c.category == 'LEAVE_TYPE')
    used = sum(intersect(r['startDate'], r['endDate'], date(today.year, 1, 1), r['endDate']) for r in leaves if r['status'] == 'APPROVED')
    shift_counts = Counter(r['shiftType'] for r in shifts)
    return {'kpi': {'presentToday': f"{len({r['employeeId'] for r in records})}/{len(active)}",
                   'onLeave': sum(r['status'] == 'APPROVED' and r['startDate'] <= today <= r['endDate'] for r in leaves),
                   'lateArrivals': sum(late(r) for r in records), 'pendingRequests': sum(r['status'] == 'PENDING' for r in leaves)},
            'leaveSidebar': {'activeCount': sum(p['status'] == 'ACTIVE' for p in policies), 'inactiveCount': sum(p['status'] == 'INACTIVE' for p in policies),
                             'totalEntitlementDays': sum(p['config'].get('days', 0) for p in policies if p['status'] == 'ACTIVE' and isinstance(p['config'], dict) and type(p['config'].get('days', 0)) in (int, float))},
            'shiftSidebar': {key: rounded(100 * shift_counts[kind] / len(shifts)) if shifts else 0 for key, kind in [('dayPct', 'MORNING'), ('eveningPct', 'EVENING'), ('nightPct', 'NIGHT')]},
            'entitlementSidebar': {'activeEmployees': len(active), 'leaveDaysUsed': used, 'totalLeaveDays': max(used, used + rounded(sum(b['balanceDays'] for b in balances)))}}


def own_logs(db, owner, days):
    today = now().date()
    records = {r['workDate']: r for r in attendance_window(db, owner, today - timedelta(days=days - 1), today)}
    data = []
    for offset in range(days):
        day = today - timedelta(days=offset)
        if day.weekday() >= 5:
            continue
        record = records.get(day) or {}
        data.append({'id': record.get('id', day.isoformat()), 'date': nice_date(day), 'day': day.strftime('%A'),
                     'checkIn': display_time(record.get('checkIn')) or '—', 'checkOut': display_time(record.get('checkOut')) or '—',
                     'status': 'Absent' if not record.get('checkIn') else 'Late' if late(record) else 'Present'})
    return data


@router.get('/leave-attendance/logs')
def self_logs(days: int = Query(30, ge=7, le=120), user=Depends(staff), db=Depends(get_db)):
    owner = employee_id(db, user)
    return {'logs': own_logs(db, owner, days) if owner else []}


@router.get('/leave-attendance/overview')
def self_overview(user=Depends(staff), db=Depends(get_db)):
    owner = employee_id(db, user)
    if not owner:
        raise HTTPException(404, 'No employee record linked to your account')
    today = now().date()
    start, end = month_bounds(today.year, today.month)
    records = attendance_window(db, owner, start, end)
    leaves = leave_window(db, start, end, owner)
    tbl = table(db, 'EmployeeShift')
    shifts = db.execute(select(tbl).where(tbl.c.employeeId == owner, tbl.c.shiftDate >= today).order_by(tbl.c.shiftDate).limit(7)).mappings()
    return {'stats': {'totalWorkingDays': sum(day.weekday() < 5 for day in days_between(start, end)),
            'daysPresent': sum(bool(r['checkIn']) for r in records), 'lateOrEarly': sum(late(r) for r in records),
            'leavesTaken': sum(intersect(r['startDate'], r['endDate'], start, end) for r in leaves)},
            'upcomingShifts': [{'id': r['id'], 'date': nice_date(r['shiftDate']), 'day': r['shiftDate'].strftime('%A'),
                                'shiftType': r['shiftType'].title(), 'checkIn': r['startLabel'], 'checkOut': r['endLabel'], 'location': r['location'] or '—'} for r in shifts],
            'recentAttendance': own_logs(db, owner, 14)[:5]}


def activity_when(instant):
    if not instant:
        return None
    delta = (now().date() - instant.date()).days
    label = 'Today' if delta == 0 else 'Yesterday' if delta == 1 else nice_date(instant)
    return label + ' ' + display_time(instant)


@router.get('/employees/{id}/attendance')
def employee_attendance(id: str, period: str = 'yearly', year: int | None = Query(None, ge=2000, le=2100),
                        month: int | None = Query(None, ge=1, le=12), user=Depends(admin), db=Depends(get_db)):
    find(db, 'Employee', id)
    today = now().date()
    year = year or today.year
    monthly = period == 'monthly'
    month = (month or today.month) if monthly else None
    start, end = month_bounds(year, month) if monthly else (date(year, 1, 1), date(year, 12, 31))
    records = attendance_window(db, id, start, end)
    by_day = {r['workDate']: r for r in records}
    leaves = leave_window(db, start, end, id)
    present = absent = on_leave = working = 0
    for day in days_between(start, min(today, end)):
        if day.weekday() >= 5:
            continue
        working += 1
        if any(r['startDate'] <= day <= r['endDate'] for r in leaves):
            on_leave += 1
        elif by_day.get(day, {}).get('checkIn'):
            present += 1
        else:
            absent += 1
    balances = rows(db, 'LeaveBalance', table(db, 'LeaveBalance').c.employeeId == id, table(db, 'LeaveBalance').c.year == year)
    summary = []
    for balance in balances:
        kind = find(db, 'LeaveType', balance['leaveTypeId'])
        cap = kind['daysPerYear']
        summary.append({'label': kind['name'], 'used': min(cap, max(0, rounded(cap - balance['balanceDays']))) if cap and cap > 0 else 0,
                        'total': cap if cap and cap > 0 else max(1, rounded(balance['balanceDays']))})
    summary.sort(key=lambda s: s['label'])
    all_leaves = rows(db, 'LeaveRequest', table(db, 'LeaveRequest').c.employeeId == id, table(db, 'LeaveRequest').c.status == 'APPROVED')
    latest = max(all_leaves, key=lambda r: r['endDate']) if all_leaves else None
    recent = None if not latest else nice_date(latest['startDate']) + ('–' + nice_date(latest['endDate']) if latest['endDate'] != latest['startDate'] else '')
    return {'employeeId': id, 'period': 'monthly' if monthly else 'yearly', 'periodLabel': start.strftime('%B %Y') if monthly else str(year), 'year': year, 'month': month,
            'overview': {'attendanceRatePercent': rounded(100 * present / (present + absent)) if present + absent else 0, 'presentDays': present,
                         'absentDays': absent, 'onLeaveDays': on_leave, 'workingDaysInPeriod': working},
            'leaveSummary': summary[:6], 'recentActivity': {'lastCheckIn': activity_when(max((r['checkIn'] for r in records if r['checkIn']), default=None)),
            'lastCheckOut': activity_when(max((r['checkOut'] for r in records if r['checkOut']), default=None)), 'recentLeave': recent}}


@router.get('/admin/attendance-records')
def admin_records(date: str = '', limit: int = Query(4, ge=1, le=200), user=Depends(admin), db=Depends(get_db)):
    selected = calendar_date(date) if date else None
    tbl = table(db, 'AttendanceRecord')
    query = select(tbl).order_by(tbl.c.workDate.desc(), tbl.c.id.desc()).limit(limit)
    if selected:
        query = query.where(tbl.c.workDate == selected)
    data = []
    colors = ['#f59e0b', '#475569', '#f43f5e', '#ec4899', '#8b5cf6', '#3b82f6']
    for index, row in enumerate(db.execute(query).mappings()):
        record = dto(tbl, row)
        employee = find(db, 'Employee', record['employeeId'])
        data.append({'id': record['id'], 'name': display_name(employee), 'checkIn': display_time(record['checkIn']) or '—',
                     'checkOut': display_time(record['checkOut']) or '—', 'date': nice_date(record['workDate']),
                     'status': '—' if not record['checkIn'] else 'Late' if late(record) else 'On time',
                     'initials': ((employee['firstName'] or '')[:1] + (employee['lastName'] or '')[:1]).upper() or '?',
                     'bg': colors[(index + 2) % len(colors)], 'workDateIso': output(record['workDate'])})
    return {'rows': data, 'selectedDate': selected.isoformat() if selected else None}
