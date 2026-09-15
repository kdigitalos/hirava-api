"""Organization directory configuration on existing imported tables."""
from fastapi import Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, create_model
from sqlalchemy import func, select

from app.core.compatibility_routing import APIRouter
from app.data.database import get_db
from app.data.imported import dto, find, table
from app.modules.workforce.imported_assets import admin, insert, now, rows, wire

router = APIRouter(prefix='/api', tags=['HRMS organization compatibility'])


def count_employees(db, field, value):
    employees = table(db, 'Employee')
    return db.scalar(select(func.count()).select_from(employees).where(employees.c[field] == value))


def update(db, model, id, values):
    find(db, model, id, lock=True)
    tbl = table(db, model)
    return dto(tbl, db.execute(tbl.update().where(tbl.c.id == id).values(**values, updatedAt=now()).returning(tbl)).mappings().one())


def delete_unassigned(db, model, id, employee_field):
    find(db, model, id, lock=True)
    if count_employees(db, employee_field, id):
        raise HTTPException(409, 'Employees still use this record. Reassign them before deleting it.')
    tbl = table(db, model)
    db.execute(tbl.delete().where(tbl.c.id == id))


def designation_dto(db, record):
    return {**{key: record[key] for key in ('id', 'title', 'hierarchyLevel', 'description')},
            'employees': count_employees(db, 'designationId', record['id'])}


def department_dto(db, record):
    designation = table(db, 'Designation')
    head = find(db, 'Employee', record['departmentHeadEmployeeId'], required=False)
    return {'id': record['id'], 'name': record['name'], 'code': record['code'] or '',
            'description': record['description'] or '', 'employees': count_employees(db, 'departmentId', record['id']),
            'departmentHeadEmployeeId': record['departmentHeadEmployeeId'],
            'departmentHead': {key: head[key] for key in ('id', 'firstName', 'lastName', 'employeeCode')} if head else None,
            'designations': [designation_dto(db, item) for item in rows(db, 'Designation', designation.c.departmentId == record['id'], order=designation.c.title)]}


class NameInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=255)


class DepartmentInput(NameInput):
    code: str | None = Field(None, max_length=64)
    description: str = Field(min_length=1, max_length=8000)
    departmentHeadEmployeeId: str = Field(min_length=1, max_length=100)


class DepartmentPatch(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str | None = Field(None, min_length=1, max_length=255)
    code: str | None = Field(None, max_length=64)
    description: str | None = Field(None, max_length=8000)
    departmentHeadEmployeeId: str | None = Field(None, min_length=1, max_length=100)


@router.get('/departments')
def departments(user=Depends(admin), db=Depends(get_db)):
    return [department_dto(db, row) for row in rows(db, 'Department', order=table(db, 'Department').c.name)]


@router.post('/departments', status_code=201)
def create_department(body: DepartmentInput, user=Depends(admin), db=Depends(get_db)):
    find(db, 'Employee', body.departmentHeadEmployeeId)
    return department_dto(db, insert(db, 'Department', body.model_dump()))


@router.get('/departments/{id}')
def department(id: str, user=Depends(admin), db=Depends(get_db)):
    return department_dto(db, find(db, 'Department', id))


@router.patch('/departments/{id}')
def patch_department(id: str, body: DepartmentPatch, user=Depends(admin), db=Depends(get_db)):
    values = body.model_dump(exclude_unset=True)
    if not values or any(key in values and values[key] is None for key in ('name', 'departmentHeadEmployeeId')):
        raise HTTPException(422, 'Supply fields to update; name and department head cannot be empty')
    if body.departmentHeadEmployeeId:
        find(db, 'Employee', body.departmentHeadEmployeeId)
    return department_dto(db, update(db, 'Department', id, values))


@router.delete('/departments/{id}', status_code=204)
def delete_department(id: str, user=Depends(admin), db=Depends(get_db)):
    designation = table(db, 'Designation')
    if db.execute(select(designation.c.id).where(designation.c.departmentId == id)).first():
        raise HTTPException(409, 'Remove or reassign the department designations first')
    delete_unassigned(db, 'Department', id, 'departmentId')
    return Response(status_code=204)


class DesignationInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=255)
    hierarchyLevel: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=8000)


