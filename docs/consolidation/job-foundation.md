# Canonical job foundation — 12 September 2026

The existing FastAPI requisition now stores validated `job_details`. This adds richer job data without creating another vacancy table. This is the backend foundation portion of delivery step 2; the imported screens and their candidate/interview relationships have **not** switched to it.

## Delivered

- Existing `POST /api/v1/rms/requisitions` accepts `job_details` while retaining the existing position/title/description contract.
- `GET /api/v1/rms/requisitions/{id}` exposes a scoped staff detail view.
- `PATCH /api/v1/rms/requisitions/{id}` edits drafts with `expected_version`; stale edits fail with 409. Submission locks terms against this edit endpoint. Status, approver, requester and position cannot be injected through the patch body.
- The list accepts `search` (literal title/description substring) and `status`, with existing pagination and manager scope.
- Money uses validated decimal amounts and explicit currency; openings cannot exceed the position's configured capacity. The eventual hiring conversion still checks available capacity atomically.
- Assigned recruiter references must resolve to an active recruiter/admin in the same customer.
- Private budgets, recruiter assignment and arbitrary custom fields are excluded from the existing public careers response.
- Edit audit records list changed fields without copying sensitive job payloads into audit details.

`job_details` is a whole-object replacement when provided in PATCH. Omit it to retain all existing details. Clients should load the current object, edit it, and submit with the current version. This makes clearing versus retaining fields explicit.

## Field mapping

| Imported field(s) | Canonical field / remaining mapping |
|---|---|
| jobTitle / title | title (native limit currently 200; source RMS allows 255, so longer source titles require schema extension or explicit review before import) |
| jobDescription | description; employee-board jobs without a description need reviewed completion |
| companyName / company | job_details.company_name |
| department | job_details.department |
| location | job_details.location |
| jobType / type | job_details.job_type; source label normalization still required |
| workMode | job_details.work_mode |
| recruiter | job_details.recruiter_id only after verified user mapping; source display text must not become an authority |
| hiringDueDate | job_details.hiring_due_date; source timestamps require an explicit business-timezone mapping |
| targetDate / dateOpened (previously dropped by imported handler) | job_details.target_date / date_opened |
| jobLink | job_details.job_link |
| budget | job_details.budget plus explicit currency; currency cannot be inferred silently |
| salaryMin / salaryMax | job_details.salary_min / salary_max plus currency |
| noOfOpenings | job_details.no_of_openings, bounded by linked position capacity |
| requiredSkills | job_details.required_skills |
| hiringFlow | job_details.hiring_flow; configuration reference normalization remains |
| extraFields | job_details.extra_fields, JSON limited to 64 KiB |
| logo | job_details.logo |
| id / jobId | Source-ID crosswalk and display-code policy remain pending; no guessed UUID/integer conversion |
| candidateIds | Derive from canonical applications after migration; not a second editable candidate relationship list |
| status / isActive | Explicit lifecycle/publication mapping; cannot bypass approval by supplying Open/true |
| createdBy | requested_by only after verified identity mapping |
| createdAt / updatedAt | Preserve original timestamps as migration provenance; never overwrite history with guessed dates |

## Database and validation

- Applied additive RDS migration `c37d9f21a640` to `hirava_core.requisitions`: one non-null JSON column with an empty-object default for old rows. Existing public tables and business rows were not merged or removed.
- Tested a fresh SQLite Alembic migration through the new head.
- Native suite: **46 passed** (39 existing + 7 new job tests). These test persistence, audit/version conflicts, input validation, scope/module enforcement, literal search and public-field protection.
- Ran `scripts/check_job_cutover.py` against configured RDS. Inspected native/imported job and imported candidate/form/interview/schedule/application/referral tables were empty; tested orphan counts were zero at the time of inspection. This is not a promise that they stay empty.
- No UI build/browser test was run for this change because no frontend source changed. No production release or full job-screen cutover is claimed.

## Remaining before switching both screens

1. Map canonical position selection, approved state transitions and validated recruiter assignments into both job forms.
2. Resolve identifier compatibility for candidate, interview, employee application and referral endpoints; those handlers still query the imported job tables.
3. Complete source-specific import adapters and repeatable crosswalks if data arrives before cutover; check fresh counts immediately before switching.
4. Preserve the existing mixed form/table capabilities through the shared API adapters, including search/filter, custom fields and detail links.
5. Switch both entry points and their dependent references together, then verify create/edit/approval/publication and related candidate flows in the browser.

The old handlers remain active until these dependencies are implemented. The backend addition does not itself remove their duplicate writes.
