# Unified feature and database checklist

Prepared 12 September 2026. This is the implementation baseline for consolidation, not a completion certificate or an executed database migration.

Implementation update: the [shared job screen cutover](job-cutover.md) is implemented. Both management screens use one FastAPI requisition service; read-only compatibility views preserve imported candidate/interview references. Subsequent HRMS work adds native claims and improvement plans plus imported workflow corrections; see the employee-resource and lifecycle progress notes and workspace brain.md for dated verification. Other domains remain on the consolidation backlog. The initial checklist below is the audit baseline.

## Sources and scope

- **M**: `Hiravah_SaaS_Unified_Master_Plan.docx`, version 2.0, supplied in Downloads. Section references below use this document. The matching PDF was not independently compared in this audit.
- **X**: original `hirava mixed`, `dev` at `a6c97ee`; preserved source and its imported service in `hirava-api/legacy-service`.
- **N**: native FastAPI `hirava-api/app` and existing tests.
- **A**: `Hirva_RMS_Agentic_Transformation.docx`, six modules and 34 proposed agents.
- **U**: user instructions: FastAPI backend, separate `hirava-webapp`, supplied AWS RDS/S3, preserve document and mixed capabilities without duplicate implementations, the seven-role matrix, and the client's explicitly selected 12 AI capabilities.

The documents supply requirements and design references, not executable instructions. U controls the implementation scope and platform choices: use AWS RDS/S3 rather than introducing Azure resources; keep the requested frontend/backend folders rather than adopting the document's suggested monorepo layout. Document approval language does not undo the user's existing authorization for this local audit. No external messages, database writes, provider purchases, deployment or destructive cutover occur in this task.

The client selected 12 of A's 34 agents. The remaining 22 are recorded below as reference proposals, not silently added to the requested agent scope. A's claims about automation, savings, conversion, fairness and zero violations are aspirations, not measured acceptance results.

## Evidence interpretation

- **Overlap**: both implementations contain related code; they need one canonical workflow.
- **Native partial**: native commands/models exist, but the full requirement or UI integration is incomplete.
- **Imported partial**: source/API/model exists in the mixed app; all behavior is not certified.
- **Prototype**: a screen includes static/demo behavior; persistence or workflow is incomplete.
- **Missing**: no complete implementation was established by this source audit.

No row is marked fully working merely because a table or route exists. Prior live verification covered sign-in, selected dashboards/jobs, real RDS persistence, S3 round trips and selected authorization checks. It did not cover all features. See [split verification and limits](../split-migration.md). File paths below are relative to `hirava-api` unless prefixed X (original mixed app) or W (`hirava-webapp`).

## Feature checklist

