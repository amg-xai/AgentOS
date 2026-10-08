# Architecture

Status: proposed; implementation has not started.

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

Use SQLite initially, keeping transactions around state changes and associated
events. Persist failures so retry and restart are observable. Introduce a durable
worker before claiming background execution survives process restarts.

## Provider and integration strategy

Model providers implement an execution interface; role manifests reference
configuration, never secrets. Start with deterministic test executors, then
connect a real provider explicitly. Do not label test fixtures as AI execution.
There is no existing LangGraph code to reuse; evaluate it when orchestration
requirements are implemented. Slack and Jira remain optional adapters.
