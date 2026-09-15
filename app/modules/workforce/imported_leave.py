"""Existing leave records with verified employee and direct-report authorization."""
from datetime import date, datetime, timezone
from typing import Literal

from fastapi import Depends, HTTPException, Query, Response
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select, or_

from app.core.compatibility_routing import APIRouter
from app.core.imported_identity import linked_employee
from app.core.security import require
from app.data.database import get_db
from app.data.imported import dto, find, table
from app.modules.workforce.imported_assets import admin, insert, now, rows
from app.modules.workforce.imported_organization import update

router = APIRouter(prefix='/api', tags=['HRMS leave compatibility'])
staff = require('hr', 'employee', 'manager', module='hrms')


def privileged(user):
    return user.role in ('admin', 'hr')


def employee_id(db, user):
    employee = linked_employee(db, user, required=False)
    return employee['id'] if employee else None


def output(value):
    # Prisma serialized both date-only columns and timestamps as UTC ISO strings.
    return jsonable_encoder(value, custom_encoder={
        datetime: lambda d: d.replace(tzinfo=timezone.utc).isoformat().replace('+00:00', 'Z') if d.tzinfo is None else d.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z'),
        date: lambda d: d.isoformat() + 'T00:00:00.000Z',
    })


def own_or_admin(db, user, owner):
    if not privileged(user) and employee_id(db, user) != owner:
        raise HTTPException(403, 'You can only access your own employee record')


def remove(db, model, id):
    find(db, model, id, lock=True)
    tbl = table(db, model)
    db.execute(tbl.delete().where(tbl.c.id == id))
    return Response(status_code=204)


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class LeaveTypePatch(Input):
    name: str | None = Field(None, min_length=1, max_length=200)
    daysPerYear: int | None = Field(None, ge=0, le=366, strict=True)
    colorHex: str | None = Field(None, pattern=r'^#[0-9A-Fa-f]{6}$')


class LeaveTypeCreate(LeaveTypePatch):
    name: str = Field(min_length=1, max_length=200)


@router.get('/leave-types')
def leave_types(user=Depends(staff), db=Depends(get_db)):
    return output(rows(db, 'LeaveType', order=table(db, 'LeaveType').c.name))


@router.post('/leave-types', status_code=201)
def create_type(body: LeaveTypeCreate, user=Depends(admin), db=Depends(get_db)):
    return output(insert(db, 'LeaveType', body.model_dump()))


@router.get('/leave-types/{id}')
def get_type(id: str, user=Depends(staff), db=Depends(get_db)):
    return output(find(db, 'LeaveType', id))


@router.patch('/leave-types/{id}')
def patch_type(id: str, body: LeaveTypePatch, user=Depends(admin), db=Depends(get_db)):
    values = body.model_dump(exclude_unset=True)
    if not values or ('name' in values and values['name'] is None):
        raise HTTPException(422, 'Supply fields to update; the name cannot be empty')
    return output(update(db, 'LeaveType', id, values))


@router.delete('/leave-types/{id}')
def delete_type(id: str, user=Depends(admin), db=Depends(get_db)):
    find(db, 'LeaveType', id, lock=True)
    for model in ('LeaveRequest', 'LeaveBalance'):
        tbl = table(db, model)
        if db.scalar(select(tbl.c.id).where(tbl.c.leaveTypeId == id).limit(1)):
            raise HTTPException(409, 'This leave type is used by saved requests or balances')
    return remove(db, 'LeaveType', id)


Status = Literal['PENDING', 'APPROVED', 'REJECTED', 'CANCELLED']


class RequestPatch(Input):
    startDate: date | None = None
    endDate: date | None = None
    status: Status | None = None
    reason: str | None = Field(None, max_length=20000)
    leaveTypeId: str | None = Field(None, min_length=1, max_length=100)

    @field_validator('startDate', 'endDate', mode='before')
    @classmethod
    def date_only(cls, value):
        if value is not None and (not isinstance(value, str) or len(value) != 10):
            raise ValueError('Use YYYY-MM-DD dates')
        return value


class RequestCreate(RequestPatch):
    employeeId: str | None = Field(None, min_length=1, max_length=100)
    leaveTypeId: str = Field(min_length=1, max_length=100)
    startDate: date
    endDate: date
    status: Literal['PENDING'] = 'PENDING'


def validate_dates(start, end):
    if start is None or end is None or end < start:
        raise HTTPException(422, 'End date must be on or after start date')


def reject_overlap(db, owner, start, end, exclude=None):
    tbl = table(db, 'LeaveRequest')
    query = select(tbl.c.id).where(tbl.c.employeeId == owner, tbl.c.status.in_(['PENDING', 'APPROVED']),
                                 tbl.c.startDate <= end, tbl.c.endDate >= start)
    if exclude:
        query = query.where(tbl.c.id != exclude)
    if db.scalar(query.limit(1)):
        raise HTTPException(409, 'An active leave request already covers these dates')