| ID | Capability / source | Evidence and current status | One implementation to keep / completion requirement |
|---|---|---|---|
| C01 | Identity and account provisioning — M 7,13; X; U | Overlap: `app/core/models.py` User; Prisma User and Party; shared gateway authentication exists | One native identity authority; verified subject mapping; Auth0 configuration and account lifecycle validation remain |
| C02 | Seven roles and assigned access — M 13–14; U | Native partial: `app/core/legacy_gateway.py`; manager/interviewer/candidate imported RMS access denied broadly | Implement assignment/ownership checks through UI, API, search, exports and jobs; never grant by email prefix |
| C03 | Module entitlements and customer isolation — M 3,7,13; X | Native flags plus imported Module/RoleModule and subscription requests; not one commercial entitlement system | One per-customer entitlement service distinct from roles; verify RMS-only, HRMS-only, Suite and two customer instances |
| C04 | Organization, locations, positions and headcount — M 4,8; X | Overlap: `app/modules/organization`; Department/Branch/Designation/JobTitle/company profile | Retain hierarchy and imported details; extend native job-profile/location/effective-date support; positions retain capacity semantics |
| C05 | Roles editor and access administration — X; M 13 | Imported partial: OrganizationRoleSetting, organization/roles routes | One role grant policy; definitions/labels cannot independently authorize users |
| C06 | Documents and private storage — M 8,13; X | Overlap: native Document + EmployeeDocument; S3 read/write verified on selected flows | One metadata/storage API with domain-scoped links; preserve expiry, review, ownership, hashes and existing objects |
| C07 | Policies and acknowledgements — M 4,9; X | Overlap: native Policy/Acknowledgement + PrivacyPolicy | Merge policy content, version, audience, effective dates and acknowledgement records |
| C08 | Tasks, approvals, audit and notifications — M 10; X | Native partial: audit/outbox/notification models, domain decisions; imported tasks and approval states | One command/audit/outbox foundation; retain domain-specific approval rules and histories |
| C09 | Search, dashboards and exports — M 14,24; X | Imported partial: search and dashboard routes; source queries exist | One scoped read model per metric; document denominators, dates and record access; remove demo values |
| C10 | Party management — X | Imported partial: Party and six related business/identity models | Preserve business contacts, relationships, addresses and bank details; separate them from authentication and employee records |
| C11 | Subscription enquiries and SaaS operations — M 3,7,15; X | Imported enquiry form/models; native module flags; billing/provisioning not complete | Preserve enquiry workflow; add manual plan administration and release/setup runbooks; no inferred payment engine |
| R01 | Requisition creation, approval and publication — M 4–5; X | Overlap: native Requisition; imported RmsJobOpening and JobOpening | One requisition with approved versions and publication records; employee job list is a view of the same jobs |
| R02 | Careers and candidate application forms — M 4–5; X | Overlap: native Candidate/Application; RmsCandidateFormDetail and public-looking UI behind gateway | One application intake; preserve custom questions/resume; repair public/candidate route contract with consent and abuse controls |
| R03 | Candidate profile and pipeline — M 4,8; X | Overlap: native person/application separation; RmsCandidate is job-bound JSON | One candidate identity, multiple applications; preserve extended profile fields and stage history without flattening applications |
| R04 | Hiring-flow stages, forms and question configuration — X; M 4 | Imported partial: RmsSectionValue, RmsHiringFlow, RmsQuestion | Port versioned configuration; map old labels and stage JSON, retain original source values for reconciliation |
| R05 | Internal applications and referrals — X | Imported partial: JobApplication, JobReferral, HRMS recruitment views | Use canonical jobs/applications with referrer linkage; internal mobility remains reviewed employment change |
| R06 | Interview rounds, panels and scheduling — M 4; X | Overlap: native Interview; RmsInterview/RmsInterviewSchedule | Extend native panels, timezones and scheduling history; one interview identity; calendar adapter pending |
| R07 | Scorecards, questions and feedback — M 4; X | Overlap: native Scorecard has basic competency; RmsFeedback has round/rating/recommendation | Keep richer structured responses and attribution; restrict by assigned panel; separate feedback from hiring decision |
| R08 | Offers, approvals and acceptance — M 4–5 | Native partial: `app/modules/offers`; imported status labels are not offer evidence | Use native governed offer workflow; add version amendments, templates and selected signature boundary; never synthesize acceptance from a hired label |
| R09 | HR conversion and commencement — M 5 | Native partial: `app/modules/conversion`; no imported canonical linkage | One HR-reviewed allowlisted mapping; source lineage, idempotency, atomic capacity checks and explicit commencement |
| R10 | Rehire, no-show, withdrawal and internal mobility — M 5 | Native basic lifecycle; advanced multiple employment and exception policies missing | Extend employment multiplicity and reviewed linkage; retain separate applicant/offer/worker states |
| R11 | Email templates and candidate communication — X; M 11 | Imported RmsTemplate/sendEmails; live mail unconfigured | Preserve templates; delivery through shared outbox with scoped approval, provider receipts, retries and opt-out handling |
| R12 | Recruiting analytics and recruiter metrics — X; M 24 | Imported query-backed routes including dashboard/detailPerformanceMetrics; not unified | Canonical event history and attribution; distinguish accepted offer, conversion and employment start; AI reads same metrics |
| H01 | Employee directory and profile — M 4; X | Overlap: Worker/Employment and Employee/EmployeeProfile | Canonical worker and employment; preserve profile extensions and restricted fields; no candidate evidence bulk-copy |
| H02 | Manager mapping and reporting hierarchy — M 4,13; X | Overlap: native manager link; mixed reporting-hierarchy/manager-mapping import routes | Preserve import/reorder tools; validate cycles, scope, effective dates and error reports |
| H03 | Onboarding templates, groups and cases — M 4–5; X | Overlap: native lifecycle cases/tasks; OnboardingGroup/Template/Candidate | Port templates/groups into one case/task service; acceptance alone cannot activate employee access |
| H04 | Probation management — X; M 4 | Imported partial: ProbationRecord/PolicySettings and routes | Port records, policy and review tasks to FastAPI; retain human decision and history |
| H05 | Profile changes and self-service requests — M 4; X | Overlap: native name-change request; imported typed request payloads and review | Extend native typed changes to preserve richer forms; apply only approved fields with original decision evidence |
| H06 | Leave types, balances, requests and approval — M 4; X | Overlap: two sets of leave models | One leave ledger/rules service; reconcile units and approved balances before cutover; test retry and concurrent approval |
| H07 | Holiday calendars and richer leave rules — M 4; X | PublicHoliday model; native Monday–Friday integer-day checks only | Retain calendar data; complete accrual, carryover, half days and cross-year policy where required |
| H08 | Attendance, policies, reports and shifts — X; M 11 | Imported partial: AttendanceRecord/Policy/EmployeeShift and report endpoints | Port existing basics; connect external attendance only through explicit adapter; do not infer shift optimization |
| H09 | Asset inventory, vendors and photos — X | Imported partial: asset models/routes/screens | Keep unique asset domain, referencing canonical workers and shared documents |
| H10 | Asset allocation, returns and lost/damage workflows — X | Imported partial: assignment/return/incident/policy models | Preserve audit/history and approval; integrate offboarding tasks rather than duplicate exit tracking |
| H11 | HR cases, helpdesk tickets and restricted notes — M 4; X | Overlap: HRCase/CaseNote + SupportTicket, several route surfaces | One case service, multiple authorized views; add SLA/routing fields without exposing confidential case notes |
| H12 | Knowledge base and FAQs — X; M 9 | Imported partial: KnowledgeBaseArticle/Faq | Preserve content and publication controls; policy AI retrieval must honor audiences and effective sources |
| H13 | Performance goals, feedback and appraisals — M 4; X | Overlap: native basic goals/reviews + richer imported goal/appraisal/feedback | Merge goals/reviews; retain weights, reflections and cycles; calibration and advanced reviews remain incomplete |
| H14 | Learning, certification and renewals — M 4 | Native partial: Course/LearningAssignment | Keep basic learning; extend certifications/renewals and approved external LMS references |
| H15 | Exit requests, clearance, templates and lifecycle — M 4–5; X | Overlap: native offboarding + ExitRequest/ExitOffboardingTemplate | One exit lifecycle; preserve clearance steps, asset links and revocation evidence |
| H16 | Full/final settlement and payroll profile — X; M 11 | Imported partial: FnfSettlement and employee payroll routes | Retain recorded amounts/settlement workflow; payroll provider export/reconciliation remains distinct from statutory calculation |
| H17 | Payslip/document screens — X | Source screens present; not certified as payroll-generated persisted payslips | Preserve useful document views; verify actual source and persistence before claiming payroll delivery |
| H18 | Reimbursements/claims — X | Native workflow added: `app/modules/claims` and shared `ClaimsWorkspace`; draft/submit/review with own receipts, audit and versions | Verify full browser handoff; company limits, payment/reconciliation and notification delivery remain pending. Document initially excluded expenses but U requests mixed features |
| H19 | Performance improvement plan — X | Native workflow added: `app/modules/improvement`; draft/publish/acknowledge/reviews/close with scoped identity and audit | Verify shared HR/employee UI; assignment extensions, amendment policy and notification delivery remain pending |
| H20 | Announcements and calendar items — X | Imported partial: Announcement/AdminScheduleItem | Keep unique content and schedule records; reuse shared notifications rather than another delivery service |
| P01 | Provider contracts, inbox/outbox and durable repair — M 10–11 | Native outbox partial; imported direct provider code | Add verified inbox, idempotency, timers, backoff and reconciliation; replace direct side effects in migrated commands |
| P02 | Auth0 lifecycle, SSO, MFA and recovery — M 13 | Adapter exists; real tenant settings/configuration absent | Configure and validate once across frontend and FastAPI; no duplicate identity store |
| P03 | Privacy, retention, rights and legal hold — M 8,13 | Document authorization partial; lifecycle automation missing | Add source and derived-data retention, export/delete review and hold enforcement |
| P04 | Recovery, deployment, observability and accessibility — M 14–18 | Selected local flows/builds tested; full deployment/restore/accessibility evidence absent | Verify full topology, restore/rollback, keyboard flows and provider outage repair before release claims |
| P05 | AI foundation, evaluations, budgets and fallback — M 9 | `app/intelligence` reserved; no complete agent execution platform | One agent registry/run/proposal/evaluation foundation; core workflows work with AI disabled |
| P06 | Policy assistant and job-description drafts — M 9 | Missing complete assistants; distinct from selected 12 operational agents | Retain master-document capabilities; share retrieval/drafting runtime; do not invent a second JD service |
| P07 | MCP — M 12 | Reserved/optional, no complete runtime established | Track as optional external interface; not internal service bus or prerequisite for core completion |

