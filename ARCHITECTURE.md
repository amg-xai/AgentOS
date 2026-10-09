# Architecture

Status: registry, role loading, persisted missions, explicit orchestration,
result approvals, artifacts, scoped local tools, a configurable model adapter,
workspace memory, and React Mission Control are implemented. Live provider and
browser acceptance verification remain outstanding.

Opted-in normal Creator missions use Creator planning version 2: script preparation
followed by a registered graphic-layout agent and local PNG rendering. The same
orchestrator stages the image, frozen rendering receipt and exact bound text for
human review. Acceptance verifies stored evidence without rerendering. Default
Creator v1 plans and fixed demos retain their contracts. Developer v2/v3 test-result
semantics remain guarded by role. See [Creator workflow](docs/creator-workflow.md).

Normal Developer creation now uses a registered tool-free planner and validated
capability routing. [Bounded planning](docs/developer-planning.md) compiles into
the existing mission engine; it does not introduce another workflow runtime.
Planning evidence persists with mission snapshots and audit events. New Developer
tested results require explicit passing outcomes before human acceptance.

New normal Developer plans use version 3 with deterministic baseline tests and
separate baseline/patched outcomes and a tool-free registered local Issue Agent.
The issue binds investigation/baseline evidence; patch and testing use that same
structured proposal. Final review owns the exact baseline report, patched report,
tested diff and JSON/text issue copies. Issue output is checked against its frozen
artifacts before downstream dispatch, review and revision. V3 review also binds
goal/scope/planning/task definitions through a digest. Suggested reproduction and
criteria do not prove test success or coverage. Saved Developer v1/v2 plans and
the offline preset retain their contracts; no storage migration is introduced.

An explicitly selected offline Calculator demo reuses the same mission, tool,
and approval services with scripted generation and actual local tests. Its
databases, memory, artifacts, and scratch work live under `.agentos/demo/`.
Normal startup never falls back to demo execution. Demo source fingerprints and
its fixed goal prevent canned responses from being used for another project.
The same explicit demo also offers fixed Creator outline/script fixtures with
persistent provenance and no test execution for content missions.
Student adds a fixed notes/quiz fixture in the same isolated demo history.

## Boundaries

- **Core domain:** agent and tool definitions, role manifests, missions, tasks,
  dependency validation, states, permissions, approvals, and events.
- **Application services:** orchestration, context retrieval, artifact handling,
  retries, cancellation, and approval/resume operations.
- **Adapters:** SQLite repositories, filesystem artifacts, model providers,
  local Git, and optional external services.
- **API:** FastAPI exposes application services to local clients.
- **UI:** React/TypeScript Mission Control consumes the API.
- **Desktop:** checkout-based Electron shell with an owned loopback backend;
  standalone packaging and native renderer acceptance remain outstanding.

Domain code must not import service-specific SDKs or the HTTP/UI layer.
Agents and workflows share the same execution and persistence infrastructure.

## Proposed layout

```text
backend/
  pyproject.toml
  src/agentos/
    domain/
    services/
    adapters/
    api/
  tests/
packages/              # Versioned role and agent manifests
frontend/              # React/TypeScript Mission Control, served at /app/
docs/
```

## Execution contract

A mission owns dependency-linked tasks. The orchestrator runs ready tasks
through registered agents and permission-checked tools. Inputs include selected
memory and upstream outputs. Each meaningful transition persists with an audit
event. Approval decisions authorize a specific action and payload; resuming must
not repeat completed work. Artifacts reference durable files or structured data.

SQLite stores versioned mission snapshots and ordered audit events. Optimistic
version checks reject stale mutations; a transaction writes the snapshot, events,
artifact metadata, and approval records together. Schema 2 adds durable run
claims, approvals, and artifacts; migration from schema 1 preserves missions and
history. Unsupported versions fail initialization. Connections close after each
operation. Claim checks and mutations share the same immediate transaction.

Mission status is derived from task states. Failure blocks downstream tasks;
retry refreshes their readiness while preserving completed work. Cancellation
terminates unfinished tasks. Explicit runs claim a mission, execute ready tasks
sequentially through ExecutorRegistry, validate resolved IO schemas, and persist
each step. Input bindings reference outputs of direct dependencies.

