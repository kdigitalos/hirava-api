"""Imported employee directory. Account permissions remain native-core authority."""
import logging
import mimetypes
from datetime import date, datetime
from pathlib import PurePosixPath
from typing import Literal
from uuid import uuid4

from fastapi import Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import func, select
from starlette.datastructures import UploadFile

from app.core import imported_storage
from app.core.compatibility_routing import APIRouter
from app.core.imported_identity import linked_employee
from app.core.security import require
from app.data.database import get_db
from app.data.imported import dto, find, table
from app.modules.workforce.imported_assets import admin, insert, rows, wire
from app.modules.workforce.imported_shared import UploadRoute
from app.modules.workforce.imported_organization import update

router = APIRouter(prefix='/api', tags=['HRMS employee directory'], route_class=UploadRoute)
EmployeeStatus = Literal['ACTIVE', 'PROBATION', 'ON_LEAVE', 'TERMINATED']


def full_employee(db, record):
    return {**record, 'department': find(db, 'Department', record['departmentId'], required=False),
            'jobTitle': find(db, 'JobTitle', record['jobTitleId'], required=False),
            'user': find(db, 'User', record['userId'], required=False)}


class EmployeePatch(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    userId: str | None = None
    employeeCode: str | None = Field(None, min_length=1, max_length=64)
    firstName: str | None = Field(None, min_length=1, max_length=255)
    lastName: str | None = Field(None, min_length=1, max_length=255)
    email: str | None = Field(None, max_length=255)
    phone: str | None = Field(None, max_length=64)
    departmentId: str | None = Field(None, max_length=100)
    jobTitleId: str | None = Field(None, max_length=100)
    status: EmployeeStatus | None = None
    employeeDetails: dict | None = None
    hireDate: date | None = None
    terminationDate: date | None = None

    @field_validator('hireDate', 'terminationDate', mode='before')
    @classmethod
    def date_value(cls, value):
        if not value:
            return None
        if isinstance(value, str):
            value = value[:10]
            try:
                return date.fromisoformat(value)
            except ValueError:
                for fmt in ('%d-%m-%Y', '%d/%m/%Y'):
                    try:
                        return datetime.strptime(value, fmt).date()
                    except ValueError:
                        pass
        return value


class EmployeeInput(EmployeePatch):
    employeeCode: str = Field(min_length=1, max_length=64)
    firstName: str = Field(min_length=1, max_length=255)
    lastName: str = Field(min_length=1, max_length=255)
    status: EmployeeStatus = 'ACTIVE'


def validate_references(db, values, existing=None):
    if 'userId' in values:
        requested = values.pop('userId')
        if requested != (existing or {}).get('userId'):
            raise HTTPException(409, 'Manage account links through Account Access')
    for key, model in (('departmentId', 'Department'), ('jobTitleId', 'JobTitle')):
        if key in values:
            values[key] = values[key] or None
            if values[key]:
                find(db, model, values[key])
    if any(key in values and values[key] is None for key in ('employeeCode', 'firstName', 'lastName', 'status')):
        raise HTTPException(422, 'Employee code, name and status cannot be empty')


@router.get('/employees')
def employees(user=Depends(admin), db=Depends(get_db)):
    tbl = table(db, 'Employee')
    records = rows(db, 'Employee', order=tbl.c.lastName)
    return wire([full_employee(db, row) for row in sorted(records, key=lambda row: (row['lastName'], row['firstName']))])


@router.post('/employees', status_code=201)
async def create_employee(request: Request, user=Depends(admin), db=Depends(get_db)):
    photo = None
    designation = None
    if 'multipart/form-data' in request.headers.get('content-type', ''):
        async with request.form(max_files=1, max_fields=40) as form:
            required = ('firstName', 'lastName', 'contact', 'email', 'userName', 'employeeCode', 'address',
                        'designation', 'hireDate', 'location', 'manager', 'accountHolderName', 'accountNumber', 'bankName', 'branchName')
            data = {key: str(form.get(key, '')).strip() for key in required}
            missing = [key for key, value in data.items() if not value]
            if missing:
                raise HTTPException(422, 'Missing required fields: ' + ', '.join(missing))
            file = form.get('employeePhoto')
            if not isinstance(file, UploadFile) or not file.filename:
                raise HTTPException(422, 'Employee photo is required')
            extension = PurePosixPath(file.filename).suffix.lower()
            if extension not in ('.jpg', '.jpeg', '.png', '.webp'):
                raise HTTPException(422, 'Photo must be JPG, PNG or WebP')
            content = await file.read(5 * 1024 * 1024 + 1)
            if not content or len(content) > 5 * 1024 * 1024:
                raise HTTPException(413, 'Photo must be nonempty and at most 5 MB')
            photo = (extension, content)
            designation = data['designation']
            body = {key: data[key] for key in ('firstName', 'lastName', 'email', 'employeeCode', 'hireDate')}
            body.update(phone=data['contact'], departmentId=str(form.get('departmentId', '')).strip() or None,
                        employeeDetails={key: data[key] for key in ('userName', 'address', 'location', 'manager',
                            'accountHolderName', 'accountNumber', 'bankName', 'branchName')})
    else:
        try:
            body = await request.json()
        except ValueError:
            raise HTTPException(422, 'Invalid JSON body') from None
    try:
        values = EmployeeInput.model_validate(body).model_dump()
    except ValidationError as exc:
        raise HTTPException(422, [{'field': '.'.join(map(str, error['loc'])), 'message': error['msg']} for error in exc.errors()]) from None
    validate_references(db, values)
    saved = None
    try:
        if designation:
            titles = table(db, 'JobTitle')
            title_id = db.scalar(select(titles.c.id).where(func.lower(titles.c.name) == designation.lower()))
            values['jobTitleId'] = title_id or insert(db, 'JobTitle', {'name': designation})['id']
        record = insert(db, 'Employee', {**values, 'orgSortOrder': 0})
        if photo:
            extension, content = photo
            key = f"employees/{record['id']}/{uuid4().hex}{extension}"
            imported_storage.save(request.app.state.settings, key, content, mimetypes.guess_type(key)[0])
            saved = key
            record = update(db, 'Employee', record['id'], {'employeeDetails': {**(record['employeeDetails'] or {}), 'employeePhoto': key}})
        result = full_employee(db, record) if photo else record
        db.commit()
        return wire(result)
    except Exception:
        db.rollback()
        if saved:
            try:
                imported_storage.remove(request.app.state.settings, saved)
            except Exception:
                logging.getLogger(__name__).error('Employee photo cleanup failed')
        raise


@router.get('/employees/peers')
def peers(user=Depends(require('employee', 'manager', module='hrms')), db=Depends(get_db)):
    if user.role == 'admin':
        raise HTTPException(400, 'Use the employee directory from the administrator account')
    mine = linked_employee(db, user, required=False)
    if not mine:
        return []
    tbl = table(db, 'Employee')
    result = []
    for row in rows(db, 'Employee', tbl.c.id != mine['id'], tbl.c.status == 'ACTIVE', order=tbl.c.lastName):
        title = find(db, 'JobTitle', row['jobTitleId'], required=False)
        result.append({**{key: row[key] for key in ('id', 'firstName', 'lastName', 'email')},
                       'jobTitle': {'name': title['name']} if title else None})
    return result


@router.get('/employees/{id}')
def employee(id: str, user=Depends(admin), db=Depends(get_db)):
    return wire(full_employee(db, find(db, 'Employee', id)))


@router.patch('/employees/{id}')
def patch_employee(id: str, body: EmployeePatch, user=Depends(admin), db=Depends(get_db)):
    existing = find(db, 'Employee', id, lock=True)
    values = body.model_dump(exclude_unset=True)
    validate_references(db, values, existing)
    return wire(update(db, 'Employee', id, values))


@router.delete('/employees/{id}')
def delete_employee(id: str, user=Depends(admin), db=Depends(get_db)):
    find(db, 'Employee', id, lock=True)
    # Directory entries anchor documents, allocations and employment history.
    raise HTTPException(409, 'Employee history is retained. Use Exit Management to end employment.')
