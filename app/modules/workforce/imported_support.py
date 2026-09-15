"""Helpdesk tickets with normalized legacy labels and verified employee ownership."""
import re
from collections import Counter
from datetime import timedelta
from typing import Literal

from fastapi import Depends, HTTPException, Query, Response
from pydantic import AliasChoices, Field, field_validator
from sqlalchemy import or_, text

from app.core.compatibility_routing import APIRouter
from app.core.imported_identity import linked_employee
from app.data.database import get_db
from app.data.imported import find, table
from app.modules.workforce.imported_assets import admin, insert, now, rows
from app.modules.workforce.imported_dashboards import avatar, lookup
from app.modules.workforce.imported_employee_profile import full_name
from app.modules.workforce.imported_leave import Input, output, staff
from app.modules.workforce.imported_organization import update

router = APIRouter(prefix='/api', tags=['HRMS helpdesk'])
STATUSES = ('OPEN', 'IN_PROGRESS', 'ESCALATED', 'RESOLVED', 'CLOSED')
PRIORITIES = ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')
CATEGORIES = {'PAYROLL': 'Payroll', 'IT': 'IT Support', 'HR': 'HR', 'LEAVE': 'Leave', 'POLICY': 'Policy', 'GENERAL': 'Other'}


def token(value):
    return re.sub(r'[\s-]+', '_', value.strip().upper())


