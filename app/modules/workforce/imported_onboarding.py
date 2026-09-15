"""Onboarding setup and candidate records on existing public tables."""
import re
import secrets
from typing import Any, Literal

from fastapi import Depends, HTTPException, Response
from pydantic import Field, create_model
from sqlalchemy import select, text

from app.core.compatibility_routing import APIRouter
from app.data.database import get_db
from app.data.imported import find, table
from app.modules.workforce.imported_assets import admin, insert, rows
from app.modules.workforce.imported_attendance import calendar_date
from app.modules.workforce.imported_leave import Input, output
from app.modules.workforce.imported_organization import update

router = APIRouter(prefix='/api', tags=['HRMS onboarding'])
SYSTEM_GROUP = '__hirava_candidates_page__'
GroupInput = create_model('OnboardingGroupInput', __base__=Input,
    **{key: (str | None, Field(None, max_length=10000)) for key in
       'name description roleLabel location manager department probationPolicy templateSource additionalRecipients groupCode'.split()},
    autoConvert=(bool | None, None),
    status=(Literal['DRAFT', 'ACTIVE', 'CONVERSION_PENDING', 'ARCHIVED'] | None, None),
    progress=(Literal['GOOD', 'AVERAGE', 'BAD'] | None, None),
    progressPercent=(int | None, Field(None, ge=0, le=100)), currentTask=(int | None, Field(None, ge=0, le=10000)),
    windowStart=(str | None, None), windowEnd=(str | None, None))


def onboarding_lock(db):
    # Serializes display-ID allocation and dependent edits across Python workers.
    if db.bind.dialect.name == 'postgresql':
        db.execute(text('SELECT pg_advisory_xact_lock(7310462)'))


def group_values(body, existing=None):
    values = body.model_dump(exclude_unset=True)
    for key in ('windowStart', 'windowEnd'):
        if key in values:
            # The frontend sends either date-only input or an ISO midnight value.
            values[key] = calendar_date(values[key][:10]) if values[key] else None
    merged = {**(existing or {}), **values}
    if merged.get('windowStart') and merged.get('windowEnd') and merged['windowEnd'] < merged['windowStart']:
        raise HTTPException(422, 'Onboarding end date must be on or after its start date')
    if merged.get('status') == 'ACTIVE' and not merged.get('name'):
        raise HTTPException(422, 'Enter a group name before activating it')
    if existing and any(key in values and not values[key] for key in ('name', 'status')):
        raise HTTPException(422, 'Group name and status cannot be empty')
    if 'autoConvert' in values and values['autoConvert'] is None:
        raise HTTPException(422, 'Choose whether automatic conversion is enabled')
    return values


@router.get('/onboarding-groups')
def groups(user=Depends(admin), db=Depends(get_db)):
    return output(rows(db, 'OnboardingGroup', order=table(db, 'OnboardingGroup').c.updatedAt.desc()))


@router.post('/onboarding-groups', status_code=201)
def add_group(body: GroupInput, user=Depends(admin), db=Depends(get_db)):
    onboarding_lock(db)
    values = group_values(body)
    values['name'] = values.get('name') or 'Untitled group'
    values['status'] = values.get('status') or 'DRAFT'
    values.setdefault('autoConvert', True)
    values['groupCode'] = values.get('groupCode') or str(secrets.randbelow(90_000_000) + 10_000_000)
    return output(insert(db, 'OnboardingGroup', values))


@router.get('/onboarding-groups/{id}')
def group(id: str, include: str = '', user=Depends(admin), db=Depends(get_db)):
    record = find(db, 'OnboardingGroup', id)
    if include == 'candidates':
        record['candidates'] = []
        for candidate in rows(db, 'OnboardingCandidate', table(db, 'OnboardingCandidate').c.groupId == id, order=table(db, 'OnboardingCandidate').c.createdAt):
            employee = find(db, 'Employee', candidate['employeeId'], required=False)
            record['candidates'].append({**{key: candidate[key] for key in ('id', 'name', 'email', 'roleLabel', 'status', 'details')},
                'employee': {'employeeCode': employee['employeeCode']} if employee else None})
    return output(record)


@router.patch('/onboarding-groups/{id}')
def patch_group(id: str, body: GroupInput, user=Depends(admin), db=Depends(get_db)):
    onboarding_lock(db)
    existing = find(db, 'OnboardingGroup', id, lock=True)
    return output(update(db, 'OnboardingGroup', id, group_values(body, existing)))


