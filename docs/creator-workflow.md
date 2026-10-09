# Creator workflow

Creator plans a supplied content goal into bounded outline work and a short video script,
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

New normal missions use a registered tool-free Creator planner. Creation invokes
structured planning; running the mission separately invokes its content agents.
Live calls remain disabled until explicitly authorized. Invalid planning produces
an error without creating a mission; normal mode never substitutes a fixed graph.

Configure the ignored `.env` file as described in [providers.md](providers.md).
Creator requires a Responses-compatible structured model, but no Developer
workspace configuration, Git commands, source selection, or test runner.

```powershell
.\.venv\Scripts\python.exe -m agentos doctor --workflow creator
.\Start-AgentOS.ps1
```

Choose Creator, create a mission with your brief, then run and review it as above.
Planned missions send the original goal, extracted constraints and task objectives
to content generation, with dependency-bound outline context where required.
Optional pasted sources add research before the outline and script. Workspace
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
Web/file research, images/thumbnails, rendered video, and publishing remain deferred.
Student notes/quiz are implemented separately; original PLAN.md retains the full scope.

## Optional supplied-source research

In normal mode, use **Add source** to paste labelled text before creating the
mission. No URL is fetched and no project files are discovered. All supplied
text is shared with the configured model for research, outline, and script.
The model treats source text as untrusted data. Live calls remain disabled until
explicitly authorized in the local configuration. The fixed demo rejects sources.

Sources require unique stable IDs, nonblank labels (up to 160 characters), and
nonblank bodies (up to 12,000 characters). Supply at most eight sources and
48,000 total body characters. Text whitespace and Unicode are preserved exactly.
API clients may add `sources: [{id, label, body}]` to the existing creation body;
unknown fields, duplicate IDs, and exceeded bounds are rejected before persistence.

Research produces a summary (up to 2,000 characters), one to eight evidence
items (`source_id`, exact `quote`, `interpretation`, the latter two up to 800
characters each), and up to eight limitations of 500 characters each. Each ID
must reference supplied text and each quote must match a literal substring.
These checks establish provenance, not source truth or interpretation correctness.
Invalid research fails its task and blocks outline/script execution.

The source dependency chain is research → outline → script, with optional planned
outline refinements; script also depends directly on research. Downstream agents
receive the original goal, exact sources, and bound
research fields. Script additionally receives the bound outline. Creation and run
preflight verify this graph, tool-free READ permissions, executor bindings, input/
output schemas, and mandatory final human review. Manual completion is unavailable.

At review, inspect `script.md`, `reviewed-outline.md`, `reviewed-research.json`, and
`reviewed-sources.json`. The script attempt owns all four copies. Staging and
approval verify their exact contents in addition to existing hashes, scope, attempt,
and digest checks. Acceptance records content review and implies no test outcome.
Denial followed by retry repeats only script; completed research/outline persist.
The same evidence and approval remain inspectable after restart.

## Goal-driven planning contract

New normal missions persist Creator planning contract version 1, rationale,
extracted constraints, task objectives, registered assignments and input bindings.
The original goal is preserved after the existing request normalization;
constraints are a model interpretation for human inspection. Mission Control exposes
**Inspect validated Creator plan** alongside the task/artifact/activity views.

Plans contain 2–6 tasks: one final script, one to four outlines/refinements, and
exactly one research task when pasted sources are supplied. Outline refinements
can bind a previous outline as context. Every task leads to the final script review.
Agents are selected by registered supported capabilities, including alternate IDs;
no canonical task IDs are required. Goal, constraints and objective reach each step.

The planner receives source IDs/labels, not source bodies; research and subsequent
content steps receive the exact supplied bodies. Source-backed outlines and script
bind the verified research fields, and script binds its exact final outline. Literal
quotes are verified before releasing dependents. Source research still means supplied
text only, not web discovery or independent fact checking.

Creation and run preflight enforce graph bounds, acyclic dependencies, role/capability
membership, executor availability, exact schemas, tool-free READ permissions, typed
bindings, consistent sources and one final human review. Planned tasks cannot be
manually completed. Missing executors, unsupported assignments, invalid plans and
altered persisted inputs fail before execution. Retry repeats only failed work.

All plans reuse the existing mission engine, persistence, artifacts and approval
service without a storage migration. Script review owns exact script/final-outline
copies, plus research/sources for source-backed missions. Staging and acceptance
verify the bundle contents, scope, hashes, attempt and digest. Content completion
never establishes tests passed or factual correctness. Original outline artifacts
and prior decisions remain inspectable after restart.

Saved unplanned brief/source graphs and the fixed demo retain their previous behavior.
Creator thumbnails/images, external research and live quality acceptance remain
unfinished original PLAN.md requirements; this milestone does not complete Phase 9.

`/status.workflows` exposes optional `source_research_ready` for Creator. A package
without research support can still create brief-only missions; clients omit sources
for that path. Saved brief-only missions remain inspectable and the demo stays unchanged.