def request_detail(db, record):
    employee = find(db, 'Employee', record['employeeId'])
    return {**record, 'employee': {key: employee[key] for key in ('id', 'firstName', 'lastName', 'employeeCode', 'reportsToEmployeeId')},
            'leaveType': find(db, 'LeaveType', record['leaveTypeId'])}


@router.get('/leave-requests')
def requests(scope: str = '', status: str = 'ALL', leaveTypeId: str = '', q: str = Query('', max_length=200),
             user=Depends(staff), db=Depends(get_db)):
    tbl, employees = table(db, 'LeaveRequest'), table(db, 'Employee')
    owner = None if privileged(user) and scope not in ('self', 'team') else employee_id(db, user)
    criteria = []
    if scope == 'team':
        if user.role != 'manager' or not owner:
            raise HTTPException(403, 'Manager employee linkage required')
        criteria.append(tbl.c.employeeId.in_(select(employees.c.id).where(employees.c.reportsToEmployeeId == owner, employees.c.id != owner)))
    elif owner:
        criteria.append(tbl.c.employeeId == owner)
    elif not privileged(user) or scope == 'self':
        return {'requests': [], 'pendingTotal': 0}
    pending = db.scalar(select(func.count()).select_from(tbl).where(*criteria, tbl.c.status == 'PENDING'))
    if status.upper() in ('PENDING', 'APPROVED', 'REJECTED', 'CANCELLED'):
        criteria.append(tbl.c.status == status.upper())
    if leaveTypeId:
        criteria.append(tbl.c.leaveTypeId == leaveTypeId)
    if q.strip():
        pattern = '%' + q.strip().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        criteria.append(tbl.c.employeeId.in_(select(employees.c.id).where(or_(*(employees.c[key].ilike(pattern, escape='\\') for key in ('firstName', 'lastName', 'employeeCode'))))))
    data = db.execute(select(tbl).where(*criteria).order_by(tbl.c.createdAt.desc()).limit(200)).mappings()
    return output({'requests': [request_detail(db, dto(tbl, record)) for record in data], 'pendingTotal': pending})


@router.post('/leave-requests', status_code=201)
def create_request(body: RequestCreate, user=Depends(staff), db=Depends(get_db)):
    own = employee_id(db, user)
    if not privileged(user) and body.employeeId and body.employeeId != own:
        raise HTTPException(403, 'Cannot submit leave for another employee')
    owner = body.employeeId if privileged(user) and body.employeeId else own
    if not owner:
        raise HTTPException(403, 'No employee linked to account')
    find(db, 'Employee', owner, lock=True)
    find(db, 'LeaveType', body.leaveTypeId)
    validate_dates(body.startDate, body.endDate)
    reject_overlap(db, owner, body.startDate, body.endDate)
    return output(insert(db, 'LeaveRequest', {**body.model_dump(), 'employeeId': owner, 'reason': body.reason or None}))


def can_review(db, user, record, owner=None):
    own = employee_id(db, user)
    employee = owner or find(db, 'Employee', record['employeeId'])
    team = user.role == 'manager' and own is not None and own != record['employeeId'] and employee['reportsToEmployeeId'] == own
    if not privileged(user) and own != record['employeeId'] and not team:
        raise HTTPException(403, 'You can only access your own leave or requests from direct reports')
    return own, team


@router.get('/leave-requests/{id}')
def get_request(id: str, user=Depends(staff), db=Depends(get_db)):
    record = find(db, 'LeaveRequest', id)
    can_review(db, user, record)
    return output(request_detail(db, record))


