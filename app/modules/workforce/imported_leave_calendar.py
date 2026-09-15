"""Organization leave calendar, visible only to HR and administrators."""
import re
from datetime import timedelta

from fastapi import Depends, Query
from sqlalchemy import select, func

from app.core.compatibility_routing import APIRouter
from app.data.database import get_db
from app.data.imported import table
from app.modules.workforce.imported_assets import admin, now, rows
from app.modules.workforce.imported_attendance_views import avatar, days_between, display_name, intersect, leave_window, month_bounds, rounded

router = APIRouter(prefix='/api', tags=['HRMS leave calendar'])


def color(kind):
    value = (kind['colorHex'] or '').strip()
    if re.fullmatch(r'#[0-9A-Fa-f]{6}', value):
        return value
    name = kind['name'].lower()
    if any(word in name for word in ('annual', 'vacation', 'pto')):
        return '#3B82F6'
    return '#EF4444' if 'sick' in name else '#7C3AED' if 'personal' in name else '#6366F1'


@router.get('/leave-manager')
def calendar(year: int | None = Query(None, ge=2000, le=2100), month: int | None = Query(None, ge=1, le=12),
             user=Depends(admin), db=Depends(get_db)):
    today = now().date()
    year, month = year or today.year, month or today.month
    start, end = month_bounds(year, month)
    this_start, this_end = month_bounds(today.year, today.month)
    previous = this_start - timedelta(days=1)
    prev_start, prev_end = month_bounds(previous.year, previous.month)
    lo, hi = min(start, this_start, prev_start), max(end, this_end, today + timedelta(days=120))
    employees = {r['id']: r for r in rows(db, 'Employee', table(db, 'Employee').c.status == 'ACTIVE')}
    types = rows(db, 'LeaveType', order=table(db, 'LeaveType').c.name)
    by_type = {r['id']: r for r in types}
    leaves = [r for r in leave_window(db, lo, hi) if r['employeeId'] in employees]
    used = sum(intersect(r['startDate'], r['endDate'], this_start, this_end) for r in leaves)
    prior = sum(intersect(r['startDate'], r['endDate'], prev_start, prev_end) for r in leaves)
    tbl = table(db, 'LeaveBalance')
    remaining = rounded(db.scalar(select(func.sum(tbl.c.balanceDays)).where(tbl.c.year == today.year)) or 0, 1)
    tbl = table(db, 'LeaveRequest')
    pending = db.scalar(select(func.count()).select_from(tbl).where(tbl.c.status == 'PENDING'))
    upcoming = sorted([r for r in leaves if r['startDate'] > today], key=lambda r: (r['startDate'], r['endDate']))
    next_date = upcoming[0]['startDate'] if upcoming else None
    summary = {'daysTaken': used, 'daysTakenDeltaFromLastMonth': used - prior, 'daysRemaining': remaining,
               'daysRemainingLabel': f'{rounded(remaining):g} days in balance pool ({today.year})', 'pendingRequestsCount': pending,
               'upcomingLeavesCount': len(upcoming), 'nextLeaveDate': next_date.isoformat() if next_date else None,
               'nextLeaveLabel': f'{next_date:%b} {next_date.day}' if next_date else None}
    events = {}
    on_leave = []
    for record in leaves:
        employee, kind = employees[record['employeeId']], by_type[record['leaveTypeId']]
        for day in days_between(max(start, record['startDate']), min(end, record['endDate'])):
            events.setdefault(day, []).append({'leaveTypeName': kind['name'], 'colorHex': color(kind), 'label': display_name(employee)[:12]})
        if record['startDate'] <= today <= record['endDate']:
            on_leave.append({'employeeId': employee['id'], 'employeeName': display_name(employee), 'avatarUrl': avatar(employee),
                             'leaveTypeName': kind['name'], 'colorHex': color(kind), 'startDate': record['startDate'].isoformat(),
                             'endDate': record['endDate'].isoformat(), 'durationDays': (record['endDate'] - record['startDate']).days + 1,
                             'reason': record['reason']})
    tbl = table(db, 'PublicHoliday')
    for holiday in rows(db, 'PublicHoliday', tbl.c.date >= start, tbl.c.date <= end, order=tbl.c.date):
        day = holiday['date'].date() if hasattr(holiday['date'], 'hour') else holiday['date']
        events.setdefault(day, []).append({'leaveTypeName': 'Public Holiday', 'colorHex': '#22C55E', 'label': holiday['name'][:14]})
    grid_start = start - timedelta(days=(start.weekday() + 1) % 7)
    weeks = []
    for week in range(6):
        data = []
        for index in range(7):
            day = grid_start + timedelta(days=week * 7 + index)
            inside = day.year == year and day.month == month
            data.append({'date': day.isoformat(), 'dayOfMonth': day.day if inside else None, 'inMonth': inside,
                         'isToday': day == today, 'events': events.get(day, [])})
        weeks.append(data)
    return {'summary': summary, 'calendarTitle': start.strftime('%B %Y'), 'calendarYear': year, 'calendarMonth': month,
            'calendarWeeks': weeks, 'legend': [{'key': t['id'], 'name': t['name'], 'colorHex': color(t)} for t in types] +
            [{'key': 'public_holiday', 'name': 'Public Holidays', 'colorHex': '#22C55E'}],
            'onLeaveToday': sorted(on_leave, key=lambda r: r['employeeName'])}