@router.delete('/onboarding-groups/{id}')
def delete_group(id: str, user=Depends(admin), db=Depends(get_db)):
    onboarding_lock(db)
    find(db, 'OnboardingGroup', id, lock=True)
    for model in ('OnboardingCandidate', 'OnboardingTemplate'):
        tbl = table(db, model)
        if db.scalar(select(tbl.c.id).where(tbl.c.groupId == id).limit(1)):
            raise HTTPException(409, 'This group has candidates or templates. Archive it to preserve their history.')
    tbl = table(db, 'OnboardingGroup')
    db.execute(tbl.delete().where(tbl.c.id == id))
    return Response(status_code=204)


class TemplateInput(Input):
    name: str | None = Field(None, min_length=1, max_length=1000)
    groupId: str | None = Field(None, max_length=255)
    category: str | None = Field(None, max_length=255)
    templateType: str | None = Field(None, max_length=255)
    complexity: str | None = Field(None, max_length=255)
    department: str | None = Field(None, max_length=255)
    stagesJson: Any = None


def template_payload(db, record):
    return {**record, 'group': find(db, 'OnboardingGroup', record['groupId'], required=False)}


@router.get('/onboarding-templates')
def templates(q: str = '', category: str = '', type: str = '', level: str = '', department: str = '', user=Depends(admin), db=Depends(get_db)):
    result = rows(db, 'OnboardingTemplate', order=table(db, 'OnboardingTemplate').c.createdAt.desc())
    for field, value, sentinel in (('category', category, 'all-categories'), ('templateType', type, 'all-types'), ('complexity', level, 'all-levels'), ('department', department, 'all-departments')):
        if value.strip() and value.strip() != sentinel:
            result = [item for item in result if item[field] == value.strip()]
    if q.strip():
        result = [item for item in result if any(q.strip().lower() in (item[key] or '').lower() for key in ('name', 'category', 'department', 'templateType'))]
    return output([template_payload(db, item) for item in result])


@router.post('/onboarding-templates', status_code=201)
def add_template(body: TemplateInput, user=Depends(admin), db=Depends(get_db)):
    onboarding_lock(db)
    if not body.name:
        raise HTTPException(422, 'Enter a template name')
    values = body.model_dump(exclude_unset=True)
    if body.groupId:
        find(db, 'OnboardingGroup', body.groupId)
    metadata = body.stagesJson if isinstance(body.stagesJson, dict) else {}
    for key in ('department', 'complexity'):
        if not values.get(key) and isinstance(metadata.get(key), str):
            values[key] = metadata[key].strip()[:255] or None
    values['category'] = values.get('category') or values.get('department')
    return output(insert(db, 'OnboardingTemplate', values))


@router.get('/onboarding-templates/{id}')
def template(id: str, user=Depends(admin), db=Depends(get_db)):
    return output(template_payload(db, find(db, 'OnboardingTemplate', id)))


@router.patch('/onboarding-templates/{id}')
def patch_template(id: str, body: TemplateInput, user=Depends(admin), db=Depends(get_db)):
    onboarding_lock(db)
    values = body.model_dump(exclude_unset=True)
    if 'name' in values and not body.name:
        raise HTTPException(422, 'Enter a template name')
    if body.groupId:
        find(db, 'OnboardingGroup', body.groupId)
    return output(update(db, 'OnboardingTemplate', id, values))


@router.delete('/onboarding-templates/{id}')
def delete_template(id: str, user=Depends(admin), db=Depends(get_db)):
    onboarding_lock(db)
    find(db, 'OnboardingTemplate', id, lock=True)
    candidate = table(db, 'OnboardingCandidate')
    if db.scalar(select(candidate.c.id).where(candidate.c.templateId == id).limit(1)):
        raise HTTPException(409, 'Candidates use this template. Preserve it until they are reassigned.')
    tbl = table(db, 'OnboardingTemplate')
    db.execute(tbl.delete().where(tbl.c.id == id))
    return Response(status_code=204)


class CandidateInput(Input):
    groupId: str | None = Field(None, max_length=255)
    templateId: str | None = Field(None, max_length=255)
    employeeId: str | None = Field(None, max_length=255)
    email: str | None = Field(None, min_length=3, max_length=320)
    name: str | None = Field(None, min_length=1, max_length=1000)
    roleLabel: str | None = Field(None, max_length=255)
    status: Literal['INVITED', 'IN_PROGRESS', 'COMPLETED', 'WITHDRAWN'] | None = None
    details: dict[str, Any] | None = None


def standalone_group(db):
    tbl = table(db, 'OnboardingGroup')
    existing = db.scalar(select(tbl.c.id).where(tbl.c.name == SYSTEM_GROUP).limit(1))
    return existing or insert(db, 'OnboardingGroup', {'name': SYSTEM_GROUP, 'status': 'ACTIVE', 'autoConvert': True,
        'description': 'System group for candidates added from the Candidates screen.'})['id']


