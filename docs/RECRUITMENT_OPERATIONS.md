# Recruitment operations batch — 21 September 2026

Open **RMS → Operations** after signing in as administrator, HR, or recruiter.

## Manual checks

1. **Duplicate review:** use two test applications with the same email. Mark Same person, refresh, then Undo. Both applications must remain intact. This saves a reversible identity decision; it does not destructively merge applications.
2. **Talent pools:** create a test pool, add a candidate, choose their recorded contact preference, then refresh. Remove membership and confirm the candidate still exists.
3. **Other matching roles:** select a candidate with saved skills and compare the listed published jobs. Optional AI analysis compares up to five chosen jobs and consumes provider credits only after confirmation.
4. **Reports and activity:** choose a period and create a report with AI unchecked. It should save without an AI call. Change a test candidate's stage and refresh metrics; new transitions should appear. Historical transitions are not invented.
5. **Recruitment costs:** record a test expense for a job. Check the currency-specific total, void the entry, and confirm it disappears from the total while remaining in history. These are entered expenses, not a complete accounting ledger.
6. **Work queue:** click Check current work. Overdue feedback, failed screenings, and applications Unassessed for more than seven days can appear. Repeating the scan must not duplicate items. Resolving the underlying condition resolves its open item on the next scan.
7. **Scheduling:** select a real Hirava interviewer account for a test round. Try an overlapping round for that same account: it must be rejected. Adjacent slots should work. This checks recorded Hirava reservations only; it cannot see Google/Microsoft calendars or older unreserved interviews.

`RECRUITMENT_OPERATIONS_ENABLED=true` enables a scan every 60 seconds. It does not call an AI, send emails, post jobs, retry paid screenings, or change hiring decisions. Manual scanning is available when disabled.

## Client scope: implementation boundaries

The selected scope has 12 agents. The following is a capability map, not a claim that all 12 are complete.

| Selected capability | Available foundation | Remaining end-to-end work |
| --- | --- | --- |
| Hiring conversion improvement | Stage snapshots, newly recorded transitions, application-to-hired timing | Complete historical cohorts and validated conversion analysis |
| Multi-platform job poster | Hirava careers publication; saved destination preparation and explicitly manual listing/closure tracking (see JOB_DISTRIBUTION.md) | Approved platform access, destination adapters, automatic publish/update/close delivery, refresh and provider metrics |
| CV screening | Existing resume extraction, OCR, screening and evidence review | Manual acceptance tests on representative resumes and provider outputs |
| Job matching | Saved-skill rediscovery and optional AI comparison to chosen roles | Broader semantic retrieval at scale and acceptance validation |
| Passive candidate finder | No external sourcing adapter in this batch | Approved source, access credentials where required, source import and verification workflow |
| Duplicate detector | Exact contact/fuzzy-name suggestions, reversible reviewed identity links | Canonical-person consolidation if the client requires physical merging |
| Scheduling | Per-round interviewer assignment and internal overlap protection | External calendar availability, booking and meeting-provider integrations |
| Feedback collection | Per-interviewer submissions in round cards and in-app due work | Configured email reminders and delivery recovery |
| Executive report writer | Saved factual reports and optional aggregate AI narrative | Approved reporting schedule and delivery integration |
| Recruiter performance tracker | Recorded actions, stage events, expenses by currency | Agreed performance definitions, historical coverage and complete cost attribution |
| Recruitment orchestrator | Periodic detection of overdue/stalled/failed work | Configured external actions and recovery workflows; hiring decisions remain human |
| Talent pool manager | Named pools, memberships, contact preferences, review dates and role discovery | Approved outreach delivery and retention/refresh workflow |

Provider choice for optional AI uses the existing shared OpenAI/Groq configuration. Internal comparisons, duplicate checks, factual metrics, pool updates and work scans do not spend AI credits. No external outreach was sent during implementation or tests.
