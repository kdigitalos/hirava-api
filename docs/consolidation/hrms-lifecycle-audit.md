# HRMS lifecycle audit and implementation

Updated 2026-09-12. This is code evidence and bounded implementation, not certification that all HRMS workflows are finished. No production records were changed during this subtask.

## Delivered in this batch

- Onboarding dashboard no longer shows fake 7/8/6/3/3 metrics while loading or after request failure. Request errors are visible; stale filter results are cleared. Case statuses preserve the API's Draft/Archived/Pending values rather than relabeling everything Completed/In Progress.
- Dashboard reminders now open candidate/probation review workflows. The old POST complete-task shortcut returns 409 instead of directly setting an entire candidate Completed or probation Confirmed. A reminder is not an independent approval.
- Removed unused mock people/cases/tasks from dashboard data. Quick-action links use HRMS paths; the link to groups is labeled View Groups rather than falsely labeled Audit Logs.
- PIP prototype preserved as non-route prototype-reference.tsx, excluded from live imports. The real employee page now uses ImprovementWorkspace; HR manages the same records through Admin/EmployeeSelfService/performance-improvement-plan, linked from the admin Performance Hub.
- Native improvement_plans records reference shared User identity (not a new copy of Worker/Employee), customer, HR author, time period, reason, measurable milestones/actions/support, progress, append-only reviews, acknowledgment and final outcome. Migration a61c42f5de90 follows f19a20c4d611. No PIP model existed in the imported schema.
- HR/admin author draft/create/edit/publish. Staff see only their own published records; HR/admin can inspect organization records. No broad manager team permission was added. Employee acknowledgment means receipt, not agreement. Reviews record reviewer/time/evidence; completion/cancellation records final outcome and locks the plan. Neither automatically changes employment or triggers exit.
- Date/range/length constraints, row locks and expected_version enforce validation and stale-write protection. Tenant/role/ownership checks remain server-side; audit events accompany mutations.

## Verification

Focused native tests tests/test_improvement.py: 2 passed. Covers draft secrecy, unrelated manager denial, employee own read/acknowledgment, HR unable to acknowledge for employee, stale version conflicts, review evidence/progress, invalid progress/dates, author self-plan denial, unrelated customer authentication denial, employee mutation denial, draft edits and immutable closed plans.

Frontend typecheck passed. Full builds/live persistence verification are coordinated by the root agent; consult brain.md for final outcomes. No external providers or live DB mutation were needed for these tests.

## Remaining lifecycle completion checklist

### Onboarding

- Existing imported group/template/candidate APIs are real but must be verified end-to-end, including failure, assignment and access checks.
- RMS accepted offer -> HR reviewed conversion -> single employee identity -> readiness tasks -> actual joining is still a cross-schema consolidation task. Do not create another candidate or employee merely to make a page work.
- Dashboard progress percentages are currently status heuristics, not measured checklist completion. Replace with actual task aggregates before treating them as workflow completion percentages.
- Dashboard team/location/owner filter options still contain preset values. Derive from directory/group data; verify every filter against the backend semantics.
- Case cards still have inert more-options controls. Bind to real case actions or remove inactive controls.
- Notification/invitation, due-date reminder delivery, policy acknowledgment evidence and signed documents need explicit durable workflow and provider verification.

### Probation

- List/create/extend/review/confirm/policy settings have imported APIs. Current direct confirm needs consistent allowed transitions, reviewed evidence, actor/time audit and duplicate-submit checks.
- add-review currently can automatically confirm based on recommendation; separate recorded recommendation from authorized final decision and verify employee status consistency.
- Company-defined period, extension policy and reviewer ownership must be configured. Do not assume legal durations or automatically terminate when overdue.
- Confirm/extend/reject outcomes need browser/API/DB coverage and employee visibility as appropriate.

### Performance / PIP

- New PIP supports bounded draft -> active -> completed/cancelled and append-only reviews, not the entire appraisal product.
- Imported employee performance goals/feedback/self-appraisal have APIs; admin performance overview, manager assignment scoping, review cycles/calibration and appraisal signoff remain to consolidate and test.
- Assigned manager authorship is intentionally not enabled without a trustworthy shared reporting relationship. HR/admin currently author and review; all staff have only own published visibility except HR/admin oversight.
- PIP duration/extension/amendment policy, dispute/comments, supporting document attachments, notification delivery and structured stakeholder assignment are pending. Active definition edits are forbidden; do not silently replace historical expectations.
- Plans target active staff identities. Imported employees without linked login identities need the existing identity provisioning/linking workflow, not duplicated user accounts.
- No automatic adverse employment decisions or AI performance scoring were introduced.

