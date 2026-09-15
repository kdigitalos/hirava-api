# Employee payroll snapshot progress

Verified 2026-09-12. This slice fixes employee compensation records; it does not implement a full payroll engine.

## Delivered

- Removed invented salary, deductions, net pay, tax regime, masked account and benefit enrollments from missing snapshots.
- Missing amounts are null, distinct from a recorded zero. The screen displays missing data honestly and retains decimal amounts.
- Removed inferred net-pay arithmetic from field editing. Entered snapshot values do not imply payroll approval or payment.
- PATCH validates JSON types, finite non-negative amounts and benefit lists. Explicit null clears an amount, empty text clears a text field and an empty list clears benefits.
- One parameterized PostgreSQL update merges supplied fields into the existing JSON, preserving independent compensation/benefit updates and other metadata.
- Database failures propagate as errors (503 from the payroll handler), never default payroll. Existing authentication and HR/admin write restrictions remain.
- Compensation and benefit editors cannot be opened simultaneously; save buttons are disabled while submitting. Existing custom benefit names remain available in the editor.

## Evidence

- Both TypeScript checks and production builds passed. Frontend still emits the existing Auth0 dependency-expression warning.
- `node scripts/test-payroll.cjs` from `legacy-service`: missing vs zero, decimals, clearing, malformed input, missing employee, database failure propagation and parameterized update checks passed.
- Live frontend/API tests: missing data, invalid input rejection, anonymous GET/PATCH rejection, concurrent independent compensation/benefit updates, decimal/zero persistence and explicit clearing passed.
- Browser saved gross salary 81345.67, deductions 0 and Monthly frequency. API reload and an independent RDS query confirmed these values and netPay=null. After renewing an expired preview session, the payroll screen displayed the saved decimal amount with no benefits recorded and no framework error overlay.
- Synthetic employee removed after testing; preview administrator retained. Ignored screenshot: `test-output/payroll-persisted.png`.

## Boundaries and next steps

No schema migration was needed. Existing stored values were not erased or guessed to be demo data. The INR compensation snapshot is not effective-dated salary history, a payroll run, a payslip, bank verification or tax calculation. Same-field concurrent edits still use last-write-wins; version checks and audit/approval history belong to the next compensation workflow work. Full role/ownership coverage was not re-certified by the anonymous-access checks.

See [operational workflow plan](operational-workflow-plan.md) for reviewed attendance inputs, pay periods, approval/finalization, published payslips and payment reconciliation. Continue attendance/leave verification next, while retaining the RMS consolidation backlog.
