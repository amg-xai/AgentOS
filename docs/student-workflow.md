# Student workflow

Student turns supplied study material into concise notes and a multiple-choice
quiz with a separate answer key. Review the bundle, download the files, and save
references using the same mission/history/memory features as Developer and Creator.

## Offline walkthrough

Install dependencies and build the client using [getting-started.md](getting-started.md).
From the repository root:

```powershell
.\.venv\Scripts\python.exe -m agentos doctor --demo --workflow student
.\Start-AgentOS.ps1 -Demo
```

Use `.venv-runtime` for diagnostics if your launcher selects that environment.
Open [Mission Control](http://127.0.0.1:8000/app/):

1. Choose **Student** in **Workflow**, select **+ New mission**, and create the
   fixed stacks-and-queues demo. Its brief includes all the source facts.
2. Select **Run mission**. Notes complete, then the quiz task pauses at review.
3. Select **Inspect artifacts** to open `quiz.md`, which contains questions and
   four choices per question. Attempt them before selecting `answer-key.md` for
   the correct choices and explanations. Use **Download** to save each file.
4. Inspect `reviewed-notes.md`, the exact notes used by this quiz attempt. The
   earlier `notes.md` remains in history. Review covers the quiz, key, and notes copy.
5. **Accept result** records review and completes the mission. **Deny result**,
   **Retry task**, then **Run mission** generates a new quiz attempt while keeping
   the completed notes and earlier artifacts.
6. Save an artifact reference to memory. Stop with Ctrl+C and restart with `-Demo`
   to inspect the same mission, artifacts, review, and saved reference.

All six demo artifacts have persistent fixture labels, including per-task
`offline-demo.txt`. Student performs no model calls, research, software tests,
scoring, or independent correctness verification. There is no test-pass badge.
Developer and Creator demo histories remain in the same `.agentos/demo/` directory.
Normal history/configuration and sample source are preserved. Demo startup still
requires the unchanged bundled Calculator sample; custom briefs need normal mode.

## Normal execution

New normal missions first invoke a registered tool-free mission planner, then
validate and persist its bounded task graph. Creation plans work; **Run mission**
separately executes content tasks. Live calls remain disabled until explicitly
authorized. Invalid planning returns an error without persisting a mission;
normal mode never substitutes a fixed graph or demo result.

Configure a Responses-compatible structured model through the ignored `.env` file
as described in [providers.md](providers.md). Student needs no Developer workspace,
Git commands, selected source files, or test runner configuration.

```powershell
.\.venv\Scripts\python.exe -m agentos doctor --workflow student
.\Start-AgentOS.ps1
```

Choose Student and include the topic, learning goal, and source material in the
study brief. Planning receives the brief, registered capability catalog and explicit
optional time settings. Execution receives the original goal, extracted constraints,
task objectives and bound notes/quiz context. Workspace
memory is available for saving references but is not added to Student prompts.
Normal mode never substitutes demo fixtures.

The brief is bounded to 8,000 characters and notes to 24,000 characters. The quiz
contains 3–8 questions, each with a prompt of up to 600 characters, exactly four
choices of up to 240 characters each, an answer index from 0 to 3, and an
explanation of up to 1,000 characters. Invalid output fails the current task before
writing its artifacts. Explicit retry preserves already completed notes.

## Review, API, and limits

POST `{"goal": "Study goal and source material"}` to `/workflows/student`.
Use existing mission run, task retry, cancellation, artifact, memory, and approval
endpoints. `/status.workflows` reports Student readiness; legacy `workflow_ready`
continues to describe Developer. Viewer access permits inspection and downloads,
while creating, running, retrying, cancelling, and reviewing require Operator/Admin.

Approval binds the quiz, key, and notes copy to the task attempt, content hashes,
and immutable digest. Tampered files and stale/replayed decisions are rejected.
Acceptance records review of the study material; it does not independently verify
facts, grade answers, or establish exam readiness. Questions and answers are
separate artifacts for convenient study, not an access-control boundary.

Live AI quality remains deferred. Browser visual, responsive, and screen-reader
acceptance remains unverified. Interactive answering/scoring, independent research,
calendar scheduling and standalone Electron packaging remain deferred.
Optional bounded study planning is described below.

## Supplied-source research and summarization (v2)

In normal Mission Control, select Student and **Add source** to paste labelled
study material separately from the original goal. Nonempty sources select Student
planning contract v2. Goal-only creation, saved v1 plans, legacy missions and the
fixed offline demo retain their existing contracts. The demo rejects custom sources.
Normal mode never falls back to scripted content, and live calls remain disabled
until explicitly authorized. Source-backed model quality has not been live-tested.

POST to `/workflows/student` with `goal`, optional `study_settings`, and
`sources: [{id, label, body}]`. Source bounds match Creator: at most eight sources,
160-character labels, 12,000-character bodies and 48,000 total body characters.
IDs must be unique; text must be nonblank. Whitespace and Unicode are preserved.
Only source IDs/labels go to the planner; exact bodies go to execution steps.
No websites or files are opened, and memory is not implicitly added to prompts.

The registered sourced planner selects capabilities and objectives for 4–8 tasks:
one Research/Study, one Summarizer, one to four notes/refinements, one quiz, and
Focus only when explicit settings are supplied. All tasks lead to one human review.
Creation and run preflight validate role membership, tool-free READ permissions,
executor schemas, graph bounds/dependencies, typed bindings, original goal,
constraints, exact sources and settings. No canonical agent/task IDs are required.

Research records a summary, limitations and 1–8 evidence items with source IDs,
literal quotes and interpretations. Quotes must occur in the supplied source.
The structured study summary has 1–8 topics, each with nonempty, unique one-based
references into research evidence. Notes reference summary topics; each quiz
question has its own references into topics covered by the bound notes. Unknown,
duplicate, out-of-range or missing references block execution. These checks establish
traceability; they do not prove that interpretations, notes or answers are correct.

Intermediate tasks own frozen `sources.json`, `research.json`, `study-summary.json`,
`notes.md` and `notes-provenance.json` as applicable. Before downstream execution
and acceptance, retained outputs must still match their scoped immutable artifacts.
The final quiz or Focus attempt adds these five files to its existing result bundle:

- `reviewed-sources.json`
- `reviewed-research.json`
- `reviewed-study-summary.json`
- `reviewed-notes-provenance.json`
- `reviewed-quiz-provenance.json`

There are eight final review files without Focus, eleven with Focus. The notes
provenance lists one-based summary topic indices; quiz provenance has one such list
per question. Follow summary topics to research evidence and then literal source
quotes. The final attempt owns every reviewed copy. Approval binds the original
goal and plan definitions through a digest as well as attempt, outputs, artifact
references, exact content and hashes. Changed evidence or stale decisions are
rejected. Deny/retry reruns only the final task, preserving completed upstream
work and earlier attempts. Restart preserves plans, evidence and approvals.

Automated acceptance exercises actual React against an isolated real HTTP backend
with injected model transport: source-form validation, capability assignments,
research/summary/notes/quiz with and without Focus, artifact inspection, explicit
approval and restart before/after acceptance. Invalid research blocks downstream
tasks and produces no approval. This validates the offline integration contract,
not genuine AI quality, native browser rendering or exam readiness.

## Optional bounded study planning

In normal mode with planning support, select **Include a study plan** before
creating a Student mission. Set available study minutes (10–240) and maximum
minutes per session (10–60), both whole numbers. Defaults are 60 and 25 minutes.
No budget or deadline is inferred from your brief. The fixed demo retains its
existing notes/quiz scenario and rejects custom settings.

API clients may POST this body to `/workflows/student`:

```json
{
  "goal": "Prepare stacks and queues using these supplied facts: ...",
  "study_settings": {"total_minutes": 60, "max_session_minutes": 25}
}
```

Omitting `study_settings`, or passing null, requests notes/quiz without Focus.
`/status.workflows` exposes optional `study_planning_ready` for Student.
Packages without the Focus agent or its supported executor contracts keep ordinary
notes/quiz creation available; opted-in requests fail before persistence.

The opted-in chain is notes → quiz → Focus, with Focus also directly depending
on the same final notes as the quiz. Planned notes refinements can precede quiz.
The original goal and time settings persist as task inputs.
Focus receives the bound notes and structured questions without project, memory,
or web enrichment. Quiz is intermediate content in this graph; the single final
human review covers the complete study bundle. Old missions retain their original
quiz review boundary. Neither completed intermediate tasks nor acceptance establish
correctness, elapsed study effort, software test outcomes, or exam readiness.

The Focus agent proposes a nonblank summary (up to 1,000 characters), 1–12 study
blocks, and up to eight limitations of 500 characters each. Blocks use review_notes,
practice_quiz, or recall; each has a nonblank objective of up to 500 characters,
5–60 whole minutes, and 1–8 unique one-based quiz references. All referenced questions
must exist and every supplied question must be covered. Each block fits the original
session limit and the summed durations cannot exceed the original total budget.
This validates proposed effort and references, not semantic coverage or fact quality.
Time-budget failures are recorded with fixed messages, without raw model content.

At the final review, inspect the current attempt's six owned files:

- `study-plan.md`: readable proposed effort and original time settings.
- `study-plan.json`: structured planner output.
- `reviewed-study-settings.json`: exact time settings.
- `reviewed-notes.md`: exact notes used.
- `quiz.md`: questions and choices.
- `answer-key.md`: answers and explanations for those same questions.

Staging and acceptance verify exact contents against persisted evidence in addition
to existing scope, attempt, hashes, version, and approval digest checks. Missing or
tampered evidence cannot be accepted. Viewer can inspect and download but cannot
mutate. Denial/retry repeats only the planner, preserving completed notes/quiz and
prior evidence. Upstream failures block planning until explicitly retried. Restart
preserves the same settings, content, and review records.

The plan suggests sequential effort; it creates no timer, calendar entry, reminder,
grading record, or automatic background work. Research remains future roadmap work.
Live model calls stay disabled until separately authorized; implementation verification
uses injected transport and does not establish real model quality. Original PLAN.md
and the full Developer/Creator/Student scope remain unchanged.

## Goal-driven mission planning contract

The mission planner decomposes work; Focus produces a study-effort artifact. They
are separate registered capabilities. New normal missions persist Student planning
contract version 1, rationale, extracted constraints, task objectives, assignments
and typed input bindings. **Inspect validated Student plan** exposes that evidence.
Constraints are model interpretations for human inspection, not proof of compliance.

Plans contain 2–6 tasks: one to four notes/refinements, exactly one quiz, and one
Focus task only when explicit time settings are supplied. A notes refinement may
bind one earlier notes output as context. All tasks lead to one final review: quiz
without Focus, otherwise Focus. Goal, constraints, objective and exact settings
(or explicit null) reach every step. Prose mentioning an exam/deadline does not
authorize inferred settings. Equivalent registered agent IDs are supported.

Compilation and run preflight enforce bounds, unique IDs, acyclic dependencies,
role/capability membership, supported exact schemas, executor availability,
tool-free READ permissions, bound dependency outputs, consistent original inputs
and mandatory final review. Focus and quiz must bind the same final notes. Actual
nonblank notes and strict quiz values validate before releasing dependents. Managed
tasks cannot be manually completed. Unsupported graphs fail before execution claims.

Final quiz review owns exactly the questions, answer key and bound notes copy.
Final Focus review owns the existing six-file bundle. Both staging and acceptance
compare exact expected contents resolved through bindings, plus existing scope,
hash, attempt, version and digest checks. Content completion never means tests
passed, facts were independently checked, or the user completed study.

Saved unplanned notes/quiz/Focus missions and fixed demos retain their previous
contracts. Denied final results require explicit retry/run and fresh approval;
completed upstream work, artifacts and prior decisions persist across restart.
No storage migration, workflow engine, web/file/memory enrichment, scoring,
scheduling or publication is added. Research/summarizer capabilities and genuine
live acceptance remain unfinished original-roadmap work.
