# API access model

Every protected request resolves a currently active user within the configured customer instance. Database identity, role, ownership, and module entitlement are evaluated on the server. Candidate/customer IDs in request bodies never select another instance.

| Role | Access |
| --- | --- |
| Admin | All module APIs subject to entitlement; cannot bypass separate-person approvals, assigned-interviewer/task attestation, or self-approval restrictions. Own account cannot be deactivated. |
| HR | Organization references; requisition/offer approval; conversion; workforce, leave, cases, HR notes, HR documents, learning/performance administration. No general candidate-list access. |
| Recruiter | Recruiting records, interviews, offers, RMS documents and reports. No workforce or restricted HR case APIs. |
| Manager | Requisitions for managed positions; assigned interviews; self/direct-report workforce, leave decisions, goals/reviews and learning. Own HR cases only. |
| Interviewer | Assigned interview records and own scorecards. No unrestricted candidate list. |
| Employee | Own linked worker/employment data, leave, profile changes, goals/reviews, learning, and own HR cases. |
| Candidate | Public jobs, own candidate profile/applications and approved offers. No employee, staff recruiting, scorecard, or internal disposition evidence. |

Shared policies are available to active staff accounts, excluding candidates. Notifications are recipient-only. Document upload/download currently requires the relevant staff role: recruiter/admin for RMS or HR/admin for HRMS. Employees and candidates cannot upload/download through the staff document API.

The instance administrator is a privileged business administrator in this baseline, not a restricted SaaS support operator. Production support-access controls require a separate implementation.
