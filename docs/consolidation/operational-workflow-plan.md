# Operational workflow plan

Added 2026-09-12 after the user authorized practical workflow suggestions and additions. These are implementation priorities, not completed functionality. Extend existing domains rather than building parallel modules. See the full feature checklist for document and mixed-code requirements.

## Hiring into employment

Use the existing canonical requisition approval/publication flow, then consolidate candidate identity and separate applications. Interviews and scorecards belong to an application and assigned interviewers. An approved offer, candidate acceptance, HR-reviewed conversion and actual joining are separate recorded steps. A label such as "hired" must not automatically issue an employment record, activate payroll or imply that the person joined.

Preserve explicit withdrawal, declined offer, no-show and rehire paths. Reuse candidate identity where appropriate while retaining application history. Verify permissions at the API for each transition and record the actor and time.

## Compensation and payroll

The current employee Payroll tab is a recorded compensation snapshot in INR. It is not a calculation engine, approved payroll run, payslip or payment confirmation.

Priorities for later implementation:

1. Effective-dated compensation changes and an audit trail: preserve previous values and who approved the change. Reuse the existing audit/approval foundation.
2. Explicit pay period, currency and processing status. Keep salary setup distinct from amounts calculated for a particular period; do not overwrite historical payslips when salary changes.
3. Reviewed attendance/leave inputs and separately recorded adjustments. A proposed adjustment should not silently alter finalized pay.
4. Draft calculation or provider import, HR/admin review, approval, finalization and payslip publication. Define cancellation/correction behavior; finalized records require a traceable correction rather than silent edits.
5. Employee access to their own published payslips and private documents, with ownership checks on downloads as well as pages.
6. Payment export/reconciliation as a separate status: generating a payslip does not prove payment. Reuse existing document/storage functionality.
7. One authoritative bank-detail workflow with controlled edits and masked display. The current masked label is display metadata, not verified bank instructions.

Do not guess statutory deductions, tax rates, eligibility or jurisdiction-specific rules from the current fields. Country, policy, provider and calculation requirements must be established before implementing that engine. This does not block fixing snapshot persistence.

## Attendance and leave

Verify employee submission, manager/HR review, balances, cancellation and reporting against the same records. Approved leave and attendance exceptions need clear dates/statuses and should feed downstream payroll only through an explicit reviewed process. Preserve the existing policy and self-service features, replacing prototype actions individually.

## Verification standard

For each delivered slice, check browser action, API authorization, persistence after reload and database evidence using synthetic records. Include failure and ownership checks where relevant. Remove only records created by the verification. Record completion separately from this plan in `brain.md`.