## Client-selected agents: one capability each

All 12 are **not complete**. Existing CRUD, charts, scheduling fields or email templates are prerequisites, not evidence of a working AI agent. Runtime/model/provider configuration and evaluation are pending.

| ID | Module / exact requested capability | Reuse and required completion | Acceptance evidence |
|---|---|---|---|
| A01 | Dashboard / Improves Hiring Conversion | R12 stage/event metrics; identify bottlenecks and explain recommendations; experiments require attributable outcomes | Recomputed funnel totals match source events; output cites window/denominators and does not claim causality without evidence |
| A02 | Job Openings / Multi-Platform Job Poster | R01 approved publication plus P01 provider jobs; channel formatting, refresh, source attribution | Same approved job version, one provider posting per idempotency key, failure/retry visible; live platform adapters require their supported access/config |
| A03 | Candidates / CV Screening Agent | C06 document parsing and R03 profile/application; extract skills and evidence-backed summaries/reviewable scores | PDF/DOCX/OCR fixtures, extraction correction, job-relevant evidence, no unsupported sensitive inference or automatic rejection |
| A04 | Candidates / Job Matching Agent | R01/R03 canonical jobs/candidates; explain skill matches and rerun when jobs change | Same person can match multiple roles; authorized scope only; evidence and missing-data uncertainty visible |
| A05 | Candidates / Passive Candidate Finder | Approved sourcing adapters, candidate provenance and R11 outreach drafts | Authorized source access, deduplication, consent/contact preferences and approved outreach; no actual messages sent during this audit |
| A06 | Candidates / Duplicate Record Detector | R03 person/application distinction plus migration crosswalk | Exact/fuzzy suggestions preserve applications, notes and documents; uncertain merges reviewed, reversible and audited |
| A07 | Interviews / Scheduling Agent | R06 interview/participant service plus shared calendar adapter | Timezones, conflicts, reschedule/cancel and duplicate retries; provider confirmation rather than local status alone |
| A08 | Interviews / Feedback Collection Agent | R07 scorecards and C08 reminders | Assigned panel only, delayed-feedback reminders, missing responses explicit, summaries preserve disagreement |
| A09 | Analytics / Executive Report Writer | R12/C09 metrics and R11 scheduled delivery | Narrative totals reconcile, audience filters apply, delivery policy respected, AI outage does not break reporting |
| A10 | Analytics / Recruiter Performance Tracker | Existing mixed recruiter metrics extended with canonical attribution/cost events | Defined time-to-hire/cost metrics, appropriate workload context, no invented costs or automatic employee ratings/actions |
| A11 | Enterprise / Recruitment Orchestrator | C08/P01 durable workflow service; coordinates other agents through domain commands | Duplicate events produce one result; approval boundaries preserved; timers/repair and AI-disabled fallback tested |
| A12 | Enterprise / Talent Pool Manager | R03/R04 matching + new pool/membership metadata; no second candidate master | Pool membership references existing candidates; refresh/retention/contact preferences enforced; new-role matching uses A04 |

