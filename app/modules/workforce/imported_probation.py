"""Probation records, independent decisions and saved review evidence."""
from calendar import monthrange
from datetime import date, timedelta
from typing import Literal
from uuid import uuid4

from fastapi import Depends, HTTPException
from pydantic import Field
from sqlalchemy import select

from app.core.compatibility_routing import APIRouter
from app.core.imported_identity import linked_employee
from app.data.database import get_db
from app.data.imported import find, table
from app.modules.workforce.imported_assets import admin, insert, now, rows
from app.modules.workforce.imported_attendance import calendar_date
from app.modules.workforce.imported_employee_profile import details, full_name
from app.modules.workforce.imported_leave import Input, output
from app.modules.workforce.imported_onboarding import onboarding_lock
from app.modules.workforce.imported_organization import update
from app.modules.workforce.imported_shared import bridge_user

router = APIRouter(prefix='/api', tags=['HRMS probation'])


def formatted(day):
    return f'{day.day} {day:%b %Y}'


def json_items(value):
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def probation_payload(db, record, full=False):
    employee = find(db, 'Employee', record['employeeId'])
    department = find(db, 'Department', employee['departmentId'], required=False)
    days = (record['probationEnd'] - now().date()).days
    confirmed = record['status'] == 'CONFIRMED'
    status = 'Confirmed' if confirmed else 'Overdue' if days < 0 else 'Extended' if record['extensions'] or record['status'] == 'EXTENDED' else 'Active Probation'
    metadata = details(employee)
    photo = metadata.get('employeePhoto')
    linked_user = find(db, 'User', employee['userId'], required=False)
    avatar = (photo if photo.startswith(('https://', 'http://')) else '/api/uploads/' + photo.lstrip('/')) if isinstance(photo, str) and photo else (linked_user or {}).get('picture')
    result = {'id': record['id'], 'name': full_name(employee), 'empId': employee['employeeCode'],
        'initials': (employee['firstName'][:1] + employee['lastName'][:1]).upper() or '?',
        'avatarColor': 'bg-indigo-200 text-indigo-700', 'avatarPhoto': avatar,
        'location': metadata.get('location') or employee['workLocation'] or '—', 'department': (department or {}).get('name') or '—',
        'reportingManager': record['reportingManager'], **{key: formatted(record[key]) for key in ('joiningDate', 'probationStart', 'probationEnd')},
        'extensions': record['extensions'], 'status': status, 'daysRemaining': 'completed' if confirmed else days, 'confirmedAt': record['confirmedAt']}
    if not full:
        return result
    title = find(db, 'JobTitle', employee['jobTitleId'], required=False)
    result['role'] = (title or {}).get('name') or '—'
    start, end = record['probationStart'], record['probationEnd']
    result['durationMonths'] = max(1, (end.year - start.year) * 12 + end.month - start.month)
    reviews = []
    for item in json_items(record['reviewsJson']):
        try:
            review_date = calendar_date(item.get('date', ''))
        except (HTTPException, TypeError):
            review_date = None
        reviews.append({**item, 'id': item.get('id') or f'rev-{len(reviews)}', 'title': item.get('title') or 'Review',
            'date': formatted(review_date) if review_date else '—', 'dateSort': review_date.isoformat() if review_date else '1970-01-01',
            'status': item.get('status') or 'Pending', 'description': item.get('description') or '', 'reviewedBy': item.get('reviewedBy') or ''})
    result['reviews'] = sorted(reviews, key=lambda item: item['dateSort'])
    extensions = []
    for item in json_items(record['extensionEventsJson']):
        try:
            event_day = calendar_date(item.get('date', ''))
        except (HTTPException, TypeError):
            event_day = None
        extensions.append({**item, 'date': formatted(event_day) if event_day else '—'})
    result['extensionHistory'] = extensions
    mid = start + (end - start) // 2
    final = end - timedelta(days=14)
    if final < start:
        final = mid + (end - mid) // 2
    milestones = [('Joining Date', record['joiningDate']), ('Probation Start', start), ('Mid Review', mid), ('Final Review', final), ('Confirmation', end)]
    # Review completion requires saved evidence; crossing a date is not a review.
    completed = [now().date() >= record['joiningDate'], now().date() >= start,
        any('mid' in r['title'].lower() and r['status'] == 'Completed' for r in reviews),
        any('final' in r['title'].lower() and r['status'] == 'Completed' for r in reviews), confirmed]
    current = next((index for index, value in enumerate(completed) if not value), len(completed))
    result['timeline'] = [{'id': f's{index + 1}', 'label': label, 'date': formatted(day),
        'state': 'completed' if completed[index] else 'current' if index == current else 'upcoming'} for index, (label, day) in enumerate(milestones)]
    return result


