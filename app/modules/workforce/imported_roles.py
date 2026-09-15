"""Retained role configuration is descriptive; native account roles grant access."""
from collections import Counter
import re
from uuid import uuid4
from fastapi import Depends, HTTPException
from pydantic import Field, StrictBool, field_validator
from sqlalchemy import select
from app.core.compatibility_routing import APIRouter
from app.core.models import User
from app.core.schemas import Input
from app.core.security import require
from app.data.database import get_db
from app.data.imported import find, table
from app.modules.workforce.imported_assets import insert, rows, wire
from app.modules.workforce.imported_organization import update

router = APIRouter(prefix='/api/organization/roles', tags=['Role configuration'])
admin = require('admin', module='hrms')
MODULES = 'dashboard employees attendance leave payroll performance recruitment training reports settings'.split()
NOTICE = 'These configuration matrices do not grant login permissions. Assign an application role in Account Access.'


class Crud(Input):
    create: StrictBool
    read: StrictBool
    update: StrictBool
    delete: StrictBool


class RoleCreate(Input):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=5000)


class RolePatch(Input):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, min_length=1, max_length=5000)
    permissions: dict[str, Crud] | None = None

    @field_validator('permissions')
    @classmethod
    def all_modules(cls, value):
        if value is not None and set(value) != set(MODULES):
            raise ValueError('Provide permissions for each supported module')
        return value


def listing(db, user):
    records = rows(db, 'OrganizationRoleSetting', order=table(db, 'OrganizationRoleSetting').c.sortOrder)
    counts = Counter(db.scalars(select(User.role).where(User.customer_id == user.customer_id)))
    return wire({'roles': [{**record, 'userCount': counts.get((record['mapsToUserRole'] or '').lower(), 0), 'permissionsEnforced': False} for record in records],
        'stats': {'totalRoles': len(records), 'customRoles': sum(not record['isSystem'] for record in records), 'totalUsers': sum(counts.values()), 'modules': len(MODULES)},
        'permissionsEnforced': False, 'notice': NOTICE})


@router.get('')
def list_roles(user=Depends(admin), db=Depends(get_db)):
    return listing(db, user)


@router.post('', status_code=201)
def create_role(body: RoleCreate, user=Depends(admin), db=Depends(get_db)):
    record_id = str(uuid4())
    slug = re.sub('[^a-z0-9]+', '-', body.name.lower()).strip('-')[:48] or 'role'
    return wire({**insert(db, 'OrganizationRoleSetting', {**body.model_dump(), 'id': record_id, 'slug': slug + '-' + record_id,
        'isSystem': False, 'isDefault': False, 'sortOrder': 100, 'mapsToUserRole': None,
        'permissions': {key: dict.fromkeys(('create', 'read', 'update', 'delete'), False) for key in MODULES}}), 'permissionsEnforced': False, 'notice': NOTICE})


@router.get('/{record_id}')
def get_role(record_id: str, user=Depends(admin), db=Depends(get_db)):
    return wire({**find(db, 'OrganizationRoleSetting', record_id), 'permissionsEnforced': False, 'notice': NOTICE})


@router.patch('/{record_id}')
def patch_role(record_id: str, body: RolePatch, user=Depends(admin), db=Depends(get_db)):
    values = body.model_dump(exclude_unset=True)
    if not values or any(value is None for value in values.values()):
        raise HTTPException(422, 'Provide a non-empty role configuration change')
    return wire({**update(db, 'OrganizationRoleSetting', record_id, values), 'permissionsEnforced': False, 'notice': NOTICE})


@router.delete('/{record_id}')
def delete_role(record_id: str, user=Depends(admin), db=Depends(get_db)):
    record = find(db, 'OrganizationRoleSetting', record_id, lock=True)
    if record['isSystem'] or record['mapsToUserRole']:
        raise HTTPException(409, 'Built-in application roles cannot be deleted')
    roles = table(db, 'OrganizationRoleSetting')
    db.execute(roles.delete().where(roles.c.id == record_id))
    return {'ok': True}
