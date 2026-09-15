"""Clearance checklist and applied offboarding template snapshots."""
from copy import deepcopy
from typing import Literal

from fastapi import Depends, HTTPException
from pydantic import Field

from app.core.compatibility_routing import APIRouter
from app.data.database import get_db
from app.data.imported import find, table
from app.modules.workforce.imported_assets import admin, insert, now, rows
from app.modules.workforce.imported_exits import exit_record
from app.modules.workforce.imported_leave import Input, output, staff
from app.modules.workforce.imported_organization import update

router = APIRouter(prefix='/api', tags=['HRMS exit clearance'])
CHECKS = [('IT', 'IT Department', 'it', ['Return laptop and accessories', 'Revoke system access', 'Clear email account', 'Return access cards']),
    ('Admin', 'Admin Department', 'admin', ['Return office keys', 'Clear desk and locker', 'Return ID card', 'Submit parking pass']),
    ('Finance', 'Finance Department', 'fin', ['Clear pending expenses', 'Return corporate card', 'Submit final timesheets', 'Clear advance payments']),
    ('HR', 'HR Department', 'hr', ['Complete exit interview', 'Return HR documents', 'Update contact information', 'Acknowledgment of policies'])]


def clearance_state(raw):
    state = {'departments': [{'key': key, 'label': label, 'status': 'Pending', 'comments': '', 'decidedBy': None, 'decidedAt': None,
        'items': [{'id': f'{prefix}-{index + 1}', 'label': title, 'done': False} for index, title in enumerate(titles)]} for key, label, prefix, titles in CHECKS]}
    existing = raw.get('departments') if isinstance(raw, dict) else None
    if isinstance(existing, list):
        for stored in existing:
            if not isinstance(stored, dict):
                continue
            target = next((item for item in state['departments'] if item['key'] == stored.get('key')), None)
            if not target:
                continue
            if stored.get('status') in ('Pending', 'Approved', 'Rejected'):
                target['status'] = stored['status']
            for field in ('comments', 'decidedBy', 'decidedAt'):
                if isinstance(stored.get(field), str):
                    target[field] = stored[field]
            for item in stored.get('items', []) if isinstance(stored.get('items'), list) else []:
                if isinstance(item, dict):
                    match = next((known for known in target['items'] if known['id'] == item.get('id')), None)
                    if match and isinstance(item.get('done'), bool):
                        match['done'] = item['done']
    return state


def all_approved(state):
    return bool(state['departments']) and all(item['status'] == 'Approved' and all(task['done'] for task in item['items']) for item in state['departments'])


class ClearanceItem(Input):
    id: str = Field(min_length=1, max_length=100)
    label: str = Field('', max_length=1000)
    done: bool


class ClearanceDepartment(Input):
    key: Literal['IT', 'Admin', 'Finance', 'HR']
    label: str = Field('', max_length=1000)
    status: Literal['Pending', 'Approved', 'Rejected'] = 'Pending'
    items: list[ClearanceItem] = Field(max_length=100)
    comments: str = Field('', max_length=2000)
    decidedBy: str | None = Field(None, max_length=1000)
    decidedAt: str | None = None


class ClearanceInput(Input):
    departments: list[ClearanceDepartment] = Field(min_length=1, max_length=4)
    complete: bool = False


@router.get('/exit-requests/{id}/clearance')
def clearance(id: str, user=Depends(staff), db=Depends(get_db)):
    return clearance_state(exit_record(db, id, user)['clearanceJson'])


@router.patch('/exit-requests/{id}/clearance')
def save_clearance(id: str, body: ClearanceInput, user=Depends(admin), db=Depends(get_db)):
    record = exit_record(db, id, user, deciding=True)
    if record['status'] not in ('APPROVED', 'IN_PROGRESS'):
        raise HTTPException(409, 'Clearance requires an approved active exit')
    if len({item.key for item in body.departments}) != len(body.departments):
        raise HTTPException(422, 'List each clearance department once')
    state = clearance_state(record['clearanceJson'])
    for supplied in body.departments:
        target = next(item for item in state['departments'] if item['key'] == supplied.key)
        supplied_ids = [item.id for item in supplied.items]
        if len(set(supplied_ids)) != len(supplied_ids) or set(supplied_ids) - {item['id'] for item in target['items']}:
            raise HTTPException(422, 'Choose valid, unique checklist items for this department')
        for item in supplied.items:
            next(known for known in target['items'] if known['id'] == item.id)['done'] = item.done
        if supplied.status == 'Approved' and not all(item['done'] for item in target['items']):
            raise HTTPException(422, 'Complete all checklist items before approving a department')
        target.update(status=supplied.status, comments=supplied.comments,
            decidedBy=None if supplied.status == 'Pending' else user.name or user.email,
            decidedAt=None if supplied.status == 'Pending' else now().isoformat() + 'Z')
    if body.complete and not all_approved(state):
        raise HTTPException(409, 'Approve all departments before completing clearance')
    update(db, 'ExitRequest', id, {'clearanceJson': state, **({'status': 'IN_PROGRESS'} if body.complete else {})})
    return state