def next_display_id(db):
    maximum = 12_356_780
    for item in rows(db, 'OnboardingCandidate'):
        details = item['details'] if isinstance(item['details'], dict) else {}
        digits = re.sub(r'\D', '', str(details.get('displayCandidateId', '')))
        if digits and len(digits) <= 18:
            maximum = max(maximum, int(digits))
    return str(maximum + 1)


def candidate_values(db, body, existing=None):
    values = body.model_dump(exclude_unset=True)
    for key in ('name', 'email', 'status', 'groupId'):
        if (existing and key in values and not values[key]) or (not existing and key in ('name', 'email') and not values.get(key)):
            raise HTTPException(422, f'Enter a valid candidate {key}')
    if values.get('email') and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', values['email']):
        raise HTTPException(422, 'Enter a valid candidate email address')
    if not existing:
        values['groupId'] = values.get('groupId') or standalone_group(db)
        values['status'] = values.get('status') or 'IN_PROGRESS'
    for key, model in (('groupId', 'OnboardingGroup'), ('templateId', 'OnboardingTemplate'), ('employeeId', 'Employee')):
        if values.get(key):
            find(db, model, values[key])
    if existing and existing['employeeId'] and 'employeeId' in values and values['employeeId'] != existing['employeeId']:
        raise HTTPException(409, 'A linked employee cannot be replaced through candidate editing')
    metadata = dict(existing['details']) if existing and isinstance(existing['details'], dict) else {}
    previous_display_id = metadata.get('displayCandidateId')
    metadata.update(body.details or {})
    metadata['displayCandidateId'] = previous_display_id or next_display_id(db)
    metadata['fullName'] = values.get('name') or (existing or {}).get('name')
    values['details'] = metadata
    if not existing and not values.get('templateId') and isinstance(metadata.get('template'), str):
        hint = metadata['template'].strip().lower()
        for item in rows(db, 'OnboardingTemplate'):
            if hint in (item['id'].lower(), item['name'].lower()):
                values['templateId'] = item['id']
                break
    return values


def candidate_payload(db, record):
    return {**record, **{key: find(db, model, record[key + 'Id'], required=False)
        for key, model in (('group', 'OnboardingGroup'), ('template', 'OnboardingTemplate'), ('employee', 'Employee'))}}


@router.get('/onboarding-candidates')
def candidates(user=Depends(admin), db=Depends(get_db)):
    return output([candidate_payload(db, item) for item in rows(db, 'OnboardingCandidate', order=table(db, 'OnboardingCandidate').c.createdAt.desc())])


@router.post('/onboarding-candidates', status_code=201)
def add_candidate(body: CandidateInput, user=Depends(admin), db=Depends(get_db)):
    onboarding_lock(db)
    return output(insert(db, 'OnboardingCandidate', candidate_values(db, body)))


class BulkInput(Input):
    groupId: str | None = Field(None, max_length=255)
    candidates: list[CandidateInput] = Field(min_length=1, max_length=500)


@router.post('/onboarding-candidates/bulk', status_code=201)
def bulk_candidates(body: BulkInput, user=Depends(admin), db=Depends(get_db)):
    onboarding_lock(db)
    group_id = body.groupId or standalone_group(db)
    find(db, 'OnboardingGroup', group_id, lock=True)
    seen = {item['email'].strip().lower() for item in rows(db, 'OnboardingCandidate', table(db, 'OnboardingCandidate').c.groupId == group_id)}
    created = []
    for candidate in body.candidates:
        if not candidate.name or not candidate.email or candidate.email.lower() in seen:
            continue
        values = candidate_values(db, candidate.model_copy(update={'groupId': group_id, 'status': 'IN_PROGRESS'}))
        created.append(insert(db, 'OnboardingCandidate', values))
        seen.add(candidate.email.lower())
    return output({'created': created})


@router.get('/onboarding-candidates/{id}')
def candidate(id: str, user=Depends(admin), db=Depends(get_db)):
    return output(candidate_payload(db, find(db, 'OnboardingCandidate', id)))


@router.patch('/onboarding-candidates/{id}')
def patch_candidate(id: str, body: CandidateInput, user=Depends(admin), db=Depends(get_db)):
    onboarding_lock(db)
    existing = find(db, 'OnboardingCandidate', id, lock=True)
    return output(update(db, 'OnboardingCandidate', id, candidate_values(db, body, existing)))


@router.delete('/onboarding-candidates/{id}')
def delete_candidate(id: str, user=Depends(admin), db=Depends(get_db)):
    onboarding_lock(db)
    existing = find(db, 'OnboardingCandidate', id, lock=True)
    if existing['employeeId'] or existing['status'] == 'COMPLETED':
        raise HTTPException(409, 'Completed or employee-linked onboarding records must be retained')
    tbl = table(db, 'OnboardingCandidate')
    db.execute(tbl.delete().where(tbl.c.id == id))
    return Response(status_code=204)
