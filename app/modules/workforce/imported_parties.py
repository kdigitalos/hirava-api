"""Administrator-managed parties and their owned contact records."""
from typing import Literal
from uuid import uuid4

from fastapi import Depends, HTTPException, Query
from pydantic import Field, create_model
from sqlalchemy import or_, select

from app.core.compatibility_routing import APIRouter
from app.core.schemas import Input
from app.core.security import require
from app.data.database import get_db
from app.data.imported import SCHEMA, find, table
from app.modules.workforce.imported_assets import insert, rows, wire
from app.modules.workforce.imported_organization import update

router = APIRouter(prefix='/api/parties', tags=['Party compatibility'])
admin = require('admin', module='hrms')
CHILDREN = {'roles': 'PartyRole', 'contactPersons': 'PartyContactPerson', 'addresses': 'PartyAddress', 'bankDetails': 'PartyBankDetail'}
DEFAULTS = {'Party': {'partyType': 'ORGANIZATION', 'status': 'ACTIVE', 'currency': 'USD'},
    'PartyRole': {'status': 'ACTIVE'}, 'PartyContactPerson': {'isPrimary': False},
    'PartyAddress': {'addressType': 'OFFICE', 'country': 'USA', 'isPrimary': False}, 'PartyBankDetail': {'isPrimary': False}}


def input_fields(model, partial=False):
    fields = {}
    for field in SCHEMA[model]['fields']:
        key = field['key']
        if key in ('id', 'partyId', 'auth0UserId', 'createdAt', 'updatedAt'):
            continue
        enum = field.get('enum')
        typ = Literal[tuple(enum['values'])] if enum else bool if field['type'] == 'Boolean' else str
        default = DEFAULTS[model].get(key, None if field['nullable'] or partial else ...)
        if field['nullable'] or partial:
            typ = typ | None
        options = {}
        if typ in (str, str | None):
            options = {'max_length': 10000 if key == 'notes' else 1000}
            if not field['nullable']:
                options['min_length'] = 1
            if key == 'currency':
                options = {'pattern': r'^[A-Z]{3}$'}
        fields[key] = (typ, Field(default=default, **options))
    return fields


children = {key: create_model(model + 'Input', __base__=Input, **input_fields(model)) for key, model in CHILDREN.items()}
PartyInput = create_model('PartyInput', __base__=Input, **input_fields('Party'),
    **{key: (list[model], Field(default_factory=list, max_length=100)) for key, model in children.items()})
PartyPatch = create_model('PartyPatch', __base__=Input, **input_fields('Party', partial=True),
    **{key: (list[model] | None, Field(default=None, max_length=100)) for key, model in children.items()})


def detail(db, record):
    return wire({**record, **{key: rows(db, model, table(db, model).c.partyId == record['id']) for key, model in CHILDREN.items()}})


def replace_children(db, record_id, values):
    for key, model in CHILDREN.items():
        if key not in values:
            continue
        records = values.pop(key)
        if records is None:
            raise HTTPException(422, f'{key} must be an array; use an empty array to clear it')
        if key == 'roles' and len({record['roleType'] for record in records}) != len(records):
            raise HTTPException(422, 'Each party role can appear only once')
        if sum(bool(record.get('isPrimary')) for record in records) > 1:
            raise HTTPException(422, f'Choose at most one primary record in {key}')
        child = table(db, model)
        db.execute(child.delete().where(child.c.partyId == record_id))
        for record in records:
            insert(db, model, {'partyId': record_id, **record})


@router.get('')
def listing(search: str = Query('', max_length=200), partyType: Literal['INDIVIDUAL', 'ORGANIZATION'] | None = None,
            roleType: Literal['VENDOR', 'CLIENT', 'SUPPLIER', 'CUSTOMER', 'PARTNER', 'CONTRACTOR'] | None = None,
            status: Literal['ACTIVE', 'INACTIVE', 'PROSPECT', 'ARCHIVED'] | None = None,
            user=Depends(admin), db=Depends(get_db)):
    party = table(db, 'Party')
    filters = []
    if search.strip():
        pattern = '%' + search.strip().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        filters.append(or_(*(party.c[key].ilike(pattern, escape='\\') for key in ('name', 'code', 'legalName', 'email', 'taxId'))))
    if partyType:
        filters.append(party.c.partyType == partyType)
    if status:
        filters.append(party.c.status == status)
    if roleType:
        roles = table(db, 'PartyRole')
        filters.append(party.c.id.in_(select(roles.c.partyId).where(roles.c.roleType == roleType)))
    return [detail(db, record) for record in rows(db, 'Party', *filters, order=party.c.createdAt.desc())]


@router.post('', status_code=201)
def create(body: PartyInput, user=Depends(admin), db=Depends(get_db)):
    values = body.model_dump()
    child_values = {key: values.pop(key) for key in CHILDREN}
    values['code'] = values.get('code') or 'PRT-' + uuid4().hex[:12].upper()
    record = insert(db, 'Party', values)
    replace_children(db, record['id'], child_values)
    return detail(db, record)


@router.get('/{record_id}')
def get_party(record_id: str, user=Depends(admin), db=Depends(get_db)):
    return detail(db, find(db, 'Party', record_id))


@router.put('/{record_id}')
def put_party(record_id: str, body: PartyPatch, user=Depends(admin), db=Depends(get_db)):
    record = find(db, 'Party', record_id, lock=True)
    values = body.model_dump(exclude_unset=True)
    for key in ('name', 'partyType', 'status', 'currency'):
        if key in values and values[key] is None:
            raise HTTPException(422, f'{key} cannot be empty')
    replace_children(db, record_id, values)
    if values:
        record = update(db, 'Party', record_id, values)
    return detail(db, record)


@router.delete('/{record_id}')
def delete_party(record_id: str, user=Depends(admin), db=Depends(get_db)):
    find(db, 'Party', record_id, lock=True)
    for model in CHILDREN.values():
        child = table(db, model)
        db.execute(child.delete().where(child.c.partyId == record_id))
    party = table(db, 'Party')
    db.execute(party.delete().where(party.c.id == record_id))
    return {'success': True, 'message': 'Party deleted successfully'}
