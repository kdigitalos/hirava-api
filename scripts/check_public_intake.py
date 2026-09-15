"""Explicit live smoke check; deletes only its randomly identified synthetic intake and S3 object."""
import sys
from pathlib import Path
from uuid import uuid4
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from sqlalchemy import select
from app.core.config import Settings
from app.core import object_storage
from app.data.database import build_engine, session_factory
from app.modules.recruiting.public_intake import pipeline_table

settings = Settings()
engine = build_engine(settings.database_url)
sessions = session_factory(engine)
email = f"intake-smoke-{uuid4().hex}@example.com"
content = b"%PDF-1.4\nSynthetic integration check only\n%%EOF"
keys = []
origin = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
try:
    data = {"name": "Synthetic Intake Check", "email": email, "phone": "+91 9000000000", "consent": "on"}
    for attempt in range(2):
        response = httpx.post(origin + "/api/v1/careers/jobs/6/apply", data=data,
            headers={"Origin": origin}, files={"resume": ("synthetic.pdf", content, "application/pdf")}, timeout=90)
        print(f"Guest submission {attempt + 1}: HTTP {response.status_code}")
        assert response.status_code == 200, "Submission failed; inspect sanitized API log"
    with sessions() as db:
        table = pipeline_table(db)
        records = [r for r in db.execute(select(table)).mappings() if isinstance(r['object'], list)
            and any(isinstance(f, dict) and f.get('name') == 'email' and f.get('value') == email for f in r['object'])]
        assert len(records) == 1, "Expected exactly one existing-pipeline candidate"
        profile = {f['name']: f['value'] for f in records[0]['object']}
        receipt = profile['resume'].rsplit('/', 1)[-1]
        keys.append(f"resumes/{receipt}.pdf")
        stream = object_storage.download(settings, keys[0])
        assert stream.read() == content
        stream.close()
        print("RDS pipeline record and exact private S3 resume bytes verified; duplicate retry preserved one record.")
finally:
    with sessions.begin() as db:
        table = pipeline_table(db)
        for row in db.execute(select(table)).mappings():
            profile = row['object']
            if isinstance(profile, list) and any(isinstance(f, dict) and f.get('name') == 'email' and f.get('value') == email for f in profile):
                for f in profile:
                    if f.get('name') == 'resume':
                        keys.append(f"resumes/{f['value'].rsplit('/', 1)[-1]}.pdf")
                db.execute(table.delete().where(table.c.id == row['id']))
    for key in set(keys):
        object_storage.s3_client(settings).delete_object(Bucket=settings.aws_bucket_name, Key=object_storage.object_key(settings, key))
    engine.dispose()
    print("Synthetic intake records and resume objects cleaned up.")