def time_left(row):
    status = token(row['status'])
    if status in ('RESOLVED', 'CLOSED'):
        return status.title()
    if not row['dueAt']:
        return '—'
    hours = int((row['dueAt'] - now()).total_seconds() // 3600)
    return 'Overdue' if hours < 0 else f'{hours}h left' if hours < 24 else f'{hours // 24}d left'


def own_item(row):
    return {'id': row['ticketNumber'], 'rowId': row['id'], 'status': token(row['status']).replace('_', ' ').title(),
        'priority': token(row['priority']).title(), 'timeLeft': time_left(row), 'title': row['title'],
        'description': row['description'], 'category': row['category'], 'createdOn': row['createdAt'].strftime('%b %d, %Y')}


def ticket_item(db, row):
    employee = find(db, 'Employee', row['employeeId'])
    department = find(db, 'Department', employee['departmentId'], required=False) if employee['departmentId'] else None
    assigned = find(db, 'Employee', row['assignedToEmployeeId']) if row['assignedToEmployeeId'] else None
    return {'rowId': row['id'], 'ticketNumber': row['ticketNumber'], 'employee': full_name(employee),
        'dept': department['name'] if department else row['department'] or '—', 'initials': avatar(employee)['initials'],
        'avatarColor': 'bg-sky-200 text-sky-700', 'subject': row['title'],
        'category': CATEGORIES.get(token(row['category']), row['category']), 'priority': token(row['priority']).title(),
        'status': token(row['status']).replace('_', ' ').title(), 'assignedAgent': full_name(assigned) if assigned else 'Unassigned',
        'createdDate': row['createdAt'].strftime('%b %d, %Y')}


def ticket_record(db, id, lock=False):
    record = find(db, 'SupportTicket', id, required=False)
    if not record:
        matches = rows(db, 'SupportTicket', table(db, 'SupportTicket').c.ticketNumber == id)
        record = matches[0] if matches else None
    if not record:
        raise HTTPException(404, 'Ticket not found')
    return find(db, 'SupportTicket', record['id'], lock=True) if lock else record


def ticket_matches(row, status='', priority='', category=''):
    cat = token(category)
    cat = {'IT_SUPPORT': 'IT', 'OTHER': 'GENERAL'}.get(cat, cat)
    return (token(status) not in STATUSES or token(row['status']) == token(status)) and (
        token(priority) not in PRIORITIES or token(row['priority']) == token(priority)) and (
        cat not in CATEGORIES or token(row['category']) == cat)


@router.get('/support-tickets')
def own_tickets(status: str = '', user=Depends(staff), db=Depends(get_db)):
    employee = linked_employee(db, user, required=False)
    if not employee:
        return {'items': []}
    tbl = table(db, 'SupportTicket')
    items = rows(db, 'SupportTicket', or_(tbl.c.employeeId == employee['id'], tbl.c.assignedToEmployeeId == employee['id']), order=tbl.c.createdAt.desc())
    return {'items': [own_item(row) for row in items if ticket_matches(row, status)]}


class OwnTicketInput(Input):
    title: str = Field(min_length=1, max_length=512)
    description: str = Field(min_length=1, max_length=50000)
    category: str = Field(min_length=1, max_length=128)
    priority: Literal['Low', 'Medium', 'High'] = 'Medium'
    dueInHours: float | None = Field(default=None, gt=0, le=8760, allow_inf_nan=False)


def create_ticket(db, employee_id, values):
    find(db, 'Employee', employee_id)
    if values.get('assignedToEmployeeId'):
        find(db, 'Employee', values['assignedToEmployeeId'])
    if db.bind.dialect.name == 'postgresql':
        db.execute(text('SELECT pg_advisory_xact_lock(7310463)'))
    numbers = [int(match.group(1)) for row in rows(db, 'SupportTicket')
        if (match := re.fullmatch(r'TKT-(\d+)', row['ticketNumber'], re.IGNORECASE))]
    return insert(db, 'SupportTicket', {'ticketNumber': f'TKT-{max(numbers, default=0) + 1:03}',
        'employeeId': employee_id, 'status': 'OPEN', **values})


@router.post('/support-tickets', status_code=201)
def own_create(body: OwnTicketInput, user=Depends(staff), db=Depends(get_db)):
    employee = linked_employee(db, user, required=True)
    values = body.model_dump(exclude={'dueInHours'})
    values['priority'] = token(body.priority)
    values['dueAt'] = now() + timedelta(hours=body.dueInHours or {'High': 24, 'Medium': 48, 'Low': 120}[body.priority])
    return own_item(create_ticket(db, employee['id'], values))


@router.get('/ask-me/tickets')
def ask_tickets(scope: str = '', search: str = '', status: str = '', priority: str = '', category: str = '', user=Depends(staff), db=Depends(get_db)):
    clauses = []
    if scope == 'mine':
        employee = linked_employee(db, user, required=False)
        if not employee:
            return {'tickets': []}
        clauses.append(table(db, 'SupportTicket').c.employeeId == employee['id'])
    elif user.role not in ('admin', 'hr'):
        raise HTTPException(403, 'HR or administrator access is required')
    items = []
    for row in rows(db, 'SupportTicket', *clauses, order=table(db, 'SupportTicket').c.createdAt.desc()):
        if not ticket_matches(row, status, priority, category):
            continue
        item = ticket_item(db, row)
        if search.strip().casefold() in ' '.join(str(item[key]) for key in ('ticketNumber', 'employee', 'subject', 'dept')).casefold():
            items.append(item)
        if len(items) >= 1000:
            break
    return {'tickets': items}


class AskTicketInput(Input):
    employeeId: str = Field(min_length=1, max_length=255)
    subject: str = Field(min_length=1, max_length=512)
    description: str = Field(min_length=1, max_length=50000)
    category: Literal['PAYROLL', 'IT', 'HR', 'LEAVE', 'POLICY', 'GENERAL']
    priority: Literal['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']
    assignedToEmployeeId: str | None = Field(default=None, max_length=255, validation_alias=AliasChoices('assignedToEmployeeId', 'assignedToUserId'))


@router.post('/ask-me/tickets', status_code=201)
def ask_create(body: AskTicketInput, user=Depends(staff), db=Depends(get_db)):
    values = body.model_dump(exclude={'employeeId', 'subject'})
    values['title'] = body.subject
    if user.role not in ('admin', 'hr'):
        employee = linked_employee(db, user, required=True)
        if body.employeeId != employee['id']:
            raise HTTPException(403, 'You can only create tickets for your own profile')
        values['assignedToEmployeeId'] = None
    return ticket_item(db, create_ticket(db, body.employeeId, values))


@router.get('/admin/support-tickets')
def admin_tickets(status: str = '', priority: str = '', department: str = '', q: str = '', limit: int = Query(100, ge=1, le=500), user=Depends(admin), db=Depends(get_db)):
    items = []
    for row in rows(db, 'SupportTicket', order=table(db, 'SupportTicket').c.createdAt.desc()):
        if not ticket_matches(row, status, priority) or (department and row['department'] != department):
            continue
        if q.strip().casefold() not in ' '.join(row[key] for key in ('ticketNumber', 'title', 'description')).casefold():
            continue
        item = ticket_item(db, row)
        items.append({**item, 'id': row['ticketNumber'], 'description': row['description'], 'department': row['department'],
            'assignedTo': item['assignedAgent'], 'assignedToId': row['assignedToEmployeeId'], 'timeLeft': time_left(row), 'created': item['createdDate']})
        if len(items) >= limit:
            break
    return {'items': items}


def raw_ticket(db, row):
    employee = find(db, 'Employee', row['employeeId'])
    assigned = find(db, 'Employee', row['assignedToEmployeeId']) if row['assignedToEmployeeId'] else None
    return output({**row, 'employee': {key: employee[key] for key in ('firstName', 'lastName', 'email')},
        'assignedTo': {key: assigned[key] for key in ('firstName', 'lastName')} if assigned else None})


@router.get('/admin/support-tickets/by-id/{id}')
def admin_ticket(id: str, user=Depends(admin), db=Depends(get_db)):
    return raw_ticket(db, ticket_record(db, id))


@router.get('/ask-me/tickets/by-id/{id}')
def ask_ticket(id: str, user=Depends(admin), db=Depends(get_db)):
    row = ticket_record(db, id)
    return {'ticket': {'id': row['id'], 'subject': row['title'], 'description': row['description'], 'category': row['category'],
        'priority': token(row['priority']), 'status': token(row['status']), 'assignedToEmployeeId': row['assignedToEmployeeId']}}


class TicketPatch(Input):
    subject: str | None = Field(default=None, min_length=1, max_length=512)
    description: str | None = Field(default=None, min_length=1, max_length=50000)
    category: str | None = Field(default=None, min_length=1, max_length=128)
    department: str | None = Field(default=None, max_length=255)
    status: Literal['OPEN', 'IN_PROGRESS', 'ESCALATED', 'RESOLVED', 'CLOSED'] | None = None
    priority: Literal['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'] | None = None
    assignedToEmployeeId: str | None = Field(default=None, max_length=255, validation_alias=AliasChoices('assignedToEmployeeId', 'assignedToUserId'))

    @field_validator('status', 'priority', mode='before')
    @classmethod
    def normalize(cls, value):
        return token(value) if isinstance(value, str) else value


def patch_ticket(db, id, body):
    row = ticket_record(db, id, lock=True)
    values = body.model_dump(exclude_unset=True)
    if not values or any(value is None for key, value in values.items() if key not in ('department', 'assignedToEmployeeId')):
        raise HTTPException(422, 'Provide valid ticket changes')
    if 'subject' in values:
        values['title'] = values.pop('subject')
    if values.get('assignedToEmployeeId'):
        find(db, 'Employee', values['assignedToEmployeeId'])
    if 'status' in values and values['status'] != token(row['status']):
        # Closing a resolved ticket preserves resolution evidence; reopening clears it.
        status = values['status']
        values['resolvedAt'] = row['resolvedAt'] or now() if status in ('RESOLVED', 'CLOSED') else None
        values['closedAt'] = now() if status == 'CLOSED' else None
    return update(db, 'SupportTicket', row['id'], values)


@router.patch('/admin/support-tickets/by-id/{id}')
def admin_patch(id: str, body: TicketPatch, user=Depends(admin), db=Depends(get_db)):
    return raw_ticket(db, patch_ticket(db, id, body))


@router.patch('/ask-me/tickets/by-id/{id}')
def ask_patch(id: str, body: TicketPatch, user=Depends(admin), db=Depends(get_db)):
    return {'ticket': ticket_item(db, patch_ticket(db, id, body))}


@router.delete('/ask-me/tickets/by-id/{id}', status_code=204)
def delete_ticket(id: str, user=Depends(admin), db=Depends(get_db)):
    row = ticket_record(db, id, lock=True)
    db.execute(table(db, 'SupportTicket').delete().where(table(db, 'SupportTicket').c.id == row['id']))
    return Response(status_code=204)


@router.get('/ask-me/tickets/self-employee')
def self_employee(user=Depends(staff), db=Depends(get_db)):
    return {'employeeId': linked_employee(db, user, required=True)['id']}


@router.get('/ask-me/tickets/employees')
def employee_options(q: str = '', limit: int = Query(50, ge=1, le=100), user=Depends(admin), db=Depends(get_db)):
    departments = lookup(db, 'Department')
    people = rows(db, 'Employee', order=table(db, 'Employee').c.firstName)
    return [{'id': person['id'], 'name': full_name(person), 'code': person['employeeCode'],
        'department': departments.get(person['departmentId'], {}).get('name')} for person in people
        if q.strip().casefold() in (full_name(person) + ' ' + person['employeeCode']).casefold()][:limit]


@router.get('/ask-me/tickets/agents')
def agent_options(user=Depends(admin), db=Depends(get_db)):
    departments = lookup(db, 'Department')
    people = rows(db, 'Employee', table(db, 'Employee').c.status == 'ACTIVE', order=table(db, 'Employee').c.firstName)
    # An assignee is an employee; assignment never grants an application role.
    return [{'id': person['id'], 'label': full_name(person) + ' (' + person['employeeCode'] + ')' +
        (' · ' + departments[person['departmentId']]['name'] if person['departmentId'] in departments else ''),
        'email': person['email'] or ''} for person in people]


@router.get('/admin/support-tickets/stats')
def ticket_stats(user=Depends(admin), db=Depends(get_db)):
    items = rows(db, 'SupportTicket')
    counts = Counter(token(row['status']) for row in items)
    durations = [(row['closedAt'] or row['resolvedAt']) - row['createdAt'] for row in items if row['closedAt'] or row['resolvedAt']]
    average = sum(duration.total_seconds() for duration in durations) / len(durations) / 3600 if durations else None
    buckets = Counter()
    for row in items:
        probe = ((row['department'] or '') + ' ' + row['category']).lower()
        bucket = 'HR' if 'hr' in probe else 'Payroll' if any(word in probe for word in ('payroll', 'salary', 'finance')) else 'IT' if any(word in probe for word in ('it', 'hardware', 'network', 'vpn')) else 'Leave' if any(word in probe for word in ('leave', 'pto', 'time off')) else 'Other'
        buckets[bucket] += 1
    return {'total': len(items), 'open': counts['OPEN'], 'inProgress': counts['IN_PROGRESS'], 'closed': counts['CLOSED'] + counts['RESOLVED'],
        'closedOnly': counts['CLOSED'], 'resolved': counts['RESOLVED'], 'escalated': counts['ESCALATED'],
        'unassigned': sum(not row['assignedToEmployeeId'] for row in items), 'critical': sum(token(row['priority']) == 'CRITICAL' for row in items),
        'avgResolutionHours': average, 'avgResolutionLabel': f'{average:.1f}h' if average is not None else '—',
        'departmentDistribution': [{'name': name, 'value': buckets[name]} for name in ('HR', 'Payroll', 'IT', 'Leave', 'Other') if name != 'Other' or buckets[name]]}
