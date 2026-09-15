"""Published and draft policy records; staff read and HR/Admin writes."""
from typing import Literal

from fastapi import Depends, HTTPException, Response
from pydantic import Field, field_validator

from app.core.compatibility_routing import APIRouter
from app.data.database import get_db
from app.data.imported import find, table
from app.modules.workforce.imported_assets import admin, insert, rows
from app.modules.workforce.imported_leave import Input, output, staff
from app.modules.workforce.imported_organization import update

router = APIRouter(prefix='/api/privacy-policies', tags=['HRMS privacy policies'])


class PolicyInput(Input):
    title: str | None = Field(None, min_length=1, max_length=1000)
    policyType: str | None = Field(None, min_length=1, max_length=255)
    applicableTo: str | None = Field(None, min_length=1, max_length=2000)
    description: str | None = Field(None, min_length=1, max_length=20000)
    content: str | None = Field(None, max_length=500000)
    regionSpecific: bool | None = None
    status: Literal['ACTIVE', 'DRAFT', 'INACTIVE'] | None = None

    @field_validator('status', mode='before')
    @classmethod
    def normalize_status(cls, value):
        return value.strip().upper() if isinstance(value, str) else value


def values(body, creating=False):
    result = body.model_dump(exclude_unset=True)
    required = ('title', 'policyType', 'applicableTo', 'description')
    for key in required:
        if (creating or key in result) and not result.get(key):
            raise HTTPException(422, f'Enter the policy {key}')
    if any(key in result and result[key] is None for key in ('content', 'status', 'regionSpecific')):
        raise HTTPException(422, 'Policy content, status and region selection cannot be null')
    if creating:
        result.setdefault('content', '')
        result.setdefault('status', 'DRAFT')
        result.setdefault('regionSpecific', False)
    return result


@router.get('')
def policies(user=Depends(staff), db=Depends(get_db)):
    return output(rows(db, 'PrivacyPolicy', order=table(db, 'PrivacyPolicy').c.updatedAt.desc()))


@router.post('', status_code=201)
def create_policy(body: PolicyInput, user=Depends(admin), db=Depends(get_db)):
    return output(insert(db, 'PrivacyPolicy', values(body, True)))


@router.get('/{id}')
def policy(id: str, user=Depends(staff), db=Depends(get_db)):
    return output(find(db, 'PrivacyPolicy', id))


@router.patch('/{id}')
def patch_policy(id: str, body: PolicyInput, user=Depends(admin), db=Depends(get_db)):
    return output(update(db, 'PrivacyPolicy', id, values(body)))


@router.delete('/{id}')
def delete_policy(id: str, user=Depends(admin), db=Depends(get_db)):
    find(db, 'PrivacyPolicy', id, lock=True)
    tbl = table(db, 'PrivacyPolicy')
    db.execute(tbl.delete().where(tbl.c.id == id))
    return Response(status_code=204)
