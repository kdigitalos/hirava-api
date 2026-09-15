"""Update migration coverage by matching explicit Python compatibility handlers.

The original route inventory is a source scan, not proof of behavior parity.
Tests and live checks are recorded separately in docs/consolidation/fastapi-migration.md.
"""
import json
import re
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
inventory_path = root / 'docs/consolidation/fastapi-migration-inventory.json'
inventory = json.loads(inventory_path.read_text(encoding='utf-8'))
implemented = {}
def normalized(path):
    path = re.sub(r'\[\.{3}([^\]]+)\]', r'{\1}', path)
    path = re.sub(r'\[([^\]]+)\]', r'{\1}', path)
    return re.sub(r'\{[^}]+\}', '{}', path)
sys.path.insert(0, str(root))
from app.core.config import Settings
from app.main import create_app
app = create_app(Settings(_env_file=None, environment='test', database_url='sqlite://',
                          customer_id='inventory', jwt_secret='inventory-only-' * 5, legacy_api_url=''))
for path, methods in app.openapi()['paths'].items():
    if path.startswith('/api/') and not path.startswith('/api/v1/'):
        # Next.js [...path] and Python {path:path} describe the same catch-all.
        path = normalized(path)
        implemented.setdefault(path, set()).update(method.upper() for method in methods if method.upper() in {'GET', 'POST', 'PUT', 'PATCH', 'DELETE'})
for row in inventory:
    row['methods'] = sorted(set(row['methods']))
    row['fastapi_methods'] = sorted(implemented.get(normalized(row['path']), set()))
    row['remaining_methods'] = sorted(set(row['methods']) - set(row['fastapi_methods']))
inventory_path.write_text(json.dumps(inventory, indent=2) + '\n', encoding='utf-8')
print(f'Inventoried route files: {len(inventory)}')
print(f'Explicit FastAPI compatibility handlers: {sum(map(len, implemented.values()))}')
print(f'Paths with FastAPI handlers: {len(implemented)}')
