"""Existing employee job details, compensation snapshot and lifecycle timeline."""
import math
from datetime import date
from typing import Annotated, Literal

from fastapi import Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, text

from app.core.compatibility_routing import APIRouter
from app.data.database import get_db
from app.data.imported import dto, find, table
from app.modules.workforce.imported_assets import admin, insert, rows, wire
from app.modules.workforce.imported_employees import EmployeeStatus, full_employee
from app.modules.workforce.imported_organization import update

router = APIRouter(prefix='/api/employees', tags=['HRMS employee profile'])


def details(record):
    return record['employeeDetails'] if isinstance(record['employeeDetails'], dict) else {}


def full_name(record):
    return f"{record['firstName']} {record['lastName']}".strip()


def job_payload(db, record):
    full = full_employee(db, record)
    manager = find(db, 'Employee', record['reportsToEmployeeId'], required=False)
    hire = record['hireDate']
    options = {}
    for name, model in (('departments', 'Department'), ('jobTitles', 'JobTitle')):
        options[name] = [{key: row[key] for key in ('id', 'name')} for row in rows(db, model, order=table(db, model).c.name)]
    employee = table(db, 'Employee')
    options['reportsToCandidates'] = [{'id': row['id'], 'name': full_name(row)}
        for row in rows(db, 'Employee', employee.c.id != record['id'], order=employee.c.lastName)[:500]]
    return {'employeeId': record['id'], 'position': {
        'jobTitleId': record['jobTitleId'], 'jobTitle': (full['jobTitle'] or {}).get('name', '—'),
        'departmentId': record['departmentId'], 'department': (full['department'] or {}).get('name', '—'),
        'reportsToEmployeeId': record['reportsToEmployeeId'],
        'reportsToName': full_name(manager) if manager else details(record).get('manager') or '—',
        'employmentType': record['employmentType'] or ''},
        'work': {'hireDate': hire.isoformat()[:10] if hire else None, 'hireDateDisplay': hire.strftime('%d-%m-%Y') if hire else '—',
                 'workLocation': record['workLocation'] or details(record).get('location') or '—',
                 'status': record['status'], 'statusLabel': {'ACTIVE': 'Active', 'PROBATION': 'Probation', 'ON_LEAVE': 'On leave', 'TERMINATED': 'Inactive'}[record['status']]},
        'options': options}


@router.get('/{id}/job-details')
def job_details(id: str, user=Depends(admin), db=Depends(get_db)):
    return job_payload(db, find(db, 'Employee', id))


