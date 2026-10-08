# AgentOS

A local work environment for role-specific AI agents, persistent missions,
shared memory, tools, artifacts, and human approvals.

## Current status

The first backend milestone provides validated agent/role discovery, three
Developer agent definitions, and an injectable execution contract with schema
validation. No model providers or executable tools are connected yet. Agent
definitions describe capabilities; they do not claim to perform AI work.

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
