"""Explicit model-name lookup for the existing isolated customer schema.

No runtime dependency on Prisma or Node. Callers must enforce roles and ownership.
These tables intentionally do not enter Base.metadata or native migrations.
"""
import json
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import ARRAY, BigInteger, Boolean, Column, Date, DateTime, Float, Integer, JSON, LargeBinary, MetaData, Numeric, String, Table, select
from sqlalchemy.dialects.postgresql import ENUM

SCHEMA = json.loads(Path(__file__).with_name('imported_schema.json').read_text(encoding='utf-8'))


@lru_cache(maxsize=256)
def _table(model, postgres):
    spec = SCHEMA[model]
    columns = []
    types = {'String': String, 'Int': Integer, 'BigInt': BigInteger, 'Float': Float, 'Boolean': Boolean,
             'DateTime': DateTime, 'Json': JSON, 'Bytes': LargeBinary, 'Decimal': Numeric}
    for field in spec['fields']:
        typ = types[field['type']]
        if postgres and field.get('enum'):
            spec_enum = field['enum']
            typ = ENUM(*spec_enum['values'], name=spec_enum['name'], schema='public', create_type=False)
        elif field['type'] == 'String' and field['length']:
            typ = String(field['length'])
        elif field['type'] == 'Decimal' and field['decimal']:
            typ = Numeric(*field['decimal'])
        elif field['type'] == 'DateTime' and field['date_only']:
            typ = Date
        if field['array']:
            typ = ARRAY(typ) if postgres else JSON
        options = {'primary_key': field['primary'], 'nullable': field['nullable'], 'unique': field['unique']}
        if field['generated_id']:
            options['default'] = lambda: uuid4().hex
        columns.append(Column(field['column'], typ, key=field['key'], **options))
    return Table(spec['table'], MetaData(), *columns, schema='public' if postgres else None)


def table(db, model):
    return _table(model, db.bind.dialect.name == 'postgresql')


def dto(tbl, row):
    return {column.key: row[column] for column in tbl.c}


def find(db, model, record_id, lock=False, required=True):
    tbl = table(db, model)
    query = select(tbl).where(tbl.c.id == record_id)
    if lock:
        query = query.with_for_update()
    row = db.execute(query).mappings().first()
    if row is None:
        if required:
            raise HTTPException(404, 'Record not found')
        return None
    return dto(tbl, row)