class JobPatch(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    jobTitleId: str | None = Field(None, max_length=100)
    departmentId: str | None = Field(None, max_length=100)
    reportsToEmployeeId: str | None = Field(None, max_length=100)
    employmentType: str | None = Field(None, max_length=255)
    hireDate: date | None = None
    workLocation: str | None = Field(None, max_length=512)
    status: EmployeeStatus | None = None


@router.patch('/{id}/job-details')
def patch_job(id: str, body: JobPatch, user=Depends(admin), db=Depends(get_db)):
    # Serialize hierarchy edits before checking the whole manager chain.
    if db.bind.dialect.name == 'postgresql':
        db.execute(text('SELECT pg_advisory_xact_lock(7310461)'))
    record = find(db, 'Employee', id, lock=True)
    values = body.model_dump(exclude_unset=True)
    if 'status' in values and values['status'] is None:
        raise HTTPException(422, 'Status cannot be empty')
    for key, model in (('jobTitleId', 'JobTitle'), ('departmentId', 'Department'), ('reportsToEmployeeId', 'Employee')):
        if key in values:
            values[key] = values[key] or None
            if values[key]:
                find(db, model, values[key])
    manager = values.get('reportsToEmployeeId')
    seen = {id}
    while manager:
        if manager in seen:
            raise HTTPException(409, 'This manager assignment would create a reporting cycle')
        seen.add(manager)
        manager = find(db, 'Employee', manager)['reportsToEmployeeId']
    metadata = dict(details(record))
    if 'workLocation' in values:
        metadata['location'] = values['workLocation'] or ''
    if 'reportsToEmployeeId' in values:
        metadata['manager'] = full_name(find(db, 'Employee', values['reportsToEmployeeId'])) if values['reportsToEmployeeId'] else ''
    if 'workLocation' in values or 'reportsToEmployeeId' in values:
        values['employeeDetails'] = metadata
    return job_payload(db, update(db, 'Employee', id, values))


BENEFITS = ['Health Insurance', 'Dental Insurance', 'Flexible PTO', 'Remote Work Stipend', 'Life Insurance', 'Vision Insurance']
AMOUNTS = ('grossSalary', 'deductionsAmount', 'netPay')
TEXTS = ('payFrequency', 'deductionsDescription', 'taxRegime', 'bankAccountMasked')


def payroll_payload(record):
    raw = record['payrollJson'] if isinstance(record['payrollJson'], dict) else {}
    normalized = {key: raw.get(key).strip() if isinstance(raw.get(key), str) else '' for key in TEXTS}
    for key in AMOUNTS:
        value = raw.get(key)
        normalized[key] = value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None
    normalized['benefits'] = list(dict.fromkeys(item.strip() for item in raw.get('benefits', []) if isinstance(item, str) and item.strip())) if isinstance(raw.get('benefits'), list) else []
    return {'employeeId': record['id'], 'payroll': normalized, 'benefitCatalog': BENEFITS}


@router.get('/{id}/payroll')
def payroll(id: str, user=Depends(admin), db=Depends(get_db)):
    return payroll_payload(find(db, 'Employee', id))


class PayrollPatch(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    grossSalary: float | None = Field(None, ge=0, le=90071992547409.91, allow_inf_nan=False, strict=True)
    deductionsAmount: float | None = Field(None, ge=0, le=90071992547409.91, allow_inf_nan=False, strict=True)
    netPay: float | None = Field(None, ge=0, le=90071992547409.91, allow_inf_nan=False, strict=True)
    payFrequency: str | None = Field(None, max_length=500)
    deductionsDescription: str | None = Field(None, max_length=500)
    taxRegime: str | None = Field(None, max_length=500)
    bankAccountMasked: str | None = Field(None, max_length=500)
    benefits: list[Annotated[str, Field(min_length=1, max_length=200)]] = Field(default_factory=list, max_length=100)


@router.patch('/{id}/payroll')
def patch_payroll(id: str, body: PayrollPatch, user=Depends(admin), db=Depends(get_db)):
    record = find(db, 'Employee', id, lock=True)
    values = body.model_dump(exclude_unset=True)
    if not values:
        raise HTTPException(422, 'Provide at least one payroll field')
    for key in TEXTS:
        if key in values and values[key] is None:
            values[key] = ''
    raw = record['payrollJson'] if isinstance(record['payrollJson'], dict) else {}
    return payroll_payload(update(db, 'Employee', id, {'payrollJson': {**raw, **values}}))


def event_dto(record):
    return {**{key: record[key] for key in ('id', 'kind', 'title')}, 'occurredOn': record['occurredOn'].isoformat()[:10],
            'bullets': [value.strip() for value in record['bullets'] or [] if isinstance(value, str) and value.strip()][:12]}


@router.get('/{id}/lifecycle')
def lifecycle(id: str, user=Depends(admin), db=Depends(get_db)):
    employee = find(db, 'Employee', id)
    related = {}
    for model in ('ProbationRecord', 'OnboardingCandidate'):
        tbl = table(db, model)
        records = rows(db, model, tbl.c.employeeId == id, order=tbl.c.createdAt.desc())
        related[model] = records[0] if records else {}
    probation, onboarding = related['ProbationRecord'], related['OnboardingCandidate']
    stages = [{'key': key, 'label': key.title(), 'status': 'UPCOMING', 'reachedOn': None} for key in ('ONBOARDING', 'PROBATION', 'CONFIRMATION')]
    if onboarding.get('status') == 'COMPLETED' or employee['hireDate']:
        stages[0].update(status='COMPLETED', reachedOn=(onboarding['updatedAt'] if onboarding.get('status') == 'COMPLETED' else employee['hireDate']).isoformat()[:10])
    elif onboarding.get('status') in ('IN_PROGRESS', 'INVITED'):
        stages[0]['status'] = 'ACTIVE'
    if probation.get('status') == 'CONFIRMED':
        stages[1].update(status='COMPLETED', reachedOn=probation['probationEnd'].isoformat()[:10])
        stages[2].update(status='COMPLETED', reachedOn=(probation['confirmedAt'] or probation['probationEnd']).isoformat()[:10])
    elif probation.get('status') in ('ACTIVE_PROBATION', 'EXTENDED'):
        stages[1].update(status='ACTIVE', reachedOn=probation['probationStart'].isoformat()[:10])
    events = table(db, 'EmployeeLifecycleEvent')
    return {'employeeId': id, 'stages': stages, 'timeline': [event_dto(row) for row in rows(db, 'EmployeeLifecycleEvent', events.c.employeeId == id, order=events.c.occurredOn)]}


class EventInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=200)
    occurredOn: date
    kind: str | None = Field(None, max_length=100)
    bullets: list[Annotated[str, Field(max_length=2000)]] = Field(default_factory=list, max_length=12)


class EventPatch(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    title: str | None = Field(None, min_length=1, max_length=200)
    occurredOn: date | None = None
    kind: str | None = Field(None, max_length=100)
    bullets: list[Annotated[str, Field(max_length=2000)]] | None = Field(None, max_length=12)


def event_values(values):
    if 'kind' in values:
        from app.data.imported import SCHEMA
        choices = next(field['enum']['values'] for field in SCHEMA['EmployeeLifecycleEvent']['fields'] if field['key'] == 'kind')
        if values['kind'] not in choices:
            values['kind'] = 'OTHER'
    return values


@router.post('/{id}/lifecycle', status_code=201)
def add_event(id: str, body: EventInput, user=Depends(admin), db=Depends(get_db)):
    find(db, 'Employee', id, lock=True)
    return event_dto(insert(db, 'EmployeeLifecycleEvent', {**event_values(body.model_dump()), 'employeeId': id}))


def owned_event(db, id, eventId):
    record = find(db, 'EmployeeLifecycleEvent', eventId, lock=True)
    if record['employeeId'] != id:
        raise HTTPException(404, 'Event not found')
    return record


@router.patch('/{id}/lifecycle/{eventId}')
def patch_event(id: str, eventId: str, body: EventPatch, user=Depends(admin), db=Depends(get_db)):
    owned_event(db, id, eventId)
    values = event_values(body.model_dump(exclude_unset=True))
    if any(key in values and values[key] is None for key in ('title', 'occurredOn', 'bullets')):
        raise HTTPException(422, 'Title, date and bullets cannot be null')
    return event_dto(update(db, 'EmployeeLifecycleEvent', eventId, values))


@router.delete('/{id}/lifecycle/{eventId}', status_code=204)
def delete_event(id: str, eventId: str, user=Depends(admin), db=Depends(get_db)):
    owned_event(db, id, eventId)
    tbl = table(db, 'EmployeeLifecycleEvent')
    db.execute(tbl.delete().where(tbl.c.id == eventId, tbl.c.employeeId == id))
    return Response(status_code=204)
