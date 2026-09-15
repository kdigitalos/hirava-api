"""Public prospect intake. Internal review status is never supplied by visitors."""
from datetime import date
import re
from fastapi import BackgroundTasks, Depends, Request
from fastapi.responses import JSONResponse
from app.core.compatibility_routing import APIRouter
from app.core.imported_mail import smtp_configured, subscription_emails
from app.data.database import get_db
from app.data.imported import SCHEMA
from app.modules.workforce.imported_assets import insert, wire

router = APIRouter(prefix='/api', tags=['Public subscription intake'])
EMAIL = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]{2,}$')
PHONE = re.compile(r'^[+()\d][\d\s()+-]{6,19}$')


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
    record = insert(db, 'ClientSubscriptionRequest', {**values, 'status': 'NEW'})
    db.commit()
    configured = smtp_configured(request.app.state.settings)
    if configured:
        background.add_task(subscription_emails, request.app.state.settings, record)
    return wire({'success': True, 'request': {key: record[key] for key in ('id', 'companyName', 'createdAt')},
                 'emailStatus': 'scheduled' if configured else 'not_configured'})
