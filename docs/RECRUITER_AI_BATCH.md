# Recruiter AI drafting batch

## Unified interview feedback (2026-09-21, latest)

The separate Individual interviewer feedback assignment section has been removed.
Create Interview and Schedule next round now offer an account checkbox picker in
place of free-text Panel Members. Saving the interview/round creates its feedback
tasks in the same transaction. Pick at least one interviewer. New form-created
tasks default to 24 hours after the selected local interview date/time (or 24 hours
from now for a past interview). Reminder times are stored as timezone-aware UTC.

Responses, submitted counts, due reminders and Change interviewers are grouped
inside L1-L4 cards. Give / edit my feedback opens only that round's tasks for the
signed-in account. Existing saved round feedback retains View/Edit controls.
Historical text-only panel names/numbers are not guessed into accounts: use Select
interviewers in an existing round once. Submitted responses are preserved when
changing reviewers; removed pending reviewers are cancelled. Repeated saves reuse
existing tasks. Existing manually assigned tasks appear in the same round cards.

Manual test: create an interview or schedule a next round, select yourself and
optional other staff accounts, then save. The round card should immediately show
its feedback tasks without a separate assignment action. Open Give / edit my
feedback, submit notes, return and Refresh interviewer feedback. Check that the
submitted count increases. Existing saved L1-L3 feedback should still be readable.
Use Change interviewers to update a panel and verify saved responses remain.
Scheduling retains the existing invitation-email behavior; automatic feedback
reminder emails remain disabled. AI drafting behavior is unchanged.

Earlier separate-panel instructions below are historical and superseded by this flow.

## Shared Hirava AI interface

All three drafting tools are inline on their pages; there is no AI side panel.
Generation uses a shared animated activity indicator and moving highlight with
actual request/status text, without percentages or simulated processing stages.
Draft results fade in once when received. Reduced-motion settings disable these
animations. Assessment and saved-skill matching share the same activity treatment.

**Edit draft** enables local changes without AI costs; **Generate again** makes
another paid request using the current inputs. Original source cards remain
available and labelled as original evidence after edits. **Apply draft to job
description** fills/highlights the job field and moves focus to it; normal Save
is still required. Copy and Discard remain available. Leaving/reloading loses
unsaved drafts, so copy anything you want to preserve first.

Candidate assessment leads with coverage, criteria counts and a summary. Employment
and extracted profile details expand below it. Queued/processing text reflects
backend status. Existing-candidate recommendations remain labelled saved-skill
matching, without a model call. Provider behavior and access controls are unchanged.

Three first-version workflows from the client's agent document are available together:

1. **Job-description writer:** Job Openings > New job/edit draft > AI job description
   draft. Enter title, brief and tone, confirm processing and Generate draft. Review
   missing details, then Use in job description and save through normal job controls.
2. **Interview questions:** Interviews > job > Interview Details > Interview question draft. Select
   Initial/Technical/Final (defaults to the latest scheduled round), confirm and generate. Uses the current job description and
   saved skills, work experience and education; no additional resume download/OCR.
3. **Feedback summary:** same Interview Details page > Interview feedback summary. Requires saved
   interview feedback; shows referenced reviewer statements, agreements/disagreements
   and open questions. Empty feedback fails before any provider request.

All use AI_PROVIDER and its model/key from the shared providers module. Set
AI_RECRUITER_TOOLS_ENABLED=true to enable; default false. One bounded structured
request per click, no fallback or SDK retry. A per-user in-process guard prevents
simultaneous generations within this API process; it is not a distributed spend cap.
No live paid request was required to implement or test this batch.

Only Admin/HR/Recruiter with RMS access can call the endpoints. Candidate/job and
feedback reads are tenant scoped. Profile/feedback source changes during generation
discard candidate drafts. Returned references must exist in supplied sources; this
checks source presence, not semantic accuracy. Human review remains necessary.
Audit records contain provider/model/token counts and resource IDs, not draft text or
feedback content. Drafts remain in the page until navigation/reload; copy to preserve.
Only explicitly using a JD draft followed by normal Save persists the job description.
No candidate stage changes, publication, messages, invitations or feedback edits occur.

