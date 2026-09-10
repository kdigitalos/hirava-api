# Implementation status and boundaries

The master plan describes a complete product and operating model. This repository implements a local functional backend across the principal domains. It does not certify the entire plan as delivered.

## Implemented behavior

- Persistent SQLAlchemy models with versioned Alembic migrations, per-instance customer filtering, foreign keys, unique constraints, optimistic concurrency, and transactions committed before successful HTTP responses.
- Distinct recruiting and workforce records; conversion copies only name, email, position, and start date. Source-offer linkage stays in conversion records. Salary evidence remains in offers.
- Separate-person requisition/offer approvals, HR conversion authority, required onboarding completion, explicit commencement, and controlled offboarding.
- Role and ownership checks on staff/candidate APIs. Managers see their reporting workers; interviewers see assigned interviews; HR cases/notes and recruiting evidence have separate permissions.
- A single-role local identity model and an Auth0 token-verification adapter with application-owned account provisioning.
- Local document uploads/downloads with opaque storage keys, content hashes, per-domain authorization, attachment downloads, and size limits.
- Transactional audit and in-app notification outbox with durable database receipts and retry/repair states.
- Core HR, leave, HR cases, basic goals/reviews, and basic learning assignment workflows.

## Deliberate limits requiring further implementation

| Area | Current boundary |
| --- | --- |
| Live providers | No Azure Blob, Azure Durable Functions, calendar, email, signature, screening, payroll, or attendance provider writes. References and evidence are recorded locally. |
| Identity operations | Local registration is synthetic-development only and does not verify email ownership. Auth0 signup, verification, MFA, recovery, SSO connection setup, and external account lifecycle need configuration and end-to-end validation. |
| Organization | Basic units, positions, manager reference, and capacity; no full effective-dated organization history or delegated approval policies. |
| Recruiting | A single offer per application, one assigned interviewer per interview, one competency score per scorecard. No offer-version amendments, talent pools, client placements, or job-board adapters. |
| Handoff | Duplicate email matches require human reconciliation. Advanced rehire, multiple employment/assignment records, internal mobility, post-acceptance offer amendments, and compensation mapping are not implemented. |
| Leave | Explicit annual integer-day grants and Monday-Friday working days. No public-holiday calendars, accrual, carryover, half days, statutory rule engine, or retroactive adjustments. Cross-year requests must be split. |
| HR self-service | Reviewed name changes only. Other profile fields and effective-dated employment changes need dedicated schemas and policies. |
| Performance/learning | Basic goals, published narrative reviews, acknowledgements, courses, assignments, and completion evidence. No cycle calibration, ratings engine, certification renewals, or LMS integration. |
| Documents/privacy | Local filesystem adapter only. No malware scanner, retention scheduler, legal-hold enforcement, rights-request/export/deletion orchestration, or backup service. No public file URLs. |
| Security | Basic role/ownership policy. No multi-role delegated scopes, support impersonation workflow, organization-specific field masking, or production security review. Local registration/login require a loopback synthetic environment. |
| SaaS | Module flags per isolated instance. No payment gateway, subscription billing engine, automated provisioning, metering service, or shared control plane. |
| Intelligence/MCP | Disabled/reserved. No model calls, employment decision automation, retrieval index, tracing service, or MCP endpoints. |
| Reliability | Local SQL outbox worker. Provider inbox/contracts, durable cross-service orchestration, backoff scheduling, incident runbooks, recovery objectives, and restore drills need further work. |

## Verification interpretation

Automated local tests exercise real HTTP request handling and persistent SQLite transactions, not mocked business endpoints. Auth0 verification is tested with generated RSA keys and a substituted key resolver, without contacting a real tenant. Concurrency tests confirm a single conversion result under local retries; PostgreSQL runtime behavior still requires validation in a working PostgreSQL environment.

Docker could not run because its daemon was unavailable. The installed PostgreSQL initializer lacked its required share files. Neither result establishes a PostgreSQL/Docker application failure or a successful deployment.

Test artifacts and database files are ignored by source control. No production deployment, live integration, or personal-data import was performed.
