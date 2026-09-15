# FastAPI consolidation - 2026-09-14

The retained backend endpoints now run in Python. Normal startup uses Next.js on
3000 and FastAPI on 8000. `LEGACY_API_URL` is empty in the configured API environment;
`scripts/dev.py` starts only these two services and rejects occupied ports.

## Coverage

The source inventory covers all 182 retained route files with 319 explicit Python
handlers on 182 paths; no inventoried methods remain on the Node fallback. Counts
include intentional conflict guards and configuration-only features, not a claim
that every product requirement is implemented.

Converted families include RMS jobs/candidates/interviews/forms/analytics/email,
private files, employees/profiles/documents, assets, attendance/leave/reports,
onboarding/probation/tasks, exits/clearance/settlements, performance, helpdesk,
organization/setup/hierarchy/manager imports, accounts/invitations, parties,
subscription intake, named page views, search and health.

Native and imported records remain in their existing schemas. This migrates backend
execution, not every duplicate domain model into a single model. Canonical job
views stay read-only. Imported public tables require an isolated customer database;
they cannot be shared by multiple customers. No existing accounts, candidates,
employees or S3 objects were moved or deleted.

## Verification

- Full Python suite: 103 passed. Two dependency deprecations and a Windows pytest
  cache warning; no test failures.
- Frontend production build, TypeScript and static generation passed. Existing
  Auth0 dependency-expression warnings remain. Initial sandbox worker spawn was
  denied; rerun with approved process permissions passed.
- Read-only configured-RDS checks passed across RMS/HRMS collections, organization,
  helpdesk, named views and six employee profile sections with fallback and cleanup
  disabled. One candidate and zero interviews remain. These use an in-process
  existing-admin dependency override, not an Auth0 browser session.
- Additive migration 0d761da3b892 applied to configured RDS after confirming the
  previous head b72d5306ef01. Creates only missing helpdesk settings storage; verified
  new revision/table. Upgrade/check/downgrade/upgrade rehearsed in isolated tests.
- Running HTTP checks: FastAPI health/readiness 200; frontend careers shell 200;
  staff screens redirect to sign-in; anonymous candidate reads 401; Auth0 login
  redirects. Node backend port 8001 is closed.
- Job 6 is currently CLOSED in the database. Public detail and submission correctly
  return 404; its status was not changed. Published intake is covered by synthetic
  tests, not a fresh live submission in this migration.
- Synthetic 90-agent helpdesk PDF has six pages. First/last pages visually checked;
  last agent retained. Previous 17-page attendance PDF also visually checked.
- ReportLab/Openpyxl dependencies are declared and uv.lock updated.

## Local operating notes

Run `.\.venv\Scripts\python.exe scripts\dev.py` from hirava-api. For separate
terminals, run uvicorn from hirava-api and npm run dev from hirava-webapp.
Keep LEGACY_API_URL empty and use APP_BASE_URL=http://localhost:3000 for local staff
sign-in. The launcher supplies both overrides. No third backend terminal is needed.

At verification time a separate KLMS Next.js process (PID 32672) occupied wildcard
port 3000 and returned another app at localhost. It was not stopped. Hirava's own
loopback listener at 127.0.0.1:3000 worked. Stop the KLMS server before using Hirava
at localhost; do not treat its 404 page as a Hirava migration failure.

No connected browser was available, so interactive authenticated visual acceptance
and fresh staff login remain unverified. Concurrent PostgreSQL writes, production
rollout and another-device Wi-Fi access are not claimed by these checks.

## Preserved limits and pending product work

- Native application roles enforce access. Saved permission matrices are reference
  configuration; the UI now states they do not grant permissions.
- AI assessment/agents remain separate feature work. Missing scores stay Not assessed.
- Compensation/settlement records do not prove payment or generate a payroll run.
- Onboarding autoConvert, probation reminders/auto-confirm and helpdesk automation
  flags remain configuration; this migration does not invent automation.
- Interview and subscription email adapters need configured providers. No provider
  credentials were present in either current API or legacy mail configuration;
  no real emails were sent. Provider acceptance is not inbox-delivery proof.
- File cleanup is a durable outbox operation retried inside FastAPI. The diagnostic
  server was started with cleanup disabled to avoid mutating files during checks;
  ordinary startup uses IMPORTED_STORAGE_CLEANUP_ENABLED=true from configuration.
- Employee/assignment history deletion and unsafe lifecycle shortcuts are guarded.

Cleanup update: the user authorized removal of the obsolete folders. The mixed
checkout and legacy-service were removed after preserving the schema baseline in
`migrations/imported` and hash-verifying the local upload in
`storage/imported-uploads`. Runtime storage no longer reads the retired folder;
the gateway implementation is removed and non-empty LEGACY_API_URL is rejected.
Frontend generated model types are retained because existing UI code uses them.
No Git push or external deployment was performed.

Post-cleanup verification: 99 backend tests passed after retiring four Node-gateway-only tests; frontend typecheck passed. Existing API health and frontend careers shell returned 200. No process restart or live data mutation during cleanup.

S3-only update (2026-09-14): persistent local upload storage is removed. The older file has an exact verified copy in S3; redundant local folder removed. STORAGE_PATH and the Docker document volume are removed; native and imported file endpoints require configured S3, with no local fallback. Request parsing may still use framework-managed temporary buffering. 101 backend tests passed. Restart FastAPI to load these changes.
