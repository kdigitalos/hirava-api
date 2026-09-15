# Hirava API

FastAPI backend for **Hirava** — a unified Recruitment Management System (RMS) and Human Resource Management System (HRMS), serving Core, RMS and HRMS from a single deployable service.

The frontend is a separate Next.js application (`hirava-webapp`) that consumes this API. There is no other backend service; an earlier Node backend has been removed.

```
┌──────────────────┐        ┌──────────────────┐        ┌──────────────────┐
│  Next.js webapp  │ ─────▶ │    Hirava API    │ ─────▶ │   PostgreSQL     │
│   (port 3000)    │  HTTPS │  FastAPI :8000   │        │  hirava_core +   │
└──────────────────┘        └──────────────────┘        │  public schemas  │
         │                           │                  └──────────────────┘
         │                           ├────────────────▶ ┌──────────────────┐
         └─── Auth0 (OIDC) ──────────┘   RS256 verify   │   S3 (private)   │
                                                        └──────────────────┘
```

---

## Table of contents

- [Architecture](#architecture)
- [Capabilities](#capabilities)
- [Requirements](#requirements)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [Authentication and authorization](#authentication-and-authorization)
- [Database and migrations](#database-and-migrations)
- [File storage](#file-storage)
- [Background work](#background-work)
- [API surface](#api-surface)
- [Testing](#testing)
- [Project layout](#project-layout)
- [Deployment](#deployment)
- [Troubleshooting](#troubleshooting)
- [Status and scope](#status-and-scope)

---

## Architecture

Python 3.11+, FastAPI, SQLAlchemy 2.0 and Alembic. Roughly 425 route handlers are organised into domain modules mounted under a single versioned router at `/api/v1`, plus a compatibility surface at `/api/*` used by screens inherited from the earlier system.

**Two schemas, one database.** Native Hirava tables live in `hirava_core`. Tables inherited from the imported HRMS product live in `public` and retain their original PostgreSQL enum types. Both are reached through one connection whose `search_path` spans `hirava_core,public`. This split is deliberate: it let the native product move forward without rewriting or migrating the imported data model in a single step.

**Customer isolation.** Every native record carries a `customer_id`, and all queries filter on the configured `CUSTOMER_ID`. Imported HRMS tables have no customer column, so **each configured customer requires its own isolated database or schema**. This is the single most important constraint to understand before deploying for more than one tenant.

**Authentication is not authorization.** Auth0 establishes *who* the caller is. Role, assignment, ownership and customer checks in this service determine *what* they may do. An Auth0 role assignment or a job title alone grants nothing.

---

## Capabilities

| Area | Implemented |
| --- | --- |
| Identity | Local password login with expiring JWTs; Auth0 RS256 validation; account provisioning, invitation and deactivation |
| Core | Organization units, positions and headcount, module configuration, policies and acknowledgements, audit trail, documents, notifications |
| RMS | Requisitions with separate-person approval, publication, candidate consent, applications and stage transitions |
| Candidate self-service | Published jobs, registration, profile, own application status and withdrawal, offer view and acceptance |
| Interviews | Assigned interviews, cancellation, structured scorecards restricted to the assigned interviewer |
| Offers | Salary, currency and start date; separate-person approval; acceptance evidence; decline |
| Hire-to-onboard | Allowlisted preview, HR approval, idempotent conversion, duplicate-worker prevention, atomic position reservation |
| Workforce | Direct hires, workers, employment records, account linkage, onboarding tasks, commencement, prehire cancellation |
| Employee self-service | Scoped worker and employment views, HR-reviewed name changes, policy acknowledgement |
| Leave | Types, annual balance grants, weekday calculation, overlap checks, approval and rejection, cancellation with balance restoration |
| HR service | Requester-owned cases, HR assignment and status, restricted HR notes |
| Offboarding | Approved exit, evidence tasks, closure, position release, account deactivation |
| Performance | Goals, completion, human-authored reviews, worker acknowledgement |
| Learning | Course references, scoped assignments, completion evidence |
| Reporting | Separate RMS and HRMS status counts |
| Operations | Alembic migrations, transactional audit and outbox, notification worker, bounded poison-event retries, repair endpoint |

Human approval is required for employment transitions; the API does not automate them.

---

## Requirements

- **Python 3.11+**
- **PostgreSQL 14+** for any real deployment (SQLite is supported only for isolated local experiments and tests)
- **Auth0 tenant** when `AUTH_MODE=auth0`
- **AWS S3 bucket** (private) for uploaded files
- Optional: Docker, for the bundled `Dockerfile` and `compose.yaml`

---

## Quick start

```bash
git clone https://github.com/kdigitalos/hirava-api.git
cd hirava-api

python -m venv .venv
# Windows:        .\.venv\Scripts\python.exe -m pip install -e ".[dev]"
# macOS / Linux:  ./.venv/bin/python -m pip install -e ".[dev]"

cp .env.example .env        # then edit - see Configuration
python scripts/setup_local.py
python -m alembic upgrade head
python -m app.cli create-admin --email admin@example.com
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

For the exact locked dependency set, use `uv sync --locked --extra dev` instead of pip.

### Running both services together

When working alongside the `hirava-webapp` frontend in a sibling directory:

```bash
python scripts/dev.py
```

This starts the API on 8000 and the frontend on 3000, and terminates both on Ctrl+C. It refuses to start if either port is occupied and never stops a process it does not own.

### Endpoints once running

| | |
| --- | --- |
| Swagger UI | http://127.0.0.1:8000/docs |
| ReDoc | http://127.0.0.1:8000/redoc |
| OpenAPI JSON | http://127.0.0.1:8000/openapi.json |
| Liveness | http://127.0.0.1:8000/api/v1/health |
| Readiness (DB + schema) | http://127.0.0.1:8000/api/v1/ready |

In local mode, `POST /api/v1/auth/login` with `{"email": "...", "password": "..."}` returns an `access_token` to paste into Swagger's **Authorize** dialog.

---

## Configuration

Settings load from `.env` via pydantic-settings. **Environment variables take precedence over the file** — an exported `AUTH_MODE` or `DATABASE_URL` silently overrides `.env`, which is a common source of confusing behaviour. See [Troubleshooting](#troubleshooting).

Copy `.env.example` and fill it in. Never commit `.env`; it is git-ignored.

### Core

| Variable | Default | Notes |
| --- | --- | --- |
| `ENVIRONMENT` | `local` | `local`, `test` or `production` |
| `CUSTOMER_ID` | `local-customer` | Tenant key on every native record. Changing it on a populated database orphans existing data |
| `DATABASE_URL` | local SQLite | For PostgreSQL: `postgresql+psycopg://user:password@host:5432/db` |
| `AUTH_MODE` | `local` | `local` (HS256, password login) or `auth0` (RS256 verification) |
| `JWT_SECRET` | — | Required when `AUTH_MODE=local`; minimum 32 characters |
| `TOKEN_MINUTES` | `30` | Local token lifetime, 1–120 |
| `CORS_ORIGINS` | localhost:3000 | Frontend origins |
| `EXPOSE_DOCS` | `true` | Set `false` in production to hide `/docs` |
| `RMS_ENABLED` / `HRMS_ENABLED` | `true` | Module toggles; disabled modules return 403 |
| `MAX_UPLOAD_BYTES` | 10 MB | Hard cap, 1–50 MB |

### Auth0 (`AUTH_MODE=auth0`)

| Variable | Notes |
| --- | --- |
| `AUTH0_DOMAIN` | e.g. `your-tenant.us.auth0.com` |
| `AUTH0_AUDIENCE` | API identifier; must match the audience the frontend requests |
| `AUTH0_WEB_CLIENT_ID` | Web application client ID |
| `AUTH0_MGMT_CLIENT_ID` / `AUTH0_MGMT_CLIENT_SECRET` | Management API credentials, required only for invitations |
| `AUTH0_CONNECTION` | Default `Username-Password-Authentication` |

The API verifies RS256 signatures against the tenant JWKS and **never needs the web application's client secret**.

### Storage and mail

`AWS_REGION`, `AWS_BUCKET_NAME`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN` for S3. Either `SENDGRID_API_KEY` + `SENDGRID_VERIFIED_SENDER`, or `SMTP_*` + `MAIL_FROM`, for outbound mail.

Prefer an instance role or task role over static AWS keys wherever the platform supports it.

---

## Authentication and authorization

Two modes, selected by `AUTH_MODE`:

**`local`** — `POST /api/v1/auth/login` issues an HS256 JWT signed with `JWT_SECRET`, carrying `sub`, `customer_id` and a `ver` token version. Incrementing a user's `token_version` revokes all their sessions. Intended for development and isolated installs.

**`auth0`** — the caller presents an Auth0 access token. The API fetches the tenant JWKS, verifies the RS256 signature, checks audience and issuer, then resolves the token's `sub` to a `users` row via `auth_subject`. The row must be active and belong to the configured `CUSTOMER_ID`, or the request is rejected with 401.

> **The two modes are mutually incompatible at runtime.** A service running in `local` mode rejects every Auth0 token with a 401, and vice versa. If authenticated calls fail uniformly while login itself succeeds, verify the mode the *process* actually loaded.

### Roles

`admin`, `hr`, `recruiter`, `manager`, `interviewer`, `employee`, `candidate` — one role per user. `admin` passes every role check. Beyond roles, handlers enforce assignment, ownership and customer scoping; see [`docs/access-matrix.md`](docs/access-matrix.md).

Some imported RMS routes deliberately deny manager, interviewer and candidate access until scoped workflows exist. Do not resolve that by widening access.

---

## Database and migrations

```bash
python -m alembic upgrade head          # apply
python -m alembic revision -m "..."     # create
python -m alembic downgrade -1          # roll back one
```

Migrations require a `hirava_core,public` search path.

**Fresh installations** additionally need the imported baseline and compatibility views from `migrations/imported`:

```bash
python scripts/migrate_imported.py
python scripts/install_job_views.py
python scripts/verify_job_views.py
```

> **Never run the imported empty baseline against an already-populated database.** It is intended only for new installations.

`GET /api/v1/ready` reports whether the database is reachable and the expected schema is present — use it as a deployment gate, not just `/health`.

---

## File storage

Uploads go to a **private** S3 bucket; there is no persistent local file storage. Objects are served through the API, which applies the same authorization as any other resource — the bucket must never be public.

Deletions are transactional: a delete is committed as an outbox event alongside the record change, and reads honour the deletion immediately even if the S3 object removal has not completed. An in-process loop retries failed object cleanup every 30 seconds (`IMPORTED_STORAGE_CLEANUP_ENABLED`, disabled during tests).

Note that a Next.js frontend deployed to Vercel buffers request bodies, and Vercel's documented 4.5 MB limit applies to uploads routed through it. Large-file upload needs a direct-to-S3 path.

---

## Background work

Domain changes write **audit** and **outbox** rows in the same transaction as the change itself, so an event is never lost when a write succeeds. A notification worker drains the outbox into in-app notifications:

```bash
python -m app.workers.outbox
```

The worker writes in-app notifications only — not email, and not AI processing. Poison events retry a bounded number of times and are then parked for a repair endpoint rather than blocking the queue.

---

## API surface

- `/api/v1/*` — native versioned API, the surface new work should target
- `/api/*` — compatibility routes retained for screens inherited from the imported product

Both are served by this application. Full generated documentation is at `/docs` when `EXPOSE_DOCS=true`; the machine-readable contract is at `/openapi.json`.

Public, unauthenticated routes are limited to the careers surface: published job listings, job detail, and candidate application submission.

---

## Testing

```bash
python -m pytest                        # full suite
python -m pytest tests/test_backend.py  # one module
python -m pytest -k leave               # by keyword
```

Around 40 test modules cover native flows and the imported HRMS surface. Tests run against a disposable database and never touch configured cloud resources; S3 cleanup and mail are disabled under test.

---

## Project layout

```
app/
├── api/v1/          Versioned router assembly
├── core/            Config, security, models, schemas, audit, invitations
├── data/            Registry and imported schema metadata
├── modules/         Domain modules
│   ├── recruiting/      Requisitions, jobs, candidates, applications
│   ├── interviews/      Scheduling and scorecards
│   ├── offers/          Offer lifecycle
│   ├── conversion/      Hire-to-onboard
│   ├── workforce/       Workers and employment records
│   ├── leave/           Types, balances, requests
│   ├── hr_service/      Helpdesk cases
│   ├── performance/     Goals and reviews
│   ├── learning/        Courses and assignments
│   ├── organization/    Units, positions, policies
│   ├── claims/          Expense claims
│   ├── improvement/     Performance improvement plans
│   └── saas_config/     Module and customer configuration
├── workers/         Outbox notification worker
├── integrations/    External service clients
└── workflows/       Multi-step process orchestration

migrations/          Alembic; `imported/` holds inherited schema SQL
scripts/             Setup, migration, verification, dev launcher
tests/               Pytest suite
docs/                Access matrix, Auth0 setup, migration status
```

---

## Deployment

A `Dockerfile` and `compose.yaml` are included. Two things the base image does **not** carry, and which an overlay must add for a TLS-verified RDS deployment:

1. the `scripts/` directory, and
2. the RDS CA bundle referenced by `sslrootcert` in `DATABASE_URL`.

Production checklist:

- `ENVIRONMENT=production`, `AUTH_MODE=auth0`, `EXPOSE_DOCS=false`
- `DATABASE_URL` with `sslmode=verify-full` and a valid `sslrootcert`
- Secrets from a secret manager — never baked into an image or committed
- `CORS_ORIGINS` restricted to real frontend origins
- One isolated database or schema per customer (see [Architecture](#architecture))
- Gate readiness on `/api/v1/ready`, not `/api/v1/health`

---

## Troubleshooting

**Every authenticated request returns 401, but signing in works.**
The running process is almost certainly in the wrong `AUTH_MODE`. Because environment variables override `.env`, a long-lived process can drift from its own configuration file — an `AUTH_MODE` exported in the launching shell wins silently. Restart the service from a clean shell and confirm the mode it loads. A frontend that treats such a 401 as "session expired" can produce an endless sign-in redirect loop whose real cause is entirely server-side.

**401 with a valid Auth0 token.** Check, in order: the token's `aud` matches `AUTH0_AUDIENCE`; its issuer matches `AUTH0_DOMAIN`; a `users` row exists whose `auth_subject` equals the token `sub`; that row is `active`; and its `customer_id` equals `CUSTOMER_ID`.

**`relation "..." does not exist`.** The search path is missing `public` (or `hirava_core`). Both are required.

**Readiness fails but health passes.** `/health` is liveness only. `/ready` checks database connectivity and schema — read its response body.

**Port already in use.** `scripts/dev.py` deliberately refuses to start rather than killing a process it does not own. Stop the occupying process yourself.

---

## Status and scope

This is a working functional baseline, not a finished product. Implemented API coverage is not a claim of complete frontend integration.

Known remaining work: full canonical hiring and employee consolidation, form intake parity, the planned AI capabilities, country and company policy rules, payroll and leave rule completeness, and systematic role-boundary testing. Native interview scheduling does not yet replace the imported interview screens.

Further reading in [`docs/`](docs/): [implementation status](docs/implementation-status.md), [access matrix](docs/access-matrix.md), [Auth0 setup](docs/auth0-team-setup.md), [account invitations](docs/account-invitations.md), [migration notes](docs/split-migration.md), [verification](docs/verification.md).

---

## Security

Do not commit `.env`, credentials, certificates or tokens. Keep the S3 bucket private and the database on a private subnet. Report vulnerabilities privately to the maintainers rather than opening a public issue.
