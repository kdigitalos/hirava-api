"""Recorded full-and-final settlements; these routes do not execute payments."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Literal

from fastapi import Depends, HTTPException, Response
from pydantic import Field, field_validator

from app.core.compatibility_routing import APIRouter
from app.core.imported_identity import linked_employee
from app.data.database import get_db
from app.data.imported import find, table
from app.modules.workforce.imported_assets import admin, insert, rows
from app.modules.workforce.imported_attendance import calendar_date
from app.modules.workforce.imported_employee_profile import details, full_name
from app.modules.workforce.imported_leave import Input, output
from app.modules.workforce.imported_organization import update

router = APIRouter(prefix='/api/fnf-settlements', tags=['HRMS settlement records'])


class SettlementInput(Input):
    employeeId: str | None = Field(None, min_length=1, max_length=255)
    exitDate: str | None = None
    departmentLabel: str | None = Field(None, min_length=1, max_length=255)
    netAmount: str | float | int | None = None
    companyPayout: str | float | int | None = None
    employeeRecovery: str | float | int | None = None
    exitRequestId: str | None = Field(None, max_length=255)
    status: Literal['DRAFT', 'UNDER_REVIEW', 'APPROVED', 'COMPLETED', 'OVERDUE'] | None = None
    notes: str | None = Field(None, max_length=20000)

    @field_validator('status', mode='before')
    @classmethod
    def normalize(cls, value):
        return value.strip().upper().replace(' ', '_') if isinstance(value, str) else value


def paise(value, required=False):
    if value is None or value == '':
        if required:
            raise HTTPException(422, 'Enter the net settlement amount in INR')
        return None
    try:
        amount = Decimal(str(value).replace(',', '').strip())
        if not amount.is_finite() or abs(amount) > Decimal('21474836.47'):
            raise ValueError()
        return int((amount * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError):
        raise HTTPException(422, 'Enter a valid settlement amount within the supported range') from None


def display_inr(value):
    whole, fraction = divmod(abs(value), 100)
    digits = str(whole)
    tail = digits[-3:]
    head = digits[:-3]
    groups = []
    while head:
        groups.insert(0, head[-2:])
        head = head[:-2]
    return ('-' if value < 0 else '') + '₹' + ','.join(groups + [tail]) + (f'.{fraction:02}' if fraction else '')


def settlement_payload(db, record):
    employee = find(db, 'Employee', record['employeeId'])
    photo = details(employee).get('employeePhoto')
    linked_user = find(db, 'User', employee['userId'], required=False)
    avatar = (photo if photo.startswith(('http://', 'https://')) else '/api/uploads/' + photo.lstrip('/')) if isinstance(photo, str) and photo else (linked_user or {}).get('picture')
    return {**{key: record[key] for key in ('id', 'employeeId', 'exitRequestId', 'netAmountPaise', 'companyPayoutPaise', 'employeeRecoveryPaise', 'status', 'notes', 'createdAt', 'updatedAt')},
        'name': full_name(employee), 'empId': employee['employeeCode'], 'initials': (employee['firstName'][:1] + employee['lastName'][:1]).upper(),
        'avatarColor': 'bg-indigo-200 text-indigo-700', 'avatarPhoto': avatar, 'exitDateIso': record['exitDate'].isoformat(),
        'exitDateDisplay': record['exitDate'].strftime('%d %b %Y'), 'department': record['departmentLabel'],
        'netAmountDisplay': display_inr(record['netAmountPaise']), 'statusLabel': record['status'].replace('_', ' ').title()}


def settlement_values(db, body, existing=None):
    values = body.model_dump(exclude_unset=True)
    for key in ('employeeId', 'exitDate', 'departmentLabel', 'netAmount'):
        if (existing is None or key in values) and (values.get(key) is None or values.get(key) == ''):
            raise HTTPException(422, f'Enter the settlement {key}')
    if existing and body.employeeId and body.employeeId != existing['employeeId']:
        raise HTTPException(409, 'A settlement cannot be moved to another employee')
    if 'status' in values and values['status'] is None:
        raise HTTPException(422, 'Select a settlement status')
    if 'exitDate' in values:
        values['exitDate'] = calendar_date(values['exitDate'])
    for field, column in (('netAmount', 'netAmountPaise'), ('companyPayout', 'companyPayoutPaise'), ('employeeRecovery', 'employeeRecoveryPaise')):
        if field in values:
            values[column] = paise(values.pop(field), field == 'netAmount')
    merged = {**(existing or {}), **values}
    owner = merged['employeeId']
    find(db, 'Employee', owner)
    if merged.get('exitRequestId'):
        linked_exit = find(db, 'ExitRequest', merged['exitRequestId'], lock=True)
        if linked_exit['employeeId'] != owner:
            raise HTTPException(422, 'Select an exit belonging to the settlement employee')
    return values


@router.get('')
def settlements(user=Depends(admin), db=Depends(get_db)):
    return output({'settlements': [settlement_payload(db, record) for record in rows(db, 'FnfSettlement', order=table(db, 'FnfSettlement').c.exitDate.desc())]})


@router.post('', status_code=201)
def add_settlement(body: SettlementInput, user=Depends(admin), db=Depends(get_db)):
    values = settlement_values(db, body)
    if values.get('status', 'DRAFT') != 'DRAFT':
        raise HTTPException(422, 'Create a draft settlement before submitting it for review')
    values['status'] = 'DRAFT'
    return output({'settlement': settlement_payload(db, insert(db, 'FnfSettlement', values))})


@router.get('/{id}')
def settlement(id: str, user=Depends(admin), db=Depends(get_db)):
    return output({'settlement': settlement_payload(db, find(db, 'FnfSettlement', id))})


@router.patch('/{id}')
def patch_settlement(id: str, body: SettlementInput, user=Depends(admin), db=Depends(get_db)):
    # Match exit-deletion lock order, preventing a settlement/exit deadlock.
    existing = find(db, 'FnfSettlement', id)
    for exit_id in sorted({key for key in (existing['exitRequestId'], body.exitRequestId) if key}):
        find(db, 'ExitRequest', exit_id, lock=True)
    existing = find(db, 'FnfSettlement', id, lock=True)
    if existing['status'] == 'COMPLETED':
        raise HTTPException(409, 'Completed settlements are closed')
    values = settlement_values(db, body, existing)
    if not values:
        raise HTTPException(422, 'Supply a settlement change')
    target = values.get('status', existing['status'])
    if target in ('APPROVED', 'COMPLETED'):
        own = linked_employee(db, user, required=False)
        if own and own['id'] == existing['employeeId']:
            raise HTTPException(403, 'Another HR administrator must approve your settlement')
    transitions = {'DRAFT': ('UNDER_REVIEW', 'OVERDUE'), 'UNDER_REVIEW': ('DRAFT', 'APPROVED', 'OVERDUE'), 'OVERDUE': ('UNDER_REVIEW', 'APPROVED'), 'APPROVED': ('COMPLETED',)}
    if target != existing['status'] and target not in transitions.get(existing['status'], ()):
        raise HTTPException(409, 'Submit the settlement for review before approval and completion')
    if existing['status'] == 'APPROVED' and any(key not in ('status', 'notes') and value != existing.get(key) for key, value in values.items()):
        raise HTTPException(409, 'Approved settlement amounts and ownership are locked')
    return output({'settlement': settlement_payload(db, update(db, 'FnfSettlement', id, values))})


@router.delete('/{id}')
def delete_settlement(id: str, user=Depends(admin), db=Depends(get_db)):
    existing = find(db, 'FnfSettlement', id, lock=True)
    if existing['status'] != 'DRAFT':
        raise HTTPException(409, 'Only draft settlements can be deleted')
    tbl = table(db, 'FnfSettlement')
    db.execute(tbl.delete().where(tbl.c.id == id))
    return Response(status_code=204)
