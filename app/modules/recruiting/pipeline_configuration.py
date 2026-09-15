"""Allowlisted RMS form/template tables for this isolated customer database."""
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Query
from pydantic import ConfigDict, Field, JsonValue, create_model
from sqlalchemy import Column, DateTime, Integer, JSON, MetaData, String, Table, select

from app.core.compatibility_routing import APIRouter
from app.data.database import get_db
from app.modules.recruiting.models import JobReference, Requisition
from app.modules.recruiting.pipeline_api import candidate, candidates_query, job, read, write
from app.modules.recruiting.pipeline_interviews import as_dict, parse_ids
from app.modules.recruiting.public_intake import pipeline_table

router = APIRouter(prefix='/api', tags=['RMS form configuration'])
# Explicit allowlist, never table/column names supplied by a request.
SPECS = {
    'hiringFlow': ('rms_hiring_flow', {'value': ('value', 'text', 20000)}, {}),
    'secttionValue': ('rms_section_value', {'value': ('value', 'text', 255), 'object': ('object', 'json', 0)}, {}),
    'template': ('rms_template', {'subject': ('subject', 'text', 20000), 'body': ('body', 'text', 500000)}, {'subject': '', 'body': ''}),
    'question': ('rms_question', {'candidateId': ('candidate_id', 'int', 0), 'question': ('question', 'text', 20000),
                                'questionType': ('question_type', 'text', 100)}, {'questionType': ''}),
    'candidateFormDetails': ('rms_candidate_form_details', {
        'jobOpeningId': ('job_opening_id', 'int', 0), 'dateOfBirth': ('date_of_birth', 'date', 0),
        'firstName': ('first_name', 'text', 100), 'lastName': ('last_name', 'text', 100), 'gender': ('gender', 'text', 50),
        'mobile': ('mobile', 'text', 50), 'email': ('email', 'text', 255), 'noticePeriod': ('notice_period', 'text', 100),
        'currentJobTitle': ('current_job_title', 'text', 255), 'currentCTC': ('current_ctc', 'text', 100),
        'expectedCTC': ('expected_ctc', 'text', 100), 'currentCompany': ('current_company', 'text', 255),
        'currentLocation': ('current_location', 'text', 255), 'linkedInID': ('linkedin_id', 'text', 255),
        'referredBy': ('referred_by', 'text', 255), 'availableTime': ('available_time', 'text', 100),
        'locationPreference': ('location_preference', 'text', 255), 'uploadResume': ('upload_resume', 'text', 500),
        'extraField': ('extra_field', 'json', 0), 'questions': ('questions', 'json', 0)}, {}),
}


def configuration_table(db, kind):
    name, fields, _ = SPECS[kind]
    types = {'text': String, 'json': JSON, 'int': Integer, 'date': DateTime}
    return Table(name, MetaData(), Column('id', Integer, primary_key=True),
        *(Column(column, types[typ], key=key) for key, (column, typ, _) in fields.items()),
        Column('created_at', DateTime, key='createdAt'), Column('updated_at', DateTime, key='updatedAt'),
        schema='public' if db.bind.dialect.name == 'postgresql' else None)


def owned_query(table, kind, user):
    query = select(table)
    if kind == 'candidateFormDetails':
        aliases = select(JobReference.id).join(Requisition).where(Requisition.customer_id == user.customer_id)
        query = query.where(table.c.jobOpeningId.in_(aliases))
    elif kind == 'question':
        # Existing questions inherit ownership from the candidate's canonical job.
        candidates = pipeline_table_for(table)
        ids = candidates_query(candidates, user).with_only_columns(candidates.c.id)
        query = query.where(table.c.candidateId.in_(ids))
    # Global presets/templates have no customer column. The application deliberately
    # uses one isolated imported schema per configured customer (current_user checks it).
    return query


def pipeline_table_for(table):
    return Table('rms_candidate', MetaData(), Column('id', Integer), Column('job_opening_id', Integer), schema=table.schema)


