"""Employee applications/referrals share canonical RMS requisitions."""
from typing import Literal

from fastapi import Depends, HTTPException
from pydantic import Field
from sqlalchemy import func, select

from app.core.compatibility_routing import APIRouter
from app.core.imported_identity import linked_employee
from app.data.database import get_db
from app.data.imported import find, table
from app.modules.recruiting.models import JobReference, Requisition
from app.modules.recruiting.pipeline_api import jobs_query
from app.modules.workforce.imported_assets import admin, insert, now, rows
from app.modules.workforce.imported_employee_profile import full_name
from app.modules.workforce.imported_leave import Input, staff
from app.modules.workforce.imported_organization import update

router = APIRouter(prefix='/api', tags=['HRMS employee recruitment'])


def canonical_job(db, user, id, lock=False):
    query = jobs_query(user).where(Requisition.id == id)
    if lock:
        query = query.with_for_update(of=Requisition)
    result = db.execute(query).first()
    if not result:
        raise HTTPException(404, 'Job opening not found')
    return result[1]


def date_label(value):
    return value.strftime('%b %d, %Y')


def job_payload(job):
    details = job.job_details or {}
    kind = str(details.get('job_type') or 'FULL_TIME').upper().replace('-', '_').replace(' ', '_')
    if kind not in ('FULL_TIME', 'PART_TIME', 'INTERNSHIP', 'CONTRACT'):
        kind = 'FULL_TIME'
    return {'id': job.id, 'title': job.title, 'type': kind.replace('_', '-'),
        'salaryMin': float(details.get('salary_min') or 0), 'salaryMax': float(details.get('salary_max') or 0),
        'company': details.get('company_name') or '', 'location': details.get('location') or '', 'department': details.get('department') or '',
        'logo': details.get('logo') if details.get('logo') in ('google', 'facebook') else 'default'}


@router.get('/job-openings')
def employee_jobs(user=Depends(staff), db=Depends(get_db)):
    return {'jobs': [job_payload(job) for _, job in db.execute(jobs_query(user).where(Requisition.status == 'published').order_by(Requisition.created_at.desc()))]}


@router.get('/admin/job-openings')
def admin_jobs(user=Depends(admin), db=Depends(get_db)):
    result = []
    for _, job in db.execute(jobs_query(user).order_by(Requisition.created_at.desc())):
        counts = {}
        for model, key in (('JobApplication', 'applicationsCount'), ('JobReferral', 'referralsCount')):
            tbl = table(db, model)
            counts[key] = db.scalar(select(func.count()).select_from(tbl).where(tbl.c.jobOpeningId == job.id))
        result.append({**job_payload(job), **counts, 'isActive': job.status == 'published', 'createdOn': date_label(job.created_at)})
    return {'jobs': result}


@router.post('/admin/job-openings')
@router.patch('/admin/job-openings/{id}')
@router.delete('/admin/job-openings/{id}')
def use_canonical_jobs(id: str | None = None, user=Depends(admin)):
    raise HTTPException(409, 'Use the shared job editor and requisition approval actions')


def application_payload(db, user, record, administrative=False):
    job = job_payload(canonical_job(db, user, record['jobOpeningId']))
    label = record['status'].replace('_', ' ').title()
    if administrative:
        employee = find(db, 'Employee', record['employeeId'])
        return {'id': record['id'], 'jobTitle': job['title'], 'jobType': job['type'], 'applicantName': full_name(employee),
            'applicantCode': employee['employeeCode'], 'applicantEmail': employee['email'], 'appliedOn': date_label(record['appliedAt']),
            'status': record['status'], 'statusLabel': label}
    return {'id': record['id'], 'title': job['title'], 'type': job['type'], 'company': job['company'], 'appliedOn': date_label(record['appliedAt']), 'status': label}


def scoped_applications(db, user, employee=None):
    tbl = table(db, 'JobApplication')
    allowed = select(Requisition.id).where(Requisition.customer_id == user.customer_id)
    clauses = [tbl.c.jobOpeningId.in_(allowed)]
    if employee:
        clauses.append(tbl.c.employeeId == employee['id'])
    return rows(db, 'JobApplication', *clauses, order=tbl.c.appliedAt.desc())


@router.get('/job-applications')
def own_applications(user=Depends(staff), db=Depends(get_db)):
    employee = linked_employee(db, user, required=False)
    return {'applications': [application_payload(db, user, item) for item in scoped_applications(db, user, employee)] if employee else []}


class ApplicationInput(Input):
    jobOpeningId: str = Field(min_length=1, max_length=255)
    coverLetter: str | None = Field(None, max_length=20000)