Review-required results are staged in WAITING_APPROVAL with an immutable digest
covering outputs and artifact references. ApprovalService validates the current
version, task attempt, digest, and artifact integrity before completing the task.
It never reruns the executor or grants permission to an external tool. Denied
results fail and can be retried only explicitly.

Normal version-2/3 Developer missions may explicitly replace a patch after human
denial of failed tests, with at most two cycles. A revision service validates the
current denied attempt and exact evidence, then atomically records bounded history
and reopens patch/testing through the existing version/claim-checked repository.
The same orchestrator revalidates retained evidence before claiming work and supplies
untrusted feedback plus the prior diff to the registered patch executor. Source,
test recipe, goal, constraints and graph remain unchanged. Execution requires a
separate run, and replacement results require fresh passing-test human approval.

Artifact files have generated ids and content hashes; filenames are metadata,
not user-controlled paths. Files are written and flushed before metadata commits.
Confirmed uncommitted files are removed on failure; ambiguous files are retained
for recovery. A crash can leave an orphan file, but it must not delete a committed
artifact. There is no automatic artifact garbage collector yet.

Interrupted runs retain their durable claim. Admin recovery requires the exact
claim token, current version, and explicit acknowledgement that the old worker
has stopped and potential side effects have been checked. It marks running tasks
failed and revokes the old claim; it does not retry or execute work. This is a
local single-server design, not a distributed worker lease system. No exactly-once
side-effect guarantee or autonomous background recovery is claimed.

## Provider and integration strategy

Model providers implement an execution interface; role manifests reference
configuration, never secrets. Start with deterministic test executors, then
connect a real provider explicitly. Do not label test fixtures as AI execution.
There is no existing LangGraph code to reuse; evaluate it when orchestration
requirements are implemented. Slack and Jira remain optional adapters.

The Responses adapter is an external integration with bounded transport and
strict structured output validation. The Developer executor composes it with
registered local tools rather than granting a model arbitrary filesystem or
shell access. Workspace configuration selects source files and test argv arrays.
An immutable per-mission source snapshot and explicit notes live in a separately
versioned workspace database. This leaves mission schema 2 and its history intact.
Workspace schema 2 additively stores resolved per-mission test recipes, atomically
frozen with the source snapshot and linked by integrity digests. Version-2 retries
use stored scope, argv, runner paths, and deadlines after settings changes. This
does not freeze dependencies, binaries, host state, or test intent.
Scratch directories isolate patch targets from source files; they do not provide
OS process isolation. See [local workflow details](docs/local-workflow.md).

Creator is a separate manifest package with a tool-free planner and three content agents. Its graph binds
the outline output into the script task and requires review of the script plus
an exact copy of the outline used. The executor sends supplied content and bound
planning/dependency context to the structured generator, without project-file or memory enrichment.
Optional pasted sources add a research task and bound evidence to the existing
graph. Exact quotes are checked before task completion; final review owns sources,
research, outline, and script copies. See [Creator workflow](docs/creator-workflow.md).
It uses the existing mission schema, artifact store, approval integrity checks,
and retry/recovery services. No additional database migration is required.

New normal Creator missions use bounded capability-driven planning (contract version 1)
and compile into the same Mission/TaskSpec/InputBinding engine. Role-aware preflight
keeps Developer v1/v2/v3 test boundaries intact. Creator plans support one to four
outline/refinement tasks, optional supplied-source research, and one final script
review. Bound task references resolve exact final evidence without canonical IDs.
Goal/constraints/objectives persist and reach execution; planning sees only source
IDs/labels. Legacy graphs and fixed demos retain their contracts. No live calls are
enabled by this change. See [Creator contracts](docs/creator-workflow.md).

API startup binds executors separately from manifest discovery. `/status` exposes
readiness for each installed supported workflow; its legacy `workflow_ready`
field still describes Developer. Creator needs provider configuration in normal
mode, but no Developer source/test configuration. Invalid Developer workspace
settings are reported without preventing Creator from starting. Workflow-specific
diagnostics are available through `doctor --workflow creator`.

