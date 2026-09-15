"""Attendance punches and policy configuration, using existing public records."""
from datetime import date, datetime, timezone
from typing import Literal

from fastapi import Depends, HTTPException
from pydantic import Field, JsonValue, field_validator
from sqlalchemy import func, select

from app.core.compatibility_routing import APIRouter
from app.data.database import get_db
from app.data.imported import dto, find, table
from app.modules.workforce.imported_assets import admin, insert, now, rows
from app.modules.workforce.imported_organization import update
from app.modules.workforce.imported_leave import Input, employee_id, output, own_or_admin, privileged, remove, staff

router = APIRouter(prefix='/api', tags=['HRMS attendance compatibility'])


def calendar_date(value):
    try:
        if not isinstance(value, str) or len(value) != 10:
            raise ValueError()
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(422, 'Use a valid YYYY-MM-DD calendar date') from None


def timestamp(value):
    if value is None or value == '':
        return None
    try:
        if not isinstance(value, str) or 'T' not in value:
            raise ValueError()
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ValueError()
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    except ValueError:
        raise HTTPException(422, 'Attendance times must be valid timestamps including a timezone') from None


def validate_times(start, end):
    if end is not None and (start is None or end < start):
        raise HTTPException(422, 'Check in is required and check out must not precede check in')


class AttendancePatch(Input):
    workDate: str | None = None
    checkIn: str | None = Field(None, max_length=100)
    checkOut: str | None = Field(None, max_length=100)


class Punch(AttendancePatch):
    employeeId: str | None = Field(None, min_length=1, max_length=100)
    workDate: str


def attendance_detail(db, record):
    return {**record, 'employee': find(db, 'Employee', record['employeeId'])}


@router.get('/attendance-records')
def attendance_records(scope: str = '', user=Depends(staff), db=Depends(get_db)):
    own = employee_id(db, user) if not privileged(user) or scope == 'self' else None
    if not own and (not privileged(user) or scope == 'self'):
        return []
    tbl = table(db, 'AttendanceRecord')
    query = select(tbl).order_by(tbl.c.workDate.desc(), tbl.c.employeeId)
    if own:
        query = query.where(tbl.c.employeeId == own)
    return output([attendance_detail(db, dto(tbl, row)) for row in db.execute(query).mappings()])


@router.post('/attendance-records')
def punch(body: Punch, user=Depends(staff), db=Depends(get_db)):
    own = employee_id(db, user)
    target = body.employeeId if privileged(user) and body.employeeId else own
    if not target:
        raise HTTPException(403, 'No employee linked to account')
    if not privileged(user) and body.employeeId and body.employeeId != own:
        raise HTTPException(403, 'Cannot record attendance for another employee')
    work_date = calendar_date(body.workDate)
    instant = now()
    if not privileged(user) and work_date != instant.date():
        raise HTTPException(422, 'Self-service punches are only allowed for today')
    find(db, 'Employee', target, lock=True)
    tbl = table(db, 'AttendanceRecord')
    record = db.execute(select(tbl).where(tbl.c.employeeId == target, tbl.c.workDate == work_date).with_for_update()).mappings().first()
    existing = dto(tbl, record) if record else None
    start, end = (existing['checkIn'], existing['checkOut']) if existing else (None, None)
    if privileged(user):
        if 'checkIn' in body.model_fields_set:
            start = timestamp(body.checkIn)
        if 'checkOut' in body.model_fields_set:
            end = timestamp(body.checkOut)
    else:
        if not body.checkIn and not body.checkOut:
            raise HTTPException(422, 'Specify a check-in or check-out action')
        # Client timestamps indicate an action, never the authoritative punch time.
        if body.checkIn and start is None:
            start = instant
        if body.checkOut and end is None:
            end = instant
    validate_times(start, end)
    values = {'checkIn': start, 'checkOut': end}
    saved = update(db, 'AttendanceRecord', existing['id'], values) if existing else insert(db, 'AttendanceRecord', {
        'employeeId': target, 'workDate': work_date, **values})
    return output(saved)


@router.get('/attendance-records/{id}')
def get_record(id: str, user=Depends(staff), db=Depends(get_db)):
    record = find(db, 'AttendanceRecord', id)
    own_or_admin(db, user, record['employeeId'])
    return output(attendance_detail(db, record))


