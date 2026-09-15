"""Asset assignment actions used inside the employee profile."""
from datetime import date, datetime, time
from decimal import Decimal
from uuid import uuid4

from fastapi import Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from app.core.compatibility_routing import APIRouter
from app.data.database import get_db
from app.data.imported import find, table
from app.modules.workforce.imported_assets import AllocationPatch, Condition, admin, insert, now, return_asset, rows, wire
from app.modules.workforce.imported_employee_profile import details, full_name

router = APIRouter(prefix='/api/employees', tags=['HRMS employee assets'])


def assignment_dto(db, assignment):
    asset = find(db, 'Asset', assignment['assetId'])
    category = find(db, 'AssetCategory', asset['categoryId'], required=False)
    return wire({'id': assignment['id'], 'assignedAt': assignment['assignedAt'], 'notes': assignment['notes'],
        'asset': {**{key: asset[key] for key in ('id', 'assetTag', 'name', 'model', 'condition', 'status', 'purchaseValue', 'notes')},
                  'category': (category or {}).get('name')}})


@router.get('/{id}/assets')
def employee_assets(id: str, user=Depends(admin), db=Depends(get_db)):
    employee = find(db, 'Employee', id)
    department = find(db, 'Department', employee['departmentId'], required=False)
    title = find(db, 'JobTitle', employee['jobTitleId'], required=False)
    designation = find(db, 'Designation', employee['designationId'], required=False)
    metadata = details(employee)
    assignments = table(db, 'AssetAssignment')
    return {'employee': {'id': id, 'name': full_name(employee), 'jobTitle': (title or {}).get('name') or (designation or {}).get('title') or '—',
                         'department': (department or {}).get('name'), 'location': metadata.get('location') or employee['workLocation'] or '—',
                         'status': employee['status'], 'avatarPhoto': metadata.get('avatarPhoto') or metadata.get('photoUrl')},
            'assignments': [assignment_dto(db, row) for row in rows(db, 'AssetAssignment', assignments.c.employeeId == id,
                            assignments.c.returnedAt.is_(None), order=assignments.c.assignedAt.desc())]}


class ProfileAssetInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    assetName: str = Field(min_length=1, max_length=255)
    assetType: str = Field('', max_length=255)
    condition: Condition = 'NEW'
    dateHandedToEmployee: date | None = None
    originalPrice: Decimal | None = Field(None, ge=0, max_digits=14, decimal_places=2)
    displaySize: str = Field('', max_length=255)
    notes: str = Field('', max_length=20000)


@router.post('/{id}/assets', status_code=201)
def add_employee_asset(id: str, body: ProfileAssetInput, user=Depends(admin), db=Depends(get_db)):
    employee = find(db, 'Employee', id, lock=True)
    notes = '\n'.join(value for value in (f'Display Size: {body.displaySize}' if body.displaySize else '', body.notes) if value)
    asset = insert(db, 'Asset', {'assetTag': 'AST-' + uuid4().hex[:20].upper(), 'name': body.assetName,
        'model': body.assetType or None, 'condition': body.condition, 'status': 'ALLOCATED', 'purchaseValue': body.originalPrice,
        'location': details(employee).get('location') or employee['workLocation'] or '—', 'notes': notes})
    assignment = insert(db, 'AssetAssignment', {'assetId': asset['id'], 'employeeId': id,
        'assignedAt': datetime.combine(body.dateHandedToEmployee or now().date(), time.min), 'notes': body.notes or None})
    return assignment_dto(db, assignment)


@router.delete('/{id}/assets/{assignmentId}', status_code=204)
def release_employee_asset(id: str, assignmentId: str, user=Depends(admin), db=Depends(get_db)):
    original = find(db, 'AssetAssignment', assignmentId)
    find(db, 'Asset', original['assetId'], lock=True)
    assignment = find(db, 'AssetAssignment', assignmentId, lock=True)
    if assignment['employeeId'] != id:
        raise HTTPException(404, 'Allocation not found')
    if assignment['returnedAt'] is None:
        return_asset(assignmentId, AllocationPatch(returnedAt=now()), user=user, db=db)
    return Response(status_code=204)