Limits: title200 chars, brief12000, candidate source total40000 chars, at most20 feedback
records, model output4000 tokens and rendered draft20000 chars. Errors are safe and
generic; unsupported model/access/quota requires manual correction/retry.

## Manual acceptance batch

- Draft a Python developer JD from confirmed details. Check it adds no invented salary
  or benefits; insert into the form and save as draft.
- Open an interview for a candidate with saved skills and generate Technical questions. Expand Supporting
  source; verify personalization refers only to supplied evidence.
- On an interview whose candidate has no feedback, summary should explain that feedback is required.
- Add two synthetic feedback records through existing interview workflows. Generate
  a summary and verify opinions are attributed and disagreements retained.
- Reload: unsaved drafts disappear, but saved JD and original feedback are unchanged.
- Test both configured providers separately; changing .env requires an API restart.

## Remaining client scope

These are useful drafting slices, not completion of three entire client agents.
JD market salary intelligence is not implemented. Automatic pre-interview
dispatch and guaranteed non-repetition across rounds are pending.
Individual panel submissions, completeness counts and in-app reminder due dates are
now available (see the latest batch below). Automatic email reminders and dashboards
remain pending. No automated interview scoring or hiring recommendations are introduced.
Persisted history for JD/summary drafts, distributed rate/cost limits and
real-provider/user acceptance are follow-up work. Question history is available.

Interview tools were moved off candidate profiles. Candidate assessment stays there.
The interview response supplies candidateId (never the interview route ID); components
reset when interview/candidate/initial round changes. Feedback summary covers all
saved rounds for that candidate application, not only the selected round.

## Interview workflow batch (2026-09-21)

Interview Details now offers **Save [round] questions** after generation. Edit the
draft first if needed. Saved versions persist in interview_question_sets, with
interview/candidate/customer, saving staff member and timestamp. Identical saves
for the same round reuse the existing version. New text adds a version; history
shows the latest 50, with plain-text display and Copy. Saving/history uses no AI
credits and remains available independently of AI provider configuration. Saved
text is staff-reviewed draft content, not verified AI provenance; original source
quotes are not copied into this history. Interview deletion removes its history.

The feedback section shows four round slots and which are scheduled, submitted,
or awaiting feedback. **Add feedback** and **Edit feedback** open the existing
staff form directly. **View feedback** opens the saved record. **Copy feedback
link** uses the /RMS/feedback/apply route and does not send a message. Current
backend supports one submission per round, not one per panel member; counts
therefore reflect round coverage, not panel completeness or overdue deadlines.
Feedback fetch failure is shown as unavailable, never as zero submissions.

Manual checks:
1. Generate questions, edit, save, then reload: saved text remains in history.
2. Save unchanged text again: no duplicate version. Save changed text: new version.
3. Add feedback to a scheduled round, save, and confirm its status changes.
4. View and edit that feedback; generate a summary from the saved records.
5. Another tenant or unauthorized role must not access saved question text.

At that checkpoint the pending items were automatic question dispatch, automated
feedback reminders, per-panel-member submissions, semantic repeat avoidance, and
saved AI summaries. The newer batch below supersedes the panel-feedback/repeat notes.
Earlier browser-only draft notes apply to unsaved drafts and feedback summaries;
saved question history is now the exception.

## Email-box AI button (2026-09-21)

Create Interview has a small sparkle icon inside the email editor frame, at the
lower right. Clicking opens an inline drafting preview, not a side panel. Add an
optional meeting link/location, confirm processing, and Draft email. Review/edit
plain text, then Use draft to replace the editor content. Insertion escapes HTML;
it does not send mail, create an interview, or overwrite until explicitly applied.
The existing Create action retains its existing interview/email behavior.

