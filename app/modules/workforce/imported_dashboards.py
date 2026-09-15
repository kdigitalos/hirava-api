"""HR dashboards computed from saved imported records, without GET side effects."""
from collections import Counter
from datetime import date, datetime, timedelta
from math import isfinite

from fastapi import Depends, HTTPException

from app.core.compatibility_routing import APIRouter
from app.core.imported_identity import linked_employee
from app.data.database import get_db
from app.data.imported import table
from app.modules.workforce.imported_assets import admin, now, rows
from app.modules.workforce.imported_employee_profile import full_name
from app.modules.workforce.imported_leave import output, staff
from app.modules.workforce.imported_settlements import display_inr

router = APIRouter(prefix='/api', tags=['HRMS dashboards'])
ACTIVE = ('ACTIVE', 'ON_LEAVE', 'PROBATION')
OPEN_EXIT = ('PENDING', 'PENDING_HR', 'APPROVED', 'IN_PROGRESS')
COLORS = ('#4338ca', '#818cf8', '#a5b4fc', '#c4b5fd', '#94a3b8')
AVATARS = ('#f59e0b', '#475569', '#f43f5e', '#ec4899', '#8b5cf6', '#3b82f6')


def day(value):
    return value.date() if isinstance(value, datetime) else value


def month_offset(value, offset):
    total = value.year * 12 + value.month - 1 + offset
    return date(total // 12, total % 12 + 1, 1)


def avatar(employee, index=0):
    return {'initials': ((employee.get('firstName') or '')[:1] + (employee.get('lastName') or '')[:1]).upper() or '?',
        'bg': AVATARS[index % len(AVATARS)]}


def lookup(db, model):
    return {item['id']: item for item in rows(db, model)}


def role_name(employee, titles, designations):
    return titles.get(employee['jobTitleId'], {}).get('name') or designations.get(employee['designationId'], {}).get('title') or '—'


def numeric_pay(employee, field):
    payroll = employee.get('payrollJson')
    value = payroll.get(field) if isinstance(payroll, dict) else None
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value) else None