### Exit / full and final

- Imported exit initiation, detail edit, clearance, templates, settlement create/edit and dashboard APIs exist; they are not automatically certified by page existence.
- Verify employee/manager/HR approvals, notice/last-working-date rules, clearances and asset return ownership, document delivery and settlement calculations before completion.
- Final settlement inputs are not proof of payment or statutory correctness. Currency, policy, applicable payroll jurisdiction/provider, approval and payment reconciliation need agreed rules.
- Employment end and identity access revocation must be separate traceable authorized steps; verify retry safety and rehiring/history behavior.
- Exit dashboard uses real API data but links/error/stale-response behavior require broader browser review.

### Whole HRMS release dependencies

Attendance/leave, employee documents/assets/profile and claims are owned by parallel workstreams. Organization/manager mapping, tenant access, Auth0 production setup, audit coverage, import/export, notification workers/provider credentials, backups/restore, monitoring and complete role journeys remain release work. Existing API/model inventory is not an end-to-end completion certificate.

## Actual decisions needed vs implementable work

No customer input is needed to continue persistence, validation, scoping, error handling, navigation and synthetic verification. Real company policies are required for payroll calculations, leave entitlements, probation/notice rules and performance cycle/decision ownership. Auth0 tenant configuration and external mail/calendar/e-sign providers are needed for their respective production integrations, not for local CRUD development. Keep these explicit rather than inventing policy or marking delivery complete.


## Second lifecycle pass (before integrated build)

- Private probation detail GET/PATCH now explicitly require HR/admin in addition to the public gateway. Self-review/decision and mutations after confirmation are denied. Review recommendation no longer auto-confirms; the explicit confirmation action remains. Reviewer identity/time are derived from authenticated actor. Updates match previously read status/updatedAt to avoid lost concurrent changes. Extension events record notificationRequested separately from notified=false, and UI no longer promises an email that was never sent.
- Self-service review rejects self-review and already-reviewed status changes. Non-profile reviewed requests now record reviewer/time/note. This closes the misleading approved -> rejected relabel without rollback, but profile helper transactional atomicity is still next work.
- Exit detail and clearance ownership checks fail closed when the actor has no linked employee. Exit PATCH/DELETE require HR/admin and deny self-decision. Closed records cannot be modified; delete is limited to pending requests. Explicit status transitions and valid ordered calendar dates are enforced. Completion requires recorded approved clearance checklist items.
- Clearance cannot be self-approved or edited before exit approval/after closure; approval requires checked items. Decision actor/time are server-derived. Completion advances an approved case to IN_PROGRESS rather than regressing its status to APPROVED.
- Checks: private TypeScript noEmit passed. scripts/test-lifecycle-guards.cjs passed 12 scenarios with stubbed persistence and asserts no write on denied operations. This tests route guards but does not replace live workflow checks.
- Still pending: profile-change service applies EmployeeProfile, Employee and request status separately; make that atomic next. Probation confirmation still needs richer explicit decision evidence/audit and employee lifecycle synchronization. Existing profile/exit provider policies and full schema consolidation remain open.


## Atomic profile review follow-up

The profile review service now uses one Prisma transaction for conditional pending-request claim, EmployeeProfile upsert, Employee/core/reference changes and review stamp. Rejection also claims only pending state transactionally. Duplicate/concurrent/self review is rejected in the service as well as the route; employee-profile-service DTO converters are reused unchanged. A failure applying employee fields rolls back the profile and approved status too.

scripts/test-profile-review-transaction.cjs passed injected failure rollback, atomic success, duplicate/self-review rejection, concurrent claim loss and rejection-without-profile-mutation. Tests use an isolated transactional stub and do not prove live RDS isolation; root handles live verification. This resolves the non-atomicity item above. Other self-service request types still represent recorded decisions rather than automatically executing every requested operational change; verify each domain handoff before advertising completion.
