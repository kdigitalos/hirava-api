"""Existing hand-written helpdesk settings table; schema creation is a migration."""
from copy import deepcopy
from typing import Literal

from fastapi import Depends, HTTPException
from pydantic import Field
from sqlalchemy import Column, DateTime, JSON, MetaData, String, Table, inspect, select

from app.core.compatibility_routing import APIRouter
from app.data.database import get_db
from app.data.imported import table
from app.modules.workforce.imported_assets import admin, now, rows
from app.modules.workforce.imported_employee_profile import full_name
from app.modules.workforce.imported_leave import Input

router = APIRouter(prefix='/api/ask-me/settings', tags=['Helpdesk settings'])
DEFAULTS = {'categories': [], 'escalations': [], 'deptAgents': {key: 'Select agent.' for key in ('hr', 'it', 'payroll', 'admin')},
    'slaConfig': {key: None for key in ('Low', 'Medium', 'High', 'Critical')}}


def settings_table(db):
    return Table('ask_me_helpdesk_settings', MetaData(), Column('id', String, primary_key=True),
        Column('payload', JSON, nullable=False), Column('updated_at', DateTime(timezone=True), nullable=False),
        schema='public' if db.bind.dialect.name == 'postgresql' else None)


class Category(Input):
    id: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=255)
    type: str = Field(max_length=255)
    defaultPriority: Literal['Low', 'Medium', 'High', 'Critical']
    slaHours: float = Field(gt=0, le=8760, allow_inf_nan=False)
    autoAssign: bool = Field(strict=True)
    defaultAssignee: str = Field(max_length=255)


class Escalation(Input):
    id: str = Field(min_length=1, max_length=255)
    category: str = Field(max_length=255)
    priority: str = Field(max_length=255)
    afterHours: float = Field(gt=0, le=8760, allow_inf_nan=False)
    escalateTo: str = Field(max_length=255)
    escalateDept: str = Field(max_length=255)
    notifyManagement: bool = Field(strict=True)


class DepartmentAgents(Input):
    hr: str = Field(max_length=255)
    it: str = Field(max_length=255)
    payroll: str = Field(max_length=255)
    admin: str = Field(max_length=255)


class SLA(Input):
    Low: float | None = Field(gt=0, le=8760, allow_inf_nan=False)
    Medium: float | None = Field(gt=0, le=8760, allow_inf_nan=False)
    High: float | None = Field(gt=0, le=8760, allow_inf_nan=False)
    Critical: float | None = Field(gt=0, le=8760, allow_inf_nan=False)


class SettingsInput(Input):
    categories: list[Category] = Field(max_length=200)
    escalations: list[Escalation] = Field(max_length=200)
    deptAgents: DepartmentAgents
    slaConfig: SLA


def settings_available(db, tbl):
    return inspect(db.connection()).has_table(tbl.name, schema=tbl.schema)


@router.get('')
def get_settings(user=Depends(admin), db=Depends(get_db)):
    tbl = settings_table(db)
    stored = db.scalar(select(tbl.c.payload).where(tbl.c.id == 'default')) if settings_available(db, tbl) else None
    agents, seen = ['Select agent.'], set()
    for employee in rows(db, 'Employee', table(db, 'Employee').c.status == 'ACTIVE', order=table(db, 'Employee').c.firstName):
        name = full_name(employee) or employee['employeeCode']
        agents.append(name + (' (' + employee['employeeCode'] + ')' if name in seen else ''))
        seen.add(name)
    return {'settings': stored if isinstance(stored, dict) else deepcopy(DEFAULTS), 'agents': agents}


@router.put('')
def save_settings(body: SettingsInput, user=Depends(admin), db=Depends(get_db)):
    for items in (body.categories, body.escalations):
        if len({item.id for item in items}) != len(items):
            raise HTTPException(422, 'Each settings entry needs a unique ID')
    tbl = settings_table(db)
    if not settings_available(db, tbl):
        raise HTTPException(503, 'Helpdesk settings storage is not initialized. Run the backend database migrations.')
    if db.bind.dialect.name == 'postgresql':
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    values = {'id': 'default', 'payload': body.model_dump(), 'updated_at': now()}
    stmt = insert(tbl).values(**values)
    db.execute(stmt.on_conflict_do_update(index_elements=[tbl.c.id], set_={'payload': values['payload'], 'updated_at': values['updated_at']}))
    return {'ok': True}
