# FastAPI on Vercel Pro

The owner selected Vercel Pro for both applications. Separate projects are rooted at `hirava-api` and `hirava-new-webapp`. Existing RDS and S3 remain storage providers. This supersedes the old ECS hosting plan. Backend production deployment is READY at https://hirava-api.vercel.app; health/readiness returned200, including RDS schema reads. Anonymous cron access returned401; recurring cron invocations appeared in runtime logs.

## Backend build and configuration

`vercel.json` uses FastAPI detection (`app/main.py:app`), installs locked AI dependencies, sets an 800-second invocation limit, and schedules maintenance/screening every minute on production. Preview deployments do not run Vercel cron. `.vercelignore` excludes private environment files, local databases, instance directories, uploads, tests and caches. The public RDS CA certificate remains included.

Set backend variables through the authenticated CLI or Vercel project settings, never through committed files:

- `ENVIRONMENT=production`, `AUTH_MODE=auth0`, `EXPOSE_DOCS=false`.
- `DATABASE_URL`: approved PostgreSQL URL with TLS verification and the bundled `certs/rds-global-bundle.pem`; replace the current Windows CA path for Linux. Verify Vercel-to-RDS network reachability without opening the database indiscriminately.
- Preserve the intended `CUSTOMER_ID`, Auth0 domain/audience, immutable platform-admin IDs and approved feature/provider settings. Do not migrate or bootstrap customer data during build.
- Configure S3 region/bucket and scoped credentials for the backend, plus provider secrets only where required.
- `CORS_ORIGINS`: JSON array containing the exact HTTPS frontend origin.
- `CRON_SECRET`: independently generated high-entropy secret. Vercel sends it as a bearer token. Endpoints reject missing/incorrect credentials and are unavailable outside Vercel.
- Vercel supplies `VERCEL=1`. This disables persistent startup workers and voice recovery; local behavior is unchanged.

## Scheduled work

- `/api/internal/cron/maintenance`: at most 50 notification events and five file deletion retries, plus the existing organization-serialized recruitment scan when enabled.
- `/api/internal/cron/screening`: processes one queue item using the existing atomic claim. It respects the screening feature flag. Interrupted paid requests are not automatically resubmitted; existing stale-job recovery applies.

Maintenance commits work through existing transaction/locking paths. Cron invocations can overlap. Screening throughput is one new job per minute per deployment; processing duration and backlog need measurement. Do not point multiple production projects at the same queue unintentionally.

## Known release limitations

- Live WebRTC interviews require the existing persistent transcript observer. Vercel now rejects new live calls with 503 before creating a provider call or changing interview state. This is an explicit temporary limitation, not a completed migration of live voice. A durable observer redesign and acceptance test remain required.
- Uploads/downloads/exports still traverse functions; the existing large-file deployment gate remains. Direct private S3 transfers need implementation and testing for unrestricted file sizes.
- Locked AI dependencies installed successfully in the cloud. The initial 534 MB bundle exceeded the standard limit; deployment passed after setting `VERCEL_SUPPORT_LARGE_FUNCTIONS=1`, using Vercel's large-functions beta.
- Existing shared-company isolation/provisioning work is unfinished and is not solved by deployment.

## Deployment order and acceptance

Authenticate the Vercel CLI, verify the Pro team, link the backend, set private variables, and deploy a preview. Check health/readiness and anonymous authorization denial without running business jobs. Link/configure the frontend with the backend URL and exact Auth0 callbacks, then build/deploy it. Check Auth0 sign-in, protected RMS/HRMS pages and scoped data access. Production promotion activates cron and therefore real queued work; inspect the intended queue and environment first. Do not describe a preview as full production readiness.
