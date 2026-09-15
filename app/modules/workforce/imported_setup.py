"""Organization setup dashboard and atomic structure creation."""
from collections import Counter
from typing import Literal
from uuid import uuid4
import re

from fastapi import Depends, HTTPException
from pydantic import Field
from app.core.compatibility_routing import APIRouter
from app.core.schemas import Input
from app.data.database import get_db
from app.data.imported import find, table
from app.modules.workforce.imported_assets import admin, insert, rows
from app.modules.workforce.imported_company import stored
from app.modules.workforce.imported_employee_profile import full_name

router = APIRouter(prefix='/api/organization/setup-dashboard', tags=['Organization setup'])


def percentage(part, total):
    return round(part * 100 / total) if total else 0


@router.get('')
def dashboard(user=Depends(admin), db=Depends(get_db)):
    departments, branches, designations, employees = [rows(db, model) for model in ('Department', 'Branch', 'Designation', 'Employee')]
    profile = stored(db)
    people = {row['id']: row for row in employees}
    dep, loc, des = [Counter(row[key] for row in employees) for key in ('departmentId', 'branchId', 'designationId')]
    total = len(employees)
    assigned = sum(bool(row['departmentId'] or row['branchId'] or row['designationId']) for row in employees)
    coded = sum(bool(row['code']) for row in departments)
    stats = [('bu', len(branches), 'Total Business Units'), ('dep', len(departments), 'Departments Count'),
        ('loc', sum(row['isActive'] for row in branches), 'Active Locations'), ('dl', len(designations), 'Designation Levels'),
        ('cc', len({row['code'] for row in departments if row['code']}), 'Department Codes'), ('asn', f'{percentage(assigned, total)}%', 'Employees Assigned to Structure')]
    health = [('Departments configured', len(departments), len(departments) or 1),
        ('Managers assigned to departments', sum(bool(row['departmentHeadEmployeeId']) for row in departments), len(departments)),
        ('Employees assigned to designations', sum(bool(row['designationId']) for row in employees), total),
        ('Locations mapped to employees', sum(bool(row['branchId']) for row in employees), total),
        ('Department codes configured', coded, len(departments))]
    colors = ['#3B82F6', '#10B981', '#F59E0B', '#8B5CF6', '#EF4444', '#06B6D4', '#A855F7']
    hierarchy = []
    for row in sorted(departments, key=lambda value: value['name'])[:4]:
        head = people.get(row['departmentHeadEmployeeId'])
        hierarchy.append({'id': row['id'], 'title': full_name(head) if head else 'No head assigned', 'subtitle': f"{row['name']} · {dep[row['id']]} Employees",
            'tone': 'director', 'children': [{'id': row['id'] + '-desig', 'title': 'Designations',
                'subtitle': str(sum(value['departmentId'] == row['id'] for value in designations)) + ' Levels', 'tone': 'team'}]})
    senior = sum(des[row['id']] for row in designations if re.search('senior|head|director|vp', row['hierarchyLevel'], re.I))
    junior = sum(des[row['id']] for row in designations if re.search('junior|associate|intern|entry', row['hierarchyLevel'], re.I) and not re.search('senior|head|director|vp', row['hierarchyLevel'], re.I))
    assigned_designations = sum(des[row['id']] for row in designations)
    return {'stats': [{'key': key, 'value': str(value), 'label': label, 'iconBg': 'bg-blue-50', 'iconColor': 'text-blue-500'} for key, value, label in stats],
        'healthItems': [{'label': label, 'status': 'ok' if denominator and numerator == denominator else 'warning', 'highlight': f'{percentage(numerator, denominator)}%'} for label, numerator, denominator in health],
        'hierarchy': {'id': 'org-root', 'title': (profile or {}).get('companyName') or 'Organization', 'subtitle': 'Organization Overview', 'tone': 'ceo', 'children': hierarchy},
        'departmentDistribution': [{'label': row['name'], 'value': dep[row['id']], 'color': colors[i % len(colors)]} for i, row in enumerate(sorted(departments, key=lambda value: -dep[value['id']])[:7]) if dep[row['id']]],
        'locationBars': [{'label': row['name'], 'value': loc[row['id']]} for row in sorted(branches, key=lambda value: -loc[value['id']])[:5]],
        'designationBars': [{'label': label, 'value': value, 'color': color} for label, value, color in [('Senior', senior, '#EF4444'), ('Mid-level', max(0, assigned_designations - senior - junior), '#F59E0B'), ('Junior', junior, '#10B981')]],
        'costCenters': [{'name': row['name'] + (f" ({row['code']})" if row['code'] else ''), 'employees': dep[row['id']], 'allocation': f"{percentage(dep[row['id']], total)}%"} for row in sorted(departments, key=lambda value: -dep[value['id']])[:6]],
        'recentChanges': []}


