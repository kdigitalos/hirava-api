# HRMS/RMS separation

> Historical split notes. Superseded for startup and backend execution by the
> [2026-09-14 FastAPI migration](consolidation/fastapi-migration.md).
> All 182 retained route paths now have explicit Python handlers. Normal startup
> runs frontend 3000 and FastAPI 8000, with `LEGACY_API_URL` empty. The third
> service described below is retained source only. Auth0 is configured on this
> machine; older local-auth and schema revision statements below are historical.

The subsequent [consolidation checklist](consolidation/README.md) maps both implementations and the selected AI requirements to one intended FastAPI backend. The separate data models described here remain transitional.

Update: [job management now shares native records](consolidation/job-cutover.md). The old job names in `public` are compatibility views; candidate/interview and other business-domain consolidation is still pending.

## Result

The source is `konadigitalai/hirava-mixed`, branch `dev`, commit `a6c97ee`. The original checkout in `Hirava/hirava mixed` is unchanged.

```text
Hirava/
  hirava mixed/             Original developer checkout
  hirava-webapp/            Next.js frontend and browser-session bridge
  hirava-api/
    app/                   Native FastAPI application and public gateway
    legacy-service/        Imported API-only TypeScript/Prisma business service
    migrations/            Native FastAPI database migrations
    certs/                 Public RDS certificate authority bundle
```

All 118 original pages were preserved. All 181 original API route files were preserved in the backend, with a new named page-data endpoint. Database queries embedded in frontend pages were extracted into named loaders. Six API response contract modules were separated from route implementations. The frontend retains browser-safe generated model contracts and enums, without exporting a Prisma database client.

This preserves existing TypeScript business logic behind FastAPI; it is **not a full Python rewrite**. The public API remains FastAPI. The two backend processes must run together.

## Requests and identity

```text
Browser :3000
  -> Next.js session/HTTP bridge
    -> FastAPI :8000
      -> native /api/v1 endpoints
      -> signed, short-lived identity -> private service :8001
        -> RDS public schema / S3
```

FastAPI authenticates the existing local JWT or Auth0 access token, looks up an active, provisioned account, checks module/role access, and signs the internal identity for the exact method/path. The internal listener binds to loopback and rejects missing, expired, or forged assertions. Browser identity headers, cookies, and access tokens are not forwarded to the private service.

The local frontend keeps the access token in an HttpOnly cookie. Mutations require the configured frontend origin. Auth0's browser application must request `AUTH0_AUDIENCE`, matching FastAPI's audience. Auth0 settings are currently empty, so the installed configuration uses local login. No permanent administrator or default password was created by the migration.

Employee records must be explicitly linked by HR; signing in no longer creates employment or claims an employee record solely by email.

## Database and files

- The supplied RDS credentials were used with TLS certificate and hostname verification.
- Native FastAPI tables are in `hirava_core`, at Alembic revision `99a3ef1c2db4`.
- The imported app uses `public`: 69 application tables and `hirava_schema_migrations`.
- `scripts/migrate_imported.py` installs the imported baseline transactionally only into an empty schema; it checks the baseline checksum on subsequent runs.
- The old developer migrations remain historical reference. Do not replay/reset them against this database.
- The supplied private S3 bucket is used for imported uploads and native FastAPI documents. Both write/read paths were tested using synthetic content.
- Database/AWS credentials exist only in ignored backend `.env` files. The frontend `.env.local` contains service URLs.

The native and imported applications currently retain **separate business data models**. A record created through native `/api/v1` workflows does not automatically become a Prisma record. Do not operate two parallel hiring pipelines for the same hire. The preserved UI uses the imported API contracts; the native workflows remain available through `/api/v1`.

## Fixes included

- Removed email-prefix role escalation and implicit email-based account relinking from imported session handling.
- Added the authenticated FastAPI/private-service boundary, role/module checks, bounded forwarding, and frontend origin validation.
- Persisted organization role definitions in PostgreSQL instead of process memory. Definitions do not themselves grant FastAPI access.
- Routed profile POST/PUT edits through the existing approval workflow and removed the direct deletion bypass.
- Prevented employee-created leave from starting in an approved state and scoped pending leave counts.
- Removed managers' blanket HR administrator treatment in imported HRMS handlers.
- Connected document downloads to S3 and scoped private document/object access.
- Removed demo profile values from the imported employee profile loader's fallback.
- Added local sign-in, logout, and a frontend error boundary.

## Start locally

Dependencies are installed on this machine. From `hirava-api`:

```powershell
.\.venv\Scripts\python.exe -m app.cli create-admin --email YOUR_EMAIL --name "Administrator"
.\.venv\Scripts\python.exe scripts\dev.py
```

The first command prompts for a password. Run it once with your actual administrator email. The second starts the frontend, FastAPI, and the private service. Open http://localhost:3000; API documentation is at http://127.0.0.1:8000/docs. Stop existing listeners on ports 3000, 8000, and 8001 before launching a second copy.

For a fresh checkout: run `uv sync --extra dev` in the API, `npm ci` in `legacy-service` and `hirava-webapp`, and `npm run db:generate` in `legacy-service`. Supply the ignored environment files from their examples. RDS was already migrated during this session; do not reset it.

The original `compose.yaml` is for the native local PostgreSQL development stack, not the complete imported application. The three services were verified with separate launches; the final combined-launcher restart was interrupted and has not been verified end to end.

## Verification

- Native suite: 39 tests pass, including new role-boundary and identity-forwarding tests.
- Private identity assertion test passes, including wrong method/path, invalid audience/role, expiry, and tampering.
- Both Next.js projects compile and build; final build status is recorded in the migration handoff.
- Browser: local sign-in, system chooser, HRMS dashboard, and RMS job list rendered; no browser runtime errors were reported.
- Live frontend -> FastAPI -> imported service -> RDS: account resolution, HRMS dashboard, RMS listings, role definitions, and employee dashboard returned 200.
- A synthetic RMS job was created through the frontend, independently read from RDS, and displayed in the RMS job list.
- Imported and native uploads returned the original bytes after an S3 round trip.
- Anonymous/forged requests returned 401. Tested employee administration/RMS access, leave-balance edits, and foreign-origin mutations returned 403.
- Synthetic accounts, jobs, documents, and objects are removed after verification; no permanent test login is provided.

## Remaining product boundaries

This migration does not certify all 118 screens or every master-plan workflow end to end. The preserved app contains prototype UI and integrations that need separate acceptance testing. Auth0 and outbound email are not configured or exercised. No emails were sent by verification.

Assigned manager/interviewer/candidate workflows exist in the native FastAPI API. Equivalent assignment checks are not implemented throughout the imported RMS routes, so those roles are denied broad imported RMS collections instead of receiving all records. HR has imported RMS read access; native approvals/hiring handoff remain in `/api/v1`. A single canonical hiring workflow and frontend integration for these roles is still required before claiming complete role-by-role feature parity.

See `implementation-status.md` for the original native backend's master-plan limitations. Deployment, full Python conversion, and complete role parity are not claimed by the local split verification.
