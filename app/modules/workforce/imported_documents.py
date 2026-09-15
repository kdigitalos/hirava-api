"""Employee document repository, reviews and private S3/local reads."""
import logging
import mimetypes
from datetime import date, timedelta
from pathlib import PurePosixPath
from typing import Literal
from urllib.parse import quote
from uuid import uuid4

from fastapi import Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from starlette.datastructures import UploadFile

from app.core import imported_storage
from app.core.compatibility_routing import APIRouter, CompatibilityRoute
from app.core.imported_identity import linked_employee
from app.core.security import require
from app.data.database import get_db
from app.data.imported import find, table
from app.modules.workforce.imported_assets import admin, insert, now, rows, wire
from app.modules.workforce.imported_employee_profile import details, full_name
from app.modules.workforce.imported_organization import update


class DocumentRoute(CompatibilityRoute):
    max_body_bytes = 15 * 1024 * 1024 + 65536


router = APIRouter(prefix='/api', tags=['HRMS document compatibility'], route_class=DocumentRoute)
self_actor = require('hr', 'employee', 'manager', module='hrms')


def owned_document(db, document_id, employee_id):
    record = find(db, 'EmployeeDocument', document_id, lock=True)
    if record['employeeId'] != employee_id:
        raise HTTPException(404, 'Document not found')
    return record


def delete_document(db, user, record):
    from app.workers.imported_storage_cleanup import queue_delete
    tbl = table(db, 'EmployeeDocument')
    db.execute(tbl.delete().where(tbl.c.id == record['id']))
    # Preserve a shared object while another imported document still references it.
    if not db.scalar(select(tbl.c.id).where(tbl.c.storagePath == record['storagePath']).limit(1)):
        queue_delete(db, user.customer_id, record['storagePath'])
    return Response(status_code=204)


@router.delete('/employees/{id}/documents/{docId}')
def delete_profile_document(id: str, docId: str, user=Depends(admin), db=Depends(get_db)):
    return delete_document(db, user, owned_document(db, docId, id))


@router.delete('/employee-documents/{id}')
def delete_own_document(id: str, user=Depends(self_actor), db=Depends(get_db)):
    employee = linked_employee(db, user)
    return delete_document(db, user, owned_document(db, id, employee['id']))


def document_rows(db, employee_id=None):
    tbl = table(db, 'EmployeeDocument')
    return rows(db, 'EmployeeDocument', *([tbl.c.employeeId == employee_id] if employee_id else []), order=tbl.c.uploadedAt.desc())


def display_status(record):
    if record['status'] == 'APPROVED':
        return 'Approved'
    if record['expiresAt'] and record['expiresAt'] < now().date():
        return 'Expired'
    return 'Under Review' if record['status'] == 'REJECTED' else 'Pending'


@router.get('/documents')
def documents(search: str = Query('', max_length=255), department: str = '', role: str = '', user=Depends(admin), db=Depends(get_db)):
    result = []
    for record in document_rows(db):
        employee = find(db, 'Employee', record['employeeId'])
        dept = find(db, 'Department', employee['departmentId'], required=False)
        title = find(db, 'JobTitle', employee['jobTitleId'], required=False)
        dept_name, role_name = (dept or {}).get('name', '—'), (title or {}).get('name', '—')
        name = full_name(employee)
        if search.strip() and not any(search.strip().casefold() in value.casefold() for value in (name, employee['employeeCode'], record['title'])):
            continue
        if department not in ('', 'Departments', 'All', 'All Departments', dept_name) or role not in ('', 'Role', 'All', 'All Roles', role_name):
            continue
        photo = details(employee).get('employeePhoto')
        result.append({'id': record['id'], 'employeeId': employee['id'], 'employeeName': name, 'employeeCode': employee['employeeCode'],
            'department': dept_name, 'role': role_name, 'documentName': record['title'], 'documentType': record['documentType'] or '',
            'status': display_status(record), 'expiryDate': record['expiresAt'].isoformat() if record['expiresAt'] else None,
            'createdAt': record['uploadedAt'].isoformat() + 'Z', 'avatarPhoto': '/api/uploads/' + photo.lstrip('/') if isinstance(photo, str) and photo else None})
    return result


