# Verification record

Verified locally on 9 September 2026 after installing the dependencies in `uv.lock` into the isolated `.venv`.

| Check | Result |
| --- | --- |
| Automated suite | 37 passed; two upstream Starlette/AnyIO deprecation warnings |
| Alembic upgrade and schema comparison | Passed; no pending schema changes |
| Migration downgrade/re-upgrade | Passed on a dedicated synthetic SQLite database |
| PostgreSQL offline migration SQL | Compiled successfully; does not verify a running PostgreSQL server |
| Docker Compose configuration | Validated with `docker compose config --quiet` |
| Local notification worker | Batch command ran successfully |
| Real Uvicorn HTTP startup | Readiness and OpenAPI passed over loopback; verification process stopped afterward |
| API surface | 102 operations, 30 database tables |

The tests include candidate ownership, staff roles, customer isolation, module flags, separate-person approvals, idempotent/concurrent conversion, exhausted-headcount rollback, stale-write rejection, onboarding, leave balances, restricted notes/documents, employee profile changes, performance/learning, offboarding, outbox retries, Auth0 signature/audience checks, and migrations.

Auth0 tests use locally generated RSA keys and a substituted JWKS resolver. No live Auth0 tenant was contacted. Docker runtime validation was unavailable because the daemon was stopped. PostgreSQL runtime validation was unavailable because the installed initializer lacked its share files.

Local `.env` secrets were generated, never printed, and are ignored by Git and Docker. The local database contains the migrated schema and no seeded administrator or business records. Create your administrator using the password-prompting command in the README.
