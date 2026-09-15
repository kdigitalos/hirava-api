# Coordinated HRMS batch — 2026-09-12

This batch replaces several demo workflows and closes ownership/state-transition gaps. It is not completion of every document or mixed-code feature. Original mixed source remains preserved. Public API remains FastAPI; imported private TypeScript/Prisma service is still required.

## Implemented

- Native reimbursement claims: exact decimal amounts, own drafts and receipts, submission/withdrawal, HR review with reason, no self-approval, version checks and audit events. Shared employee/admin screens use persisted data. Approval does not claim payment; company limits are explicitly unconfigured.
- Native improvement plans: HR authoring, private drafts, publication, employee acknowledgement, evidence-based progress reviews and closure. Shared UI replaces mock plans. No automated employment decision or notification is claimed.
- Leave and attendance: fail-closed employee linkage, strict dates/transitions, serialized overlap checks, withdrawal history, no employee self-approval/balance editing/historical attendance correction. Managers can review only direct reports through a dedicated page. Approval retries are idempotent; opposite terminal decisions conflict.
- Assets/documents/profile: HR review guards, document rejection reason, atomic allocation prevents double assignment, employee return request then HR approval then physical receipt, stale returns cannot release a later allocation. Job-detail clearing works without resurrecting JSON fallback. Profile-change approval updates profile, employee and decision in one transaction.
- Lifecycle/helpdesk: removed invented onboarding/support fallback data, separated probation recommendation from confirmation, tightened exit/clearance ownership and transitions. Helpdesk settings support editable category/rule drafts with real save/error behavior; automation is explicitly inactive.

## Verification

- Native pytest: 53 passed. Both Next applications passed TypeScript checks and production builds.
- Eight focused private-service scripts passed: attendance-leave, employee-resources, job-details, asset-workflow, payroll, lifecycle-guards, profile-review-transaction and helpdesk. These use mocked persistence and supplement live checks.
- Fresh SQLite migration rehearsal passed. RDS upgrade applied expense claims and improvement plans; head is `a61c42f5de90`.
- Live browser BFF → FastAPI → RDS verified claim draft/submit/review and denied self-approval; PIP draft privacy, publication, acknowledgement and review.
- Imported live routes additionally traversed the private service: manager direct-report leave approval, denied unrelated/self decisions, employee leave-type read-only access, server-stamped attendance with denied historical edit. Two simultaneous asset allocations returned one 201 and one 409. Return approval left inventory allocated until physical receipt released it.
- Browser PIP review (75%) and claim (456.78) were independently confirmed in RDS. Date-input automation required setting the native date field explicitly; the empty required field correctly blocked the earlier submit. Manager page rendered the assigned employee's approved request and role-specific navigation. PIP screenshot was visually inspected; minor question-mark separators remain cosmetic cleanup.
- Synthetic records and four test accounts were removed in a transaction, including imported identity rows and test audit events. Test state was deleted and browser test session logged out. Permanent preview account preserved. No S3 object was created in this live batch.
- Existing build warnings remain (Auth0 dependency expression and local standalone-start configuration). Builds passed; this is not deployment certification.

## Remaining work

Leave balances are HR-maintained: no automatic debit/reversal ledger, accrual/carryover or agreed opening-balance migration yet. Existing UTC attendance conventions need company policy review. Imported asset/leave decision audit metadata needs expansion. Full performance cycles, manager authoring policy and notifications remain beyond the basic PIP workflow.

Onboarding-to-employment handoff, probation/lifecycle synchronization, exit settlement/payroll reconciliation, effective-dated compensation, approved payroll/payslips and statutory rules remain incomplete. Helpdesk background routing/escalation is not implemented, and dynamic settings DDL needs a migration. Canonical employee/leave consolidation, organization-wide role/customer checks, Auth0, providers, imports/exports, backups/restore and release checks remain.

RMS candidate/application/interview/referral consolidation, offers and hiring handoff, custom form-builder parity, and the client's 12 AI agents remain in the shared project backlog. Do not equate model/surface inventory with working end-to-end features.

Company operating countries and approved policies were requested but not supplied. Continue policy-independent work without inventing entitlements, deductions or notification/payment delivery. Detailed evidence and limitations also appear in `employee-resources-progress.md` and `hrms-lifecycle-audit.md`. All batch changes are local, uncommitted/unpushed.