No adverse screening based simply on employment gaps or short tenure, sensitive-attribute inference, automatic hiring/rejection, or autonomous compensation/employee action is introduced from A's examples. The master plan's assistance-first boundary supplies the product design: humans review consequential decisions; operational automation invokes the same authorized commands as the UI.

### Other 22 agent proposals in A

Reference only unless separately selected; overlap with an existing master-plan feature does not create a second feature:

- Dashboard (3): Predicts Future Hiring Needs; Explains Your Numbers; Spots Problems Early.
- Job Openings (4): Smart Job Description Writer (already represented by P06); Approval Workflow Manager (C08/R01); Salary & Market Intelligence; Application Volume Predictor.
- Candidates (3): Candidate Engagement Agent; Background Check Agent; Candidate Sentiment Analyser.
- Interviews (4): AI First-Round Screener; Interview Question Generator; Interview Analytics Agent; Skills Assessment Agent.
- Analytics (4): Job Board ROI Analyst; Diversity & Inclusion Monitor; Cost Tracking Agent; Predictive Hiring Forecaster.
- Enterprise (4): Compliance & Legal Monitor; Onboarding Coordinator (H03/R09); Hiring Manager Communications Agent; Offer Negotiation Assistant.

## Database mapping and migration design

[database-map.csv](database-map.csv) accounts for the 69 imported models and the native models. The initial audit had 30 native models; job unification adds a numeric-ID mapping model, bringing the current native count to 31. The two migration-ledger tables and retained empty archive tables are outside this source-model mapping. Imported job models now read compatibility views, not independent job tables. [model-inventory.json](model-inventory.json) retains source definitions and locations. [surface-inventory.json](surface-inventory.json) lists original pages/routes, including aliases and the auth profile route; presence is not behavioral certification.

