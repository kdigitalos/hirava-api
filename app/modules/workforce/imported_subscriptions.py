"""Public prospect intake. Internal review status is never supplied by visitors."""
from datetime import date
import re
from typing import Literal
from pydantic import Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from app.core.models import CompanyRegistrationReview
from app.core.schemas import Input
from app.core.service import audit, view
from fastapi import BackgroundTasks, Depends, Request, HTTPException, Query, Response
from app.core.security import current_user
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from app.core.compatibility_routing import APIRouter
from app.core.imported_mail import smtp_configured, subscription_emails
from app.data.database import get_db, utcnow
from app.data.imported import SCHEMA, table, dto, find
from app.modules.workforce.imported_assets import insert, wire

router = APIRouter(prefix='/api', tags=['Public subscription intake'])
EMAIL = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]{2,}$')
PHONE = re.compile(r'^[+()\d][\d\s()+-]{6,19}$')


def platform_admin(request: Request, user=Depends(current_user)):
    allowed = {value.strip() for value in request.app.state.settings.platform_admin_user_ids.split(',') if value.strip()}
    if user.id not in allowed:
        raise HTTPException(403, 'Platform Admin access is required')
    return user


@router.get('/platform/access')
def platform_access(user=Depends(platform_admin)):
    return {'allowed': True}


@router.get('/platform/registrations')
def registrations(response: Response, page: int = Query(1, ge=1),
                  q: str = Query('', max_length=200), user=Depends(platform_admin), db=Depends(get_db)):
    response.headers['Cache-Control'] = 'no-store'
    tbl = table(db, 'ClientSubscriptionRequest')
    query = select(tbl)
    if q.strip():
        query = query.where(func.lower(tbl.c.companyName).contains(q.strip().lower(), autoescape=True))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    records = db.execute(query.order_by(tbl.c.createdAt.desc(), tbl.c.id).offset((page - 1) * 20).limit(20)).mappings().all()
    items = [dto(tbl, row) for row in records]
    reviews = {r.registration_id: view(r) for r in db.scalars(select(CompanyRegistrationReview).where(
        CompanyRegistrationReview.customer_id == user.customer_id,
        CompanyRegistrationReview.registration_id.in_([r['id'] for r in items])))} if items else {}
    for item in items:
        item['review'] = reviews.get(item['id'])
    return wire({'items': items, 'total': total, 'page': page, 'pageSize': 20})


class RegistrationDecision(Input):
    decision: Literal['APPROVED', 'REJECTED', 'PENDING']
    note: str = Field(default='', max_length=2000)
    expected_version: int = Field(ge=0)


@router.post('/platform/registrations/{registration_id}/review')
def review_registration(registration_id: str, body: RegistrationDecision, request: Request,
                        actor=Depends(platform_admin), db=Depends(get_db)):
    registration = find(db, 'ClientSubscriptionRequest', registration_id, lock=True)
    if registration['status'] == 'CONVERTED':
        raise HTTPException(409, 'This registration has already been converted and cannot be reviewed here.')
    if body.decision == 'REJECTED' and not body.note.strip():
        raise HTTPException(422, 'Add a reason before rejecting this request.')
    record = db.scalar(select(CompanyRegistrationReview).where(
        CompanyRegistrationReview.customer_id == actor.customer_id,
        CompanyRegistrationReview.registration_id == registration_id).with_for_update())
    if body.expected_version != (record.version if record else 0):
        raise HTTPException(409, 'This request was changed by another review. Refresh before saving.')
    previous = record.decision if record else 'PENDING'
    if record is None:
        record = CompanyRegistrationReview(customer_id=actor.customer_id, registration_id=registration_id)
        db.add(record)
    record.decision, record.note = body.decision, body.note.strip()
    record.reviewed_by, record.reviewed_at = actor.id, utcnow()
    record.requested_terms = {k: registration[k] for k in ('productRequired', 'subscriptionPlan', 'rmsUserCount', 'hrmsUserCount')}
    try:
        db.flush()
        audit(db, actor, 'company_registration.reviewed', record, request,
              registration_id=registration_id, previous_decision=previous, decision=record.decision)
        db.flush()
    except (IntegrityError, StaleDataError):
        raise HTTPException(409, 'This request changed while saving. Refresh before trying again.') from None
    return wire({'review': view(record), 'message': 'Review saved. No login access was activated and no invitation was sent.'})


