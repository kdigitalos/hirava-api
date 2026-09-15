"""Assigned employee tasks and HR calendar items."""
from datetime import datetime
from typing import Literal

from fastapi import Depends, HTTPException
from pydantic import Field

from app.core.compatibility_routing import APIRouter
from app.core.imported_identity import linked_employee
from app.data.database import get_db
from app.data.imported import find, table
from app.modules.workforce.imported_assets import admin, insert, now, rows
from app.modules.workforce.imported_attendance import calendar_date, timestamp
from app.modules.workforce.imported_leave import Input, output, staff
from app.modules.workforce.imported_organization import update

router = APIRouter(prefix='/api', tags=['HRMS employee tasks'])


@router.get('/employee-tasks')
def own_tasks(user=Depends(staff), db=Depends(get_db)):
    employee = linked_employee(db, user, required=False)
    if not employee:
        return {'items': []}
    def item(id, kind, title, category, due, complete):
        day = due.date() if isinstance(due, datetime) else due
        return {'id': id, 'kind': kind, 'title': title, 'category': category, 'date': f'{day:%b} {day.day}',
            'dueIso': day.isoformat(), 'status': 'Completed' if complete else 'Over Due' if day < now().date() else 'Pending'}
    result = [item(row['id'], 'task', row['title'], {'ONBOARDING': 'On boarding', 'LEARNING': 'Training'}.get(row['source'], 'HR'),
                   row['dueDate'], row['status'] == 'COMPLETED') for row in rows(db, 'EmployeeTask', table(db, 'EmployeeTask').c.employeeId == employee['id'])]
    for row in rows(db, 'SupportTicket', table(db, 'SupportTicket').c.assignedToEmployeeId == employee['id']):
        result.append(item('ticket:' + row['id'], 'ticket', row['ticketNumber'] + ': ' + row['title'], 'Support', row['dueAt'] or row['createdAt'], row['status'].strip().lower() in ('resolved', 'closed')))
    return {'items': sorted(result, key=lambda row: (row['dueIso'], row['title']))}


class CompletionInput(Input):
    completed: bool = Field(strict=True)


@router.patch('/employee-tasks/{id}')
def complete_task(id: str, body: CompletionInput, user=Depends(staff), db=Depends(get_db)):
    employee = linked_employee(db, user)
    task = find(db, 'EmployeeTask', id, lock=True)
    if task['employeeId'] != employee['id']:
        raise HTTPException(404, 'Task not found')
    update(db, 'EmployeeTask', id, {'status': 'COMPLETED' if body.completed else 'IN_PROGRESS'})
    return {'ok': True}


class TaskInput(Input):
    employeeId: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=512)
    description: str = Field(min_length=1, max_length=20000)
    source: Literal['LEAVE', 'LEARNING', 'ONBOARDING']
    dueDate: str


@router.post('/admin/employee-tasks', status_code=201)
def assign_task(body: TaskInput, user=Depends(admin), db=Depends(get_db)):
    find(db, 'Employee', body.employeeId)
    task = insert(db, 'EmployeeTask', {**body.model_dump(), 'dueDate': calendar_date(body.dueDate), 'status': 'IN_PROGRESS', 'detailKind': 'generic'})
    return {'id': task['id']}


class ScheduleInput(Input):
    type: Literal['meetings', 'events']
    title: str = Field(min_length=1, max_length=512)
    location: str = Field(min_length=1, max_length=1000)
    startAt: str
    endAt: str


def schedule_item(record):
    return {**{key: record[key] for key in ('id', 'title', 'location', 'startAt', 'endAt')},
        'type': 'meetings' if record['itemType'] == 'MEETING' else 'events'}


@router.get('/admin/schedule-items')
def schedule(user=Depends(admin), db=Depends(get_db)):
    return output({'items': [schedule_item(item) for item in rows(db, 'AdminScheduleItem', order=table(db, 'AdminScheduleItem').c.startAt)[:50]]})


@router.post('/admin/schedule-items', status_code=201)
def add_schedule(body: ScheduleInput, user=Depends(admin), db=Depends(get_db)):
    start, end = timestamp(body.startAt), timestamp(body.endAt)
    if end <= start:
        raise HTTPException(422, 'The end time must be after the start time')
    record = insert(db, 'AdminScheduleItem', {'itemType': 'MEETING' if body.type == 'meetings' else 'EVENT',
        'title': body.title, 'location': body.location, 'startAt': start, 'endAt': end})
    return output({'item': schedule_item(record)})