@router.get('/documents/stats')
def document_stats(user=Depends(admin), db=Depends(get_db)):
    current = now()
    month = current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    previous = (month - timedelta(days=1)).replace(day=1)
    records = document_rows(db)
    approved = [row for row in records if row['status'] == 'APPROVED']
    this_month = sum(row['uploadedAt'] >= month for row in approved)
    last_month = sum(previous <= row['uploadedAt'] < month for row in approved)
    if last_month:
        delta = round((this_month - last_month) / last_month * 100, 1)
        label = f'{delta:+g}% from last month'
    else:
        label = f'+{this_month} this month' if this_month else '— from last month'
    employee = table(db, 'Employee')
    return {'totalEmployees': db.scalar(select(func.count()).select_from(employee)),
            'newEmployeesThisMonth': db.scalar(select(func.count()).select_from(employee).where(employee.c.createdAt >= month)),
            'documentsApprovedPercent': round(len(approved) / len(records) * 100, 1) if records else 0,
            'approvalChangeLabel': label, 'pendingReviews': sum(row['status'] in ('PENDING', 'REJECTED') for row in records),
            'pendingDueThisWeek': sum(row['status'] == 'PENDING' and row['expiresAt'] is not None and current.date() <= row['expiresAt'] <= current.date() + timedelta(days=7) for row in records),
            'expiredDocuments': sum(row['expiresAt'] is not None and row['expiresAt'] < current.date() for row in records)}


@router.get('/documents/recent-activity')
def recent_activity(user=Depends(admin), db=Depends(get_db)):
    return [{'id': row['id'], 'text': f"{row['title']} · {full_name(find(db, 'Employee', row['employeeId']))}",
             'dot': {'APPROVED': 'green', 'REJECTED': 'orange'}.get(row['status'], 'blue')} for row in document_rows(db)[:25]]


@router.get('/documents/deadlines')
def deadlines(user=Depends(admin), db=Depends(get_db)):
    today = now().date()
    records = [row for row in document_rows(db) if row['status'] != 'APPROVED' and row['expiresAt'] and today <= row['expiresAt'] <= today + timedelta(days=120)]
    result = []
    for row in sorted(records, key=lambda row: row['expiresAt'])[:8]:
        days = (row['expiresAt'] - today).days
        result.append({'id': 'd-' + row['id'], 'text': f"{row['title']} · {full_name(find(db, 'Employee', row['employeeId']))}",
                       'dot': 'orange' if days <= 14 else 'blue', 'urgency': 'urgent' if days <= 7 else 'medium' if days <= 14 else 'low',
                       'label': 'Today' if days == 0 else 'In 1 day' if days == 1 else f'In {days} days'})
    return result


async def save_document(request, db, employee_id=None, repository=False):
    if 'multipart/form-data' not in request.headers.get('content-type', ''):
        raise HTTPException(415, 'Use multipart/form-data')
    async with request.form(max_files=1, max_fields=20) as form:
        employee_id = employee_id or str(form.get('employeeId', '')).strip()
        employee = find(db, 'Employee', employee_id, lock=True)
        file = form.get('file')
        if not isinstance(file, UploadFile) or not file.filename:
            raise HTTPException(422, 'Choose a file to upload')
        extension = PurePosixPath(file.filename).suffix.lower()
        allowed = ('.pdf', '.png', '.jpg', '.jpeg', '.webp', '.doc', '.docx', '.xls', '.xlsx') if repository else ('.pdf', '.png', '.jpg', '.jpeg')
        if extension not in allowed:
            raise HTTPException(415, 'Unsupported document file type')
        limit = (15 if repository else 10) * 1024 * 1024
        content = await file.read(limit + 1)
        if not content or len(content) > limit:
            raise HTTPException(413, f'Choose a nonempty file no larger than {limit // 1024 // 1024} MB')
        title = str(form.get('documentName' if repository else 'title', '')).strip()
        doc_type = str(form.get('documentType', '')).strip()
        if repository and (not title or not doc_type):
            raise HTTPException(422, 'Document name and type are required')
        expiry = str(form.get('expiryDate', '')).strip() if repository else ''
        try:
            expiry_date = date.fromisoformat(expiry) if expiry else None
        except ValueError:
            raise HTTPException(422, 'Use YYYY-MM-DD for expiry date') from None
        values = {'employeeId': employee_id, 'category': str(form.get('category', 'general')).strip() or 'general',
                  'title': title or PurePosixPath(file.filename).stem or 'Untitled', 'documentType': doc_type or None,
                  'originalFilename': file.filename[:240], 'mimeType': mimetypes.guess_type(file.filename)[0] or 'application/octet-stream',
                  'sizeBytes': len(content), 'expiresAt': expiry_date, 'status': 'PENDING', 'uploadedAt': now()}
    key = f"{'documents' if repository else 'employee-documents'}/{employee_id}/{uuid4().hex}{extension}"
    saved = False
    try:
        imported_storage.save(request.app.state.settings, key, content, values['mimeType'])
        saved = True
        record = insert(db, 'EmployeeDocument', {**values, 'storagePath': key})
        db.commit()
    except Exception:
        db.rollback()
        if saved:
            try:
                imported_storage.remove(request.app.state.settings, key)
            except Exception:
                logging.getLogger(__name__).error('Document upload cleanup failed')
        raise
    return {'id': record['id'], 'message': f'Uploaded for {full_name(employee)}'} if repository else wire(record)


