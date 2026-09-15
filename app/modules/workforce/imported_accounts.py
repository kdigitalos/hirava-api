"""Retained invitation URLs delegate to the authoritative native account service."""
from fastapi import Depends, HTTPException, Request
from pydantic import EmailStr, Field, ValidationError, field_validator
from sqlalchemy import select

from app.core.compatibility_routing import APIRouter
from app.core.invitations import Invite, invite
from app.core.schemas import Input, Role
from app.core.models import User
from app.core.service import audit
from app.core.security import require
from app.data.database import get_db
from app.data.imported import dto, find, table

router = APIRouter(prefix='/api', tags=['Account compatibility'])
admin = require('admin', module='hrms')


class CreateAccount(Input):
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    role: Role
    employeeId: str | None = Field(default=None, min_length=1, max_length=100)
    employeeCode: str | None = Field(default=None, min_length=1, max_length=100)

    @field_validator('role', mode='before')
    @classmethod
    def normalize_role(cls, value):
        if isinstance(value, str):
            value = value.strip().lower()
            return {'hr_manager': 'hr', 'team_lead': 'manager'}.get(value, value)
        return value


class Provision(Input):
    employeeId: str = Field(min_length=1, max_length=100)
    role: Role

    @field_validator('role', mode='before')
    @classmethod
    def normalize_role(cls, value):
        return value.strip().lower() if isinstance(value, str) else value


def result(data):
    accepted = data['invitation']['status'] == 'accepted_by_provider'
    account = data['account']
    return {**data, 'success': accepted,
            'user': {'id': account['id'], 'email': account['email'], 'role': account['role']},
            'message': ('Account ready. Auth0 accepted the password-setup email request; inbox delivery is not confirmed.'
                        if accepted else 'Invitation needs attention. Check its status and retry from Account Access.')}


@router.get('/admin/employees-pending-access')
def pending(actor=Depends(admin), db=Depends(get_db)):
    employees = table(db, 'Employee')
    query = select(employees).where(employees.c.userId.is_(None), employees.c.email.is_not(None),
                                   employees.c.status != 'TERMINATED').order_by(employees.c.lastName, employees.c.firstName)
    records = [dto(employees, row) for row in db.execute(query).mappings()]
    return [{key: row[key] for key in ('id', 'employeeCode', 'firstName', 'lastName', 'email')}
            for row in records if row['email'].strip()]


@router.post('/admin/create-user', status_code=201)
def create(body: CreateAccount, request: Request, actor=Depends(admin), db=Depends(get_db)):
    employee_id = body.employeeId
    if body.employeeCode:
        employees = table(db, 'Employee')
        selected = db.scalar(select(employees.c.id).where(employees.c.employeeCode == body.employeeCode))
        if not selected:
            raise HTTPException(404, 'Employee code was not found')
        if employee_id and employee_id != selected:
            raise HTTPException(422, 'Employee ID and code refer to different employees')
        employee_id = selected
    return result(invite(Invite(name=body.name, email=body.email, role=body.role, employee_id=employee_id), request, actor, db))


@router.post('/admin/provision-employee-access', status_code=201)
def provision(body: Provision, request: Request, actor=Depends(admin), db=Depends(get_db)):
    employee = find(db, 'Employee', body.employeeId, lock=True)
    if employee.get('userId'):
        raise HTTPException(409, 'This employee already has a linked account')
    if employee['status'] == 'TERMINATED':
        raise HTTPException(409, 'A terminated employee cannot receive new login access')
    if not (employee.get('email') or '').strip():
        raise HTTPException(422, 'Add a valid email to the employee record before inviting them')
    name = ' '.join(value for value in (employee.get('firstName'), employee.get('lastName')) if value)
    try:
        invitation = Invite(name=name, email=employee['email'], role=body.role, employee_id=body.employeeId)
    except ValidationError:
        raise HTTPException(422, 'Add a valid name and email to the employee record before inviting them')
    return result(invite(invitation, request, actor, db))


def account_dto(account):
    return {'id': account.id, 'name': account.name, 'email': account.email,
            'role': account.role.upper(), 'active': account.active, 'createdAt': account.created_at, 'version': account.version}


def account_by_id(db, record_id, actor, lock=False):
    query = select(User).where(User.id == record_id, User.customer_id == actor.customer_id)
    account = db.scalar(query.with_for_update() if lock else query)
    if not account:
        # Old links can contain a Prisma ID. Resolve only through a verified subject.
        bridge = find(db, 'User', record_id, required=False)
        if bridge and bridge.get('auth0Sub'):
            query = select(User).where(User.auth_subject == bridge['auth0Sub'], User.customer_id == actor.customer_id)
            account = db.scalar(query.with_for_update() if lock else query)
    if not account:
        raise HTTPException(404, 'Account not found')
    return account


class AccountPatch(Input):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    role: Role | None = None

    @field_validator('role', mode='before')
    @classmethod
    def normalize_role(cls, value):
        return value.strip().lower() if isinstance(value, str) else value


@router.get('/users')
def users(actor=Depends(admin), db=Depends(get_db)):
    return [account_dto(account) for account in db.scalars(select(User).where(User.customer_id == actor.customer_id).order_by(User.created_at.desc()))]


@router.get('/users/{record_id}')
def get_account(record_id: str, actor=Depends(admin), db=Depends(get_db)):
    return account_dto(account_by_id(db, record_id, actor))


@router.patch('/users/{record_id}')
def patch_account(record_id: str, body: AccountPatch, request: Request, actor=Depends(admin), db=Depends(get_db)):
    account = account_by_id(db, record_id, actor, lock=True)
    if not body.model_dump(exclude_none=True):
        raise HTTPException(422, 'Provide a name or application role')
    previous_role = account.role
    if body.role and body.role != account.role:
        if account.id == actor.id:
            raise HTTPException(409, 'Another administrator must change your role')
        if body.role == 'candidate':
            employee, bridge = table(db, 'Employee'), table(db, 'User')
            linked = db.scalar(select(employee.c.id).select_from(employee.join(bridge, employee.c.userId == bridge.c.id))
                .where(bridge.c.auth0Sub == (account.auth_subject or f'local|{account.id}')))
            if linked:
                raise HTTPException(409, 'Unlink the employee before changing this account to Candidate')
        account.role = body.role
        account.token_version += 1
    if body.name:
        account.name = body.name
    audit(db, actor, 'user.profile_role_changed', account, request, previous_role=previous_role, role=account.role)
    return account_dto(account)
