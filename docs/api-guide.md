# Local API and runtime reference

Detailed lifecycle, configuration and review examples preserved from the repository README. Start with the [quick start](../README.md#getting-started) or [full setup guide](getting-started.md). Generation remains disabled under the ₹0 budget; these examples do not authorize model calls or external actions.

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
[developer-mission.json](examples/developer-mission.json) to `/missions`.
The response includes task states and a mission `version`. Then POST actions to
`/missions/{mission_id}/tasks/{task_id}/actions`, supplying the current version:

```json
{ "expected_version": 1, "action": "start" }
```

Complete a running task with `action: "complete"` and an `outputs` object, or
record a failure with `action: "fail"` and an `error` string. Use `action: "retry"`
on a failed task before starting it again. Every successful action increments
the mission version. Read the returned version before the next action; stale
versions return HTTP 409. Only tasks with completed prerequisites can start.

GET `/missions`, `/missions/{id}`, and `/missions/{id}/events` to inspect persisted
work. POST `{"expected_version": <current version>}` to `/missions/{id}/cancel`
to cancel unfinished tasks. See [workflow semantics](workflows.md).

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
{
  "expected_version": 7,
  "decision": "approve",
  "payload_digest": "<digest returned by the approval endpoint>"
}
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
[runtime semantics and recovery](workflows.md) before recovering an
interrupted run. Offline continuous acceptance is automated for all three
profiles. Real-model acceptance remains unvalidated and generation stays disabled.

## Manifest configuration

Role manifests list agents and tools; agent manifests declare schemas,
permissions, instructions, and optional provider configuration. See
`../packages/developer/` for examples and the [agent contract](agents.md).
Schemas use Draft 2020-12 and local fragment references only. Provider
configuration may reference an environment variable name, never an inline
credential. Registered tool dispatch enforces user and agent permissions and
records scoped audit events.