Drafting uses the selected candidate/job (server ownership checked), supplied form
schedule in browser timezone, company/type/platform/duration and optional joining
details. It does not send resumes or feedback to this drafting endpoint. Missing
time/date/timezone/joining information is flagged; generated wording still needs
human review. Context changes reset the preview so an old candidate's draft cannot
be applied to a newly selected candidate. Drafting uses shared provider/model and
request guard, no automatic paid retries. No new database migration required.

Manual check: enter job/candidate and schedule, click the email-box sparkle,
generate once, review warnings, edit and Use draft. Verify text is editable in
CKEditor. Generate failure must preserve existing email; changing candidate or
schedule must clear the prior preview. Opening the icon alone uses no AI credits.

Next-round scheduling also uses the same email-box sparkle (2026-09-21 fix).
In Interview Details > Schedule next round, enter the NEW date/time/platform,
then scroll to the bottom-right of the Email editor. Draft and Use draft work
inside the scheduling dialog. Candidate/job/company come from the parent interview;
schedule information comes only from the new-round form, never the original slot.
Changing form context resets the draft preview. No backend changes or extra AI calls
are required for this integration; Add retains its existing scheduling behavior.

## Individual feedback, reminder dates and question reuse checks (2026-09-21)

Interview Details now has **Individual interviewer feedback**. Assign an active
Hirava account to a scheduled round, optionally select a local reminder due time,
then choose **Assign feedback**. The free-text Panel Members field is not an account
assignment; use this new section to identify each reviewer. Counts reflect assigned
responses, with legacy one-per-round feedback kept separately above.

Each reviewer opens `/interview-feedback` while signed in. They see only their own
tasks and can submit/edit observations (20-12000 characters), with an optional 1-5
rating. Recruiters can read the submissions but cannot submit as another reviewer.
For a one-account local test, assign your own account. Copy task link is available
for sharing manually; no message is sent by copying, assigning or submitting.

The default due time is 24 hours **after assignment**; choose a later date for future
interviews. Reminder due dates persist and become **Reminder due** when overdue;
the recruiter panel refreshes every minute, or use Refresh. Reschedule reminder
updates the deadline. Submitted or cancelled tasks have no pending reminder.
These are in-app due indicators, not email/push notifications or a background
delivery worker. Email reminders and automatic post-interview assignment remain
future work. Tasks attached to a deleted round stay detached if it is recreated.

Feedback summaries now include submitted, non-cancelled individual responses along
with legacy feedback, preserving reviewer attribution and source references. The
combined limit remains 20 records. Assignment/feedback/reminder actions use no AI
credits; explicitly generating questions or summaries uses the configured provider.

Question generation now receives saved question versions for the same interview
across all rounds and is instructed to avoid repeats. A local similar-wording check
flags possible repeats after generation; review them and edit before saving. This
does not guarantee semantic uniqueness. There is no automatic paid regeneration.
Only saved text participates; unsaved drafts and questions asked outside Hirava do
not. At most 50 versions / 30000 history characters are accepted for comparison;
larger history requires manual review. Changing history during generation discards
the result with a reload message.

Manual test:
1. Hard-refresh Interview Details. Generate Initial questions, review and Save.
2. Generate Technical questions and check the saved-version comparison notice.
3. In Individual interviewer feedback, assign yourself to L1 and set a due time
   two minutes ahead. Do not create a new interview or send an invitation for this test.
4. Open My feedback tasks; leave it pending until due and Refresh. Confirm the
   reminder appears, then reschedule it from Interview Details.
5. Submit observations and an optional rating through My feedback tasks. Refresh
   Interview Details: submitted count increases and reminder is no longer due.
6. Generate the feedback summary once; confirm it represents the submitted notes.
7. If a second staff account is available, assign it too; each account should only
   be able to submit its own task. Cancelling a pending task removes it from My tasks.

Schema: additive migration `b321de02`, table `interview_panel_feedback`; API prefix
`/api/interview-panel`. Tenant/role checks, concrete round binding and optimistic
versions protect task updates. No candidate hiring status changes are performed.
