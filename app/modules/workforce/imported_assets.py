"""Asset inventory and allocation, on existing customer-isolated public tables."""
import logging
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Literal
from uuid import uuid4

from fastapi import Depends, HTTPException, Query, Request, Response
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import func, select
from starlette.datastructures import UploadFile

from app.core.compatibility_routing import APIRouter, CompatibilityRoute
from app.core import imported_storage
from app.core.security import require
from app.data.database import get_db
from app.data.imported import dto, find, table


class AssetRoute(CompatibilityRoute):
    max_body_bytes = 50 * 1024 * 1024 + 65536


router = APIRouter(prefix='/api', tags=['HRMS asset compatibility'], route_class=AssetRoute)
admin = require('hr', module='hrms')


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def wire(value):
    return jsonable_encoder(value, custom_encoder={Decimal: str})


def rows(db, model, *criteria, order=None):
    tbl = table(db, model)
    query = select(tbl).where(*criteria)
    if order is not None:
        query = query.order_by(order)
    return [dto(tbl, row) for row in db.execute(query).mappings()]


def insert(db, model, values):
    tbl = table(db, model)
    values = dict(values)
    if 'createdAt' in tbl.c:
        values.setdefault('createdAt', now())
    if 'updatedAt' in tbl.c:
        values['updatedAt'] = now()
    return dto(tbl, db.execute(tbl.insert().values(**values).returning(tbl)).mappings().one())


def asset_detail(db, record):
    photos = table(db, 'AssetPhoto')
    return {**record, 'category': find(db, 'AssetCategory', record['categoryId'], required=False),
            'vendor': find(db, 'AssetVendor', record['vendorId'], required=False),
            'department': find(db, 'Department', record['departmentId'], required=False),
            'photos': rows(db, 'AssetPhoto', photos.c.assetId == record['id'])}


def allocation_detail(db, record):
    asset = find(db, 'Asset', record['assetId'])
    employee = find(db, 'Employee', record['employeeId'])
    return {**record, 'asset': {**asset, 'category': find(db, 'AssetCategory', asset['categoryId'], required=False)},
            'employee': {**employee, 'department': find(db, 'Department', employee['departmentId'], required=False)}}


class CategoryInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=255)
    idPrefix: str = Field(min_length=1, max_length=32, pattern=r'^[A-Za-z0-9_-]+$')
    description: str = Field(min_length=1, max_length=20000)


@router.get('/asset-categories')
def categories(user=Depends(admin), db=Depends(get_db)):
    category = table(db, 'AssetCategory')
    asset = table(db, 'Asset')
    counts = dict(db.execute(select(asset.c.categoryId, func.count()).group_by(asset.c.categoryId)).all())
    return wire([{**row, 'assetCount': counts.get(row['id'], 0)} for row in rows(db, 'AssetCategory', order=category.c.name)])


@router.post('/asset-categories', status_code=201)
def create_category(body: CategoryInput, user=Depends(admin), db=Depends(get_db)):
    return wire({**insert(db, 'AssetCategory', {**body.model_dump(), 'idPrefix': body.idPrefix.upper()}), 'assetCount': 0})


class VendorInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=255)


@router.get('/vendors')
def vendors(user=Depends(admin), db=Depends(get_db)):
    return wire(rows(db, 'AssetVendor', order=table(db, 'AssetVendor').c.name))


@router.post('/vendors', status_code=201)
def create_vendor(body: VendorInput, user=Depends(admin), db=Depends(get_db)):
    return wire(insert(db, 'AssetVendor', body.model_dump()))


Condition = Literal['NEW', 'GOOD', 'FAIR', 'POOR', 'USED', 'REFURBISHED']
Status = Literal['AVAILABLE', 'ALLOCATED', 'IN_REPAIR', 'RETIRED', 'LOST', 'DISPOSED']


class AssetInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    assetTag: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    model: str = Field(min_length=1, max_length=255)
    serialNumber: str = Field(min_length=1, max_length=128)
    categoryId: str = Field(min_length=1, max_length=100)
    condition: Condition
    status: Status = 'AVAILABLE'
    vendorId: str = Field(min_length=1, max_length=100)
    purchaseOrder: str = Field(min_length=1, max_length=128)
    invoiceNumber: str = Field(min_length=1, max_length=128)
    purchaseDate: date
    purchaseValue: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    usefulLifeMonths: int = Field(gt=0, le=1200)
    warrantyEndDate: date
    location: str = Field(min_length=1, max_length=512)
    departmentId: str | None = Field(None, max_length=100)
    notes: str = Field(min_length=1, max_length=20000)

    @field_validator('purchaseValue', mode='before')
    @classmethod
    def clean_money(cls, value):
        return ''.join(value.replace(',', '').split()) if isinstance(value, str) else value


