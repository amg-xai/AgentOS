# Architecture

Status: agent registry, role loading, IO validation, persisted mission/task
lifecycle, and a local API implemented. Tools, orchestration, action approval,
memory retrieval, and clients are planned.

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
version checks reject stale mutations; a transaction writes the snapshot and all
events together. Schema version 1 is initialized atomically, and unsupported
versions fail initialization. Repository connections close after each operation.

Mission status is derived from task states. Failure blocks downstream tasks;
retry refreshes their readiness while preserving completed work. Cancellation
terminates unfinished tasks. WAITING_APPROVAL is persisted, but there is no
decision/resumption endpoint yet. A restart restores recorded state without
automatically executing or recovering a worker. Introduce a durable worker
before claiming background execution survives process restarts.

## Provider and integration strategy

Model providers implement an execution interface; role manifests reference
configuration, never secrets. Start with deterministic test executors, then
connect a real provider explicitly. Do not label test fixtures as AI execution.
There is no existing LangGraph code to reuse; evaluate it when orchestration
requirements are implemented. Slack and Jira remain optional adapters.