@router.post('/job-applications', status_code=201)
def apply(body: ApplicationInput, user=Depends(staff), db=Depends(get_db)):
    employee = linked_employee(db, user)
    job = canonical_job(db, user, body.jobOpeningId, lock=True)
    if job.status != 'published':
        raise HTTPException(404, 'This job is not accepting applications')
    tbl = table(db, 'JobApplication')
    if db.scalar(select(tbl.c.id).where(tbl.c.jobOpeningId == job.id, tbl.c.employeeId == employee['id']).limit(1)):
        raise HTTPException(409, 'You have already applied to this job')
    record = insert(db, 'JobApplication', {'jobOpeningId': job.id, 'employeeId': employee['id'], 'coverLetter': body.coverLetter,
        'status': 'APPLIED', 'appliedAt': now()})
    return application_payload(db, user, record)


@router.get('/admin/job-applications')
def all_applications(user=Depends(admin), db=Depends(get_db)):
    return {'applications': [application_payload(db, user, item, True) for item in scoped_applications(db, user)]}


class ApplicationStatus(Input):
    status: Literal['APPLIED', 'IN_REVIEW', 'INTERVIEW', 'REJECTED', 'OFFERED']


@router.patch('/admin/job-applications/{id}')
def review_application(id: str, body: ApplicationStatus, user=Depends(admin), db=Depends(get_db)):
    record = find(db, 'JobApplication', id, lock=True)
    canonical_job(db, user, record['jobOpeningId'])
    employee = linked_employee(db, user, required=False)
    if employee and employee['id'] == record['employeeId']:
        raise HTTPException(403, 'Another HR administrator must review your application')
    return application_payload(db, user, update(db, 'JobApplication', id, {'status': body.status}), True)


def referral_payload(db, user, record, administrative=False):
    if record['jobOpeningId']:
        job = canonical_job(db, user, record['jobOpeningId'])
    else:
        job = None
    if administrative:
        referrer = find(db, 'Employee', record['referredByEmployeeId'])
        return {**{key: record[key] for key in ('id', 'candidateName', 'candidateEmail', 'role', 'status')},
            'referrerName': full_name(referrer), 'jobTitle': job.title if job else None,
            'referredOn': date_label(record['referredAt']), 'statusLabel': record['status'].title()}
    return {'id': record['id'], 'name': record['candidateName'], 'email': record['candidateEmail'], 'role': record['role'],
        'referredOn': date_label(record['referredAt']), 'status': record['status'].title()}


def scoped_referrals(db, user, employee=None):
    tbl = table(db, 'JobReferral')
    allowed = select(Requisition.id).where(Requisition.customer_id == user.customer_id)
    clauses = [tbl.c.jobOpeningId.is_(None) | tbl.c.jobOpeningId.in_(allowed)]
    if employee:
        clauses.append(tbl.c.referredByEmployeeId == employee['id'])
    return rows(db, 'JobReferral', *clauses, order=tbl.c.referredAt.desc())


@router.get('/job-referrals')
def own_referrals(user=Depends(staff), db=Depends(get_db)):
    employee = linked_employee(db, user, required=False)
    return {'referrals': [referral_payload(db, user, item) for item in scoped_referrals(db, user, employee)] if employee else []}


class ReferralInput(Input):
    candidateName: str = Field(min_length=1, max_length=255)
    candidateEmail: str = Field(min_length=3, max_length=255, pattern=r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
    role: str = Field(min_length=1, max_length=255)
    jobOpeningId: str | None = Field(None, max_length=255)


@router.post('/job-referrals', status_code=201)
def refer(body: ReferralInput, user=Depends(staff), db=Depends(get_db)):
    employee = linked_employee(db, user)
    if body.jobOpeningId:
        job = canonical_job(db, user, body.jobOpeningId, lock=True)
        if job.status != 'published':
            raise HTTPException(404, 'This job is not accepting referrals')
    record = insert(db, 'JobReferral', {**body.model_dump(), 'jobOpeningId': body.jobOpeningId or None,
        'referredByEmployeeId': employee['id'], 'status': 'PENDING', 'referredAt': now()})
    return referral_payload(db, user, record)


@router.get('/admin/job-referrals')
def all_referrals(user=Depends(admin), db=Depends(get_db)):
    return {'referrals': [referral_payload(db, user, item, True) for item in scoped_referrals(db, user)]}


class ReferralStatus(Input):
    status: Literal['PENDING', 'HIRED', 'REJECTED']


@router.patch('/admin/job-referrals/{id}')
def review_referral(id: str, body: ReferralStatus, user=Depends(admin), db=Depends(get_db)):
    record = find(db, 'JobReferral', id, lock=True)
    if record['jobOpeningId']:
        canonical_job(db, user, record['jobOpeningId'])
    return referral_payload(db, user, update(db, 'JobReferral', id, {'status': body.status}), True)
