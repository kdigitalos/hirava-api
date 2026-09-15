# Shared job screen cutover

12 September 2026. Supersedes the pending job-screen switch in [job-foundation.md](job-foundation.md).

## Result

RMS job management and HRMS Recruitment → Manage Jobs render the same `src/features/jobs/JobWorkspace.tsx` component in `hirava-webapp`. The component creates, reads and edits **one** `hirava_core.requisitions` record through `/api/v1/rms/requisitions`. Submit, separate-person approval, publication and closure use the existing native commands. The HRMS Applications/Referrals tabs and employee job board retain their existing interfaces.

The common editor includes position selection, job/company/department/location, job type, work mode, recruiter assignment, hiring dates, budget/salary/currency, openings, skills, description, hiring flow, logo and custom field definitions. It replaces the previous job creation wizard and direct active/inactive/delete controls. Custom definitions are retained as JSON configuration; the previous multi-step visual form-builder experience has not been recreated in the common editor. Draft edits require the current version. Closed jobs retain their history and references; the UI no longer deletes applications as a side effect of deleting a vacancy.

RMS `/job-openings/[id]` resolves its numeric ID through `/api/v1/rms/job-aliases/{id}`. The existing detail/statistics screen remains at `/RMS/job-openings/[id]/pipeline`; its Edit action returns to the canonical editor. Candidate/interview records remain in the imported domain for now, with their existing numeric job references intact. This does not claim those domains have been rewritten in Python or that candidate-to-employee integration is complete.

## Database objects

| Object | Purpose |
|---|---|
| `hirava_core.requisitions` | Sole authoritative job content and lifecycle |
| `hirava_core.job_references` | One numeric alias per requisition; no copied job content |
| `public.rms_job_openings` | Read-only view in the legacy RMS shape, derived from requisitions and aliases |
| `public.job_openings` | Read-only employee-board view; canonical requisition UUID is its ID |
| `public.rms_job_openings_pre_unification` | Retained original empty RMS table |
| `public.job_openings_pre_unification` | Retained original empty employee-board table |

These views store no second job records. Candidate IDs in the RMS view are derived from candidate rows rather than appended to a second job array. Job monetary values remain exact decimal strings in native JSON; compatibility views expose floating-point numbers expected by the old frontend, so financial calculations should use native values. Legacy updated timestamps derive from requisition audit events. Displayed job codes preserve the entire numeric alias above 999.

Employee application/referral foreign keys now reference canonical requisition IDs. RMS candidate/form/interview/schedule/feedback job references now reference the numeric alias table. Deletion is restricted rather than cascading across hiring history. Views are scoped to the configured customer in the isolated RDS database. This is not a pooled multi-customer deployment design.

The authenticated gateway refuses old job mutation paths with 409, directing callers to canonical commands. Their underlying joined views are non-updatable as a second protection. Existing imported read endpoints and Prisma joins continue to resolve the views. RMS dashboard paths are classified under the RMS module so recruiters do not require HRMS access.

## Installation and recovery

1. Run native Alembic migrations through `e4b82170ac19`.
2. Run `python scripts/verify_job_views.py` to rehearse SQL views and references in a transaction that is always rolled back.
3. Run `python scripts/install_job_views.py` to apply the view cutover. The script takes an advisory lock and locks all affected source tables, refuses existing recruiting data, rewires known foreign keys, renames the original empty tables and creates the views in one transaction. Unknown dependencies or nonempty source tables cause failure rather than guessed migration.
4. Generate the private Prisma client (`npm run db:generate`) and build both Next applications. The current Prisma job models describe compatibility views, including floating-point presentation amounts. Do not use `prisma db push` or historical imported migrations to recreate those views as independent writable tables.
5. Run FastAPI plus the private service and frontend, using the same configured RDS customer.

This installation was applied on the configured RDS database after a successful rollback rehearsal. Re-running the installer detects installed views. It does not perform schema drift repair or backfill an existing production dataset. No matching of real candidates, jobs or identities was attempted.

After cutover, a native migration downgrade must not drop referenced tables. To roll back application behavior after new writes, first prepare an explicit export/reconciliation migration for those writes and links. Renaming the empty archived tables back would lose access to newly created canonical jobs and is not a valid rollback.

## Verification

- Both Next production builds passed (frontend has an existing Auth0 dynamic-dependency warning).
- 47 native tests passed, including alias resolution, job persistence/versioning, scope, public-field exclusion, legacy-write rejection and RMS dashboard classification.
- PostgreSQL rehearsal verified both view shapes, decimal display values, derived candidate IDs, interview joins, orphan rejection and rejection of direct view updates; all rehearsal rows and DDL were rolled back.
- Live frontend proxy → FastAPI → RDS: create, read, edit, submit, separate HR approval and publish passed. Both imported job read shapes returned the same canonical job. The employee list excluded drafts and included the published job.
- Imported candidate and interview creation succeeded against the canonical alias; candidate IDs and interview read endpoints resolved correctly. Recruiter dashboard returned 200 after the gateway classification fix.
- Browser login, creating a draft, viewing it on both RMS and HRMS screens, and loading the preserved pipeline/statistics page passed. Browser errors output was empty.
- Synthetic test records/identities are removed after validation; no permanent test account, email delivery or deployment is included.

## Remaining work

Unify candidate/application, interview and referral business models; complete role-specific imported UI access; integrate offers and HR conversion; port remaining HRMS features and implement the selected AI agents. Recreating the previous visual custom form-builder experience is a UI parity item; its data definitions are preserved by the common editor. This cutover completes shared job persistence, not the full product consolidation.