The final backend owner is **FastAPI**, extending native domain commands with the useful imported fields and workflows. The private TypeScript service is transitional. Existing tables stay intact while each feature is ported and validated. A single feature can legitimately use several related tables and schemas; eliminating duplicate features does not mean putting candidate and employee information into one table.

### Highest-risk mappings

| Source | Canonical target and required transformation |
|---|---|
| `public.rms_job_openings`, `public.job_openings` | Native requisition plus publication metadata. Title matching alone cannot prove the two source rows are the same vacancy. Preserve recruiter, stage configuration and job-specific fields. Map publication/approval statuses separately. |
| `public.rms_candidate` | Split job-bound record into candidate identity and application. Parse JSON profile into typed fields with retained original provenance; preserve additional questions/status/contact history. |
| `public.rms_candidate_form_details`, `public.job_applications` | Form submission and application links; reconcile against canonical person/job IDs. Missing consent or owner linkage must be flagged, never fabricated. |
| `public.rms_interview`, `public.rms_interview_schedule`, `public.rms_feedback` | Interview, rounds, participants, slot history and scorecards. String names/emails are not verified assignments. Resolve timezone and stage fields S2–S4/F1–F5 explicitly. |
| `public."Employee"`, `public.employee_profiles` | Worker, employment and restricted profile extensions. Preserve financial/identity details in protected fields. Existing native one-employment-per-worker constraint must change before rehire support. |
| `public."OnboardingCandidate"` | Preboarding/lifecycle context, linked by reviewed lineage. Do not duplicate RMS candidates or infer accepted offers/HR approval from a name or status. |
| Imported/native leave and performance records | Preserve units, dates, statuses, requester/reviewer identity and histories. Same table name in different schemas does not prove compatible semantics. |
| `public."User"`, `public.parties`, role tables | Explicit subject-to-user crosswalk; business parties and business relationship roles remain distinct from authorization grants. Email alone cannot establish account ownership. |

