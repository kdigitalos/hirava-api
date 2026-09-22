# Employment history review

The existing structured assessment request now extracts explicitly listed jobs,
internships and contracts with exact employer, role and date strings plus resume
passage references. No separate provider call is made. Unsupported entries are
discarded. This validates source presence, not semantic correctness; recruiters
must check the original resume, especially when OCR was used.

The backend calculates review flags, separate from the evidence score and hiring
status. Defaults are a possible gap of at least six complete uncovered months between
listed roles and completed employment periods spanning fewer than six calendar months.
These numeric thresholds are product defaults, not requirements supplied by the client.
Short roles may be planned contracts or internships and are not adverse recommendations.

Version 2 suppresses short-tenure warnings when every role in the grouped period has
an explicitly source-backed Intern/Internship or Fixed-term label in its role title.
Those entries retain their titles, durations and evidence in the neutral timeline.
A generic Contract title alone does not establish a planned fixed term; unrelated
internship words elsewhere in a source passage do not classify the role. Labels
outside the extracted title are not classified by this conservative first rule.
Mixed periods with other role types retain the review prompt. Gap wording explicitly
describes time between listed roles, not proof of unemployment, and mentions education.
Saved assessments get these display rules on read without changing stored evidence,
the assessment date, score, stage, or making another provider request.

Supported date forms: named English month/year, YYYY-MM, YYYY/MM, MM/YYYY and valid
ISO YYYY-MM-DD. Year-only, two-digit years, missing, ambiguous, reversed and future
dates remain unknown. Present/Current/Ongoing/Now must be explicitly in the source;
ongoing roles use the recorded assessment date and are not flagged as short tenure.
Month counts describe calendar months touched, not exact days of service.

Overlapping and adjacent roles at the same named employer are merged for tenure
checks. If that employer also has unclear dates, short-tenure calculation is suppressed.
All known employment intervals are combined for gap checks. If any extracted entry
has uncertain dates or an unsupported entry was discarded, gap analysis is marked
incomplete and no gap flags are created. No gap is inferred before the first listed
job or after the last job. Missing work history is not proof of no experience.

Results are retained in screening_jobs.result.employment_history, including source
quotes, thresholds, assessment date and related entry indices. No migration is needed.
Older assessments can be explicitly rerun to add this feature; no automatic backfill,
rejection or outreach occurs. The UI exposes the timeline, source passages and prompts
for clarification, without asserting that gaps are unexplained or problematic.