@router.patch('/attendance-records/{id}')
def patch_record(id: str, body: AttendancePatch, user=Depends(admin), db=Depends(get_db)):
    if not body.model_fields_set:
        raise HTTPException(422, 'Supply attendance fields to update')
    initial = find(db, 'AttendanceRecord', id)
    find(db, 'Employee', initial['employeeId'], lock=True)
    current = find(db, 'AttendanceRecord', id, lock=True)
    start = timestamp(body.checkIn) if 'checkIn' in body.model_fields_set else current['checkIn']
    end = timestamp(body.checkOut) if 'checkOut' in body.model_fields_set else current['checkOut']
    validate_times(start, end)
    work_date = calendar_date(body.workDate) if 'workDate' in body.model_fields_set else current['workDate']
    tbl = table(db, 'AttendanceRecord')
    if db.scalar(select(tbl.c.id).where(tbl.c.employeeId == current['employeeId'], tbl.c.workDate == work_date, tbl.c.id != id).limit(1)):
        raise HTTPException(409, 'An attendance record already exists for this employee and day')
    return output(update(db, 'AttendanceRecord', id, {'checkIn': start, 'checkOut': end, 'workDate': work_date}))


@router.delete('/attendance-records/{id}')
def delete_record(id: str, user=Depends(admin), db=Depends(get_db)):
    record = find(db, 'AttendanceRecord', id)
    find(db, 'Employee', record['employeeId'], lock=True)
    return remove(db, 'AttendanceRecord', id)


Category = Literal['LEAVE_TYPE', 'SHIFT', 'ENTITLEMENT']


class PolicyPatch(Input):
    name: str | None = Field(None, min_length=1, max_length=200)
    status: Literal['ACTIVE', 'INACTIVE'] | None = None
    sortOrder: int | None = Field(None, ge=-1000000, le=1000000)
    config: dict[str, JsonValue] | None = None


class PolicyCreate(PolicyPatch):
    category: Category
    name: str = Field(min_length=1, max_length=200)
    status: Literal['ACTIVE', 'INACTIVE'] = 'ACTIVE'
    config: dict[str, JsonValue]


def policy_config(category, value):
    if not isinstance(value, dict):
        raise HTTPException(422, 'Policy config must be an object')
    if category == 'SHIFT':
        result = {}
        for key in ('startTime', 'endTime', 'breakNotes'):
            raw = value.get(key)
            if not isinstance(raw, str) or not raw.strip() or len(raw) > 2000:
                raise HTTPException(422, f'Policy {key} is required (up to 2000 characters)')
            result[key] = raw.strip()
        return result
    days = value.get('days')
    import math
    if type(days) not in (float, int) or not math.isfinite(days) or not 0 <= days <= 1000000:
        raise HTTPException(422, 'Policy days must be a non-negative finite number')
    result = {'days': math.floor(days)}
    if category == 'LEAVE_TYPE':
        if type(value.get('carryForward')) is not bool:
            raise HTTPException(422, 'Policy carryForward must be a boolean')
        result['carryForward'] = value['carryForward']
    return result


def policy_detail(record):
    config = record.get('config') or {}
    category = record['category']
    if category == 'LEAVE_TYPE':
        carry = 'Carry forward Allowed' if config.get('carryForward') else 'No Carry forward'
        detail = f"{config.get('days', 0)} days · {carry}"
    elif category == 'SHIFT':
        detail = f"{config.get('startTime', '')} to {config.get('endTime', '')} · {config.get('breakNotes', '')}"
    else:
        detail = f"{config.get('days', 0)} days"
    return output({**record, 'detail': detail})


@router.get('/attendance-policies')
def policies(category: Category, user=Depends(admin), db=Depends(get_db)):
    tbl = table(db, 'AttendancePolicy')
    data = db.execute(select(tbl).where(tbl.c.category == category).order_by(tbl.c.sortOrder, tbl.c.createdAt)).mappings()
    return [policy_detail(dto(tbl, row)) for row in data]


@router.post('/attendance-policies', status_code=201)
def create_policy(body: PolicyCreate, user=Depends(admin), db=Depends(get_db)):
    tbl = table(db, 'AttendancePolicy')
    values = body.model_dump()
    values['config'] = policy_config(body.category, body.config)
    if body.sortOrder is None:
        values['sortOrder'] = (db.scalar(select(func.max(tbl.c.sortOrder)).where(tbl.c.category == body.category)) or 0) + 1
    return policy_detail(insert(db, 'AttendancePolicy', values))


@router.get('/attendance-policies/{id}')
def get_policy(id: str, user=Depends(admin), db=Depends(get_db)):
    return policy_detail(find(db, 'AttendancePolicy', id))


@router.patch('/attendance-policies/{id}')
def patch_policy(id: str, body: PolicyPatch, user=Depends(admin), db=Depends(get_db)):
    values = body.model_dump(exclude_unset=True)
    if not values or any(value is None for value in values.values()):
        raise HTTPException(422, 'Supply valid policy fields')
    current = find(db, 'AttendancePolicy', id, lock=True)
    if 'config' in values:
        values['config'] = policy_config(current['category'], values['config'])
    return policy_detail(update(db, 'AttendancePolicy', id, values))


@router.delete('/attendance-policies/{id}')
def delete_policy(id: str, user=Depends(admin), db=Depends(get_db)):
    return remove(db, 'AttendancePolicy', id)