### Safe migration sequence

1. Add canonical missing fields/tables and a source-ID crosswalk keyed by customer, source schema/table/ID. Crosswalk and migration-run ledger are proposed additions, not installed by this audit.
2. Produce read-only counts, invalid foreign-key/orphan reports, status/value distributions and ambiguous identity/job matches. Run detailed field mappings on synthetic fixtures before real backfill.
3. Dry-run each mapping with source/target counts, excluded fields, preserved provenance and exception reports. Do not guess ambiguous identities or discard JSON fields that lack a target.
4. Backfill a feature through idempotent migration commands. Keep old IDs in the crosswalk; validate references, histories, permissions and source-to-target totals. Do not dual-write the same business command to both models.
5. Switch its frontend and compatibility routes to the canonical FastAPI service together; freeze the old feature's writes during final reconciliation. Other features can remain on the private service temporarily.
6. Test migrated commands and views end to end, including repeated requests and all affected roles. Rollback after new writes requires reconciled delta replay; simply pointing back to stale old tables is unsafe.
7. Retire old writes/service modules only after acceptance and a tested recovery path. Archive/drop decisions are separate from this non-destructive plan.

## Role acceptance matrix

| Role | Required final scope | Current integration gap |
|---|---|---|
| Admin | Both enabled modules and administration | Selected flows verified; full field/business-approval policy still needs acceptance |
| Recruiter | RMS recruitment features | Imported RMS basics available; unified records and agent scopes pending |
| HR | HRMS plus RMS approvals/handoff | Imported RMS currently read-only; native approvals/handoff need frontend integration |
| Manager | Assigned hiring and managed team | Imported broad RMS denied; assigned views/actions need canonical endpoints |
| Interviewer | Assigned interviews and scorecards | Imported broad RMS denied; scoped packet and submission UI pending |
| Employee | Own HRMS self-service | Selected boundaries verified; all self-service persistence/ownership paths need acceptance |
| Candidate | Own applications and offers | Native scope exists; imported/public intake and candidate workspace wiring incomplete |

## Ordered delivery backlog

| Step | Work | Exit criterion |
|---|---|---|
| 1 — This deliverable | Source checklist, full model inventory and model-level mapping | All models accounted for; 12 selected agents separated from 22 proposals; no feature silently discarded |
| 2 — First implementation slice | Canonical organization/identity references, job/requisition fields and compatibility contracts (C01–04, R01) | Create/update one job through either UI entry and observe one canonical record; preserve extra mixed fields; role/module checks pass |
| 3 | Candidate/application intake, custom forms and referrals (R02–05) | One candidate can apply to multiple jobs without duplicate person records; unresolved identity matches remain reviewable |
| 4 | Interviews, offers, HR conversion and onboarding (R06–10, H03) | Job → application → assigned interview → offer approval/acceptance → HR handoff → onboarding → commencement passes, including retries |
| 5 | HRMS overlap and unique mixed capabilities (H01–20) | Port each listed feature, preserve fields/history, verify employee/manager scope; remove demo dependencies |
| 6 | Shared AI runtime and 12 selected agents (P05–06, A01–12) | Each agent meets its evidence contract and uses canonical workflows; no second candidate/job/approval system |
| 7 | Provider, privacy and release acceptance (P01–04) | Actual configured integrations, failure/recovery, accessibility and full role journey evidence recorded |

Implementation steps can share foundations, but a dependent feature is not declared finished before its canonical data and authorization contracts exist. This audit does not estimate dates without implementation sizing or claim that the remaining work has been done.

## Rebuilding the source inventory

From `hirava-api`, run `.\.venv\Scripts\python.exe scripts\build_feature_inventory.py`. It reads local source only and regenerates the CSV and JSON inventories; it does not use credentials or connect to RDS. The manually reviewed feature checklist and design decisions above are maintained separately.
