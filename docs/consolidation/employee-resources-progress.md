# Employee resources and asset workflow progress

Date: 2026-09-12. This note records code and focused mocked tests, not live certification.

## Implemented

- Profile document review and asset/lifecycle mutations require HR/admin in private handlers. Ownership alone cannot approve documents or alter inventory/lifecycle history.
- Document review validates input, requires a rejection reason and clears stale reasons on approval. Frontend collects the reason.
- Returning an old asset allocation cannot release a newer allocation. Release only changes ALLOCATED inventory when no active allocations remain.
- Job Details does not invent Full-time employment. Work location edits use the draft correctly; clearing manager/location removes old JSON fallback values without deleting unrelated details.
- Inventory, categories, available assets, allocation lists/timeline and allocation mutations explicitly require HR/admin.
- Allocation creation conditionally claims AVAILABLE inventory inside its transaction, preventing two concurrent assignments from claiming it successfully.
- Allocation receipt closes the active record and releases inventory together; reopening and deleting allocation history are rejected. Admin UI includes Confirm receipt.
- Employee Return creates a return request rather than declaring physical receipt. Return requests are ownership-scoped; creation locks the assignment and checks for an existing pending request. HR can approve/reject once. Approval does not release inventory; HR receipt is a separate action.
- Incident detail rejects users without an employee mapping; incident aggregates are scoped like the list; employee incident creation requires their currently assigned asset. Review remains HR/admin-only.

## Focused verification

From `hirava-api/legacy-service`:

- `node scripts/test-employee-resources.cjs`: role-denial matrix; document validation/rejection; repeat/stale asset return behavior.
- `node scripts/test-job-details.cjs`: empty employment type; manager/location clearing; unrelated metadata preservation.
- `node scripts/test-asset-workflow.cjs`: inventory access; owned return list/create; invalid dates; pending duplicate; HR review transition conflict.

All three passed against mocked service dependencies. They do not prove transaction behavior on PostgreSQL or browser/server integration. Root integration pass owns typechecks, builds and live verification.

## Remaining work

- No new migration. Return-request model has no reviewer identity/rejection explanation fields; full review audit requires planned schema/audit integration.
- Live simultaneous allocation and return-request tests on isolated synthetic records are still required.
- Broad asset creation accepts legacy status choices; validate/reconcile pre-existing inventory inconsistencies and lifecycle semantics before production.
- Incident attachments/storage cleanup and incident-number concurrency need further verification. Incident status changes do not automatically classify inventory as lost/in repair; policy and receipt decisions remain explicit work.
- Generic asset editing and error handling are not fully certified. Server-side employee self-service profile rendering may use imported models distinct from admin profile records.
- Lifecycle stage derivation currently treats hire date as onboarding-completion evidence; this is not proof of task/document completion.
- Auth0, tenant isolation, retention/audit, notifications, backups and remaining project backlog are not completed by these changes.

## Helpdesk and task pass

- Ticket-list errors/unauthenticated responses no longer produce twelve fictitious tickets. Dashboard unavailable data displays Unavailable rather than zero-as-if-loaded.
- Helpdesk default settings no longer invent people, automatic assignments, escalation rules or SLA durations. Empty/unconfigured defaults preserve existing persisted configuration. PUT validates nested fields and numeric bounds; frontend saves report network failures.
- AskMe global ticket/settings/KB/FAQ/report operations and employee/agent pickers restrict management to HR/admin. Other authenticated users may create tickets only for their own employee record; assigned-ticket manager workflow still requires scoped implementation.
- KB list without a limit correctly defaults to 100 rather than accidentally returning one item.
- Admin task creation rejects wrong field types and impossible YYYY-MM-DD dates.
- `node scripts/test-helpdesk.cjs` passed with mocked dependencies: management denial, KB defaults/cap, settings validation/defaults and task input handling.

Remaining helpdesk scope: Settings Add Category/Add Rule now open validated editable drafts and persist through the existing Save Configuration API. Saved escalation configuration is not consumed by a background runner; the UI explicitly labels routing/notifications inactive. Do not describe automated assignment/escalation/notifications as complete. Settings persistence still uses the imported dynamic table-creation helper and should be migrated into controlled schema management. Organization role/company-profile/reporting APIs were only audited, not changed in this pass; several retain broad/private auth guards. Employee tasks already persist and enforce ownership but workflow-source completion coupling is not certified.

Existing persisted configuration was preserved. Removing default generators does not prove that previously seeded settings represent approved company policy; HR must review those settings before production use.