@router.get('/probation-records')
def probation_records(user=Depends(admin), db=Depends(get_db)):
    return output([probation_payload(db, item) for item in rows(db, 'ProbationRecord', order=table(db, 'ProbationRecord').c.probationEnd)])


class ProbationInput(Input):
    employeeId: str = Field(min_length=1, max_length=255)
    reportingManager: str = Field(min_length=1, max_length=1000)
    joiningDate: str
    probationStart: str
    probationEnd: str
    extensions: int = Field(0, ge=0, le=100, strict=True)
    status: Literal['ACTIVE_PROBATION', 'EXTENDED', 'CONFIRMED'] = 'ACTIVE_PROBATION'


@router.post('/probation-records', status_code=201)
def create_probation(body: ProbationInput, user=Depends(admin), db=Depends(get_db)):
    find(db, 'Employee', body.employeeId, lock=True)
    values = body.model_dump()
    for key in ('joiningDate', 'probationStart', 'probationEnd'):
        values[key] = calendar_date(values[key])
    if values['probationEnd'] < values['probationStart']:
        raise HTTPException(422, 'Probation end must be on or after its start date')
    own = linked_employee(db, user, required=False)
    if body.status == 'CONFIRMED' and own and own['id'] == body.employeeId:
        raise HTTPException(403, 'You cannot confirm your own probation')
    tbl = table(db, 'ProbationRecord')
    if db.scalar(select(tbl.c.id).where(tbl.c.employeeId == body.employeeId, tbl.c.status.in_(['ACTIVE_PROBATION', 'EXTENDED'])).limit(1)):
        raise HTTPException(409, 'This employee already has an active probation record')
    values['confirmedAt'] = now() if body.status == 'CONFIRMED' else None
    return output(probation_payload(db, insert(db, 'ProbationRecord', values)))


@router.get('/probation-records/filter-options')
def probation_options(user=Depends(admin), db=Depends(get_db)):
    locations = {item['city'] for item in rows(db, 'Branch', table(db, 'Branch').c.isActive.is_(True))}
    employees = rows(db, 'Employee')
    managers = {item['reportingManager'] for item in rows(db, 'ProbationRecord')}
    by_id = {item['id']: item for item in employees}
    for employee in employees:
        metadata = details(employee)
        locations.update([employee['workLocation'], metadata.get('location')])
        managers.add(metadata.get('manager'))
        if employee['reportsToEmployeeId'] in by_id:
            managers.add(full_name(by_id[employee['reportsToEmployeeId']]))
    clean = lambda values: sorted({item.strip() for item in values if isinstance(item, str) and item.strip()}, key=str.casefold)
    return {'departments': clean(item['name'] for item in rows(db, 'Department')), 'locations': clean(locations), 'managers': clean(managers)}


@router.get('/probation-records/{id}')
def probation_record(id: str, user=Depends(admin), db=Depends(get_db)):
    return output(probation_payload(db, find(db, 'ProbationRecord', id), True))


class DecisionInput(Input):
    action: Literal['confirm', 'extend', 'add-review']
    monthsAdded: int | None = Field(None, ge=1, le=6, strict=True)
    newProbationEnd: str | None = None
    note: str | None = Field(None, max_length=10000)
    notifyEmployee: bool = True
    title: str | None = Field(None, max_length=120)
    date: str | None = None
    status: Literal['Pending', 'Completed'] = 'Completed'
    description: str | None = Field(None, max_length=500)
    reviewedBy: str | None = Field(None, max_length=1000)
    performanceRating: int | None = Field(None, ge=1, le=5, strict=True)
    attendanceRating: Literal['Excellent', 'Good', 'Satisfactory', 'Needs Improvement', 'Poor'] | None = None
    skills: list[str] = Field(default_factory=list, max_length=100)
    recommendation: Literal['CONFIRM', 'EXTEND', 'TERMINATE'] | None = None


