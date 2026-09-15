"""Employee return requests and HR allocation history on existing tables."""
from datetime import date
from typing import Literal

from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.core.compatibility_routing import APIRouter
from app.core.imported_identity import linked_employee
from app.core.security import require
from app.data.database import get_db
from app.data.imported import find, table
from app.modules.workforce.imported_assets import admin, insert, now, rows

router = APIRouter(prefix='/api', tags=['HRMS asset returns'])
actor = require('hr', 'employee', 'manager', module='hrms')


def return_dto(db, record):
    allocation = find(db, 'AssetAssignment', record['assetAssignmentId'])
    asset = find(db, 'Asset', allocation['assetId'])
    employee = find(db, 'Employee', allocation['employeeId'])
    return {'id': record['id'], 'assetId': asset['assetTag'], 'assetName': asset['name'],
            'employee': f"{employee['firstName']} {employee['lastName']}".strip(),
            'requestDate': record['requestedAt'].strftime('%d-%m-%Y'),
            'expectedReturn': record['expectedReturnDate'].strftime('%d-%m-%Y'),
            'reason': record['reason'],
            'status': {'APPROVED': 'Approved', 'REJECTED': 'Rejected'}.get(record['status'], 'Pending Approval')}


@router.get('/asset-return-requests')
def requests(user=Depends(actor), db=Depends(get_db)):
    request, allocation = table(db, 'AssetReturnRequest'), table(db, 'AssetAssignment')
    filters = []
    if user.role not in ('admin', 'hr'):
        employee = linked_employee(db, user)
        filters.append(request.c.assetAssignmentId.in_(select(allocation.c.id).where(allocation.c.employeeId == employee['id'])))
    return [return_dto(db, row) for row in rows(db, 'AssetReturnRequest', *filters, order=request.c.requestedAt.desc())]


class ReturnInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    assetAssignmentId: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=20000)
    expectedReturnDate: date


@router.post('/asset-return-requests', status_code=201)
def request_return(body: ReturnInput, user=Depends(actor), db=Depends(get_db)):
    owner = None if user.role in ('admin', 'hr') else linked_employee(db, user)['id']
    allocation = find(db, 'AssetAssignment', body.assetAssignmentId, lock=True)
    if allocation['returnedAt'] is not None or owner and allocation['employeeId'] != owner:
        raise HTTPException(404, 'Active allocation not found or not owned by you')
    request = table(db, 'AssetReturnRequest')
    if db.execute(select(request.c.id).where(request.c.assetAssignmentId == body.assetAssignmentId,
                                           request.c.status == 'PENDING_APPROVAL')).first():
        raise HTTPException(409, 'A pending return request already exists')
    record = insert(db, 'AssetReturnRequest', {**body.model_dump(), 'requestedAt': now(), 'status': 'PENDING_APPROVAL'})
    return return_dto(db, record)


class ReviewInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(min_length=1, max_length=100)
    status: Literal['APPROVED', 'REJECTED']


@router.patch('/asset-return-requests')
def review_return(body: ReviewInput, user=Depends(admin), db=Depends(get_db)):
    request = table(db, 'AssetReturnRequest')
    changed = db.execute(request.update().where(request.c.id == body.id, request.c.status == 'PENDING_APPROVAL')
                         .values(status=body.status, updatedAt=now()))
    if changed.rowcount != 1:
        raise HTTPException(409, 'Request is missing or already reviewed')
    return body.model_dump()


@router.get('/asset-assignments/timeline')
def timeline(user=Depends(admin), db=Depends(get_db)):
    events = []
    def append(event_id, title, allocation, at):
        asset = find(db, 'Asset', allocation['assetId'])
        employee = find(db, 'Employee', allocation['employeeId'])
        events.append({'id': event_id, 'event': title,
                       'detail': f"{asset['assetTag']} · {employee['firstName']} {employee['lastName']}".strip(),
                       'date': at.strftime('%d-%m-%Y'), 'time': at.strftime('%I:%M %p').lstrip('0'),
                       'timestamp': at.isoformat() + 'Z'})
    assignment, request = table(db, 'AssetAssignment'), table(db, 'AssetReturnRequest')
    for record in rows(db, 'AssetAssignment', order=assignment.c.createdAt.desc())[:400]:
        append(f"alloc-{record['id']}", 'Asset Allocated', record, record['createdAt'])
        if record['returnedAt']:
            append(f"returned-{record['id']}", 'Asset Returned', record, record['returnedAt'])
    for record in rows(db, 'AssetReturnRequest', order=request.c.requestedAt.desc())[:400]:
        allocation = find(db, 'AssetAssignment', record['assetAssignmentId'])
        append(f"return-req-{record['id']}", 'Return Requested', allocation, record['requestedAt'])
        if record['status'] in ('APPROVED', 'REJECTED'):
            approved = record['status'] == 'APPROVED'
            append(f"return-{'appr' if approved else 'rej'}-{record['id']}",
                   'Return Approved' if approved else 'Return Rejected', allocation, record['updatedAt'])
    return sorted(events, key=lambda event: event['timestamp'], reverse=True)
