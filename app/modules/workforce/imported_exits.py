"""Exit filing, private attachments and independently reviewed transitions."""
import logging
from pathlib import PurePosixPath
from typing import Literal
from uuid import uuid4

from fastapi import Depends, HTTPException, Request, Response
from pydantic import Field, ValidationError
from sqlalchemy import select
from starlette.datastructures import UploadFile

from app.core import imported_storage
from app.core.compatibility_routing import APIRouter, CompatibilityRoute
from app.core.imported_identity import linked_employee
from app.data.database import get_db
from app.data.imported import find, table
from app.modules.workforce.imported_assets import admin, insert, rows
from app.modules.workforce.imported_attendance import calendar_date
from app.modules.workforce.imported_leave import Input, output, privileged, staff
from app.modules.workforce.imported_organization import update
from app.workers.imported_storage_cleanup import queue_delete


class ExitRoute(CompatibilityRoute):
    max_body_bytes = 80 * 1024 * 1024 + 65536


router = APIRouter(prefix='/api/exit-requests', tags=['HRMS exits'], route_class=ExitRoute)
STATES = Literal['PENDING', 'PENDING_HR', 'APPROVED', 'IN_PROGRESS', 'COMPLETED', 'REJECTED']
TRANSITIONS = {'PENDING': ('PENDING_HR', 'APPROVED', 'REJECTED'), 'PENDING_HR': ('APPROVED', 'REJECTED'),
               'APPROVED': ('IN_PROGRESS',), 'IN_PROGRESS': ('COMPLETED',)}
MIMES = {'.pdf': 'application/pdf', '.doc': 'application/msword', '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'}


class ExitInput(Input):
    employeeId: str | None = Field(None, max_length=255)
    status: STATES | None = None
    lastWorkingDate: str | None = None
    resignationDate: str | None = None
    reason: str | None = Field(None, max_length=20000)
    exitType: str | None = Field(None, max_length=255)
    additionalNotes: str | None = Field(None, max_length=20000)
    noticeWaived: bool = False
    employeeCodeEntered: str | None = Field(None, max_length=255)
    fullNameEntered: str | None = Field(None, max_length=1000)
    departmentEntered: str | None = Field(None, max_length=1000)
    managerEntered: str | None = Field(None, max_length=1000)
    contactEmail: str | None = Field(None, max_length=320)
    policyAccepted: bool = False
    isDraft: bool = False


def exit_record(db, id, user, deciding=False):
    record = find(db, 'ExitRequest', id, lock=True)
    own = linked_employee(db, user, required=False)
    if not privileged(user) and (not own or own['id'] != record['employeeId']):
        raise HTTPException(403, 'Exit access denied')
    if deciding and own and own['id'] == record['employeeId']:
        raise HTTPException(403, 'Another HR administrator must review your exit')
    return record


def full_exit(db, record):
    employee = find(db, 'Employee', record['employeeId'])
    employee['department'] = find(db, 'Department', employee['departmentId'], required=False)
    employee['jobTitle'] = find(db, 'JobTitle', employee['jobTitleId'], required=False)
    manager = find(db, 'Employee', employee['reportsToEmployeeId'], required=False)
    employee['reportsToEmployee'] = {key: manager[key] for key in ('firstName', 'lastName', 'employeeCode')} if manager else None
    settlements = rows(db, 'FnfSettlement', table(db, 'FnfSettlement').c.exitRequestId == record['id'], order=table(db, 'FnfSettlement').c.updatedAt.desc())[:1]
    return {**record, 'employee': employee, 'fnfSettlements': [{key: item[key] for key in ('status', 'updatedAt')} for item in settlements]}


def dates(values, existing=None):
    for key in ('resignationDate', 'lastWorkingDate'):
        if key in values:
            values[key] = calendar_date(values[key]) if values[key] else None
    merged = {**(existing or {}), **values}
    resignation, last = merged.get('resignationDate'), merged.get('lastWorkingDate')
    if resignation and last and (last < resignation or (not merged.get('noticeWaived') and last == resignation)):
        raise HTTPException(422, 'Last working date must follow resignation, or be the same day when notice is waived')
    return values


async def attachments(form):
    files = form.getlist('attachments')
    if len(files) > 8:
        raise HTTPException(422, 'Upload at most eight attachments at a time')
    result = []
    for file in files:
        if not isinstance(file, UploadFile):
            raise HTTPException(422, 'Choose valid attachment files')
        suffix = PurePosixPath(file.filename or '').suffix.lower()
        if suffix not in MIMES:
            raise HTTPException(422, 'Exit attachments must be PDF, DOC or DOCX files')
        content = await file.read(10 * 1024 * 1024 + 1)
        if not content or len(content) > 10 * 1024 * 1024:
            raise HTTPException(422, 'Each attachment must be between 1 byte and 10 MB')
        result.append((file.filename, suffix, content))
    return result


def save_attachments(db, settings, record, files):
    added, saved = [], []
    try:
        for name, suffix, content in files:
            key = f"exit-requests/{record['id']}/{uuid4().hex}{suffix}"
            imported_storage.save(settings, key, content, MIMES[suffix])
            saved.append(key)
            added.append({'fileName': name, 'relativePath': key})
        merged = (record['attachmentsJson'] if isinstance(record['attachmentsJson'], list) else []) + added
        update(db, 'ExitRequest', record['id'], {'attachmentsJson': merged})
        db.commit()
    except Exception:
        db.rollback()
        for key in saved:
            try:
                imported_storage.remove(settings, key)
            except Exception:
                logging.getLogger(__name__).warning('Failed exit attachment compensation')
        raise
    return {'attachments': merged, 'added': added}


