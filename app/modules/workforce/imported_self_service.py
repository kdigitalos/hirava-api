"""Employee profile changes remain proposals until independently reviewed."""
from datetime import datetime, time, timedelta
from uuid import uuid4

from fastapi import Depends, HTTPException, Query
from pydantic import Field, ValidationError, create_model
from sqlalchemy import func, select

from app.core.compatibility_routing import APIRouter
from app.core.imported_identity import linked_employee
from app.data.database import get_db
from app.data.imported import dto, find, table
from app.modules.workforce.imported_assets import admin, insert, now, rows
from app.modules.workforce.imported_attendance import calendar_date, timestamp
from app.modules.workforce.imported_attendance_views import display_name
from app.modules.workforce.imported_leave import Input, employee_id, output, staff
from app.modules.workforce.imported_organization import update
from app.modules.workforce.imported_shared import bridge_user

router = APIRouter(prefix='/api', tags=['HRMS self-service requests'])

PROFILE_FIELDS = ('nationality maritalStatus displayName gender country state preferredLanguage timeZone personalEmail personalPhone '
                  'homeAddress permanentAddress emergencyName emergencyPhone emergencyEmail emergencyRelationship socialSecurityNumber '
                  'driversLicense passportNumber pastCompanyName pastJobTitle pastEmploymentType pastStartDate pastEndDate pastLocation '
                  'pastResponsibilities degree fieldOfStudy institution eduStartDate eduEndDate grade modeOfStudy eduLocation workSchedule '
                  'lastPromotionDate salaryBand payFrequency bankName bankAccountNumber bankRoutingNumber').split()
CORE_FIELDS = {'firstName': 'firstName', 'lastName': 'lastName', 'workEmail': 'email', 'workPhone': 'phone',
               'employmentType': 'employmentType', 'workLocation': 'workLocation', 'jobTitleName': 'jobTitleId', 'departmentName': 'departmentId'}
ProfileInput = create_model('ProfileChangeInput', __base__=Input,
    **{key: (str | None, Field(None, max_length=20000 if key in ('homeAddress', 'permanentAddress', 'pastResponsibilities') else 1000))
       for key in [*PROFILE_FIELDS, *CORE_FIELDS, 'dateOfBirth']},
    benefits=(list[str] | None, Field(None, max_length=100)))
TYPE_LABELS = {key: key.replace('_', ' ').title() for key in ('PROFILE_UPDATE', 'LEAVE_ADJUSTMENT', 'ADDRESS_CHANGE', 'EMERGENCY_CONTACT', 'DOCUMENT_REQUEST', 'BANK_DETAILS')}
TYPE_BY_LABEL = {value: key for key, value in TYPE_LABELS.items()}


def profile_values(body):
    values = body.model_dump(exclude_unset=True)
    if not values:
        raise HTTPException(422, 'Supply at least one profile field to change')
    for key, value in values.items():
        if isinstance(value, str):
            values[key] = value.strip() or None
    if values.get('dateOfBirth'):
        calendar_date(values['dateOfBirth'])
    if isinstance(values.get('benefits'), list):
        if any(len(item) > 1000 for item in values['benefits']):
            raise HTTPException(422, 'Each benefit must be no longer than 1000 characters')
        values['benefits'] = [item.strip() for item in values['benefits'] if item.strip()]
    return values


def profile_record(db, owner):
    tbl = table(db, 'EmployeeProfile')
    row = db.execute(select(tbl).where(tbl.c.employeeId == owner)).mappings().first()
    return dto(tbl, row) if row else None


def profile_dto(record):
    if not record:
        return {}
    result = {key: record[key] for key in [*PROFILE_FIELDS, 'benefits']}
    result['dateOfBirth'] = record['dateOfBirth'].isoformat()[:10] if record['dateOfBirth'] else None
    return result


def profile_payload(db, employee):
    department = find(db, 'Department', employee['departmentId'], required=False)
    title = find(db, 'JobTitle', employee['jobTitleId'], required=False)
    manager = find(db, 'Employee', employee['reportsToEmployeeId'], required=False)
    return {'employee': {**{key: employee[key] for key in ('id', 'employeeCode', 'firstName', 'lastName', 'email', 'phone', 'hireDate', 'employmentType', 'workLocation')},
                         'department': department['name'] if department else None, 'jobTitle': title['name'] if title else None,
                         'manager': display_name(manager) if manager else None},
            'profile': profile_dto(profile_record(db, employee['id']))}


@router.get('/my-profile')
def my_profile(user=Depends(staff), db=Depends(get_db)):
    return output(profile_payload(db, linked_employee(db, user)))


