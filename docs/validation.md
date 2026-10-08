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

## Review bundle and bundled sample verification

The Developer review result now owns both `tested.diff` and `test-report.txt`.
Approval integrity checks therefore cover the tested patch directly. A damaged
tested patch blocks acceptance while still allowing denial. Mission Control
identifies the review attempt and covered artifacts, and opens the bound patch
instead of an earlier task's proposal.

The bundled Calculator project is covered by an integration check: reproduce
its two failing tests, generate a controlled test patch through mocked model
transport, execute all three tests successfully in scratch, restart, approve,
and verify the original sample remains byte-for-byte unchanged. This is model
transport test evidence, not a live AI acceptance result.

Local startup diagnostics (`python -m agentos doctor`) check manifests, provider
configuration, permissions, Git, selected source, test runners, and referenced
client assets without contacting a model, running tests, or creating runtime
databases. Tests cover missing/invalid settings, absent runners, malformed
manifests, escaping/remote/missing assets, credential redaction, `.env` loading,
and CLI exit codes. Live model verification is deferred at the user's request.
Hosted backend checks now cover both Linux and Windows.

The current suite passes 151 backend tests locally (two symlink skips on this
Windows account) and nine React component tests. The client additionally fetches
current approval artifact metadata when those artifacts are outside the first
history page, with a regression test confirming they can still be inspected.
Backend lint/format/types and frontend production build/format checks pass.

## Mission history continuity

Mission Control now pages through artifact history and polls activity after its
last loaded event instead of repeatedly displaying only the first 1,000 events.
Previously inspected review artifacts remain available after acceptance, including
artifacts fetched outside the first page. Refresh responses are ordered so a
delayed older request cannot replace a newer mission revision; successful refreshes
clear transient connection errors without clearing action failures.

Thirteen React component tests pass, including 101-artifact and 1,001-event
histories, inspection after acceptance, overlapping refreshes, and connection
recovery. TypeScript, production build, and formatting checks pass. These are
JSDOM checks; live provider and browser acceptance remain deferred/unverified.

## Explicit offline Calculator demo

The approved demo uses deterministic investigation/patch generation, registered
local tools, and the existing durable engine. It is selected only by `--demo`
(`-Demo` in the PowerShell launcher), with separate `.agentos/demo/` data and
persistent UI/artifact labels. Model configuration is ignored; no live model
request is made or claimed.

- 165 backend tests pass locally; three symlink tests are skipped because this
  Windows account cannot create symlinks. New coverage includes the actual
  three-test Calculator pass, restart/approval, memory, source/config/history
  preservation, denial/retry, review integrity, viewer permissions, fixed mission
  restrictions, sample fingerprint failures before startup/creation/execution,
  ignoring valid and malformed provider settings, storage redirect rejection,
  explicit CLI factory selection, and read-only demo diagnostics.
- Sixteen React/JSDOM tests pass. Demo coverage verifies the fixed read-only
  mission goal, no missing-provider block, persistent labels through review and
  reload, separated memory messaging, viewer controls, and clearing the previous
  mission selection when switching server execution modes.
- Backend Ruff lint/format and strict Mypy (Windows and Linux definitions),
  frontend TypeScript/Vite build, and Prettier checks pass.
- The actual PowerShell launcher was run on loopback port 8767. An HTTP/API smoke
  created the scripted mission, checked the actual three-test pass and eight
  artifacts, and saved an artifact reference. After stopping and restarting the
  launcher, the same review was accepted to COMPLETED and persisted artifacts,
  memory, source files, and normal configuration/history hashes were verified.
  Both smoke servers were stopped afterward; the ignored demo history is kept
  for local inspection. The smoke script and review proposal remain Git-ignored.
- `python -m agentos doctor --demo --json` passes all local prerequisites and
  explicitly reports `live_provider_verified: false`.

The offline workflow is available for user testing. Browser visual, responsive,
and accessibility verification is still outstanding; the prior browser access
restriction was respected. Live AI quality and full product acceptance remain
separate from scripted workflow evidence. Scratch execution is not an OS sandbox.

## Artifact delivery and keyboard navigation

Mission Control offers a download link for the currently selected, verified
artifact, using its original filename and the existing integrity-checked API.
The link is available to viewers and is hidden while content is loading or an
integrity error is shown. Downloading records no approval and applies no patch.

Mission detail tabs now provide roving focus with Left/Right wraparound, Home/End,
and associated labelled panels. Eighteen React/JSDOM tests pass, including keyboard
focus and panel associations, viewer downloads, selection changes, and suppression
of download links after artifact integrity failure. TypeScript/Vite and Prettier
checks pass. These checks do not establish browser or screen-reader acceptance.

## Creator package and role selection

Validated on Windows on 2026-10-09:

- 179 backend tests pass; three symlink tests are skipped on this Windows account.
  Creator coverage includes exact provider dependency inputs without workspace
  enrichment, bounded output, durable artifacts/memory and restart, denial/retry
  preserving the completed outline, replay/cancellation rejection, tamper detection
  for both reviewed files, viewer restrictions, and per-role readiness. Provider
  requests use mocked transport. Demo tests block model HTTP client construction
  with hostile live settings present and verify source/normal-state preservation.
- Twenty React/JSDOM tests pass. Creator coverage exercises both workflow selectors,
  readiness without Developer setup, normal and fixed-demo creation, script-first
  review, downloads, memory references, denial/retry, acceptance, and reload. It
  checks that content review displays no test-pass badge; earlier Developer,
  history pagination, integrity, viewer, and keyboard checks remain passing.
- Ruff lint/format passes across 52 Python files; strict Mypy passes across 35
  source files with Windows and Linux platform definitions. TypeScript/Vite
  production build and frontend Prettier checks pass.
- The actual PowerShell demo launcher passed a loopback HTTP/API smoke on port
  8767: Creator reached review with five labelled artifacts, then accepted the
  same bound result after process restart. Artifact references and memory persisted,
  existing Developer demo history remained available, and normal database/config
  and sample source hashes were unchanged. Both smoke servers were stopped;
  diagnostic scripts/logs and demo data remain ignored.
- `doctor --demo --workflow creator --json` passes all local prerequisites and
  reports `live_provider_verified: false`. Creator diagnostics skip Developer
  source/Git/test-runner requirements in normal mode.

Creator offline interaction is ready for user testing. Live AI quality remains
deferred and browser visual/responsive/screen-reader acceptance remains unverified;
the prior browser restriction was respected. No research, media generation,
publication, Student workflow, or desktop packaging is claimed.