@router.get('/admin/dashboard')
def admin_dashboard(user=Depends(admin), db=Depends(get_db)):
    employees = rows(db, 'Employee', order=table(db, 'Employee').c.createdAt.desc())
    people = {person['id']: person for person in employees}
    departments, titles, designations = lookup(db, 'Department'), lookup(db, 'JobTitle'), lookup(db, 'Designation')
    today = now().date()
    d30, d60 = today - timedelta(days=30), today - timedelta(days=60)
    active = [employee for employee in employees if employee['status'] in ACTIVE]
    def count(field, start, end, terminated=False):
        return sum(employee[field] is not None and start <= day(employee[field]) < end and
            (not terminated or employee['status'] == 'TERMINATED') for employee in employees)
    hires, previous = count('hireDate', d30, today + timedelta(days=1)), count('hireDate', d60, d30)
    exits, previous_exits = count('terminationDate', d30, today + timedelta(days=1), True), count('terminationDate', d60, d30, True)
    pending = sum(row['status'] == 'PENDING' for row in rows(db, 'LeaveRequest'))
    pending += sum(row['status'] in ('PENDING', 'PENDING_HR') and not row['isDraft'] for row in rows(db, 'ExitRequest'))
    pending += sum(row['status'] == 'PENDING' for row in rows(db, 'EmployeeDocument'))
    headcounts = Counter(departments.get(employee['departmentId'], {}).get('name', 'Unassigned') for employee in active)
    title_counts = Counter(titles.get(employee['jobTitleId'], {}).get('name', 'Unassigned') for employee in active).most_common()
    mix = [{'label': label, 'value': value, 'color': COLORS[index]} for index, (label, value) in enumerate(title_counts[:4])]
    if len(title_counts) > 4:
        mix.append({'label': 'Other', 'value': sum(value for _, value in title_counts[4:]), 'color': COLORS[4]})
    def series(months, uppercase=False):
        return {'monthLabels': [month.strftime('%b').upper() if uppercase else month.strftime('%b') for month in months],
            'hires': [count('hireDate', month, month_offset(month, 1)) for month in months],
            'exits': [count('terminationDate', month, month_offset(month, 1), True) for month in months]}
    employee_items, payroll = [], []
    for index, employee in enumerate(employees[:100]):
        manager = people.get(employee['reportsToEmployeeId'])
        employee_items.append({'recordId': employee['id'], 'id': employee['employeeCode'], 'employeeCode': employee['employeeCode'],
            'name': full_name(employee), 'role': role_name(employee, titles, designations), 'lead': full_name(manager) if manager else '—',
            'status': employee['status'], **avatar(employee, index)})
        if index < 4:
            gross = numeric_pay(employee, 'grossSalary')
            # Compensation metadata cannot establish that a payroll payment occurred.
            payroll.append({'name': full_name(employee), 'position': role_name(employee, titles, designations),
                'salary': display_inr(round(gross * 100)) if gross is not None else '—', 'status': 'Pending',
                'paymentVerified': False, **avatar(employee, index)})
    records = rows(db, 'AttendanceRecord', order=table(db, 'AttendanceRecord').c.workDate.desc())[:4]
    attendance = []
    for index, record in enumerate(records):
        employee = people.get(record['employeeId'])
        if not employee:
            continue
        checkin = record['checkIn']
        attendance.append({'name': full_name(employee),
            'checkIn': checkin.strftime('%I:%M %p UTC') if checkin else '—',
            'checkOut': record['checkOut'].strftime('%I:%M %p UTC') if record['checkOut'] else '—',
            'date': day(record['workDate']).strftime('%d %b %Y'),
            'status': ('Late' if (checkin.hour, checkin.minute) > (9, 30) else 'On time') if checkin else '—', **avatar(employee, index + 2)})
    return {'summary': {'totalEmployees': len(active), 'newHires30d': hires,
        'newHiresChangePercent': (hires - previous) / previous * 100 if previous else None if hires else 0,
        'pendingApprovals': pending, 'attritionRate30dPercent': round(exits / len(active) * 100, 1) if active else 0,
        'attritionChangePercentPoints': round((exits - previous_exits) / len(active) * 100, 1) if active and (exits or previous_exits) else None},
        'departmentHeadcount': [{'name': label, 'count': value} for label, value in headcounts.most_common()],
        'attritionTrend': series([month_offset(today, offset) for offset in range(-11, 1)]),
        'hiringExitsYear': {'year': today.year, **series([date(today.year, month, 1) for month in range(1, 13)], True)},
        'jobTitleMix': mix, 'employees': employee_items, 'payroll': payroll, 'attendance': attendance}


