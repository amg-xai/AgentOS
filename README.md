# AgentOS

A local work environment for role-specific AI agents, persistent missions,
shared memory, tools, artifacts, and human approvals.

## Current status

The backend provides validated agent/role discovery and a persisted mission/task
engine with dependency handling, retry, cancellation, version checks, and event
history. Three Developer agent definitions and an injectable execution contract
are available. No model providers or executable tools are connected yet; task
actions currently record lifecycle changes rather than running agents.

## Development

- Read [AGENTS.md](AGENTS.md) and [ARCHITECTURE.md](ARCHITECTURE.md).
- Build and review one milestone at a time, with tested, coherent commits.
- Store local credentials in ignored environment files, never in Git.

The proposed stack is Python/FastAPI with SQLite and React/TypeScript.
Desktop packaging follows a working local web application.

See [validation evidence](docs/validation.md) for the verified scope and runtime.

## Run locally

From the repository root, with Python 3.11 or newer (PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e "./backend[dev]"
.\.venv\Scripts\python.exe -m uvicorn agentos.api.app:create_app --factory --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000/docs for API documentation. Available read-only
endpoints: `/health`, `/agents`, `/agents/{id}`, `/roles`, `/roles/{id}`.
The health response identifies the current capability as `discovery`.
Keep the service on loopback: authentication and remote operation are not built.

By default, the API loads `packages/` relative to the working directory. Set
`AGENTOS_PACKAGES` to an absolute manifest directory when starting elsewhere.
Invalid manifests fail application initialization rather than loading partially.

Mission state and events are stored in `.agentos/agentos.sqlite3`, which is
Git-ignored. Set `AGENTOS_DATABASE` to use another database path. The service
opens/closes connections per operation and keeps completed outputs after restart.

## Mission lifecycle API

Use the interactive API documentation to POST the sample in
[developer-mission.json](docs/examples/developer-mission.json) to `/missions`.
The response includes task states and a mission `version`. Then POST actions to
`/missions/{mission_id}/tasks/{task_id}/actions`, supplying the current version:

```json
{"expected_version": 1, "action": "start"}
```

Complete a running task with `action: "complete"` and an `outputs` object, or
record a failure with `action: "fail"` and an `error` string. Use `action: "retry"`
on a failed task before starting it again. Every successful action increments
the mission version. Read the returned version before the next action; stale
versions return HTTP 409. Only tasks with completed prerequisites can start.

GET `/missions`, `/missions/{id}`, and `/missions/{id}/events` to inspect persisted
work. POST `{"expected_version": <current version>}` to `/missions/{id}/cancel`
to cancel unfinished tasks. See [workflow semantics](docs/workflows.md).

`wait_approval` records a waiting state. Approval decisions and resumption are
not implemented yet, and the API cannot bypass that waiting state. This backend
milestone is not the complete autonomous Developer workflow or Mission Control UI.

## Verify

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests
.\.venv\Scripts\python.exe -m ruff check backend
.\.venv\Scripts\python.exe -m ruff format --check backend
.\.venv\Scripts\python.exe -m mypy --config-file backend/pyproject.toml backend/src
```

Role manifests list agents and tools; agent manifests declare schemas,
permissions, instructions, and optional provider configuration. See
`packages/developer/` for examples. Schemas use Draft 2020-12 and local fragment
references only. Provider configuration may reference an environment variable
name, never an inline credential. Permissions here are metadata; actual tool
dispatch must enforce authorization when tool execution is implemented.