@router.get('/my-profile/pending-request')
def pending_profile(user=Depends(staff), db=Depends(get_db)):
    owner = employee_id(db, user)
    if not owner:
        return {'pending': None}
    tbl = table(db, 'EmployeeSelfServiceRequest')
    record = db.execute(select(tbl).where(tbl.c.employeeId == owner, tbl.c.requestType == 'PROFILE_UPDATE',
        tbl.c.status == 'PENDING').order_by(tbl.c.submittedAt.desc()).limit(1)).mappings().first()
    if record is None:
        return {'pending': None}
    record = dto(tbl, record)
    return output({'pending': {**{key: record[key] for key in ('id', 'referenceCode', 'submittedAt')}, 'payload': record['payloadJson'] or {}}})


@router.post('/my-profile', status_code=202)
@router.put('/my-profile', status_code=202)
@router.patch('/my-profile', status_code=202)
def propose_profile(body: ProfileInput, user=Depends(staff), db=Depends(get_db)):
    employee = linked_employee(db, user)
    values = profile_values(body)
    # Consistent owner-then-request lock order also serializes competing submissions.
    find(db, 'Employee', employee['id'], lock=True)
    tbl = table(db, 'EmployeeSelfServiceRequest')
    instant = now()
    db.execute(tbl.update().where(tbl.c.employeeId == employee['id'], tbl.c.requestType == 'PROFILE_UPDATE', tbl.c.status == 'PENDING')
        .values(status='REJECTED', reviewedAt=instant, updatedAt=instant, reviewNote='Superseded by a newer change request from the employee.'))
    record = insert(db, 'EmployeeSelfServiceRequest', {'employeeId': employee['id'], 'requestType': 'PROFILE_UPDATE', 'initiatedBy': 'SELF',
        'status': 'PENDING', 'referenceCode': 'SSR-' + uuid4().hex[:16].upper(), 'payloadJson': values, 'submittedAt': instant})
    return output({'pending': True, 'message': 'Your changes have been submitted for admin approval.',
                   'request': {key: record[key] for key in ('id', 'referenceCode', 'submittedAt')}})


@router.delete('/my-profile')
def delete_profile(user=Depends(staff)):
    raise HTTPException(409, 'Submit a profile change request for HR approval')


def request_row(db, record):
    employee = find(db, 'Employee', record['employeeId'])
    department = find(db, 'Department', employee['departmentId'], required=False)
    return {'id': record['id'], 'referenceCode': record['referenceCode'], 'type': TYPE_LABELS[record['requestType']],
            'employee': display_name(employee), 'empId': employee['employeeCode'], 'initiated': 'HR' if record['initiatedBy'] == 'HR' else record['initiatedBy'].title(),
            'dateSubmitted': record['submittedAt'].strftime('%m/%d/%Y'), 'status': record['status'].title(), 'department': department['name'] if department else '—'}


@router.get('/admin/self-service-requests')
def all_requests(search: str = Query('', max_length=200), type: str = '', status: str = '', department: str = '', dateFrom: str = '', dateTo: str = '',
                 user=Depends(admin), db=Depends(get_db)):
    data = rows(db, 'EmployeeSelfServiceRequest', order=table(db, 'EmployeeSelfServiceRequest').c.submittedAt.desc())
    total = len(data)
    target_type = TYPE_BY_LABEL.get(type, type if type in TYPE_LABELS else None)
    target_status = status.upper() if status.upper() in ('PENDING', 'APPROVED', 'REJECTED') else None
    start = datetime.combine(calendar_date(dateFrom), time.min) if dateFrom else None
    end = datetime.combine(calendar_date(dateTo), time.max) if dateTo else None
    selected = []
    for record in data:
        if target_type and record['requestType'] != target_type or target_status and record['status'] != target_status:
            continue
        if start and record['submittedAt'] < start or end and record['submittedAt'] > end:
            continue
        row = request_row(db, record)
        if department and department != 'All Departments' and row['department'] != department:
            continue
        if search and not any(search.casefold() in str(row[key]).casefold() for key in ('id', 'referenceCode', 'employee', 'empId')):
            continue
        selected.append(row)
    return {'requests': selected, 'departments': [r['name'] for r in rows(db, 'Department', order=table(db, 'Department').c.name)], 'total': total}


class AdminRequest(Input):
    employeeId: str = Field(min_length=1, max_length=100)
    requestType: str = Field(min_length=1, max_length=100)
    initiatedBy: str = 'SELF'
    status: str = 'PENDING'
    submittedAt: str | None = None
    notes: str | None = Field(None, max_length=20000)


