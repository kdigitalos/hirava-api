"""Build a scalar-only schema map from the retained Prisma source (no DB writes).

Used to address existing tables during migration. This does not generate routes,
grant permissions, create tables, or replace individual workflow validation.
"""
import json
import re
from pathlib import Path

root = Path(__file__).resolve().parents[1]
source = (root / 'migrations/imported/schema.prisma').read_text(encoding='utf-8')
enums = set(re.findall(r'^enum (\w+)', source, re.M))
enum_specs = {}
for name, body in re.findall(r'^enum (\w+)\s*\{(.*?)^\}', source, re.M | re.S):
    mapped = re.search(r'@@map\("([^"]+)"\)', body)
    values = re.findall(r'^\s*(\w+)\s*(?://[^\n]*)?$', body, re.M)
    enum_specs[name] = {'name': mapped[1] if mapped else name, 'values': values}
models = {}
for name, body in re.findall(r'^model (\w+)\s*\{(.*?)^\}', source, re.M | re.S):
    mapped = re.search(r'@@map\("([^"]+)"\)', body)
    fields = []
    for line in body.splitlines():
        match = re.match(r'\s*(\w+)\s+(\w+)(\?|\[\])?\s*(.*)', line)
        if not match:
            continue
        key, typ, modifier, options = match.groups()
        if typ not in enums | {'String', 'Int', 'BigInt', 'Float', 'Decimal', 'Boolean', 'DateTime', 'Json', 'Bytes'}:
            continue
        column = re.search(r'@map\("([^"]+)"\)', options)
        length = re.search(r'@db.VarChar\((\d+)\)', options)
        decimal = re.search(r'@db.Decimal\((\d+),\s*(\d+)\)', options)
        fields.append({'key': key, 'column': column[1] if column else key, 'type': 'String' if typ in enums else typ,
                       'enum': enum_specs.get(typ),
                       'nullable': modifier == '?', 'array': modifier == '[]', 'primary': '@id' in options,
                       'unique': '@unique' in options, 'date_only': '@db.Date' in options and '@db.DateTime' not in options,
                       'length': int(length[1]) if length else None,
                       'decimal': [int(decimal[1]), int(decimal[2])] if decimal else None,
                       'generated_id': '@default(cuid())' in options or '@default(uuid())' in options,
                       'auto_increment': '@default(autoincrement())' in options})
    models[name] = {'table': mapped[1] if mapped else name, 'fields': fields}
target = root / 'app/data/imported_schema.json'
target.write_text(json.dumps(models, indent=2) + '\n', encoding='utf-8')
print(f'Extracted scalar metadata for {len(models)} tables; no database access.')
