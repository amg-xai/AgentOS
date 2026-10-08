# Architecture

Status: registry, role loading, persisted missions, explicit orchestration,
result approvals, artifacts, tool contracts, and a local API implemented.
Production model/tool adapters, workspace memory, and clients are planned.

## Boundaries

- **Core domain:** agent and tool definitions, role manifests, missions, tasks,
  dependency validation, states, permissions, approvals, and events.
- **Application services:** orchestration, context retrieval, artifact handling,
  retries, cancellation, and approval/resume operations.
- **Adapters:** SQLite repositories, filesystem artifacts, model providers,
  local Git, and optional external services.
- **API:** FastAPI exposes application services to local clients.
- **UI:** React/TypeScript Mission Control consumes the API.
- **Desktop:** Electron shell after the local web workflow is verified.

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
frontend/              # Added when API-backed workflows are usable
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
Scratch directories isolate patch targets from source files; they do not provide
OS process isolation. See [local workflow details](docs/local-workflow.md).