@router.post('/assets', status_code=201)
async def create_asset(request: Request, user=Depends(admin), db=Depends(get_db)):
    files = []
    if 'multipart/form-data' in request.headers.get('content-type', ''):
        async with request.form(max_files=10, max_fields=25) as form:
            values = {key: value for key, value in form.items() if key != 'photos'}
            if not values.get('departmentId'):
                values['departmentId'] = None
            for file in form.getlist('photos'):
                if not isinstance(file, UploadFile) or not file.filename:
                    continue
                extension = file.filename.rsplit('.', 1)[-1].lower()
                if extension not in {'jpg', 'jpeg', 'png', 'webp'}:
                    raise HTTPException(422, 'Photos must be JPG, PNG or WebP')
                content = await file.read(5 * 1024 * 1024 + 1)
                if len(content) > 5 * 1024 * 1024:
                    raise HTTPException(413, 'Each photo must be 5 MB or smaller')
                if content:
                    files.append((file.filename, extension, content))
    elif 'application/json' in request.headers.get('content-type', ''):
        try:
            values = await request.json()
        except ValueError:
            raise HTTPException(422, 'Invalid JSON') from None
    else:
        raise HTTPException(415, 'Use JSON or multipart form data')
    try:
        body = AssetInput.model_validate(values)
    except ValidationError as exc:
        first = exc.errors()[0]
        raise HTTPException(422, f"{'.'.join(map(str, first['loc']))}: {first['msg']}") from None
    if body.status == 'ALLOCATED':
        raise HTTPException(409, 'Create the asset, then use Allocate Asset to assign it')
    for model, ref in [('AssetCategory', body.categoryId), ('AssetVendor', body.vendorId), ('Department', body.departmentId)]:
        if ref:
            find(db, model, ref)
    record = insert(db, 'Asset', body.model_dump())
    saved = []
    settings = request.app.state.settings
    try:
        for filename, extension, content in files:
            mime = {'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png', 'webp': 'image/webp'}[extension]
            key = f"assets/{record['id']}/{uuid4().hex}.{extension}"
            imported_storage.save(settings, key, content, mime)
            saved.append(key)
            insert(db, 'AssetPhoto', {'assetId': record['id'], 'originalFilename': filename[:255],
                'storagePath': key, 'mimeType': mime, 'sizeBytes': len(content)})
        result = wire(asset_detail(db, record))
        # Commit before success and compensate uploaded objects on any DB failure.
        db.commit()
    except Exception:
        db.rollback()
        for key in saved:
            try:
                imported_storage.remove(settings, key)
            except Exception:
                logging.getLogger(__name__).warning('Asset photo cleanup needs retry')
        raise
    return result


@router.get('/assets')
def assets(user=Depends(admin), db=Depends(get_db)):
    asset, assignments = table(db, 'Asset'), table(db, 'AssetAssignment')
    active = {row['assetId']: row for row in rows(db, 'AssetAssignment', assignments.c.returnedAt.is_(None), order=assignments.c.assignedAt)}
    result = []
    for row in rows(db, 'Asset', order=asset.c.createdAt.desc()):
        allocation = active.get(row['id'])
        employee = find(db, 'Employee', allocation['employeeId'], required=False) if allocation else None
        category = find(db, 'AssetCategory', row['categoryId'], required=False)
        result.append({**{key: row[key] for key in ('id', 'assetTag', 'name', 'model', 'serialNumber', 'status', 'condition', 'location', 'purchaseValue', 'createdAt')},
            'category': category['name'] if category else None, 'warranty': row['warrantyEndDate'],
            'assignedTo': ' '.join(filter(None, (employee['firstName'], employee['lastName']))) if employee else None,
            'bookValue': f"₹ {row['purchaseValue']:,.2f}" if row['purchaseValue'] is not None else '—'})
    return wire(result)


@router.get('/assets/available')
def available(user=Depends(admin), db=Depends(get_db)):
    asset, assignment = table(db, 'Asset'), table(db, 'AssetAssignment')
    busy = select(assignment.c.assetId).where(assignment.c.returnedAt.is_(None))
    result = []
    for row in rows(db, 'Asset', asset.c.status == 'AVAILABLE', asset.c.id.not_in(busy), order=asset.c.assetTag):
        category = find(db, 'AssetCategory', row['categoryId'], required=False)
        result.append({**{key: row[key] for key in ('id', 'assetTag', 'name', 'model')}, 'category': category['name'] if category else None})
    return result


@router.get('/assets/{id}')
def get_asset(id: str, user=Depends(admin), db=Depends(get_db)):
    return wire(asset_detail(db, find(db, 'Asset', id)))


