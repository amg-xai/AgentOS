# Registry milestone validation

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