class DesignationPatch(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    title: str | None = Field(None, min_length=1, max_length=255)
    hierarchyLevel: str | None = Field(None, min_length=1, max_length=128)
    description: str | None = Field(None, max_length=8000)


@router.post('/departments/{id}/designations', status_code=201)
def create_designation(id: str, body: DesignationInput, user=Depends(admin), db=Depends(get_db)):
    find(db, 'Department', id, lock=True)
    return designation_dto(db, insert(db, 'Designation', {**body.model_dump(), 'departmentId': id}))


@router.patch('/designations/{id}')
def patch_designation(id: str, body: DesignationPatch, user=Depends(admin), db=Depends(get_db)):
    values = body.model_dump(exclude_unset=True)
    if not values or any(key in values and values[key] is None for key in ('title', 'hierarchyLevel')):
        raise HTTPException(422, 'Supply fields to update; title and hierarchy level cannot be empty')
    if 'description' in values and values['description'] is None:
        values['description'] = ''
    return designation_dto(db, update(db, 'Designation', id, values))


@router.delete('/designations/{id}', status_code=204)
def delete_designation(id: str, user=Depends(admin), db=Depends(get_db)):
    delete_unassigned(db, 'Designation', id, 'designationId')
    return Response(status_code=204)


@router.get('/job-titles')
def job_titles(user=Depends(admin), db=Depends(get_db)):
    return wire(rows(db, 'JobTitle', order=table(db, 'JobTitle').c.name))


@router.post('/job-titles', status_code=201)
def create_job_title(body: NameInput, user=Depends(admin), db=Depends(get_db)):
    return wire(insert(db, 'JobTitle', body.model_dump()))


@router.get('/job-titles/{id}')
def job_title(id: str, user=Depends(admin), db=Depends(get_db)):
    return wire(find(db, 'JobTitle', id))


@router.patch('/job-titles/{id}')
def patch_job_title(id: str, body: NameInput, user=Depends(admin), db=Depends(get_db)):
    return wire(update(db, 'JobTitle', id, body.model_dump()))


@router.delete('/job-titles/{id}', status_code=204)
def delete_job_title(id: str, user=Depends(admin), db=Depends(get_db)):
    delete_unassigned(db, 'JobTitle', id, 'jobTitleId')
    return Response(status_code=204)


class BranchInput(NameInput):
    code: str = Field(min_length=1, max_length=64)
    street: str = Field(min_length=1, max_length=512)
    city: str = Field(min_length=1, max_length=255)
    state: str = Field(min_length=1, max_length=255)
    zip: str = Field(min_length=1, max_length=32)
    country: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1, max_length=8000)
    email: str = Field(min_length=1, max_length=255, pattern=r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
    phone: str = Field(min_length=1, max_length=64)
    active: bool | None = None
    isActive: bool = True
    branchHeadEmployeeId: str | None = Field(None, max_length=100)


def branch_values(db, body):
    values = body.model_dump(exclude={'active', 'email', 'phone'})
    if body.active is False:
        values['isActive'] = False
    values.update(contactEmail=body.email, contactPhone=body.phone)
    values['branchHeadEmployeeId'] = body.branchHeadEmployeeId or None
    if values['branchHeadEmployeeId']:
        find(db, 'Employee', values['branchHeadEmployeeId'])
    return values


def branch_dto(db, record):
    head = find(db, 'Employee', record['branchHeadEmployeeId'], required=False)
    location = ', '.join(record[key] for key in ('city', 'state', 'country') if record[key])
    return {**{key: record[key] for key in ('id', 'name', 'code', 'street', 'zip', 'state', 'country', 'city', 'description', 'isActive', 'branchHeadEmployeeId')},
            'location': location + '.' if location else '',
            'head': f"{head['firstName']} {head['lastName']}".strip() if head else '—',
            'email': record['contactEmail'], 'phone': record['contactPhone'],
            'employees': count_employees(db, 'branchId', record['id']),
            'status': 'Active' if record['isActive'] else 'In Active'}


@router.get('/branches')
def branches(q: str = Query('', max_length=255), user=Depends(admin), db=Depends(get_db)):
    records = rows(db, 'Branch', order=table(db, 'Branch').c.name)
    serialized = [branch_dto(db, row) for row in records]
    employees = table(db, 'Employee')
    stats = {'total': len(records), 'active': sum(row['isActive'] for row in records),
             'employees': db.scalar(select(func.count()).select_from(employees).where(employees.c.branchId.is_not(None))),
             'countries': len({row['country'].strip() for row in records if row['country'].strip()})}
    if q.strip():
        serialized = [row for row in serialized if any(q.strip().casefold() in str(row[key]).casefold()
            for key in ('name', 'code', 'city', 'state', 'country', 'email', 'phone', 'street', 'head'))]
    return {'stats': stats, 'branches': serialized}


@router.post('/branches', status_code=201)
def create_branch(body: BranchInput, user=Depends(admin), db=Depends(get_db)):
    return branch_dto(db, insert(db, 'Branch', branch_values(db, body)))


@router.patch('/branches/{id}')
def patch_branch(id: str, body: BranchInput, user=Depends(admin), db=Depends(get_db)):
    return branch_dto(db, update(db, 'Branch', id, branch_values(db, body)))


@router.delete('/branches/{id}')
def delete_branch(id: str, user=Depends(admin), db=Depends(get_db)):
    delete_unassigned(db, 'Branch', id, 'branchId')
    return {'ok': True}