class Location(Input):
    name: str = Field(min_length=1, max_length=255)
    city: str = Field(min_length=1, max_length=255)
    state: str = Field(min_length=1, max_length=255)
    country: str = Field(min_length=1, max_length=255)


class Department(Input):
    name: str = Field(min_length=1, max_length=255)
    code: str | None = Field(default=None, max_length=64)
    description: str = Field(default='', max_length=8000)
    departmentHeadEmployeeId: str | None = Field(default=None, max_length=100)


class Designation(Input):
    title: str = Field(min_length=1, max_length=255)
    hierarchyLevel: str = Field(default='Mid-level', min_length=1, max_length=128)
    description: str = Field(default='', max_length=8000)


class AddLocation(Location):
    action: Literal['addLocation']


class AddDepartment(Department):
    action: Literal['createDepartment']


class AddDesignation(Designation):
    action: Literal['addDesignation']
    departmentId: str = Field(min_length=1, max_length=100)


class ImportedDesignation(Designation):
    departmentCodeOrName: str = Field(min_length=1, max_length=255)


class Structure(Input):
    locations: list[Location] = Field(default_factory=list, max_length=200)
    departments: list[Department] = Field(default_factory=list, max_length=200)
    designations: list[ImportedDesignation] = Field(default_factory=list, max_length=500)


class ImportStructure(Input):
    action: Literal['importStructure']
    structure: Structure


def location(db, values):
    return insert(db, 'Branch', {**values, 'code': 'BR-' + uuid4().hex[:12].upper(), 'street': '', 'zip': '',
        'description': '', 'contactEmail': '', 'contactPhone': '', 'isActive': True})


def department(db, values):
    if values.get('departmentHeadEmployeeId'):
        find(db, 'Employee', values['departmentHeadEmployeeId'])
    return insert(db, 'Department', {**values, 'code': values.get('code') or 'DEP-' + uuid4().hex[:12].upper()})


@router.post('/actions')
def action(body: AddLocation | AddDepartment | AddDesignation | ImportStructure, user=Depends(admin), db=Depends(get_db)):
    values = body.model_dump(exclude={'action'})
    if isinstance(body, AddLocation):
        location(db, values)
    elif isinstance(body, AddDepartment):
        department(db, values)
    elif isinstance(body, AddDesignation):
        find(db, 'Department', body.departmentId, lock=True)
        insert(db, 'Designation', values)
    else:
        references = {}
        for row in rows(db, 'Department'):
            for key in (row['name'], row['code']):
                if key:
                    references.setdefault(key.casefold(), []).append(row['id'])
        for item in body.structure.locations:
            location(db, item.model_dump())
        for item in body.structure.departments:
            created = department(db, item.model_dump())
            for key in {created['name'].casefold(), created['code'].casefold()}:
                references.setdefault(key, []).append(created['id'])
        for item in body.structure.designations:
            matching = references.get(item.departmentCodeOrName.casefold(), [])
            if len(set(matching)) != 1:
                raise HTTPException(422, 'Designation department must match exactly one name or code')
            insert(db, 'Designation', {**item.model_dump(exclude={'departmentCodeOrName'}), 'departmentId': matching[0]})
    return {'ok': True}
