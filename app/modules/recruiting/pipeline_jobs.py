"""Read compatibility for canonical requisitions; old mutation paths stay closed."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Query, Request
from sqlalchemy import select

from app.core.compatibility_routing import APIRouter
from app.core.models import AuditEvent, User
from app.data.database import get_db
from app.modules.recruiting.pipeline_api import candidates_query, jobs_query, read, write
from app.modules.recruiting.public_intake import pipeline_table
from app.modules.recruiting.models import JobReference

router = APIRouter(prefix="/api", tags=["RMS job compatibility"])


def utc(value):
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def all_jobs(db, user):
    people = {row.id: row for row in db.scalars(select(User).where(User.customer_id == user.customer_id))}
    table = pipeline_table(db)
    applicants = defaultdict(list)
    for row in db.execute(candidates_query(table, user).with_only_columns(table.c.id, table.c.job_opening_id).order_by(table.c.id)):
        applicants[row.job_opening_id].append(str(row.id))
    changed = {}
    for event in db.scalars(select(AuditEvent).where(AuditEvent.customer_id == user.customer_id,
                          AuditEvent.resource_type == 'requisitions').order_by(AuditEvent.created_at)):
        changed[event.resource_id] = event.created_at
    result = []
    fields = {'companyName': 'company_name', 'jobType': 'job_type', 'workMode': 'work_mode',
              'jobLink': 'job_link', 'location': 'location', 'hiringFlow': 'hiring_flow'}
    for alias, parent in db.execute(jobs_query(user).order_by(JobReference.id)):
        details = parent.job_details or {}
        recruiter = people.get(details.get('recruiter_id'))
        owner = people.get(parent.requested_by)
        result.append({'id': alias, 'jobId': f'job{alias:03d}', 'jobTitle': parent.title,
            'jobDescription': parent.description, 'status': {'published': 'Open', 'closed': 'Close'}.get(parent.status, parent.status.title()),
            **{key: details.get(value, '') for key, value in fields.items()},
            'recruiter': recruiter.name if recruiter else '', 'hiringDueDate': utc(details.get('hiring_due_date')),
            'budget': float(details['budget']) if details.get('budget') is not None else None,
            'noOfOpenings': details.get('no_of_openings', 1), 'extraFields': details.get('extra_fields'),
            'requiredSkills': details.get('required_skills', []), 'candidateIds': applicants[alias],
            'createdBy': (owner.auth_subject or f'local|{owner.id}') if owner else None,
            'createdAt': utc(parent.created_at), 'updatedAt': utc(changed.get(parent.id, parent.created_at))})
    return result


def filtered_jobs(db, user, params):
    rows = all_jobs(db, user)
    if params.get('id'):
        try:
            alias = int(params['id'])
        except ValueError:
            raise HTTPException(422, 'Job ID must be a number') from None
        rows = [row for row in rows if row['id'] == alias]
    for key in ('jobType', 'workMode', 'status'):
        if params.get(key):
            choices = {value.strip().lower() for value in params[key].split(',')}
            rows = [row for row in rows if row[key].lower() in choices]
    if params.get('myJob'):
        rows = [row for row in rows if row['createdBy'] == params['myJob']]
    if params.get('searchKey'):
        search = params['searchKey'].lower()
        rows = [row for row in rows if search in row['jobTitle'].lower() or search in row['companyName'].lower()]
    if params.get('priority'):
        days = {'week': 7, 'month': 30, 'year': 365}.get(params['priority'])
        if days is None:
            raise HTTPException(422, 'Choose week, month or year')
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        rows = [row for row in rows if row['createdAt'] >= cutoff]
    return rows


@router.get('/jobOpenings')
def jobs(request: Request, user=Depends(read), db=Depends(get_db)):
    rows = filtered_jobs(db, user, request.query_params)
    return {'data': (rows[0] if rows else None) if request.query_params.get('id') else rows}


@router.get('/jobOpenings/active')
def active_jobs(request: Request, user=Depends(read), db=Depends(get_db)):
    rows = sorted(filtered_jobs(db, user, request.query_params), key=lambda row: row['createdAt'], reverse=True)
    data = [{'jobTitle': row['jobTitle'], 'hiringFlow': row['hiringFlow'], 'applicationCount': len(row['candidateIds'])}
            for row in rows if row['status'] not in {'Close', 'Completed'}]
    return {'data': (data[0] if data else None) if request.query_params.get('id') else data}


@router.post('/jobOpenings')
@router.put('/jobOpenings')
@router.patch('/jobOpenings')
@router.delete('/jobOpenings')
def canonical_job_actions(user=Depends(write)):
    raise HTTPException(409, 'Use the shared job editor and requisition approval actions')
