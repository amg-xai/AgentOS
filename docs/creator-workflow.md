# Creator workflow

Creator turns a supplied content brief into an outline and a short video script,
then pauses for human review. It uses the same mission engine, durable history,
artifacts, memory references, and approval checks as Developer.

## Try the offline scenario

Install dependencies and build the client using [getting-started.md](getting-started.md).
From the repository root in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m agentos doctor --demo --workflow creator
.\Start-AgentOS.ps1 -Demo
```

Use `.venv-runtime` for diagnostics if the launcher selects that environment.
Open [Mission Control](http://127.0.0.1:8000/app/):

1. Choose **Creator** in **Workflow**, select **+ New mission**, and create the
   demo mission. The brief is fixed to an introduction to the Calculator demo.
2. Select **Run mission**. The outline completes, then the script pauses at review.
3. Select **Inspect artifacts** to read `script.md`. Inspect `reviewed-outline.md`
   for the exact outline used by that script attempt. Use **Download** to save
   either verified file. `outline.md` remains in the earlier task's history.
4. **Accept result** records acceptance and completes the mission. **Deny result**
   fails the script task; **Retry task**, then **Run mission** generates a new
   script attempt without repeating the completed outline.
5. Save an artifact reference to memory. Stop with Ctrl+C and restart with `-Demo`
   to inspect the same mission, artifacts, review decision, and note.

The outline/script are labelled fixtures. Each task also writes `offline-demo.txt`.
No model calls, research, fact-checking, tests, images, or video production occur
for this content mission. Creator displays no test-pass badge. Existing Developer
demo missions coexist in `.agentos/demo/`; normal history/configuration and the
bundled sample are preserved. Demo startup still requires the unchanged bundled
Calculator fixture. Custom briefs require normal mode.

## Use a configured model

Configure the ignored `.env` file as described in [providers.md](providers.md).
Creator requires a Responses-compatible structured model, but no Developer
workspace configuration, Git commands, source selection, or test runner.

```powershell
.\.venv\Scripts\python.exe -m agentos doctor --workflow creator
.\Start-AgentOS.ps1
```

Choose Creator, create a mission with your brief, then run and review it as above.
Only the supplied brief and generated outline are sent to the model. Workspace
notes can store artifact references but are not automatically added to Creator
requests. Briefs are limited to 8,000 characters and generated outline/script
fields to 24,000 characters each. Invalid output fails the current task; retry
explicitly after correcting the cause. Normal mode never substitutes demo fixtures.

Acceptance binds the script and reviewed outline to their attempt, content hashes,
and immutable approval digest. Corruption or stale/replayed decisions are rejected.
Viewer access permits inspection/download but cannot create, run, retry, or approve.
Acceptance records content review; external publication and sending are unavailable.

## API and limits

POST `{"goal": "Your content brief"}` to `/workflows/creator`. Use the existing
mission run, retry, cancellation, artifact, memory, and approval endpoints.
`/status.workflows` lists installed supported workflows with readiness, steps,
context notice, and optional fixed demo goal. The legacy `workflow_ready` field
continues to describe Developer; clients should use per-role readiness for Creator.

Live provider acceptance remains deferred. Automated provider tests use mocked
transport, and the offline scenario verifies interaction rather than AI quality.
Browser visual, responsive, and screen-reader acceptance remains unverified.
Research, images/thumbnails, rendered video, publishing, and Student are deferred.
