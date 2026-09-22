# LangGraph screening pilot

This is a reviewer-operated backend pilot, not the completed 34-agent programme.
It includes a durable queue, candidate-page screening and optional consent-based public-intake screening.
It runs real document text through the explicitly selected OpenAI or Groq provider. Tests use
synthetic provider doubles only; there is no production fallback or sample score.

## Configuration

Install from the API directory: `uv sync --extra ai --extra dev`, or
`.venv\Scripts\python.exe -m pip install -e ".[ai,dev]"`.

Add server-only settings to `.env` (never commit credentials):

```dotenv
AI_SCREENING_ENABLED=true
AI_SCREENING_PROVIDER=openai
OPENAI_API_KEY=<your-project-key>
OPENAI_SCREENING_MODEL=<approved-model-with-Responses-structured-output-support>
AI_TIMEOUT_SECONDS=60
```

For Groq instead, configure:

```dotenv
AI_SCREENING_PROVIDER=groq
GROQ_API_KEY=<your-groq-key>
GROQ_SCREENING_MODEL=openai/gpt-oss-120b
```

Groq uses its own API endpoint and key through the compatible SDK, with strict
Chat Completions JSON schema and local Pydantic/evidence validation. There is no
fallback to OpenAI when Groq fails. Results record the provider as well as model.
On 2026-09-19 a live synthetic-only Groq smoke test returned two validated findings
and needs_review (522 input / 423 output tokens); this is not a candidate accuracy
evaluation. The local provider selection is Groq. On 2026-09-19 the application
integration was enabled locally; the example configuration remains disabled by default.

OpenAI requests use `store=False`; Groq account data controls must be reviewed
separately before real candidate documents are processed.

No model is selected automatically. Establish project usage limits, approved data
handling and a reviewer before processing candidate data. A manual-rubric assessment makes
one bounded model request; automatic assessment first extracts criteria unless cached.
Neither step uses automatic paid retries. OpenAI receives `store=False`;
this is not a promise of zero provider retention. Configure provider data controls
as required. The pilot doesn't enable external tracing.

## Run

Provide a readable TXT, text PDF or DOCX resume, a JD file, and a reviewer-approved
rubric JSON. Scans need OCR first; files over 5 MB and PDFs over 30 pages are rejected.
DOCX extraction covers body paragraphs and tables, not images or headers.

Rubric format (replace these example requirements with exact passages in your JD):

```json
{
  "rubric_version": "python-developer-v1",
  "criteria": [
    {"id": "python", "description": "Python API development", "jd_quote": "Python API development", "weight": 3},
    {"id": "sql", "description": "SQL experience", "jd_quote": "SQL experience", "weight": 1}
  ]
}
```

```powershell
.\.venv\Scripts\python.exe -m app.agents.pilot --resume "resume.pdf" --jd "job.txt" --rubric "rubric.json" --allow-provider-processing
```

The command prints sensitive assessment JSON to stdout. It does not upload to S3,
write local persistent application storage, create database records or change hiring
status. If saving the output for review, use approved storage and access controls.

## Interpretation and validation

LangGraph invokes analysis, then evidence validation and deterministic scoring.
Every rubric criterion must quote the JD. Every evidenced finding must cite actual
resume text. Missing/duplicate criteria, invented quotes, refusal, incomplete output
or provider failure stop the run without a score. Unknown findings remain unknown.

Evidence coverage = weighted sum of evidenced (1), partial (0.5), and unknown (0),
divided by total rubric weight. This draft rubric formula needs HR acceptance; it
is not a measure of candidate quality or probability of success. If all findings
are unknown, the score is null. No separate resume-quality score is fabricated.
Every result requires human review; substring validation cannot prove that the model
interpreted evidence correctly. Reviewers must exclude discriminatory/non-job-related
criteria. Results contain model, response ID, input fingerprint, rubric/workflow
versions and token usage, not an invented monetary cost.

## Candidate page (reviewer-triggered)

Employment-history review is included in new assessments. See
[EMPLOYMENT_REVIEW.md](EMPLOYMENT_REVIEW.md) for evidence requirements, date precision
and the default gap/tenure thresholds. Flags never alter the score or hiring stage.

Resume profile extraction runs in the same structured provider request as assessment.
It returns source-backed first/last name, email, phone, skills, work-history excerpts and
education excerpts. Values must occur in their cited resume passages; unsupported values
and invalid contacts are discarded. Missing information stays blank. Populated fields
are never overwritten; ambiguous identity values remain for review. Work history is
stored as excerpts, not inferred dates or calculated experience.

On successful assessment the worker locks and rechecks the candidate/job, fills blank
profile fields and saves the result in one transaction. The profile records extraction
provenance; an audit event lists field names without contact values. The assessment's
source hash is updated for its own fill, while later edits still invalidate it. The staff
panel shows values, source passages and whether each field was filled or preserved.
Existing successful results need an explicit rerun for extraction; no historical backfill
or extra automatic paid request is performed. Scanned PDF and PNG/JPEG resumes now use
local OCR; see [LOCAL_OCR.md](LOCAL_OCR.md) for setup, limits and review requirements.

The candidate summary contains three short entries: supported requirements, partial
evidence to clarify, and requirements not established by the resume. It is composed
from validated findings, with criterion references and expandable source passages,
without a separate provider call. It does not infer missing skills or make hiring
recommendations. New assessments persist the summary; compatible older results get a
display summary on read without database changes. Stale results and their summaries
remain hidden. This is a job-specific evidence summary, not a complete career biography.

Provider evidence uses numbered passages from the extracted resume. The model selects
passage IDs and the backend copies the original passage into the saved findings, avoiding
model transcription errors. Unknown IDs fail validation; source-presence validation and
human review remain required. A real passage can still be semantically irrelevant, so
source matching alone is not proof that a skill is evidenced. Failed assessments require
an explicit staff retry; no automatic paid repair request is made.