def validate_owner(db, user, kind, values, existing=None):
    for key, value in values.items():
        if isinstance(value, datetime) and value.tzinfo is not None:
            values[key] = value.astimezone(timezone.utc).replace(tzinfo=None)
    key = 'jobOpeningId' if kind == 'candidateFormDetails' else 'candidateId' if kind == 'question' else None
    if key:
        owner = values.get(key, existing[key] if existing else None)
        if owner is None:
            raise HTTPException(422, f'{key} is required')
        if existing and owner != existing[key]:
            raise HTTPException(409, 'Create a separate record instead of moving this record')
        if kind == 'question':
            candidate(db, user, owner, lock=True)
        else:
            job(db, user, owner, lock=True)
    if kind == 'template' and any(values.get(key, '') is None for key in ('subject', 'body')):
        raise HTTPException(422, 'Template subject and body cannot be null')


def register(kind):
    _, columns, defaults = SPECS[kind]
    fields = {}
    for key, (_, typ, length) in columns.items():
        if typ == 'text':
            fields[key] = (str | None, Field(None, max_length=length))
        elif typ == 'int':
            fields[key] = (int | None, Field(None, gt=0))
        else:
            fields[key] = (JsonValue if typ == 'json' else datetime | None, None)
    schema = create_model(f'{kind}Patch', __config__=ConfigDict(extra='forbid'), **fields)

    def listing(id: int | None = Query(None, gt=0), jobOpeningId: int | None = Query(None, gt=0), user=Depends(read), db=Depends(get_db)):
        table = configuration_table(db, kind)
        query = owned_query(table, kind, user)
        if id is not None:
            query = query.where(table.c.id == id)
        if jobOpeningId is not None and kind == 'candidateFormDetails':
            query = query.where(table.c.jobOpeningId == jobOpeningId)
        rows = [as_dict(table, row) for row in db.execute(query.order_by(table.c.createdAt.desc())).mappings()]
        return {'data': (rows[0] if rows else None) if id is not None else rows}

    def create(body, user=Depends(write), db=Depends(get_db)):
        table = configuration_table(db, kind)
        values = {**defaults, **body.model_dump(exclude_unset=True)}
        validate_owner(db, user, kind, values)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        row = db.execute(table.insert().values(**values, createdAt=now, updatedAt=now).returning(table)).mappings().one()
        return {'message': 'Created successfully', 'data': as_dict(table, row)}

    def update(body, id: int = Query(..., gt=0), user=Depends(write), db=Depends(get_db)):
        table = configuration_table(db, kind)
        row = db.execute(owned_query(table, kind, user).where(table.c.id == id).with_for_update()).mappings().first()
        if row is None:
            raise HTTPException(404, 'Record not found')
        values = body.model_dump(exclude_unset=True)
        validate_owner(db, user, kind, values, as_dict(table, row))
        row = db.execute(table.update().where(table.c.id == id).values(**values, updatedAt=datetime.now(timezone.utc).replace(tzinfo=None))
                         .returning(table)).mappings().one()
        return {'message': 'Updated successfully', 'data': as_dict(table, row)}

    def delete(ids: str, user=Depends(write), db=Depends(get_db)):
        table = configuration_table(db, kind)
        found = db.execute(owned_query(table, kind, user).with_only_columns(table.c.id).where(table.c.id.in_(parse_ids(ids)))).scalars().all()
        if not found:
            raise HTTPException(404, 'Record not found')
        db.execute(table.delete().where(table.c.id.in_(found)))
        return {'message': 'Deleted successfully', 'deletedIds': found}

    create.__annotations__['body'] = schema
    update.__annotations__['body'] = schema
    for method, handler in [('GET', listing), ('POST', create), ('PUT', update), ('DELETE', delete)]:
        router.add_api_route('/' + kind, handler, methods=[method], name=f'{kind}_{method.lower()}', status_code=201 if method == 'POST' else 200)


for resource in SPECS:
    register(resource)