class TemplateTask(Input):
    id: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=1000)
    owner: Literal['HR', 'IT', 'Manager', 'Finance']
    dueLabel: str = Field('', max_length=255)


class TemplateStage(Input):
    id: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=1000)
    days: int = Field(ge=1, le=3650, strict=True)
    stageDescription: str = Field('', max_length=10000)
    taskItems: list[TemplateTask] = Field(max_length=100)
    isDefault: bool = False


class TemplateInput(Input):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(None, max_length=20000)
    roleLabel: str | None = Field(None, max_length=255)
    departmentLabel: str | None = Field(None, max_length=255)
    locationLabel: str | None = Field(None, max_length=255)
    stages: list[TemplateStage] = Field(min_length=1, max_length=100)


def template_summary(record):
    stages, tasks = record['stageCount'], record['taskCount']
    return {'id': record['id'], 'title': record['name'], 'description': record['description'] or '',
        'duration': f"{max(1, record['totalDays'])} days", 'complexity': 'Basic' if stages <= 2 and tasks <= 10 else 'Intermediate' if stages <= 4 and tasks <= 20 else 'Advanced',
        'stages': stages, 'tasks': tasks, 'author': 'Your library', 'department': record['departmentLabel'] or '—',
        'tags': [record[key] for key in ('roleLabel', 'locationLabel') if record[key]] or ['exit', 'offboarding']}


@router.get('/exit-offboarding-templates')
def exit_templates(user=Depends(admin), db=Depends(get_db)):
    return {'templates': [template_summary(item) for item in rows(db, 'ExitOffboardingTemplate', order=table(db, 'ExitOffboardingTemplate').c.updatedAt.desc())[:100]]}


@router.post('/exit-offboarding-templates', status_code=201)
def add_exit_template(body: TemplateInput, user=Depends(admin), db=Depends(get_db)):
    values = body.model_dump()
    stages = values.pop('stages')
    if len({item['id'] for item in stages}) != len(stages) or any(len({task['id'] for task in item['taskItems']}) != len(item['taskItems']) for item in stages):
        raise HTTPException(422, 'Stage and task identifiers must be unique')
    record = insert(db, 'ExitOffboardingTemplate', {**values, 'stagesJson': stages, 'stageCount': len(stages),
        'taskCount': sum(len(item['taskItems']) for item in stages), 'totalDays': sum(item['days'] for item in stages)})
    return {'template': template_summary(record)}


@router.get('/exit-offboarding-templates/{id}')
def exit_template(id: str, user=Depends(admin), db=Depends(get_db)):
    record = find(db, 'ExitOffboardingTemplate', id)
    return output({**{key: value for key, value in record.items() if key != 'stagesJson'}, 'stages': record['stagesJson']})


class ApplyInput(Input):
    exitRequestId: str = Field(min_length=1, max_length=255)


@router.post('/exit-offboarding-templates/{id}/apply', status_code=201)
def apply_template(id: str, body: ApplyInput, user=Depends(admin), db=Depends(get_db)):
    record = exit_record(db, body.exitRequestId, user, deciding=True)
    if record['isDraft'] or record['status'] in ('REJECTED', 'COMPLETED'):
        raise HTTPException(409, 'Templates can only be applied to active exit cases')
    template = find(db, 'ExitOffboardingTemplate', id)
    stages = deepcopy(template['stagesJson'])
    if not isinstance(stages, list) or not stages:
        raise HTTPException(422, 'Template has no usable stages')
    for stage in stages:
        for task in stage.get('taskItems', []):
            task['done'] = False
    snapshot = {'templateId': id, 'templateName': template['name'], 'appliedAt': now().isoformat() + 'Z', 'stages': stages}
    update(db, 'ExitRequest', record['id'], {'appliedTemplateId': id, 'appliedTemplateJson': snapshot})
    return {'applied': True, 'snapshot': snapshot, 'exitRequestId': record['id']}
