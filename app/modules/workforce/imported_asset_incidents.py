"""Lost/damaged asset reporting with employee ownership and HR review."""
import logging
import mimetypes
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import PurePosixPath
from typing import Literal
from uuid import uuid4

from fastapi import Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import select, text
from starlette.datastructures import UploadFile

from app.core import imported_storage
from app.core.compatibility_routing import APIRouter, CompatibilityRoute
from app.core.imported_identity import linked_employee
from app.data.database import get_db
from app.data.imported import find, table
from app.modules.workforce.imported_assets import admin, insert, now, rows, wire
from app.modules.workforce.imported_asset_returns import actor
from app.modules.workforce.imported_employee_profile import full_name
from app.modules.workforce.imported_organization import update


class IncidentRoute(CompatibilityRoute):
    max_body_bytes = 64 * 1024 * 1024 + 65536


router = APIRouter(prefix='/api', tags=['HRMS asset incidents'], route_class=IncidentRoute)
Status = Literal['UNDER_REVIEW', 'APPROVED', 'RESOLVED', 'REJECTED']
Priority = Literal['LOW', 'MEDIUM', 'HIGH']
IncidentType = Literal['LOST', 'DAMAGED']


def inr(value):
    if value is None:
        return None
    digits = str(Decimal(value).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    tail, rest = digits[-3:], digits[:-3]
    groups = []
    while rest:
        groups.insert(0, rest[-2:])
        rest = rest[:-2]
    return '₹' + ','.join(groups + [tail])


def list_dto(db, record):
    asset, employee = find(db, 'Asset', record['assetId']), find(db, 'Employee', record['reporterEmployeeId'])
    return {**{key: record[key] for key in ('id', 'incidentNumber', 'incidentType', 'priority', 'status')},
            'assetTag': asset['assetTag'], 'assetName': asset['name'], 'employeeName': full_name(employee),
            'incidentDate': record['incidentDate'].isoformat(), 'reportedAt': record['createdAt'].isoformat() + 'Z',
            'estimatedCost': str(record['estimatedCost']) if record['estimatedCost'] is not None else None,
            'estimatedCostFormatted': inr(record['estimatedCost'])}


@router.get('/lost-damage-incidents')
def incidents(status: Status | None = None, priority: Priority | None = None, type: IncidentType | None = None,
              user=Depends(actor), db=Depends(get_db)):
    tbl = table(db, 'LostDamageIncident')
    filters = []
    if user.role not in ('admin', 'hr'):
        filters.append(tbl.c.reporterEmployeeId == linked_employee(db, user)['id'])
    records = rows(db, 'LostDamageIncident', *filters, order=tbl.c.createdAt.desc())
    month = now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    stats = {'activeIncidents': sum(row['status'] in ('UNDER_REVIEW', 'APPROVED') for row in records),
             'pendingApproval': sum(row['status'] == 'UNDER_REVIEW' for row in records),
             'totalCostMtdFormatted': inr(sum((row['estimatedCost'] or Decimal(0)) for row in records if row['createdAt'] >= month)),
             'resolvedThisMonth': sum(row['status'] == 'RESOLVED' and row['updatedAt'] >= month for row in records)}
    filtered = [row for row in records if (not status or row['status'] == status) and (not priority or row['priority'] == priority) and (not type or row['incidentType'] == type)]
    return {'stats': stats, 'items': [list_dto(db, row) for row in filtered[:500]]}


class IncidentInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    assetId: str = Field(min_length=1, max_length=100)
    reporterEmployeeId: str = Field(min_length=1, max_length=100)
    incidentType: IncidentType
    incidentDate: date
    location: str = Field(min_length=1, max_length=512)
    description: str = Field(min_length=1, max_length=20000)
    estimatedCost: Decimal | None = Field(None, ge=0, max_digits=14, decimal_places=2)
    priority: Priority = 'MEDIUM'

    @field_validator('estimatedCost', mode='before')
    @classmethod
    def normalize_money(cls, value):
        return value.replace(',', '').replace('₹', '').replace(' ', '') or None if isinstance(value, str) else value


@router.post('/lost-damage-incidents', status_code=201)
async def report(request: Request, user=Depends(actor), db=Depends(get_db)):
    if 'multipart/form-data' not in request.headers.get('content-type', ''):
        raise HTTPException(415, 'Use multipart/form-data')
    files = []
    async with request.form(max_files=8, max_fields=20) as form:
        values = {key: value for key, value in form.items() if key != 'attachments'}
        if user.role not in ('admin', 'hr'):
            values['reporterEmployeeId'] = linked_employee(db, user)['id']
        try:
            body = IncidentInput.model_validate(values)
        except ValidationError as exc:
            raise HTTPException(422, [{'field': '.'.join(map(str, error['loc'])), 'message': error['msg']} for error in exc.errors()]) from None
        for file in form.getlist('attachments'):
            if not isinstance(file, UploadFile) or not file.filename:
                continue
            extension = PurePosixPath(file.filename).suffix.lower()
            if extension not in ('.jpg', '.jpeg', '.png', '.webp', '.pdf'):
                raise HTTPException(415, 'Attachments must be JPG, PNG, WebP or PDF')
            content = await file.read(8 * 1024 * 1024 + 1)
            if len(content) > 8 * 1024 * 1024:
                raise HTTPException(413, 'Each attachment must be 8 MB or smaller')
            if content:
                files.append((file.filename[:255], extension, content))
    find(db, 'Asset', body.assetId, lock=True)
    find(db, 'Employee', body.reporterEmployeeId)
    if user.role not in ('admin', 'hr'):
        allocation = table(db, 'AssetAssignment')
        if not db.execute(select(allocation.c.id).where(allocation.c.assetId == body.assetId,
                allocation.c.employeeId == body.reporterEmployeeId, allocation.c.returnedAt.is_(None))).first():
            raise HTTPException(403, 'You can only report incidents for your assigned assets')
    if db.bind.dialect.name == 'postgresql':
        db.execute(text('SELECT pg_advisory_xact_lock(7310462)'))
    tbl = table(db, 'LostDamageIncident')
    prefix = f'INC-{now().year}-'
    numbers = db.scalars(select(tbl.c.incidentNumber).where(tbl.c.incidentNumber.startswith(prefix))).all()
    next_number = max((int(value[len(prefix):]) for value in numbers if value[len(prefix):].isdigit()), default=0) + 1
    saved = []
    try:
        record = insert(db, 'LostDamageIncident', {**body.model_dump(), 'incidentNumber': prefix + str(next_number).zfill(4), 'status': 'UNDER_REVIEW'})
        metadata = []
        for filename, extension, content in files:
            key = f"lost-damage-incidents/{record['id']}/{uuid4().hex}{extension}"
            mime = mimetypes.guess_type(key)[0] or 'application/octet-stream'
            imported_storage.save(request.app.state.settings, key, content, mime)
            saved.append(key)
            metadata.append({'originalFilename': filename, 'storagePath': key, 'mimeType': mime, 'sizeBytes': len(content)})
        if metadata:
            record = update(db, 'LostDamageIncident', record['id'], {'attachmentsJson': metadata})
        result = {**list_dto(db, record), 'attachmentsJson': record['attachmentsJson']}
        db.commit()
        return result
    except Exception:
        db.rollback()
        for key in saved:
            try:
                imported_storage.remove(request.app.state.settings, key)
            except Exception:
                logging.getLogger(__name__).error('Incident attachment cleanup failed')
        raise


@router.get('/lost-damage-incidents/{id}')
def incident(id: str, user=Depends(actor), db=Depends(get_db)):
    record = find(db, 'LostDamageIncident', id)
    if user.role not in ('admin', 'hr') and record['reporterEmployeeId'] != linked_employee(db, user)['id']:
        raise HTTPException(403, 'Incident access denied')
    asset, employee = find(db, 'Asset', record['assetId']), find(db, 'Employee', record['reporterEmployeeId'])
    department = find(db, 'Department', employee['departmentId'], required=False)
    return wire({**{key: record[key] for key in ('id', 'incidentNumber', 'incidentType', 'incidentDate', 'location', 'description', 'estimatedCost', 'priority', 'status', 'createdAt', 'updatedAt', 'attachmentsJson')},
        'asset': {key: asset[key] for key in ('id', 'name', 'assetTag', 'model', 'serialNumber')},
        'reporter': {**{key: employee[key] for key in ('id', 'firstName', 'lastName', 'employeeCode')}, 'displayName': full_name(employee), 'departmentName': (department or {}).get('name')}})


class IncidentReview(BaseModel):
    model_config = ConfigDict(extra='forbid')
    status: Status


@router.patch('/lost-damage-incidents/{id}')
def review(id: str, body: IncidentReview, user=Depends(admin), db=Depends(get_db)):
    record = list_dto(db, update(db, 'LostDamageIncident', id, body.model_dump()))
    return {key: record[key] for key in ('id', 'incidentNumber', 'status', 'assetTag', 'assetName', 'employeeName')}


@router.get('/lost-damage-policy')
def policy(user=Depends(admin), db=Depends(get_db)):
    result = {}
    for key, model, fields in (('policyGuidelines', 'LostDamagePolicyGuideline', ('id', 'sortOrder', 'title', 'body')),
                               ('workflowSteps', 'LostDamageWorkflowStep', ('id', 'sortOrder', 'title', 'description', 'visual'))):
        seen, items = set(), []
        for row in rows(db, model, order=table(db, model).c.sortOrder):
            title = row['title'].strip().casefold()
            if title not in seen:
                seen.add(title)
                items.append({field: row[field] for field in fields})
        result[key] = items
    # Read only: never seed sample liability or approval policy as company policy.
    return result
