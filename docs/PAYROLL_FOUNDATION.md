# Payroll foundation

Client source: Payroll Module Specification.pdf (35 pages, reviewed 2026-09-25).

## Available in this batch

HRMS sidebar -> Payroll (`/HRMS/payroll`). HR/admin can create immutable salary-structure versions with a code, name, effective date, component definitions and change reason. A code/date pair is unique per customer. Saved versions can be loaded as the basis of another version. No employee salary is assigned or changed by saving a structure.

The monthly-gross preview uses Decimal arithmetic and rounds components to two decimal places, half up. Components execute in displayed order; references may use GROSS and earlier component codes. Supported operations: numeric literals, +, -, *, /, unary signs, MIN, MAX, ROUND, CEILING, FLOOR. Percentages use division by 100. No executable Python, imports, attributes, exponentiation or arbitrary function calls. Unknown/forward references, duplicate/reserved codes, negative values, unreconciled earnings and deductions exceeding gross are rejected. Employer contributions increase configured employer cost and do not reduce the employee balance.

These are illustrative structure calculations, not statutory calculations, approved net pay, CTC certification or payment instructions. Rates are entered by the user; no tax/PF/ESI rates are seeded. The optional client-document example is not automatically loaded or saved.

API: GET/POST `/api/payroll/structures`, POST `/api/payroll/preview`, and POST `/api/payroll/structures/{id}/preview?monthly_gross=42800&as_of=2026-09-25`. The latter resolves the latest version of the same code effective on the requested date. End dates are implicit at the next version's start. No payroll runs exist yet; future payroll runs must snapshot both inputs and rules to preserve historical results when versions are added.

Migration: `python -m alembic upgrade head` adds salary_structures; existing employee snapshots are untouched. Core audit events record the actor, creation, code, effective date and change reason. Full immutable payroll audit storage/retention is future scope.

## Manual test

1. Sign in as HR/admin, open HRMS -> Payroll.
2. Click Load document example. Keep preview gross 42800.
3. Calculate preview: Basic 21400, HRA 10700, Special allowance 10700, gross 42800.
4. Add Employer contribution `EMPLOYER_COST`, formula `1000`: configured employer cost becomes 43800; employee balance remains 42800.
5. Add Employee deduction `RECOVERY`, formula `500`: balance becomes 42300.
6. Enter structure name, code `ENGINEERING`, effective date and reason; save. Reload and verify saved version remains.
7. Load that saved version, use another date and save a new version. Original components remain unchanged. Same code/date returns a conflict.
8. Change Special formula to `-1` or remove balancing earnings: preview is rejected. Change formula to an unknown code or `__import__('os')`: rejected.
9. Employee/recruiter accounts cannot list, calculate or save structures.

## Remaining specification scope

Employee assignments/history; standalone component catalog; annual CTC/basic/module-based entry; configurable rounding and conditional formulas; statutory rule master and approved rules; attendance/LOP/pro-rata/overtime; tax declarations/TDS; revisions/arrears; approval/lock/reopen/payment workflows; payroll-specific roles; contracts/milestones/F&F; payslips, bank files, reports and imports. Client states, company payroll policies, approved statutory rules and bank formats are still needed. Existing employee storage uses imported customer-isolated tables; assignment integration must respect this boundary rather than create duplicate employee records.