@router.get('')
def exits(user=Depends(staff), db=Depends(get_db)):
    tbl = table(db, 'ExitRequest')
    if privileged(user):
        condition = tbl.c.isDraft.is_(False)
    else:
        employee = linked_employee(db, user, required=False)
        if not employee:
            return []
        condition = tbl.c.employeeId == employee['id']
    return output([full_exit(db, record) for record in rows(db, 'ExitRequest', condition, order=tbl.c.createdAt.desc())])


@router.post('', status_code=201)
async def create_exit(request: Request, user=Depends(staff), db=Depends(get_db)):
    multipart = 'multipart/form-data' in request.headers.get('content-type', '')
    files = []
    if multipart:
        async with request.form() as form:
            raw = {key: value for key, value in form.multi_items() if key != 'attachments'}
            for old, new in (('lastWorkingDay', 'lastWorkingDate'), ('exitReason', 'reason'), ('draft', 'isDraft')):
                if old in raw:
                    raw[new] = raw.pop(old)
            for key in ('noticeWaived', 'isDraft', 'policyAccepted'):
                raw[key] = raw.get(key) in ('true', 'on', '1')
            files = await attachments(form)
    else:
        try:
            raw = await request.json()
        except ValueError:
            raise HTTPException(422, 'Enter a valid exit request') from None
    try:
        body = ExitInput.model_validate(raw)
    except ValidationError:
        raise HTTPException(422, 'Check the exit request fields and their formats') from None
    own = linked_employee(db, user, required=False)
    owner = body.employeeId if privileged(user) else own['id'] if own else None
    if not owner:
        raise HTTPException(422, 'Select the employee for this exit')
    if body.status not in (None, 'PENDING'):
        raise HTTPException(422, 'New exits must be submitted for approval')
    find(db, 'Employee', owner, lock=True)
    values = dates(body.model_dump())
    values.update(employeeId=owner, status='PENDING')
    if multipart and not body.isDraft and not all(values.get(key) for key in ('exitType', 'resignationDate', 'lastWorkingDate', 'reason')):
        raise HTTPException(422, 'Enter the exit type, resignation date, last working day and reason')
    record = insert(db, 'ExitRequest', values)
    if files:
        save_attachments(db, request.app.state.settings, record, files)
        record = find(db, 'ExitRequest', record['id'])
    return output(full_exit(db, record) if multipart else record)


@router.get('/{id}')
def get_exit(id: str, user=Depends(staff), db=Depends(get_db)):
    return output(full_exit(db, exit_record(db, id, user)))


@router.patch('/{id}')
def patch_exit(id: str, body: ExitInput, user=Depends(admin), db=Depends(get_db)):
    record = exit_record(db, id, user, deciding=True)
    if record['status'] in ('COMPLETED', 'REJECTED'):
        raise HTTPException(409, 'Closed exit records cannot be edited')
    values = body.model_dump(exclude_unset=True)
    if 'employeeId' in values and values['employeeId'] != record['employeeId']:
        raise HTTPException(409, 'An exit cannot be moved to another employee')
    if 'status' in values and values['status'] != record['status'] and values['status'] not in TRANSITIONS.get(record['status'], ()):
        raise HTTPException(409, 'Invalid exit status transition')
    if values.get('status') == 'COMPLETED':
        from app.modules.workforce.imported_exit_clearance import clearance_state, all_approved
        if not all_approved(clearance_state(record['clearanceJson'])):
            raise HTTPException(409, 'Complete and approve all clearance items before closing the exit')
    return output(update(db, 'ExitRequest', id, dates(values, record)))


@router.delete('/{id}')
def delete_exit(id: str, user=Depends(admin), db=Depends(get_db)):
    record = exit_record(db, id, user, deciding=True)
    if record['status'] != 'PENDING':
        raise HTTPException(409, 'Only pending exits can be deleted')
    settlements = table(db, 'FnfSettlement')
    if db.scalar(select(settlements.c.id).where(settlements.c.exitRequestId == id).limit(1)):
        raise HTTPException(409, 'A settlement references this exit; retain the record')
    for item in record['attachmentsJson'] if isinstance(record['attachmentsJson'], list) else []:
        key = item.get('relativePath') if isinstance(item, dict) else None
        if isinstance(key, str) and key.startswith(f'exit-requests/{id}/'):
            queue_delete(db, user.customer_id, key)
    tbl = table(db, 'ExitRequest')
    db.execute(tbl.delete().where(tbl.c.id == id))
    return Response(status_code=204)


@router.post('/{id}/attachments', status_code=201)
async def append_attachments(id: str, request: Request, user=Depends(staff), db=Depends(get_db)):
    record = exit_record(db, id, user)
    if record['status'] in ('COMPLETED', 'REJECTED'):
        raise HTTPException(409, 'Closed exit records cannot receive new attachments')
    async with request.form() as form:
        files = await attachments(form)
    if not files:
        raise HTTPException(422, 'Choose at least one attachment')
    return save_attachments(db, request.app.state.settings, record, files)
