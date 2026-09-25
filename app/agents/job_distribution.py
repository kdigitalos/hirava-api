"""Posting preparation and explicitly manual tracking; no external delivery claim."""
from typing import Literal
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from app.agents.models import JobDistribution
from app.core.compatibility_routing import APIRouter
from app.core.security import require
from app.core.service import audit, view
from app.data.database import get_db, utcnow
from app.modules.recruiting.models import JobReference
from app.modules.recruiting.router import scoped_requisition

router = APIRouter(prefix='/api/job-distribution', tags=['Job distribution'])
reader = require('hr', 'recruiter', module='rms')
writer = require('recruiter', module='rms')
Destination = Literal['linkedin', 'indeed', 'naukri', 'monster']
DESTINATIONS = {'linkedin': 'LinkedIn', 'indeed': 'Indeed', 'naukri': 'Naukri', 'monster': 'Monster'}
HOSTS = {'linkedin': ('linkedin.com',), 'indeed': ('indeed.com',),
         'naukri': ('naukri.com',), 'monster': ('monster.com', 'foundit.in', 'foundit.com')}


class Prepare(BaseModel):
    model_config = ConfigDict(extra='forbid')
    destinations: list[Destination] = Field(min_length=1, max_length=4)


class ManualUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    expected_version: int = Field(ge=1)
    status: Literal['reported_live', 'reported_closed']
    external_url: str = Field(default='', max_length=2000)

    @model_validator(mode='after')
    def valid_url(self):
        if self.status == 'reported_live' and not self.external_url:
            raise ValueError('Enter the listing URL after posting on the destination website.')
        if self.external_url:
            parsed = urlsplit(self.external_url)
            if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None, 443):
                raise ValueError('Use an HTTPS listing URL without embedded credentials.')
        return self


def snapshot(job):
    details = job.job_details or {}
    # Exclude recruiter IDs, internal budgets and arbitrary private extra fields.
    return {'title': job.title, 'description': job.description,
            **{k: details.get(k) for k in ('company_name', 'location', 'job_type', 'work_mode',
                                         'salary_min', 'salary_max', 'currency', 'required_skills')}}


def result(db, job, user):
    current = snapshot(job)
    saved = {r.destination: r for r in db.scalars(select(JobDistribution).where(
        JobDistribution.requisition_id == job.id, JobDistribution.customer_id == user.customer_id))}
    alias = db.scalar(select(JobReference.id).where(JobReference.requisition_id == job.id))
    return {'job_status': job.status, 'careers': {'status': job.status,
            'path': f'/careers/apply/{alias}' if alias and job.status == 'published' else None},
            'destinations': [{'id': key, 'name': name, 'connected': False,
                'record': view(saved[key], exclude=('customer_id', 'actor_id')) if key in saved else None,
                'content_changed': key in saved and saved[key].snapshot != current,
                'closure_needed': key in saved and saved[key].status == 'reported_live' and job.status == 'closed'}
                for key, name in DESTINATIONS.items()]}


@router.get('/jobs/{job_id}')
def get_distribution(job_id: str, user=Depends(reader), db=Depends(get_db)):
    return result(db, scoped_requisition(db, job_id, user), user)


@router.post('/jobs/{job_id}/prepare')
def prepare(job_id: str, body: Prepare, request: Request, user=Depends(writer), db=Depends(get_db)):
    job = scoped_requisition(db, job_id, user, lock=True)
    if job.status not in ('approved', 'published'):
        raise HTTPException(409, 'Approve the job before preparing external postings.')
    current = snapshot(job)
    for destination in dict.fromkeys(body.destinations):
        row = db.scalar(select(JobDistribution).where(JobDistribution.requisition_id == job.id,
                                                       JobDistribution.destination == destination))
        if row and row.customer_id != user.customer_id:
            raise HTTPException(404, 'Record not found')
        if row and row.status == 'reported_live':
            raise HTTPException(409, 'An existing listing is recorded. Close it on the destination website and record closure before preparing a new posting.')
        if row and row.status == 'prepared' and row.snapshot == current:
            continue
        if not row:
            row = JobDistribution(customer_id=user.customer_id, requisition_id=job.id,
                                  destination=destination, status='prepared')
            db.add(row)
        row.status = 'prepared'; row.external_url = None
        row.snapshot = current; row.actor_id = user.id; row.updated_at = utcnow()
        audit(db, user, 'job_distribution.prepared', row, request, destination=destination)
    db.flush()
    return result(db, job, user)


@router.post('/jobs/{job_id}/{destination}/manual-status')
def record_manual(job_id: str, destination: Destination, body: ManualUpdate, request: Request,
                  user=Depends(writer), db=Depends(get_db)):
    job = scoped_requisition(db, job_id, user, lock=True)
    row = db.scalar(select(JobDistribution).where(JobDistribution.requisition_id == job.id,
        JobDistribution.customer_id == user.customer_id, JobDistribution.destination == destination).with_for_update())
    if not row: raise HTTPException(404, 'Prepare this destination first.')
    if row.version != body.expected_version: raise HTTPException(409, 'Posting changed. Refresh before saving.')
    if body.status == 'reported_live':
        if job.status != 'published': raise HTTPException(409, 'Publish the Hirava job before recording a live listing.')
        host = urlsplit(body.external_url).hostname
        if not any(host == domain or host.endswith('.' + domain) for domain in HOSTS[destination]):
            raise HTTPException(422, 'Use a listing URL from the selected destination.')
        row.external_url = body.external_url
    elif row.status != 'reported_live':
        raise HTTPException(409, 'Only a reported live listing can be recorded as closed.')
    row.status = body.status; row.actor_id = user.id; row.updated_at = utcnow()
    audit(db, user, 'job_distribution.manual_status', row, request, status=row.status, destination=destination)
    db.flush()
    return result(db, job, user)
