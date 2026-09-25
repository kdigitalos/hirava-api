# Job distribution — 23 September 2026

Implemented preparation and manual listing tracking, not automatic external delivery.
Open **Job Openings → a job → Job distribution**. Existing job names, approval and
publication controls remain unchanged. Administrator/recruiter can prepare and record;
HR can read. Other roles cannot use these endpoints. All records are tenant-scoped.

## Manual test

1. Open an approved job. Select LinkedIn and Indeed and click **Prepare selected**.
   Both should say **Prepared · not sent**, while their connection badge remains
   **Not connected**. Refresh; the saved content remains. Repeating preparation does
   not create duplicate records or change the version of identical content.
2. Expand **Posting preview** and use **Copy posting**. It contains only the saved
   public job fields; internal budget, recruiter identifiers and custom internal
   fields are excluded. No AI credits are used. Review the destination's requirements
   before pasting; platform-specific formatting and validation are not implemented.
3. Publish the job using the existing Hirava Publish action. The careers card should
   show **Published on your careers page** with **View job**. An approved but unpublished
   job must not display a working careers link. Local HTTP application URLs are omitted
   from copied postings; production requires a public HTTPS address.
4. After manually publishing a real listing on the selected platform, enter its HTTPS
   listing URL and click **Record manual posting**. This only records the recruiter's
   report; Hirava does not contact or verify the board. An unrelated-domain URL is rejected.
5. Close the Hirava job. A recorded live external listing should show a closure-needed
   warning. Closing Hirava does NOT close external listings. After closing the external
   listing yourself, click **Record manual closure** and confirm. Refresh to verify.
6. Try the same actions as HR (read-only) or another tenant (not found), and try saving
   stale versions from two tabs (409 conflict). Unknown destinations are rejected.

Use synthetic test records for local acceptance; do not create public sample jobs.

## Technical scope

Migration `f744bc06` adds `job_distributions`, one row per job/destination, saved public
content, recruiter-reported state, external URL, timestamps and optimistic version.
Audit events record preparation and manual status changes. Existing audit history is
retained when a closed destination is prepared again. No candidate data is exported.
API: `/api/job-distribution/jobs/{job_id}`, `/prepare`,
`/{destination}/manual-status`. Credentials are not collected by this panel.

No automatic publishing, updating, closing, refreshing, delivery worker, provider
receipt, board view/application metrics or source-attribution integration is included.
These cannot be represented as working integrations merely by adding destinations.
Client-approved account/API access and platform contracts must be confirmed first.
LinkedIn restricts posting APIs to approved developers/partners:
https://learn.microsoft.com/en-us/linkedin/talent/apply-connect/create-apply-connect-jobs
Indeed Job Sync integration obligations are documented at:
https://docs.indeed.com/legal-terms/job-sync
Naukri and Monster/foundit integration specifications must be supplied/verified with
the client's contracted provider; no undocumented endpoints or automated browser posting
are assumed. Automatic periodic reposting must follow each destination's rules.

Next integration phase: select an approved provider, implement tenant-specific secure
credentials, destination-specific payload validation, durable idempotent delivery,
provider receipt/status polling, update/close reconciliation and failure recovery.
Only call a posting live once the provider confirms it. Do not reset client jobs or
send external postings during tests without a concrete approved target.