@router.patch('/probation-records/{id}')
def decide_probation(id: str, body: DecisionInput, user=Depends(admin), db=Depends(get_db)):
    record = find(db, 'ProbationRecord', id)
    find(db, 'Employee', record['employeeId'], lock=True)
    record = find(db, 'ProbationRecord', id, lock=True)
    own = linked_employee(db, user, required=False)
    if own and own['id'] == record['employeeId']:
        raise HTTPException(403, 'You cannot review or decide your own probation')
    if record['status'] == 'CONFIRMED':
        raise HTTPException(409, 'Confirmed probation is closed')
    if body.action == 'confirm':
        values = {'status': 'CONFIRMED', 'confirmedAt': now()}
    elif body.action == 'extend':
        if not body.monthsAdded or not body.note:
            raise HTTPException(422, 'Enter an extension of 1–6 months and its reason')
        previous = record['probationEnd']
        if body.newProbationEnd:
            end = calendar_date(body.newProbationEnd)
        else:
            year, month = divmod(previous.year * 12 + previous.month - 1 + body.monthsAdded, 12)
            end = date(year, month + 1, min(previous.day, monthrange(year, month + 1)[1]))
        if end <= previous:
            raise HTTPException(422, 'New probation end must be after the current end date')
        events = json_items(record['extensionEventsJson'])
        events.append({'id': 'ext-' + uuid4().hex, 'date': now().date().isoformat(), 'monthsAdded': body.monthsAdded,
            'note': body.note, 'notifyEmployee': body.notifyEmployee, 'newEnd': end.isoformat(),
            'reviewerId': bridge_user(db, user)['id'], 'recordedAt': now().isoformat() + 'Z'})
        values = {'probationEnd': end, 'extensions': record['extensions'] + 1, 'status': 'EXTENDED', 'extensionEventsJson': events}
    else:
        skills = list(dict.fromkeys(item.strip() for item in body.skills if item.strip()))
        if not body.description or not body.performanceRating or not body.attendanceRating or not skills or any(len(item) > 64 for item in skills) or not body.recommendation:
            raise HTTPException(422, 'Provide comments, performance and attendance ratings, skills and a recommendation')
        day = calendar_date(body.date) if body.date else now().date()
        reviews = json_items(record['reviewsJson'])
        reviews.append({'id': 'rev-' + uuid4().hex, 'title': body.title or 'Manager Review', 'date': day.isoformat(), 'status': body.status,
            'description': body.description, 'reviewedBy': user.name or user.email, 'reviewerId': bridge_user(db, user)['id'],
            'recordedAt': now().isoformat() + 'Z', 'performanceRating': body.performanceRating, 'attendanceRating': body.attendanceRating,
            'skills': skills, 'recommendation': body.recommendation})
        values = {'reviewsJson': reviews}
    return output(probation_payload(db, update(db, 'ProbationRecord', id, values), True))


class DepartmentDuration(Input):
    departmentId: str = Field(min_length=1, max_length=255)
    durationMonths: int = Field(ge=1, le=24, strict=True)


class WorkflowStep(Input):
    order: int = Field(ge=1, le=20, strict=True)
    roleKey: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=255)


class SettingsInput(Input):
    defaultDurationMonths: int = Field(ge=1, le=24, strict=True)
    maxExtensions: int = Field(ge=0, le=10, strict=True)
    fullTimeDurationMonths: int = Field(ge=1, le=24, strict=True)
    contractDurationMonths: int = Field(ge=1, le=24, strict=True)
    autoConfirmationEnabled: bool
    reminder30Enabled: bool
    reminder15Enabled: bool
    reminder7Enabled: bool
    departmentDurations: list[DepartmentDuration] = Field(default_factory=list, max_length=500)
    approvalWorkflow: list[WorkflowStep] = Field(min_length=1, max_length=20)


DEFAULTS = {'id': 'default', 'defaultDurationMonths': 6, 'maxExtensions': 2, 'fullTimeDurationMonths': 6, 'contractDurationMonths': 3,
    'autoConfirmationEnabled': False, 'reminder30Enabled': True, 'reminder15Enabled': True, 'reminder7Enabled': True, 'departmentDurations': [],
    'approvalWorkflow': [{'order': index + 1, 'roleKey': key, 'label': label} for index, (key, label) in enumerate([
        ('reporting_manager', 'Reporting Manager'), ('hr_manager', 'HR Manager'), ('department_head', 'Department Head')])]}


@router.get('/probation-settings')
def probation_settings(user=Depends(admin), db=Depends(get_db)):
    record = find(db, 'ProbationPolicySettings', 'default', required=False)
    return output(record or {**DEFAULTS, 'updatedAt': None})


@router.put('/probation-settings')
def save_probation_settings(body: SettingsInput, user=Depends(admin), db=Depends(get_db)):
    onboarding_lock(db)
    values = body.model_dump()
    if len({item.departmentId for item in body.departmentDurations}) != len(body.departmentDurations) or len({item.order for item in body.approvalWorkflow}) != len(body.approvalWorkflow):
        raise HTTPException(422, 'Department durations and approval step numbers must be unique')
    for item in body.departmentDurations:
        find(db, 'Department', item.departmentId)
    values['approvalWorkflow'].sort(key=lambda item: item['order'])
    record = find(db, 'ProbationPolicySettings', 'default', required=False)
    return output(update(db, 'ProbationPolicySettings', 'default', values) if record else insert(db, 'ProbationPolicySettings', {'id': 'default', **values}))