### Automatic screening on public application

Set `AI_SCREENING_ON_INTAKE=true` and `AI_SCREENING_INTAKE_ACTOR_ID` to an existing
active Admin/HR/Recruiter in the configured customer. This identifies the accountable
automation sponsor; no login account or permission is created. Existing provider settings,
RMS access and `AI_SCREENING_ENABLED` must also be enabled. Examples default to off.

The public application form uses one required application agreement. For eligible jobs,
its visible text includes resume/JD processing for AI screening and human
review of the results. Checking this agreement and submitting sends the matching AI
consent token, so a new application queues screening without a recruiter click. There is
no separate AI checkbox. When screening is unavailable, the agreement covers only
application sharing and submission remains available for staff review. Staff can also
run an assessment from the candidate profile.

The backend intake capability remains consent-gated: eligible published jobs expose
an offer bound to the provider, model and notice version. Only a submission carrying
the valid explicit AI consent token can queue an assessment; absent, stale or invalid
consent never starts processing. Existing consent records and queued jobs are unchanged.

The candidate and ScreeningJob are saved in one transaction, with queue errors isolated
in a savepoint so a queue failure does not discard a valid application. Failures are audited
for manual review. No provider request runs in the public HTTP submission. The existing
FastAPI worker generates/reuses criteria and saves the assessment on the staff profile.
Intake audits explicitly identify an automated trigger, with no fabricated human requester.

Duplicate same-job/email submissions keep the original generic response and do not add
another queue item or alter the original application's consent. Historical applications
are not backfilled. The worker rechecks sponsor activity/role/customer, the intake switch,
provider/model consent, and source freshness before processing. Disabling the intake
switch stops queued intake work with a manual-review error; it cannot undo a provider
call already in flight. Failed/interrupted work requires staff retry. Hiring stages remain
unchanged. This uses the existing screening table and requires no new migration.

Existing per-process public-intake throttling remains; distributed abuse protection and
production provider spending limits must be established before unrestricted public rollout.

### Automatic assessment (2026-09-19)

The default candidate action is now **Assess candidate**. Confirm provider processing,
then run: the worker extracts explicit skill criteria from the saved JD, validates exact
JD quotes and unique IDs, assigns equal weights, and assesses the resume. No manual
criterion entry is needed. **Customize criteria (optional)** retains the reviewed manual
rubric workflow described below.

Automatic criteria and extraction provenance/token usage are retained in the existing
screening job JSON. A later candidate for the same customer, canonical job, unchanged
JD, provider, model and extraction version reuses criteria from a completed automatic
assessment. Resume findings are never shared. Changed JDs generate new criteria; existing
candidate results become stale. Manual overrides apply to that assessment only.
Simultaneous first assessments in separate workers can each extract criteria before a
completed result exists; this is not a central approved rubric library or a single-flight
job-level cache. No additional schema migration is required.

The first automatic run normally makes two bounded provider calls (JD extraction then
resume assessment); reuse needs only the assessment call. There are no automatic paid
retries. Empty, malformed, duplicate or unsupported JD quotes fail without scoring.
Actor access and source freshness are rechecked between extraction and assessment.
Generated criteria are **not human-approved**: review them alongside the findings before
making a hiring decision. Quote validation proves source presence, not semantic accuracy.
OCR and hiring-stage automation remain out of scope. Public-intake triggering is described above.

1. Sign in as Admin, HR or Recruiter. Open RMS → Candidates → a job → View profile.
2. In **AI candidate assessment**, select **Customize criteria (optional)** to use a manual rubric.
3. Read the saved job description. Add job-related requirements, an exact supporting
   quote from that description, weights, and a rubric version. Do not invent requirements.
4. Confirm the criteria and approved provider processing, then select **Run AI assessment**.
5. Progress updates automatically while this panel is open. You may leave and return;
   the database retains the job and result. Expand each finding to inspect its quotes.
6. Review evidence before any manual hiring-stage change. The agent never changes that stage.

A description shorter than 50 characters, such as "good", cannot be assessed: update
the job with its actual requirements first. Resumes are read from private S3 into memory
(public intake PDFs or tenant-owned user uploads). No local file persistence or arbitrary
URL fetching is used. Scans still require OCR; old unsupported resume links need re-uploading.

GET/POST `/api/candidate/{id}/assessment` enforce RMS roles and tenant ownership.
The worker rechecks actor access and source changes, saves provider provenance and
quoted evidence, and hides outdated results after profile/JD edits. Duplicate pending
requests and identical successful requests reuse the existing assessment. Failed jobs
require a manual retry; interrupted work expires after 15 minutes without automatic
provider resubmission. Individual requests may already have incurred provider usage.

The worker runs inside FastAPI, so no third local terminal is needed. Install the `ai`
extra and apply migration `f582be093dc1` before enabling the feature. This migration
extends `0d761da3b892`, the active DEV database branch; the repository also has a
pre-existing separate job-reference migration branch. Do not blindly stamp or replay
that branch against existing imported/native tables. The screening migration adds only
`screening_jobs` and its indexes; it does not rewrite candidate data.

Assessment rubrics are reviewed per run and saved with that result. A centrally approved
per-job rubric library, reviewer sign-off workflow,
OCR and the remaining client agents are not implemented in this change.

Before rollout, evaluate representative approved resumes against HR-labelled evidence
and review model accuracy, failed extractions, latency and token costs. Automated
tests validate mechanics, not model accuracy.

References: https://developers.openai.com/api/docs/guides/structured-outputs
and https://docs.langchain.com/oss/python/langgraph/graph-api
