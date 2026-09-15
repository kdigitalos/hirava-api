"""Install the imported schema on an empty database, transactionally and once.

Existing databases are rejected unless this exact baseline was already applied.
Historical developer migrations remain reference material, not a reset sequence.
"""
import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import psycopg
from app.core.config import Settings


def main():
    sql = (ROOT / "migrations/imported/imported-schema.sql").read_text(encoding="utf-8")
    if re.search(r"^\s*(DROP|TRUNCATE|DELETE)\s", sql, re.I | re.M):
        raise ValueError("Baseline contains a destructive statement")
    digest = hashlib.sha256(sql.encode()).hexdigest()
    url = Settings().database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(url, connect_timeout=15) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL search_path TO public")
            cursor.execute("SELECT pg_advisory_xact_lock(428719)")
            cursor.execute("SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname = 'public'")
            tables = {row[0] for row in cursor.fetchall()}
            if "hirava_schema_migrations" in tables:
                cursor.execute("SELECT checksum FROM hirava_schema_migrations WHERE name = 'imported-app-baseline'")
                if cursor.fetchone() == (digest,):
                    print("Imported database schema is already current")
                    return
                raise ValueError("Existing migration differs; prepare a new additive migration")
            if tables:
                raise ValueError("Public schema is not empty; existing data requires a migration review")
            cursor.execute(sql)
            cursor.execute("CREATE TABLE hirava_schema_migrations (name text PRIMARY KEY, checksum text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())")
            cursor.execute("INSERT INTO hirava_schema_migrations(name, checksum) VALUES (%s, %s)", ("imported-app-baseline", digest))
            cursor.execute("SELECT count(*) FROM pg_catalog.pg_tables WHERE schemaname = 'public'")
            print("Imported schema applied transactionally; public tables:", cursor.fetchone()[0])


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Database connection exceptions can contain credentials/host details.
        print("Migration failed:", type(error).__name__, getattr(error, "sqlstate", None))
        sys.exit(1)
