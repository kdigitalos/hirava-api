# Existing candidate recommendations

Publishing a requisition computes recommendations from saved RMS candidate skill
fields and records the match count/method in an audit event. The publish response
includes the matches. Recruiters, HR and admins can fetch current matches at
`GET /api/v1/rms/requisitions/{id}/recommendations`. Managers and public candidates
cannot access this pool. Drafts have a Preview matching candidates button; published
jobs load the panel automatically. Refresh recomputes using current job/profile data.

This first version is deterministic database skill matching, not semantic AI ranking.
It uses Required skills when supplied; otherwise a limited dictionary detects skill
mentions in the description, with a visible limitation. It matches bounded words and
known aliases (e.g. postgres/PostgreSQL), shows saved skill evidence and missing
matches, and never treats missing evidence as proof of missing ability. Recruiters
should supply explicit required skills for precise matching. No new provider calls,
resume downloads, automatic outreach or applications are made.

Only RMS profiles belonging to the job's customer are searched. People already applied
to the target job are excluded by normalized email. Other duplicate emails are grouped,
retaining the profile with most matching skills; records without email stay separate.
The UI shows source job/status and last-updated date. It does not infer availability.
At most the 5,000 most recently updated prior profiles are examined; a visible notice
reports truncation. Up to 20 matches are shown. Profiles without saved skills are
counted and omitted, so older unparsed resumes need extraction before they can match.
The native candidates table has no skill data and is not a source in this version.

Recommendations are computed on demand, not stored as stale snapshots. Closed jobs
do not expose matching. No schema migration is required. Published job edits are not
introduced by this feature; whenever supported job data changes, the next matching
request uses those current values.
