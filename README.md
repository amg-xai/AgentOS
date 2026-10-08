# AgentOS

[![Backend checks](https://github.com/amg-xai/AgentOS/actions/workflows/backend.yml/badge.svg?branch=main)](https://github.com/amg-xai/AgentOS/actions/workflows/backend.yml)

A local work environment for role-specific AI agents, persistent missions,
shared memory, tools, artifacts, and human approvals.

## Current status

The backend provides validated agent discovery, persisted missions, explicit
orchestration, scoped result review, durable text artifacts, and permission-checked
tool interfaces. Dependency outputs flow into downstream agents through bindings.
The Developer workflow now connects a configured structured model provider to
scoped source snapshots, scratch-only patch checking, and actual test execution.
Workspace notes persist with lexical retrieval. Model and workspace configuration
are explicit; the default application never silently runs test fixtures.
React/TypeScript Mission Control provides mission creation, execution history,
artifact inspection, result approval/denial, retry, and workspace memory.
The Creator package reuses that engine for a supplied brief, outline, and reviewed
video script. Student produces notes and a quiz with a separate answer key from
supplied study material. Choose Developer, Creator, or Student in the workflow
selector.

Start with the [local setup and acceptance guide](docs/getting-started.md).
Use `Start-AgentOS.ps1 -Demo` for the explicit offline Calculator walkthrough:
scripted findings/patches, real Git checks and tests, separate local history,
and human review. Select Creator for a fixed, labelled outline/script walkthrough
in the same isolated demo history. No model credentials are required and no model
calls occur.
Student also offers a fixed stacks-and-queues demo. See the
[Student guide](docs/student-workflow.md) for study bundle review and downloads.
Live AI acceptance still requires a configured model endpoint and credentials;
automated model tests use mocked transport. Browser visual verification is pending.

See [provider setup](docs/providers.md) and [local workflow scope](docs/local-workflow.md).
The [Creator guide](docs/creator-workflow.md) covers content review and its limits.

## Development

- Read [AGENTS.md](AGENTS.md) and [ARCHITECTURE.md](ARCHITECTURE.md).
- Build and review one milestone at a time, with tested, coherent commits.
- Store local credentials in ignored environment files, never in Git.

The stack is Python/FastAPI with SQLite and React/TypeScript.
The [local desktop shell](docs/desktop.md) wraps Mission Control with an owned
loopback backend. After desktop dependency/runtime setup, use
`Start-AgentOSDesktop.ps1 -Demo` to test it. Standalone packaging remains deferred.

See [validation evidence](docs/validation.md) for the verified scope and runtime.
The [workspace overview guide](docs/mission-control.md) explains global totals,
recent work, and recorded agent activity.

## Run locally

From the repository root, with Python 3.11 or newer (PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e "./backend[dev]"
.\.venv\Scripts\python.exe -m uvicorn agentos.api.app:create_app --factory --host 127.0.0.1 --port 8000
```

For the client, build `frontend/` and use the launcher in the setup guide.
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

Manual actions record lifecycle changes without running an agent. A manual
`wait_approval` is a legacy state-only operation; use orchestrated review below
to create a reviewable approval record. Reviewed tasks cannot be completed via
the manual action endpoint.

## Execution, review, and artifacts

POST `{"expected_version": <current version>}` to `/missions/{id}/run` to execute
ready tasks through configured executors. Missing configuration returns 409
without changing the mission. An execution claim prevents concurrent dispatch
and manual mutations while a run owns the mission.

Tasks can bind input fields to direct dependencies' output fields using
`input_bindings`, as shown in the sample mission. Mark a task `review_required`
to persist its result and artifacts, then pause at WAITING_APPROVAL. GET
`/missions/{id}/approvals` for pending reviews and `/missions/{id}/artifacts` for
artifact metadata. GET `/artifacts/{id}/content` to download verified content.

POST a decision to `/approvals/{id}/decision`:

```json
{"expected_version": 7, "decision": "approve", "payload_digest": "<digest returned by the approval endpoint>"}
```

Use the actual current version and digest. Approval accepts exactly the staged
result and completes that task without rerunning its executor. Run the mission
again to execute newly ready downstream tasks. Denial fails the task and blocks
dependants; explicit retry generates a new result and approval. A result review
does not authorize publishing, deployment, or any external/destructive tool.
High-impact tool dispatch is disabled in this milestone, including for Admin.

Set `AGENTOS_USER_ROLE` at server startup to `viewer`, `operator` (default), or
`admin`. This configures the single local user's access; it is not remote
authentication. Clients cannot select their role through request headers.
Keep the service on loopback and use it only from a trusted local machine.

State is migrated atomically from database schema 1 to 2. Artifacts default to
`artifacts/` alongside the database; override with `AGENTOS_ARTIFACTS`. Review
[runtime semantics and recovery](docs/workflows.md) before recovering an
interrupted run. The complete product is not yet ready for acceptance testing.

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
name, never an inline credential. Registered tool dispatch enforces user and
agent permissions and records scoped audit events.
