# Employee profile integration status

Verified 2026-09-12 against the local frontend, FastAPI compatibility gateway, private employee service and configured RDS database.

## Completed

- Admin employee Basic info saves through `PATCH /api/employees/{id}`, reloads the stored row and reports failed saves.
- Missing contact/demographic fields remain empty; display uses `Not provided` where applicable.
- Employee codes remain authoritative, without demo code rewriting.
- Profile edits preserve unrelated employee details, including bank/custom fields.
- Directory/profile department, role and location filters use returned records.
- Removed unused demo profile records and fixed the profile back-link route.

## Verification

- Frontend TypeScript check and final production build passed. Existing Auth0 dependency-expression build warning remains.
- `node scripts/test-profile-mapping.cjs` in hirava-webapp covers empty data, employee identity, retained metadata and invalid date/email/name rejection.
- Browser edited a synthetic employee email and state. A reload retained both values. An independent RDS query confirmed both values and retained code/custom metadata.
- Synthetic employee removed after verification; preview admin retained.
- Screenshot: ignored `test-output/profile-persisted.png`.

## Remaining work

This completes the Basic info persistence slice, not every HRMS/RMS screen. Payroll snapshot defaults and persistence were subsequently fixed; see [payroll progress](payroll-progress.md). Full payroll processing remains incomplete. Attendance/leave, remaining profile tabs and dashboard/demo actions still require individual verification. The admin employee record and employee self-service profile models have not been unified by this change. Auth0 remains a planned production integration; local login is still used for preview.