def change_request(db, user, id, body):
    values = body.model_dump(exclude_unset=True)
    if not values or any(key != 'reason' and value is None for key, value in values.items()):
        raise HTTPException(422, 'Supply valid fields to update')
    original = find(db, 'LeaveRequest', id)
    owner = find(db, 'Employee', original['employeeId'], lock=True)
    current = find(db, 'LeaveRequest', id, lock=True)
    own, team = can_review(db, user, current, owner)
    target = values.get('status', current['status'])
    editing = any(key != 'status' for key in values)
    if team and not privileged(user):
        if editing or target not in ('APPROVED', 'REJECTED'):
            raise HTTPException(403, 'Managers can only approve or reject pending direct-report requests')
    if not privileged(user) and not team and target != current['status'] and target != 'CANCELLED':
        raise HTTPException(403, 'Only HR, Admin or the direct-report manager can decide leave requests')
    if own == current['employeeId'] and target == 'APPROVED' and current['status'] != 'APPROVED':
        raise HTTPException(403, 'Another HR or Admin must approve your leave')
    if editing and current['status'] != 'PENDING':
        raise HTTPException(409, 'Only pending leave requests can be edited')
    if target != current['status'] and current['status'] != 'PENDING' and not (privileged(user) and current['status'] == 'APPROVED' and target == 'CANCELLED'):
        raise HTTPException(409, 'This leave request is already decided')
    start, end = values.get('startDate', current['startDate']), values.get('endDate', current['endDate'])
    validate_dates(start, end)
    if 'leaveTypeId' in values:
        find(db, 'LeaveType', values['leaveTypeId'])
    if target in ('PENDING', 'APPROVED'):
        reject_overlap(db, current['employeeId'], start, end, id)
    if 'reason' in values:
        values['reason'] = values['reason'] or None
    return output(update(db, 'LeaveRequest', id, values))


@router.patch('/leave-requests/{id}')
def patch_request(id: str, body: RequestPatch, user=Depends(staff), db=Depends(get_db)):
    return change_request(db, user, id, body)


@router.delete('/leave-requests/{id}')
def withdraw_request(id: str, user=Depends(staff), db=Depends(get_db)):
    return change_request(db, user, id, RequestPatch(status='CANCELLED'))


class BalancePatch(Input):
    year: int | None = Field(None, ge=1900, le=9999, strict=True)
    balanceDays: float | None = Field(None, ge=0, le=1000000, allow_inf_nan=False, strict=True)


class BalanceCreate(BalancePatch):
    employeeId: str = Field(min_length=1, max_length=100)
    leaveTypeId: str = Field(min_length=1, max_length=100)
    year: int = Field(ge=1900, le=9999, strict=True)
    balanceDays: float = Field(0, ge=0, le=1000000, allow_inf_nan=False, strict=True)


def balance_detail(db, record):
    return {**record, 'employee': find(db, 'Employee', record['employeeId']), 'leaveType': find(db, 'LeaveType', record['leaveTypeId'])}


@router.get('/leave-balances')
def balances(scope: str = '', user=Depends(staff), db=Depends(get_db)):
    own = employee_id(db, user) if not privileged(user) or scope == 'self' else None
    if not own and (not privileged(user) or scope == 'self'):
        return []
    tbl = table(db, 'LeaveBalance')
    query = select(tbl).order_by(tbl.c.year.desc(), tbl.c.employeeId)
    if own:
        query = query.where(tbl.c.employeeId == own)
    return output([balance_detail(db, dto(tbl, row)) for row in db.execute(query).mappings()])


def balance_unique(db, owner, leave_type, year, exclude=None):
    tbl = table(db, 'LeaveBalance')
    query = select(tbl.c.id).where(tbl.c.employeeId == owner, tbl.c.leaveTypeId == leave_type, tbl.c.year == year)
    if exclude:
        query = query.where(tbl.c.id != exclude)
    if db.scalar(query.limit(1)):
        raise HTTPException(409, 'A balance already exists for this employee, leave type and year')


@router.post('/leave-balances', status_code=201)
def create_balance(body: BalanceCreate, user=Depends(admin), db=Depends(get_db)):
    find(db, 'Employee', body.employeeId, lock=True)
    find(db, 'LeaveType', body.leaveTypeId)
    balance_unique(db, body.employeeId, body.leaveTypeId, body.year)
    return output(insert(db, 'LeaveBalance', body.model_dump()))


@router.get('/leave-balances/{id}')
def get_balance(id: str, user=Depends(staff), db=Depends(get_db)):
    record = find(db, 'LeaveBalance', id)
    own_or_admin(db, user, record['employeeId'])
    return output(balance_detail(db, record))


@router.patch('/leave-balances/{id}')
def patch_balance(id: str, body: BalancePatch, user=Depends(admin), db=Depends(get_db)):
    values = body.model_dump(exclude_unset=True)
    if not values or any(value is None for value in values.values()):
        raise HTTPException(422, 'Supply valid balance fields')
    initial = find(db, 'LeaveBalance', id)
    find(db, 'Employee', initial['employeeId'], lock=True)
    record = find(db, 'LeaveBalance', id, lock=True)
    balance_unique(db, record['employeeId'], record['leaveTypeId'], values.get('year', record['year']), id)
    return output(update(db, 'LeaveBalance', id, values))


@router.delete('/leave-balances/{id}')
def delete_balance(id: str, user=Depends(admin), db=Depends(get_db)):
    record = find(db, 'LeaveBalance', id)
    find(db, 'Employee', record['employeeId'], lock=True)
    return remove(db, 'LeaveBalance', id)