@router.post('/admin/self-service-requests', status_code=201)
def create_admin_request(body: AdminRequest, user=Depends(admin), db=Depends(get_db)):
    find(db, 'Employee', body.employeeId, lock=True)
    kind = TYPE_BY_LABEL.get(body.requestType, body.requestType)
    if kind not in TYPE_LABELS:
        raise HTTPException(422, 'Choose a valid request type')
    if body.status.upper() != 'PENDING':
        raise HTTPException(422, 'New requests must start pending review')
    initiator = body.initiatedBy.upper()
    if initiator not in ('SELF', 'MANAGER', 'HR'):
        raise HTTPException(422, 'Choose Self, Manager or HR as the initiator')
    record = insert(db, 'EmployeeSelfServiceRequest', {'employeeId': body.employeeId, 'requestType': kind, 'initiatedBy': initiator,
        'status': 'PENDING', 'referenceCode': 'SSR-' + uuid4().hex[:16].upper(), 'notes': body.notes or None,
        'submittedAt': timestamp(body.submittedAt) if body.submittedAt else now()})
    return request_row(db, record)


@router.get('/admin/self-service-requests/{id}')
def request_detail(id: str, user=Depends(admin), db=Depends(get_db)):
    record = find(db, 'EmployeeSelfServiceRequest', id)
    employee = find(db, 'Employee', record['employeeId'])
    payload = profile_payload(db, employee)
    current = {**{key: employee[column] for key, column in CORE_FIELDS.items() if key not in ('jobTitleName', 'departmentName')},
               'jobTitleName': payload['employee']['jobTitle'], 'departmentName': payload['employee']['department'], **payload['profile']}
    reviewer = find(db, 'User', record['reviewedById'], required=False)
    return output({**{key: record[key] for key in ('id', 'referenceCode', 'requestType', 'initiatedBy', 'status', 'submittedAt', 'notes', 'reviewNote', 'reviewedAt')},
                   'reviewedBy': {key: reviewer[key] for key in ('id', 'name', 'email')} if reviewer else None,
                   'employee': {**{key: employee[key] for key in ('id', 'employeeCode', 'firstName', 'lastName')}, 'displayName': display_name(employee)},
                   'payload': record['payloadJson'], 'current': current})


def apply_profile(db, owner, raw):
    if not raw:
        return
    try:
        values = profile_values(ProfileInput.model_validate(raw))
    except ValidationError:
        raise HTTPException(422, 'The saved proposal has invalid fields; ask the employee to submit it again') from None
    core = {CORE_FIELDS[key]: value for key, value in values.items() if key in CORE_FIELDS}
    for key, model in [('jobTitleName', 'JobTitle'), ('departmentName', 'Department')]:
        if key not in values:
            continue
        name = values[key]
        if name:
            tbl = table(db, model)
            found = db.scalar(select(tbl.c.id).where(func.lower(tbl.c.name) == name.lower()).limit(1))
            core[CORE_FIELDS[key]] = found or insert(db, model, {'name': name})['id']
        else:
            core[CORE_FIELDS[key]] = None
    for key in ('firstName', 'lastName'):
        if key in core and core[key] is None:
            core[key] = ''
    profile = {key: value for key, value in values.items() if key not in CORE_FIELDS}
    if profile.get('dateOfBirth'):
        profile['dateOfBirth'] = calendar_date(profile['dateOfBirth'])
    if profile:
        existing = profile_record(db, owner)
        if existing:
            update(db, 'EmployeeProfile', existing['id'], profile)
        else:
            insert(db, 'EmployeeProfile', {'employeeId': owner, **profile})
    if core:
        update(db, 'Employee', owner, core)


class Review(Input):
    status: str
    notes: str | None = Field(None, max_length=20000)
    reviewNote: str | None = Field(None, max_length=20000)


@router.patch('/admin/self-service-requests/{id}')
def review_request(id: str, body: Review, user=Depends(admin), db=Depends(get_db)):
    status = body.status.upper()
    if status not in ('PENDING', 'APPROVED', 'REJECTED'):
        raise HTTPException(422, 'Choose Pending, Approved or Rejected')
    initial = find(db, 'EmployeeSelfServiceRequest', id)
    employee = find(db, 'Employee', initial['employeeId'], lock=True)
    if employee_id(db, user) == employee['id']:
        raise HTTPException(403, 'You cannot review your own request')
    record = find(db, 'EmployeeSelfServiceRequest', id, lock=True)
    if record['status'] != 'PENDING':
        raise HTTPException(409, 'This request has already been reviewed; submit a new request for further changes')
    values = {'status': status}
    if 'notes' in body.model_fields_set:
        values['notes'] = body.notes or None
    if status != 'PENDING':
        reviewer = bridge_user(db, user)
        values.update(reviewedById=reviewer['id'], reviewedAt=now(), reviewNote=body.reviewNote or body.notes or None)
        # Payload application and decision stamp commit or roll back together.
        if status == 'APPROVED' and record['requestType'] == 'PROFILE_UPDATE':
            apply_profile(db, record['employeeId'], record['payloadJson'])
    return request_row(db, update(db, 'EmployeeSelfServiceRequest', id, values))
