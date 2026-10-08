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

## Orchestration, approval, and artifact milestone

Validated on Windows on 2026-10-08 using the established Python 3.14 environment:

- 100 tests passed; one symlink test was skipped because this Windows account
  cannot create symlinks. Linux CI exercises that test.
- End-to-end fixture workflows validate dependency IO binding, staged diffs,
  approval/denial, resume without duplicate execution, retries with new approvals,
  durable artifacts, restart persistence, and replay/stale-digest rejection.
- Safety tests cover manual review bypass, cross-mission artifact references,
  corrupted files, Viewer/Operator/Admin enforcement, request-header impersonation,
  concurrent runs/decisions, claim revocation, and interrupted-run recovery.
- Storage tests cover migration from actual schema-1 snapshots/events, migration
  rollback, failed result/decision transactions, a claim/manual-write race, and
  retaining committed artifact files after an ambiguous commit outcome.
- Tool tests verify input/output schemas, user and agent permissions, disabled
  high-impact dispatch, mandatory audit recording, and persisted running-task
  audit scope without raw inputs, provider secrets, or claim tokens in event details.
- Ruff lint and formatting passed across 34 Python files. Strict Mypy passed
  across 23 source files.
- A temporary loopback HTTP server passed execution, staged diff download,
  process restart, approval, downstream resume, and artifact checks. Its factory
  explicitly injected test executors; it is an ignored diagnostic. Both server
  instances and temporary data were cleaned up afterward.
- The runtime core commit passed [GitHub Linux checks](https://github.com/amg-xai/AgentOS/actions/runs/37812533574).

No real model provider or production tool is connected by default. Review accepts
an immutable staged result; it does not authorize an external/destructive action.
High-impact tool dispatch remains disabled. The product still needs a real local
Developer workflow, workspace memory, and Mission Control before acceptance testing.

## Local Developer workflow and Mission Control

Validated on Windows on 2026-10-08:

- 135 backend tests passed; two symlink tests were skipped because this account
  cannot create symlinks. Provider transport is mocked; filesystem reads, Git
  patch checking/application, subprocess tests, SQLite persistence, and result
  approvals run against real local adapters.
- Coverage includes immutable source snapshots, source preservation, restart,
  memory retrieval, provider failure and retry, denial, path/command restrictions,
  timeouts, output limits, child credential removal, corrupted snapshots, unknown
  workspace schemas, browser-origin/Host rejection, JSON-only writes, client
  asset serving, and non-overwriting sample setup. Earlier migration, recovery,
  concurrency, and approval integrity tests remain passing.
- Eight React component tests passed in JSDOM. They exercise configuration and
  connection states, viewer controls, creation failures, memory, a complete
  create/run/inspect/accept flow, denial/retry, and artifact integrity failures.
  Artifact contents are rendered as text rather than executable HTML.
- TypeScript compilation, Vite production build, Prettier checks, backend Ruff
  lint/format checks, and strict Mypy passed. Mypy was also checked with Linux's
  platform definitions. The backend runtime is Python 3.14.7 locally; hosted
  backend checks continue to use Python 3.11 on Linux.
- The provider and scoped-workflow commits passed hosted backend CI. Separate
  Mission Control CI now installs the committed npm lockfile and runs component
  tests, TypeScript/production build, and formatting checks.

**Remaining acceptance evidence:** No real model credentials are configured in
this environment, so no live AI result is claimed. The browser security policy
denied opening the loopback app; no alternate browser or policy workaround was
used. JSDOM tests do not replace browser visual, responsive, or accessibility
verification. Complete the real-provider and browser walkthrough in
[getting-started.md](getting-started.md) before declaring the product acceptance
ready. Scratch execution is not an OS sandbox; external integrations, remote
auth, Electron packaging, and semantic embeddings remain outside this milestone.