@router.post('/documents/upload', status_code=201)
async def repository_upload(request: Request, user=Depends(admin), db=Depends(get_db)):
    return await save_document(request, db, repository=True)


@router.get('/employees/{id}/documents')
def employee_documents(id: str, user=Depends(admin), db=Depends(get_db)):
    find(db, 'Employee', id)
    return wire(document_rows(db, id))


@router.post('/employees/{id}/documents', status_code=201)
async def employee_upload(id: str, request: Request, user=Depends(admin), db=Depends(get_db)):
    return await save_document(request, db, employee_id=id)


@router.get('/employee-documents')
def own_documents(user=Depends(self_actor), db=Depends(get_db)):
    employee = linked_employee(db, user, required=False)
    return wire(document_rows(db, employee['id'])) if employee else []


@router.post('/employee-documents', status_code=201)
async def own_upload(request: Request, user=Depends(self_actor), db=Depends(get_db)):
    return await save_document(request, db, employee_id=linked_employee(db, user)['id'])


@router.get('/employee-documents/{id}')
def own_document(id: str, user=Depends(self_actor), db=Depends(get_db)):
    return wire(owned_document(db, id, linked_employee(db, user)['id']))


class DocumentPatch(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    status: Literal['PENDING', 'APPROVED', 'REJECTED'] | None = None
    rejectionReason: str | None = Field(None, max_length=20000)
    title: str | None = Field(None, min_length=1, max_length=1000)
    documentType: str | None = Field(None, max_length=255)


@router.patch('/employees/{id}/documents/{docId}')
def review_document(id: str, docId: str, body: DocumentPatch, user=Depends(admin), db=Depends(get_db)):
    existing = owned_document(db, docId, id)
    values = body.model_dump(exclude_unset=True)
    if any(key in values and values[key] is None for key in ('title', 'status')):
        raise HTTPException(422, 'Title and status cannot be empty')
    status = values.get('status', existing['status'])
    if status == 'REJECTED' and not values.get('rejectionReason', existing['rejectionReason']):
        raise HTTPException(422, 'A rejection reason is required')
    if status != 'REJECTED':
        values['rejectionReason'] = None
    return wire(update(db, 'EmployeeDocument', docId, values))


def stream_document(request, record, inline):
    stream, _ = imported_storage.open_file(request.app.state.settings, record['storagePath'])
    def chunks():
        try:
            while chunk := stream.read(65536):
                yield chunk
        finally:
            stream.close()
    mime = record['mimeType'] or 'application/octet-stream'
    mode = 'inline' if inline and (mime == 'application/pdf' or mime.startswith('image/')) else 'attachment'
    filename = quote(record['originalFilename'], safe='')
    return StreamingResponse(chunks(), media_type=mime,
        headers={'Content-Disposition': f"{mode}; filename*=UTF-8''{filename}", 'Cache-Control': 'private, no-store'})


@router.get('/documents/{id}/download')
def repository_download(id: str, request: Request, user=Depends(admin), db=Depends(get_db)):
    return stream_document(request, find(db, 'EmployeeDocument', id), request.query_params.get('view') == '1' or request.query_params.get('inline') == '1')


@router.get('/employee-documents/{id}/download')
def own_download(id: str, request: Request, user=Depends(self_actor), db=Depends(get_db)):
    return stream_document(request, owned_document(db, id, linked_employee(db, user)['id']), request.query_params.get('download') != '1')


@router.get('/employees/{id}/documents/{docId}/download')
def employee_download(id: str, docId: str, request: Request, user=Depends(admin), db=Depends(get_db)):
    return stream_document(request, owned_document(db, docId, id), request.query_params.get('download') != '1')