class AssetPatch(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str | None = Field(None, min_length=1, max_length=255)
    serialNumber: str | None = Field(None, max_length=128)
    categoryId: str | None = Field(None, max_length=100)
    condition: Condition | None = None
    status: Status | None = None
    location: str | None = Field(None, max_length=512)
    notes: str | None = Field(None, max_length=20000)
    model: str | None = Field(None, max_length=255)


@router.patch('/assets/{id}')
def update_asset(id: str, body: AssetPatch, user=Depends(admin), db=Depends(get_db)):
    asset = table(db, 'Asset')
    current = find(db, 'Asset', id, lock=True)
    values = body.model_dump(exclude_unset=True)
    if any(key in values and values[key] is None for key in ('name', 'condition', 'status', 'location', 'notes')):
        raise HTTPException(422, 'Name, condition, status, location and notes cannot be null')
    if body.status is not None and body.status != current['status'] and 'ALLOCATED' in {body.status, current['status']}:
        raise HTTPException(409, 'Use allocation and return actions to change allocated inventory')
    if body.categoryId:
        find(db, 'AssetCategory', body.categoryId)
    row = db.execute(asset.update().where(asset.c.id == id).values(**values, updatedAt=now()).returning(asset)).mappings().one()
    return wire(dto(asset, row))


@router.delete('/assets/{id}', status_code=204)
def delete_asset(id: str, user=Depends(admin), db=Depends(get_db)):
    asset = table(db, 'Asset')
    find(db, 'Asset', id, lock=True)
    allocation = table(db, 'AssetAssignment')
    if db.execute(select(allocation.c.id).where(allocation.c.assetId == id)).first():
        raise HTTPException(409, 'Allocation history is retained; retire this asset instead')
    photos = table(db, 'AssetPhoto')
    db.execute(photos.delete().where(photos.c.assetId == id))
    db.execute(asset.delete().where(asset.c.id == id))
    return Response(status_code=204)


class AllocationInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    assetId: str = Field(min_length=1, max_length=100)
    employeeId: str = Field(min_length=1, max_length=100)
    assignedAt: date | None = None
    notes: str | None = Field(None, max_length=20000)


@router.get('/asset-assignments')
def allocations(activeOnly: bool = False, user=Depends(admin), db=Depends(get_db)):
    assignment = table(db, 'AssetAssignment')
    where = [assignment.c.returnedAt.is_(None)] if activeOnly else []
    return wire([allocation_detail(db, row) for row in rows(db, 'AssetAssignment', *where, order=assignment.c.assignedAt.desc())])


@router.post('/asset-assignments', status_code=201)
def allocate(body: AllocationInput, user=Depends(admin), db=Depends(get_db)):
    asset, assignment = table(db, 'Asset'), table(db, 'AssetAssignment')
    current = find(db, 'Asset', body.assetId, lock=True)
    if current['status'] != 'AVAILABLE' or db.execute(select(assignment.c.id).where(assignment.c.assetId == body.assetId, assignment.c.returnedAt.is_(None))).first():
        raise HTTPException(409, 'Only available assets without an active allocation can be allocated')
    find(db, 'Employee', body.employeeId)
    changed = db.execute(asset.update().where(asset.c.id == body.assetId, asset.c.status == 'AVAILABLE').values(status='ALLOCATED', updatedAt=now()))
    if changed.rowcount != 1:
        raise HTTPException(409, 'Asset changed; reload and retry')
    record = insert(db, 'AssetAssignment', {**body.model_dump(), 'assignedAt': datetime.combine(body.assignedAt or now().date(), time.min)})
    return wire(allocation_detail(db, record))


@router.get('/asset-assignments/{id}')
def get_allocation(id: str, user=Depends(admin), db=Depends(get_db)):
    return wire(allocation_detail(db, find(db, 'AssetAssignment', id)))


class AllocationPatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    assignedAt: datetime | None = None
    returnedAt: datetime | None = None


@router.patch('/asset-assignments/{id}')
def return_asset(id: str, body: AllocationPatch, user=Depends(admin), db=Depends(get_db)):
    assignment, asset = table(db, 'AssetAssignment'), table(db, 'Asset')
    original = find(db, 'AssetAssignment', id)
    find(db, 'Asset', original['assetId'], lock=True)
    existing = find(db, 'AssetAssignment', id, lock=True)
    if existing['returnedAt'] is not None:
        raise HTTPException(409, 'Allocation already returned')
    values = body.model_dump(exclude_unset=True)
    if any(value is None for value in values.values()):
        raise HTTPException(409, 'An allocation cannot be reopened or assigned an empty date')
    for key, value in values.items():
        if value.tzinfo:
            values[key] = value.astimezone(timezone.utc).replace(tzinfo=None)
    if values.get('returnedAt') and values['returnedAt'] < values.get('assignedAt', existing['assignedAt']):
        raise HTTPException(422, 'Return cannot precede allocation')
    updated = db.execute(assignment.update().where(assignment.c.id == id, assignment.c.returnedAt.is_(None))
        .values(**values, updatedAt=now()).returning(assignment)).mappings().first()
    if updated is None:
        raise HTTPException(409, 'Allocation changed; reload and retry')
    if values.get('returnedAt'):
        opened = db.execute(select(assignment.c.id).where(assignment.c.assetId == existing['assetId'], assignment.c.returnedAt.is_(None))).first()
        if not opened:
            db.execute(asset.update().where(asset.c.id == existing['assetId'], asset.c.status == 'ALLOCATED').values(status='AVAILABLE', updatedAt=now()))
    return wire(dto(assignment, updated))


@router.delete('/asset-assignments/{id}')
def retain_allocation(id: str, user=Depends(admin)):
    raise HTTPException(409, 'Allocation history is retained. Confirm return instead of deleting.')
