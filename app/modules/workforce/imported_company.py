"""Stored organization profile; reading an empty installation does not write."""
import logging
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import Depends, HTTPException, Request
from pydantic import EmailStr, Field, field_validator
from starlette.datastructures import UploadFile

from app.core import imported_storage
from app.core.compatibility_routing import APIRouter
from app.core.schemas import Input
from app.data.database import get_db
from app.data.imported import find
from app.modules.workforce.imported_assets import insert
from app.modules.workforce.imported_leave import admin, staff, output
from app.modules.workforce.imported_organization import update
from app.modules.workforce.imported_photo import PhotoRoute
from app.workers.imported_storage_cleanup import queue_delete

router = APIRouter(prefix='/api/organization/company-profile', tags=['Company profile'], route_class=PhotoRoute)
ID = 'org_company_profile_singleton'
FIELDS = ('companyName', 'industry', 'email', 'phone', 'website', 'taxId', 'description', 'streetAddress', 'city')


class Profile(Input):
    companyName: str = Field(min_length=1, max_length=255)
    industry: str = Field(min_length=1, max_length=255)
    email: EmailStr
    phone: str = Field(min_length=1, max_length=100)
    website: str = Field(min_length=1, max_length=2000)
    taxId: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=10000)
    streetAddress: str = Field(min_length=1, max_length=1000)
    city: str = Field(min_length=1, max_length=200)
    state: str | None = Field(default=None, max_length=200)
    zipCode: str | None = Field(default=None, max_length=40)
    country: str | None = Field(default=None, max_length=200)
    defaultCurrency: str = Field(pattern=r'^[A-Z]{3}$')
    timezone: str | None = Field(default=None, max_length=100)
    workStartTime: str | None = Field(default=None, pattern=r'^([01]\d|2[0-3]):[0-5]\d$')
    workEndTime: str | None = Field(default=None, pattern=r'^([01]\d|2[0-3]):[0-5]\d$')

    @field_validator('state', 'zipCode', 'country', 'timezone', 'workStartTime', 'workEndTime', mode='before')
    @classmethod
    def empty_optional(cls, value):
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator('website')
    @classmethod
    def website_url(cls, value):
        value = value if '://' in value else 'https://' + value
        parsed = urlsplit(value)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname:
            raise ValueError('Enter a valid HTTP or HTTPS website')
        return value


class ClearLogo(Input):
    clearLogo: bool


def stored(db, lock=False):
    return find(db, 'OrganizationCompanyProfile', ID, lock=lock, required=False)


def serialized(record):
    record = record or {'id': ID, **{field: '' for field in FIELDS}, 'defaultCurrency': '',
        **{field: None for field in ('state', 'zipCode', 'country', 'timezone', 'workStartTime', 'workEndTime', 'updatedAt')}}
    return output({**{key: value for key, value in record.items() if key not in ('logoStoragePath', 'createdAt')},
                   'logoUrl': '/api/uploads/' + record['logoStoragePath'] + '?view=1' if record.get('logoStoragePath') else None})


def save_profile(db, values):
    if stored(db, lock=True):
        return update(db, 'OrganizationCompanyProfile', ID, values)
    return insert(db, 'OrganizationCompanyProfile', {'id': ID, **{field: '' for field in FIELDS}, 'defaultCurrency': '', **values})


@router.get('')
def get_profile(user=Depends(staff), db=Depends(get_db)):
    return serialized(stored(db))


@router.patch('')
def patch_profile(body: Profile | ClearLogo, user=Depends(admin), db=Depends(get_db)):
    if isinstance(body, ClearLogo):
        if not body.clearLogo:
            raise HTTPException(422, 'Set clearLogo to true to remove the logo')
        previous = stored(db, lock=True)
        if previous and previous.get('logoStoragePath'):
            queue_delete(db, user.customer_id, previous['logoStoragePath'])
        return serialized(save_profile(db, {'logoStoragePath': None}))
    return serialized(save_profile(db, body.model_dump(mode='json')))


@router.post('')
async def upload_logo(request: Request, user=Depends(admin), db=Depends(get_db)):
    async with request.form() as form:
        file = form.get('logo')
        if not isinstance(file, UploadFile) or file.content_type not in ('image/png', 'image/jpeg'):
            raise HTTPException(422, 'Choose a PNG or JPEG logo')
        content = await file.read(5 * 1024 * 1024 + 1)
        if not content or len(content) > 5 * 1024 * 1024:
            raise HTTPException(422, 'Logo must be between 1 byte and 5 MB')
        suffix = '.png' if file.content_type == 'image/png' else '.jpg'
        mime = file.content_type
    key = 'organization/company-profile/' + uuid4().hex + suffix
    settings = request.app.state.settings
    previous = stored(db, lock=True)
    imported_storage.save(settings, key, content, mime)
    try:
        record = save_profile(db, {'logoStoragePath': key})
        if previous and previous.get('logoStoragePath'):
            queue_delete(db, user.customer_id, previous['logoStoragePath'])
        db.commit()
    except Exception:
        db.rollback()
        try:
            imported_storage.remove(settings, key)
        except Exception:
            logging.getLogger(__name__).warning('New company logo cleanup failed')
        raise
    return serialized(record)