Student follows the same tool-free adapter pattern: supplied study material flows
to notes, then dependency-bound notes flow to a structured multiple-choice quiz.
Strict schemas bound question count, four choices, answer indices, and text lengths.
The executor renders separate questions and answers; final review owns `quiz.md`,
`answer-key.md`, and the exact `reviewed-notes.md` used. It adds no source or memory
enrichment and needs no Developer workspace/test configuration. Existing mission
schema 2, retries, artifact integrity, and approval services remain unchanged.
`doctor --workflow student` checks its prerequisites without contacting a provider.
Optional time-budgeted planning adds a registered tool-free Focus agent after quiz.
For this graph, final review moves to study_plan and owns six exact content/settings
copies. Graph/schema/permission preflight, strict question validation, aggregate time
and reference checks, staging, and acceptance reuse the existing engine and stores.
Legacy notes/quiz and fixed demo graphs remain unchanged; no migration is needed.
See [Student workflow](docs/student-workflow.md).

New normal Student creation compiles bounded goal-driven planning contract version 1
into the same engine. Registered notes/quiz/Focus capabilities allow alternate agent
IDs and notes refinements; explicit settings alone opt into Focus. Original goal,
constraints, objectives and settings reach every step. Preflight and actual output
validation enforce bindings, same final notes for quiz/Focus and one final content
review. Binding-resolved exact three-/six-file bundles reuse existing approvals.
Saved legacy graphs and demos remain supported. Mission decomposition is distinct
from Focus's study-effort artifact; neither completion nor approval implies tests
passed or exam readiness. Live calls stay gated; no migration or new engine is added.

## Desktop lifecycle

The Electron main process spawns the selected Python environment directly and
verifies a per-launch identity in `/status` before loading `/app/`. The identity
is supplied explicitly by the private desktop CLI, not by ordinary web startup;
it is not authentication. `/status.active_runs` reports this server's executing
run count without exposing claim tokens. No HTTP shutdown endpoint exists.

Parent stdin EOF requests graceful Uvicorn shutdown. Git tools and configured test
processes use closed stdin so they cannot inherit the desktop control channel.
The shell bounds startup/shutdown waits and cleans up only its owned process tree.
It does not retry/recover interrupted work or change result approvals. Normal/demo
storage paths and existing migration/recovery semantics are preserved.

The renderer uses an ephemeral session, sandboxing, context isolation, disabled
Node integration, existing server CSP, and exact local request/navigation policies.
It receives no privileged preload bridge. Popups, webviews, device permissions,
and remote requests are refused. Verified local artifact downloads use a native
save prompt. The first desktop release is a checkout launcher; see
[desktop setup and acceptance](docs/desktop.md).

## Workspace read projection

`GET /overview` combines a read-only SQLite projection with installed manifest
agents and a separate current-server active-run count. A single read transaction
streams mission snapshots, reuses the domain's derived status, and retains bounded
review/task summaries. Approval/claim/artifact counts and the ten most recently
recorded artifact metadata entries come from the same persisted snapshot.
No schema migration, claim token, task IO, provider setting, or artifact body is
added to this response. Reading cannot execute or mutate work.

Recorded task activity is scoped to installed agent ids; historic missions remain
in workspace totals even if an agent was removed. Durable claims and persisted
RUNNING states do not establish worker liveness. The frontend labels snapshot
age/failures and rejects obsolete refreshes across pagination and mode changes.
See [overview semantics](docs/mission-control.md) for bounds and read-cost limits.

Mission history's existing array endpoint supports optional goal, role, and state
filters before pagination. Filtered reads stream snapshots in the existing stable
creation-time/id order, reuse domain status, and use literal Unicode case-folded
goal matching. Historic roles need not remain installed. Unfiltered reads keep the
existing SQL LIMIT/OFFSET path. The UI invalidates obsolete requests and keeps
filter/page state separate from workflow selection and workspace-wide totals.