@router.get('/admin/exit-dashboard')
def exit_dashboard(period: str = 'month', user=Depends(admin), db=Depends(get_db)):
    today = now().date()
    kind = period if period in ('quarter', 'year') else 'month'
    start = date(today.year, 1 if kind == 'year' else ((today.month - 1) // 3) * 3 + 1 if kind == 'quarter' else today.month, 1)
    end = month_offset(start, 12 if kind == 'year' else 3 if kind == 'quarter' else 1)
    items = [row for row in rows(db, 'ExitRequest', order=table(db, 'ExitRequest').c.createdAt.desc())
        if start <= day(row['createdAt']) < end and row['status'] != 'REJECTED' and not row['isDraft']]
    counts = Counter((row['reason'] or '').strip() or 'Not specified' for row in items).most_common()
    top = counts[:7]
    if len(counts) > 7:
        top.append(('Other', sum(count for _, count in counts[7:])))
    raw = [count / len(items) * 100 for _, count in top] if items else []
    percentages = [int(value) for value in raw]
    for index in sorted(range(len(raw)), key=lambda i: raw[i] - percentages[i], reverse=True)[:100 - sum(percentages)]:
        percentages[index] += 1
    people, departments = lookup(db, 'Employee'), lookup(db, 'Department')
    recent = []
    for row in [row for row in items if row['status'] in OPEN_EXIT][:5]:
        employee = people[row['employeeId']]
        recent.append({'id': row['id'], 'name': full_name(employee),
            'department': departments.get(employee['departmentId'], {}).get('name') or row['departmentEntered'] or '—',
            'exitDateIso': row['lastWorkingDate'], 'initials': avatar(employee)['initials'],
            'status': 'Pending Approval' if row['status'] in ('PENDING', 'PENDING_HR') else 'Clearance In Progress' if row['status'] == 'APPROVED' else 'F&F Pending'})
    return output({'period': {'kind': kind, 'startIso': datetime.combine(start, datetime.min.time()),
        'endIso': datetime.combine(end, datetime.min.time()) - timedelta(milliseconds=1)},
        'stats': {'totalExits': len(items), 'upcomingExits': sum(row['lastWorkingDate'] is not None and day(row['lastWorkingDate']) >= today and row['status'] != 'COMPLETED' for row in items),
            'pendingApprovals': sum(row['status'] in ('PENDING', 'PENDING_HR') for row in items),
            'clearancePending': sum(row['status'] == 'APPROVED' for row in items), 'fnfPending': sum(row['status'] == 'IN_PROGRESS' for row in items)},
        'reasons': [{'label': label, 'count': count, 'pct': percentages[index], 'color': COLORS[index % len(COLORS)]} for index, (label, count) in enumerate(top)],
        'recentRequests': recent})


@router.get('/employee-self-service/dashboard')
def self_dashboard(user=Depends(staff), db=Depends(get_db)):
    employee = linked_employee(db, user, required=True)
    people, titles, designations = lookup(db, 'Employee'), lookup(db, 'JobTitle'), lookup(db, 'Designation')
    departments, leave_types = lookup(db, 'Department'), lookup(db, 'LeaveType')
    today = now().date()
    tickets = rows(db, 'SupportTicket', table(db, 'SupportTicket').c.employeeId == employee['id'])
    for ticket in tickets:
        ticket['status'] = ticket['status'].strip().upper().replace(' ', '_')
    balances = rows(db, 'LeaveBalance', table(db, 'LeaveBalance').c.employeeId == employee['id'], table(db, 'LeaveBalance').c.year == today.year)
    leaves = []
    for index, balance in enumerate(sorted(balances, key=lambda row: leave_types[row['leaveTypeId']]['name'])):
        leave_type = leave_types[balance['leaveTypeId']]
        cap = leave_type['daysPerYear']
        leaves.append({'label': leave_type['name'], 'used': min(cap, max(0, cap - balance['balanceDays'])) if cap and cap > 0 else 0,
            'total': cap if cap and cap > 0 else max(balance['balanceDays'], 1), 'color': COLORS[index % len(COLORS)]})
    manager = people.get(employee['reportsToEmployeeId'])
    net = numeric_pay(employee, 'netPay')
    team = [{'id': person['id'], 'name': full_name(person), 'role': role_name(person, titles, designations),
        'status': {'ON_LEAVE': 'On leave', 'ACTIVE': 'Active', 'PROBATION': 'Active', 'TERMINATED': 'Terminated'}.get(person['status'], person['status'].replace('_', ' ')),
        **avatar(person, index)} for index, person in enumerate(sorted((person for person in people.values() if person['reportsToEmployeeId'] == employee['id']), key=lambda person: person['lastName'] or '')[:30])]
    holidays = rows(db, 'PublicHoliday', table(db, 'PublicHoliday').c.date >= today, order=table(db, 'PublicHoliday').c.date)[:5]
    approved = rows(db, 'LeaveRequest', table(db, 'LeaveRequest').c.status == 'APPROVED',
        table(db, 'LeaveRequest').c.startDate <= today, table(db, 'LeaveRequest').c.endDate >= today,
        table(db, 'LeaveRequest').c.employeeId != employee['id'], order=table(db, 'LeaveRequest').c.startDate)[:12]
    whos_out = []
    for index, leave in enumerate(approved):
        person = people[leave['employeeId']]
        start, end = day(leave['startDate']).strftime('%d %b'), day(leave['endDate']).strftime('%d %b')
        whos_out.append({'name': full_name(person), 'leaveType': leave_types[leave['leaveTypeId']]['name'],
            'dates': start if start == end else start + ' – ' + end, **avatar(person, index)})
    return {'profile': {'firstName': employee['firstName'], 'displayName': full_name(employee),
        'jobTitle': role_name(employee, titles, designations), 'department': departments.get(employee['departmentId'], {}).get('name', '—'),
        'manager': full_name(manager) if manager else '—'},
        'tasks': {'total': sum(ticket['status'] != 'CLOSED' for ticket in tickets), 'pending': sum(ticket['status'] in ('OPEN', 'IN_PROGRESS') for ticket in tickets)},
        'leaveBalances': leaves, 'payslip': {'amountInr': display_inr(round(net * 100)), 'periodLabel': 'Recorded compensation', 'hasDownload': False} if net is not None else None,
        'team': team, 'reminders': [{'title': holiday['name'], 'subtitle': holiday['date'].strftime('%B %Y')} for holiday in holidays], 'whosOut': whos_out}


@router.post('/admin/onboarding-dashboard')
def dashboard_action(user=Depends(admin)):
    raise HTTPException(409, 'Open the candidate or probation record to review and complete its workflow.')


@router.get('/admin/onboarding-dashboard')
def onboarding_dashboard(team: str = '', location: str = '', status: str = '', owner: str = '', dateRange: str = '',
                         user=Depends(admin), db=Depends(get_db)):
    today = now().date()
    status = status.strip().lower()
    starts = {'today': today, '7d': today - timedelta(days=7), '30d': today - timedelta(days=30),
        '90d': today - timedelta(days=90), 'this-month': today.replace(day=1),
        'this-quarter': date(today.year, (today.month - 1) // 3 * 3 + 1, 1), 'this-year': date(today.year, 1, 1)}
    start = starts.get(dateRange.strip().lower())
    groups, people, departments = lookup(db, 'OnboardingGroup'), lookup(db, 'Employee'), lookup(db, 'Department')
    candidates = rows(db, 'OnboardingCandidate', order=table(db, 'OnboardingCandidate').c.updatedAt.desc())
    probation = rows(db, 'ProbationRecord')
    def in_range(row):
        return not start or day(row['createdAt']) >= start
    def matches_group(group):
        return all(not value.strip() or value.strip().casefold() in (group.get(field) or '').casefold()
            for field, value in (('department', team), ('location', location), ('manager', owner)))
    group_status = {'draft': 'DRAFT', 'not-started': 'DRAFT', 'pending-approval': 'CONVERSION_PENDING', 'archived': 'ARCHIVED', 'completed': 'ARCHIVED'}.get(status, 'ACTIVE')
    candidate_status = {'invited': 'INVITED', 'pending-approval': 'INVITED', 'not-started': 'INVITED', 'completed': 'COMPLETED', 'withdrawn': 'WITHDRAWN', 'rejected': 'WITHDRAWN'}.get(status, 'IN_PROGRESS')
    exit_status = {'completed': ('COMPLETED',), 'rejected': ('REJECTED',), 'approved': ('APPROVED',),
        'pending': ('PENDING', 'PENDING_HR'), 'pending-approval': ('PENDING', 'PENDING_HR'), 'in-progress': ('IN_PROGRESS',), 'not-started': ('PENDING',)}.get(status, OPEN_EXIT)
    selected_groups = [group for group in groups.values() if group['name'] != '__hirava_candidates_page__' and group['status'] == group_status and matches_group(group) and in_range(group)]
    selected_candidates = [candidate for candidate in candidates if candidate['status'] == candidate_status and matches_group(groups.get(candidate['groupId'], {})) and in_range(candidate)]
    exits = [row for row in rows(db, 'ExitRequest', order=table(db, 'ExitRequest').c.createdAt.desc()) if row['status'] in exit_status and not row['isDraft'] and in_range(row)]
    active_probation = [record for record in probation if record['status'] in ('ACTIVE_PROBATION', 'EXTENDED')]
    stuck = sum(candidate['status'] == 'IN_PROGRESS' and bool(groups.get(candidate['groupId'], {}).get('windowEnd')) and
        day(groups[candidate['groupId']]['windowEnd']) < today and matches_group(groups[candidate['groupId']]) for candidate in candidates)
    def formatted(value):
        return f'{value:%b} {value.day}, {value.year}' if value else '—'
    group_items = []
    for group in sorted(selected_groups, key=lambda row: day(row['windowStart']) if row['windowStart'] else date.min, reverse=True)[:24]:
        members = [candidate for candidate in candidates if candidate['groupId'] == group['id']]
        progress = group['progressPercent']
        if progress is None:
            progress = int(sum(candidate['status'] == 'COMPLETED' for candidate in members) / len(members) * 100 + .5) if members else 0
        group_items.append({'id': group['id'], 'name': group['name'], 'department': group['department'] or '',
            'location': group['location'] or '', 'manager': group['manager'] or '', 'members': len(members),
            'start': formatted(group['windowStart']), 'status': group['status'].replace('_', ' ').title(), 'progress': progress})
    exit_items = []
    for row in exits[:24]:
        person = people[row['employeeId']]
        manager = people.get(person['reportsToEmployeeId'])
        exit_items.append({'id': row['id'], 'name': 'Exit — ' + full_name(person),
            'department': row['departmentEntered'] or departments.get(person['departmentId'], {}).get('name', ''),
            'manager': row['managerEntered'] or (full_name(manager) if manager else ''), 'members': 1,
            'start': formatted(row['createdAt']), 'status': row['status'].replace('_', ' ').title(),
            'progress': {'PENDING': 25, 'PENDING_HR': 40, 'APPROVED': 60, 'IN_PROGRESS': 80, 'COMPLETED': 100}.get(row['status'], 10)})
    tasks = [{'id': 'probation-' + record['id'], 'title': 'Probation review: ' + full_name(people[record['employeeId']]),
        'group': 'Probation', 'assignee': 'HR', 'date': formatted(record['probationEnd']),
        'status': 'pending' if day(record['probationEnd']) < today else 'in-progress'}
        for record in sorted(active_probation, key=lambda row: row['probationEnd']) if day(record['probationEnd']) <= today + timedelta(days=14)][:6]
    candidate_items = []
    for index, candidate in enumerate(selected_candidates[:8]):
        group = groups[candidate['groupId']]
        label = 'Standalone' if group['name'] == '__hirava_candidates_page__' else group['name']
        if index < 4:
            tasks.append({'id': 'candidate-' + candidate['id'], 'title': 'Onboarding: ' + candidate['name'],
                'group': label, 'assignee': 'HR', 'date': formatted(candidate['updatedAt']), 'status': 'in-progress'})
        candidate_items.append({'id': candidate['id'], 'name': candidate['name'], 'role': candidate['roleLabel'] or label,
            'stage': 'Current: ' + label, 'progress': {'INVITED': 20, 'IN_PROGRESS': 55, 'COMPLETED': 100}.get(candidate['status'], 0),
            'start': formatted(candidate['createdAt']), 'location': group['location'] or label,
            'atRisk': bool(group['windowEnd'] and day(group['windowEnd']) < today)})
    return {'stats': {'activeGroups': len(selected_groups), 'candidatesInProgress': len(selected_candidates),
        'openOffboardingCases': len(exits), 'tasksOverdue': stuck + sum(day(record['probationEnd']) < today for record in active_probation),
        'employeesInProbation': sum(day(record['probationStart']) <= today <= day(record['probationEnd']) for record in active_probation)},
        'onboardingGroups': group_items, 'offboardingCases': exit_items, 'todaysTasks': tasks[:8], 'candidatesInProgressList': candidate_items}
