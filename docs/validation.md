# Backend validation

## Registry milestone

Validated on Windows on 2026-10-08:

- 38 tests passed: agent discovery and membership, invalid manifests, duplicate
  ids, schema and permission validation, defensive registry copies, API routes
  and errors, execution inputs/outputs, and executor failure propagation.
- Ruff lint and formatting checks passed across 16 Python files.
- Mypy strict checks passed across 11 source files.
- A Uvicorn server bound to 127.0.0.1 passed HTTP smoke checks for health,
  agent discovery, and the Developer package. The temporary server was stopped.

Runtime tests used Python 3.14.7, FastAPI 0.128.0, Pydantic 2.12.5, and
jsonschema 4.26.0. Windows Application Control prevented the newly installed
Python 3.11 Pydantic extension from loading. A local isolated environment using
the existing Python 3.14 installation worked without changing security policy.
Sandbox restrictions also required runtime tests to run outside the sandbox.

GitHub Actions runs tests, lint, formatting, and type checks independently on
Linux with Python 3.11. Local results do not assert a successful hosted CI run.

This milestone verifies discovery and the injected execution contract only.
Real model execution, permission-checked tool adapters, persisted missions,
approvals, and the Mission Control client are not implemented yet.

## Mission engine milestone

Validated on Windows on 2026-10-08 using the same Python 3.14 runtime:

- All 61 backend tests passed, including the existing registry suite.
- New coverage includes full mission completion, reverse-ordered dependencies,
  cycles and invalid references, branching prerequisites, failure propagation,
  retry without repeating completed work, retained failure history, terminal
  states, cancellation, approval-state protection, and HTTP error contracts.
- Persistence tests cover reopening the database, event pagination, foreign-key
  enforcement, unsupported schema versions, optimistic concurrency, and rollback
  of both snapshots and events after an injected failure.
- Ruff lint/format checks passed across 21 Python files; strict Mypy checks passed
  across 14 source files.
- A temporary Uvicorn server and database passed a real loopback HTTP check for
  mission creation, transitions, ordered events, process restart persistence,
  and cancellation. Both server instances and the temporary database were cleaned
  up. The smoke script is a local ignored diagnostic, not a project deliverable.

The mission engine records manual task lifecycle actions. It does not run agents,
call model providers, execute tools, or resume after approval. Those features and
the Mission Control UI remain subsequent milestones. The complete product is not
yet ready for user acceptance testing.