def validate(raw):
    errors, values = {}, {}
    if not isinstance(raw, dict):
        return {}, {'form': 'Submit a JSON object'}
    for field in SCHEMA['ClientSubscriptionRequest']['fields']:
        key = field['key']
        if key in ('id', 'createdAt', 'updatedAt', 'status', 'internalNotes'):
            continue
        value = raw.get(key)
        if key == 'corporateSameAsRegistered':
            values[key] = value is True or value == 'true'
            continue
        value = value.strip() if isinstance(value, str) else str(value) if isinstance(value, int) and not isinstance(value, bool) else ''
        if len(value) > (2000 if 'Address' in key else 255):
            errors[key] = 'This field is too long'
        if field['type'] == 'Int':
            if value and (not value.isascii() or not value.isdigit() or len(value) > 10 or int(value) > 2147483647):
                errors[key] = 'Enter a whole number between 0 and 2147483647'
                values[key] = None
            else:
                values[key] = int(value) if value else None
        else:
            values[key] = value or None
    for key, label in (('companyName', 'Company name'), ('primaryContactName', 'Contact name'), ('primaryContactEmail', 'Email address'), ('primaryContactMobile', 'Mobile number')):
        if not values[key]:
            errors[key] = label + ' is required'
    for key in ('primaryContactEmail', 'alternateContactEmail'):
        if values[key] and not EMAIL.fullmatch(values[key]):
            errors[key] = 'Enter a valid email address'
        if values[key]:
            values[key] = values[key].lower()
    for key in ('primaryContactMobile', 'alternateContactMobile'):
        if values[key] and not PHONE.fullmatch(values[key]):
            errors[key] = 'Enter a valid mobile number'
    website = values['companyWebsite']
    if website and not re.fullmatch(r'([a-z][a-z0-9+.-]*://)?[^\s.]+\.[^\s]{2,}', website, re.I):
        errors['companyWebsite'] = 'Enter a valid website URL'
    year = values['yearOfEstablishment']
    if year is not None and not 1800 <= year <= date.today().year:
        errors['yearOfEstablishment'] = f'Enter a year between 1800 and {date.today().year}'
    product, plan = values['productRequired'], values['subscriptionPlan']
    if product not in ('RMS', 'HRMS', 'RMS_HRMS'):
        errors['productRequired'] = 'Select a valid product'
    if plan not in ('QUARTERLY', 'HALF_YEARLY', 'ANNUAL'):
        errors['subscriptionPlan'] = 'Select a valid subscription plan'
    elif plan == 'QUARTERLY' and (values['numberOfEmployees'] or 0) <= 500:
        errors['subscriptionPlan'] = 'Quarterly billing requires more than 500 employees'
    for key, needed in (('rmsUserCount', product in ('RMS', 'RMS_HRMS')), ('hrmsUserCount', product in ('HRMS', 'RMS_HRMS'))):
        if needed and (values[key] or 0) < 1:
            errors[key] = 'At least 1 user is required'
        elif not needed:
            values[key] = None
    if values['expectedGoLiveDate']:
        try:
            day = date.fromisoformat(values['expectedGoLiveDate'])
            if day.isoformat() != values['expectedGoLiveDate'] or day < date.today():
                raise ValueError()
            values['expectedGoLiveDate'] = day
        except ValueError:
            errors['expectedGoLiveDate'] = 'Enter a valid date today or later'
    if values['corporateSameAsRegistered']:
        for key in ('corporateAddress', 'corporateCity', 'corporateState', 'corporateCountry', 'corporatePinCode'):
            values[key] = None
    return values, errors


@router.post('/subscription-requests', status_code=201)
async def subscription(request: Request, background: BackgroundTasks, db=Depends(get_db)):
    try:
        raw = await request.json()
    except ValueError:
        return JSONResponse({'error': 'Expected a JSON body'}, status_code=400)
    values, errors = validate(raw)
    if errors:
        return JSONResponse({'error': 'Please correct the highlighted fields', 'fieldErrors': errors}, status_code=422)
    requests = table(db, 'ClientSubscriptionRequest')
    existing = db.execute(select(requests.c.id).where(
        func.lower(requests.c.companyName) == values['companyName'].lower(),
        func.lower(requests.c.primaryContactEmail) == values['primaryContactEmail'],
    ).limit(1)).first()
    if existing:
        return JSONResponse({'error': 'A registration request for this company and contact has already been submitted. Contact your Hirava administrator for updates.'}, status_code=409)
    record = insert(db, 'ClientSubscriptionRequest', {**values, 'status': 'NEW'})
    db.commit()
    configured = smtp_configured(request.app.state.settings)
    if configured:
        background.add_task(subscription_emails, request.app.state.settings, record)
    return wire({'success': True, 'request': {key: record[key] for key in ('id', 'companyName', 'createdAt')},
                 'emailStatus': 'scheduled' if configured else 'not_configured'})
