# Vercel development deployment

Project: `hirava-api-dev`, team: `kd-igital-os`, region: Singapore (`sin1`).
Use preview deployments. This project is a development instance with its own
Neon Free database (`hirava-dev-db`) and customer ID `hirava-dev`.

## Configuration

- `HIRAVA_DATABASE_URL`: server-only SQLAlchemy URL using `postgresql+psycopg://`.
  Overrides the raw `DATABASE_URL` injected by the Neon integration. Use the
  dedicated database's direct connection URL with TLS and URL-encoded
  `options=-csearch_path=hirava_core,public`.
- `ENVIRONMENT=local`, `AUTH_MODE=local`: native development login.
- `JWT_SECRET`: generated random secret stored in Vercel, never in Git.
- `CUSTOMER_ID=hirava-dev`, `EXPOSE_DOCS=false`, `CORS_ORIGINS=[]`.
- `IMPORTED_STORAGE_CLEANUP_ENABLED=false`: long-running cleanup is not hosted
  as a background loop in Vercel functions.
- `MAX_UPLOAD_BYTES=4000000`: leave space below the platform request limit.

Vercel Deployment Protection remains enabled. The frontend needs an API project
automation bypass secret in its server-only `HIRAVA_API_PROTECTION_BYPASS`.
This bypasses the hosting gate; application authentication is still required.

## Initialize a new isolated database

Never run this bootstrap against a database containing customer data.
Create `hirava_core` and set the database user's default search path to
`hirava_core, public`. With the configuration above loaded in the shell:

```sh
python scripts/migrate_imported.py
python -m alembic upgrade head
python scripts/install_job_views.py
python -m app.cli create-admin --email YOUR_DEV_ADMIN_EMAIL
```

The imported schema installer refuses an existing unrelated schema. The view
installer refuses nonempty imported job stores. Do not bypass these checks.

## Deploy and verify

```sh
vercel link --project hirava-api-dev --scope kd-igital-os
vercel deploy --target preview --scope kd-igital-os
```

Check the resulting deployment target. Vercel can assign a new project's first
deployment to its production slot; subsequent deployments use preview.
Use a protected request to verify `/api/v1/health`, `/api/v1/ready`, login, and
authenticated `/api/users/me`, `/api/jobOpenings`, and `/api/employees`.
After redeploying, update the frontend API URL or repoint the development alias.

## Current limits

This is an empty development database with a synthetic administrator. S3 and
mail services are unconfigured, so uploads and outgoing mail are not ready.
The persistent outbox worker is not running; cleanup retries are disabled.
Configure isolated provider resources and a supported worker/scheduler before
testing those flows. Known application defects in the review remain, except
for deployment-specific changes. Do not use real employee or candidate data.
