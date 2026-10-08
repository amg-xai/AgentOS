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

Configure a Responses-compatible structured model through the ignored `.env` file
as described in [providers.md](providers.md). Student needs no Developer workspace,
Git commands, selected source files, or test runner configuration.

```powershell
.\.venv\Scripts\python.exe -m agentos doctor --workflow student
.\Start-AgentOS.ps1
```

Choose Student and include the topic, learning goal, and source material in the
study brief. Only this brief and generated notes are sent to the model. Workspace
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
acceptance remains unverified. Interactive answering/scoring, research, citations,
scheduled study sessions, focus planning, and Electron packaging are deferred.
