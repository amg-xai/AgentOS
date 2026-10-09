# Backend validation

## Continuous Developer v3 UI/API validation

Validated on Windows on 2026-10-10:

- Three dedicated journeys render the actual React App in JSDOM against an
  isolated real HTTP backend, with same-origin headers and injected model
  transport. No frontend API response fixtures or live calls are used.
- Actual Calculator baseline execution runs three tests with two failures.
  Patched execution records its explicit pass/fail outcome. The UI inspects all
  five review files; both Issue copies equal their originals, and baseline/test
  reports share frozen source and recipe digests.
- Tests cover initial success, success on the second explicit patch revision,
  and exhaustion of both revisions. Failed-test acceptance and a third revision
  are rejected by the real API. Human decisions use UI controls. Real process
  restarts preserve missions, plans, artifacts, activity and outcomes; original
  source files remain byte-for-byte unchanged.
- Full checks: 616 backend tests passed, three Windows symlink cases skipped;
  119 frontend unit tests and 26 desktop tests passed, including owned backend
  process integration. Ruff lint/format, strict Windows/Linux Mypy, frontend
  TypeScript/Vite build, formatting, desktop syntax and offline wheel build passed.

The dedicated command and Linux/Windows CI are documented in
[getting-started.md](getting-started.md#continuous-offline-integration-validation).
Missing test Python is an error rather than a skip. The fixture reuses registered
agents, existing model injection, tools, storage, approvals and revisions; it is
not a production execution mode. No production contracts or dependencies changed.
Injected transport does not establish live model quality/compatibility, and JSDOM
is not native/browser visual acceptance. Original PLAN.md and the full three-role
scope remain unchanged. Live calls remain disabled pending explicit authorization.

## Developer planning evidence presentation follow-up

Validated on Windows on 2026-10-09: all 81 frontend tests passed, along with the
TypeScript/Vite production build and formatting checks. The existing plan
inspector now presents constraints, planner ID, task objectives, exact assigned
agent IDs, dependency input/output fields, and focus links to source tasks.
Regressions cover Viewer inspection without writes, inert model text, branching
input evidence, explicit tested-review requirements, and older missions without
planning evidence. Long evidence text wraps within the existing layout.

This presentation uses existing mission fields; backend execution, database,
permissions, desktop request policy, and original PLAN.md are unchanged. Live
calls remain disabled. Native/browser visual acceptance is still outstanding.

## Developer planning validation follow-up

Validated on Windows on 2026-10-09: 303 backend tests passed, with three Windows
link cases skipped. Ruff lint/format and strict Mypy checks for Windows and Linux
passed. The saved-plan regression first reproduced HTTP 500, then verified safe
HTTP 422 before a run claim when a changed manifest makes task inputs invalid.
The response omits input content; mission version, approvals, and artifacts remain
unchanged, with no model dispatch.

Two additional normal-workflow integrations cover independent investigation
branches and the eight-task limit, distinct findings/context bindings into one
patch, preserved goal/constraints, actual scratch tests, one final review, and
unchanged source files. Model transport is injected. No live provider calls were
made; provider configuration and live acceptance remain outstanding. No frontend,
desktop, graph-contract, or original PLAN.md changes are introduced by this fix.

## Bounded Developer planning milestone

Validated locally on Windows on 2026-10-09 with the existing Python 3.14 runtime:

- 300 backend tests passed; three symlink/junction cases remain skipped on Windows.
  Planning checks cover valid goal-dependent graphs, renamed registered agents,
  malformed/unsafe assignments, schemas, bindings, dependencies, executor readiness,
  pre-claim validation, preserved goal/constraints, planning failures, restart
  evidence, manual bypass rejection, and explicit test/review outcomes.
- Model transport is injected. Normal workflow tests still perform real scoped
  filesystem reads, Git patch validation/application, and subprocess test runs.
- Ruff lint/format checks passed across 64 files; strict Mypy passed across 42
  source files for Windows and Linux platform checks.
- 79 frontend tests passed, including inspectable planning evidence and acceptance
  disabled for false/missing test outcomes. TypeScript/Vite build and formatting passed.
- 25 desktop tests passed, including real owned backend process startup, review,
  restart, and preserved source/history across all three role workflows. Syntax
  and formatting checks passed.
- Diff and staged-file review exclude ignored proposals/review notes and preserve
  original PLAN.md, local credentials, and workspace configuration.

Live calls remain disabled; no live provider compatibility or model-quality
acceptance is claimed. Native/browser visual acceptance is still outstanding.
The full intended Developer, Creator, and Student scope remains in original PLAN.md.
Result Review History is deferred. See [planning contracts](developer-planning.md)
for supported shapes, evidence, approval enforcement, and remaining live acceptance.

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

## Student notes and quiz workflow

Validated on Windows on 2026-10-09:

- 201 backend tests pass; three symlink checks are skipped on this Windows account.
  Student integration tests verify exact provider inputs, separate quiz/key
  rendering, bounded schemas, invalid output before artifacts, partial failure
  and explicit retry, denial/retry preserving notes and earlier artifacts, restart,
  memory, replay rejection, cancellation, viewer enforcement, and corruption of
  each of the three reviewed files. Provider transport is mocked.
- Offline integration runs all three roles in one persisted demo history with
  model HTTP construction blocked and hostile live configuration present.
  Calculator tests execute in scratch; Student produces six labelled artifacts
  without claiming research, scoring, correctness verification, or software tests.
  Normal state, configuration, and source remain unchanged.
- Twenty-two React/JSDOM tests pass, including Student selection without Developer
  setup, fixed demo briefs, quiz-first inspection, separate answer-key download,
  memory references, denial/retry, acceptance, and reload. Existing Developer,
  Creator, history, viewer, integrity, and keyboard checks remain passing. Test
  workers are capped at two to avoid resource contention between large JSDOM
  histories; default per-test timeouts are retained, with existing scoped longer
  budgets for complete content workflows and the 1,001-event history.
- Ruff lint/format passes across 55 Python files. Strict Mypy passes across 37
  source files using both Windows and Linux platform definitions. TypeScript/Vite
  production build and Prettier checks pass.
- The actual PowerShell demo launcher passed a loopback HTTP/API smoke on port
  8767: Student reached review with six labelled artifacts, then completed after
  restart and approval of the same bound result. Artifacts and memory persisted;
  previous Developer/Creator missions remained available. Normal database/config
  and source hashes were unchanged. Both smoke servers were stopped; scripts,
  logs, and local demo history remain ignored.
- `doctor --demo --workflow student --json` passes local prerequisites and reports
  `live_provider_verified: false`. Student normal diagnostics do not require
  Developer workspace, Git, or test-runner configuration.

The offline Student workflow is ready for interaction testing. Live AI quality and
browser visual/responsive/screen-reader acceptance remain deferred/unverified. No
interactive quiz scoring, web research, study scheduling, or Electron is claimed.

## Checkout-based desktop shell

Validated on Windows on 2026-10-09:

- 210 backend tests pass; three symlink checks are skipped on this Windows account.
  Desktop coverage checks explicit normal/demo identity, Viewer enforcement,
  absence of HTTP shutdown, private EOF shutdown requests, and active-run counts
  with durable interrupted claims. Existing workflow and persistence checks pass.
- All 25 desktop tests pass, including a real owned Python/HTTP process test.
  Developer executes its Calculator tests; Creator and Student reach content
  review without claiming a test pass. All three histories, Student artifacts,
  and memory persist across restart, and the same bound approval completes.
  Normal history and sample source hashes are preserved with hostile live model
  settings present. Both owned processes stop gracefully through stdin EOF.
- Helper tests cover direct argv, occupied ports, readiness mismatch, startup
  timeout/failure, owned cleanup, crashes without restart, singleton focus,
  active/unknown-status exit choices, restricted window/session settings,
  navigation, permissions, and downloads using injected Electron adapters.
- Ruff lint/format passes across 57 Python files. Strict Mypy passes across 38
  source files using Windows and Linux platform definitions. Desktop JavaScript
  syntax and Prettier checks pass. The PowerShell launcher parses successfully.
- All 22 React/JSDOM regression tests pass across Developer, Creator, Student,
  history, integrity, Viewer restrictions, downloads, and keyboard navigation.
  TypeScript/Vite production build and frontend Prettier checks pass.
- The pinned Electron runtime is installed locally. It was not launched to
  inspect the previously restricted browser page. Linux/Windows desktop CI runs
  helper tests and the real Python process regression without opening Electron.

The desktop launcher is ready for manual offline acceptance using the
[desktop guide](desktop.md). Actual Electron rendering, native dialogs/downloads,
keyboard/screen-reader behavior, and live AI quality remain unverified. Standalone
installers, bundled Python, signing, updates, and deployment remain deferred.

## Workspace overview and recorded agent activity

Validated on Windows on 2026-10-09:

- 226 backend tests pass; three symlink checks are skipped on this Windows account.
  Sixteen new overview checks cover empty history, every task-derived mission
  status, 126 mixed-role/historic missions, bounded deterministic lists, actual
  review approval/denial/cancellation, artifact metadata, restart, Viewer access,
  secret/token exclusion, and a concurrent WAL writer during a consistent read.
  Existing active-run coverage now checks the separate overview run/claim counts
  before and after interruption without releasing the retained claim.
- 32 React/JSDOM tests pass. Ten overview checks cover global counts beyond the
  displayed page, older review/artifact mission links, Viewer restrictions,
  recorded agent activity, keyboard activation, failed/stale refreshes, obsolete
  polling responses, mode mismatches, pagination reset on mode switch, and a
  delayed creation response from the old mode. Existing three-role execution,
  bound reviews, downloads, history, memory, integrity, and keyboard tests pass.
- All 25 desktop tests pass. The real owned Python/HTTP process test now checks
  three-role overview counts and unchanged persisted summaries after restart,
  alongside the existing approval, history, source/normal-data preservation,
  and private EOF shutdown checks. Policy coverage allows GET `/overview` and
  rejects writes, other paths, and remote origins.
- Ruff lint/format passes across 60 Python files. Strict Mypy passes across 40
  source files with Windows and Linux platform definitions. TypeScript/Vite
  production build, frontend/desktop Prettier, and desktop syntax checks pass.

Workspace overview is ready for offline interaction testing using the
[Mission Control guide](mission-control.md). Reads scan stored mission snapshots,
so cost grows with history and can briefly delay SQLite writers. Native/browser
visual, responsive, and screen-reader acceptance remain unverified under the
existing browser restriction. Live model quality remains deferred.

## Memory search response ordering

Validated on Windows on 2026-10-09: all 33 React/JSDOM tests pass, including a
regression that completes an older canceled search after the current query has
already displayed its matching note. Workspace memory now discards that obsolete
success response instead of replacing newer results. TypeScript/Vite build and
frontend Prettier checks pass. This maintenance change adds no API, storage, or
provider behavior. Browser/native visual and screen-reader acceptance remain
unverified; live model testing remains deferred.

## Mission history search and filters

Validated on Windows on 2026-10-09:

- 256 backend tests pass; three symlink checks are skipped on this Windows account.
  Thirty history checks cover matching beyond the first 100 records, pagination
  after filtering, all task-derived mission states, combined/exact/historic role
  filters, Unicode case folding, whitespace, literal wildcard/regex characters,
  excluding task IO from matching, stable ties, Viewer access, retained claims and
  audit history, unchanged schema/default paging, and invalid parameter rejection.
- 39 React/JSDOM tests pass. Six history-filter checks cover explicit submission,
  global overview totals, independent workflow selection, older mission inspection,
  no matches, clearing, page reset, obsolete response suppression, failure/stale
  states, mode switching, query encoding, and keyboard submission retaining focus.
  Earlier three-role, memory, integrity, review, navigation, and refresh tests pass.
- All 25 desktop checks pass. The real owned Python/HTTP process test now filters
  Student's waiting mission by goal, role, and state, then verifies unchanged
  persisted overview after restart. Existing demo isolation, history/artifact/
  memory preservation, bound review, and private EOF shutdown checks remain passing.
  Renderer policy permits the filtered GET through the existing endpoint allowance.
- Ruff lint/format passes across 61 Python files. Strict Mypy passes across 40
  source files with Windows/Linux platform definitions. TypeScript/Vite production
  build, frontend/desktop Prettier, and desktop syntax checks pass.

History search is ready for offline interaction testing using the
[Mission Control guide](mission-control.md#search-mission-history). Filtered reads
scan history; the compatible array API does not supply an exact filtered total or
next-page token. Native/browser visual and screen-reader acceptance remain
unverified under the existing browser restriction. Live model testing is deferred.

## Artifact preview response ordering

Validated on Windows on 2026-10-09: all 40 React/JSDOM tests pass. A regression
holds an older artifact response body until a different artifact is selected and
displayed, then verifies the canceled body cannot replace the current preview.
The selected filename and download link continue to identify the current content.
TypeScript/Vite production build and frontend Prettier pass. No API, storage,
permission, or provider behavior changes. Native visual/accessibility acceptance
remains manual; live model testing remains deferred.

The overview review-order fixture now derives its tied timestamp from the latest
review created by that test, rather than assuming a fixed date remains newer than
the system clock. Both hosted backend jobs exposed this time-dependent assertion;
the correction preserves the original bounded-history and tie-order checks.

## Task dependency inspection

Validated on Windows on 2026-10-09: all 61 React/JSDOM tests pass, including 21
dependency checks. These cover unsorted branch/merge graphs, isolated roots,
stable snapshot ordering, all eight recorded task states, named prerequisites,
incomplete counts, duplicate titles, keyboard inspection, Viewer read-only access,
and explicit retry/approval refreshes without implicit execution. Missing or
malformed prerequisites, duplicate ids/edges, self-dependencies, and cycles report
an unavailable layout. Existing details and failure evidence remain inspectable.
Empty graphs have explicit copy; an iterative 10,000-task layout check verifies
deep graphs avoid recursion. Earlier three-role workflows, review integrity,
artifact downloads, memory, search, history, and response-order checks pass.

TypeScript/Vite production build and frontend Prettier pass. This frontend-only
view adds no API, storage, execution, or permission changes and uses the same
mission snapshot as task details. It is ready for offline interaction testing in
the Tasks tab; see the [Mission Control guide](mission-control.md#inspect-task-dependencies).
Native/browser visual, responsive, and screen-reader acceptance remain manual
under the existing browser restriction. Live model testing remains deferred.

## Memory read failures

Validated on Windows on 2026-10-09: all 63 React/JSDOM tests pass. Two new checks
verify a failed initial note load is labelled unavailable, and a failed search
cannot present earlier results as matches for the new query. Changing the search
after failure recovers normally. Read errors are separate from note-save errors;
canceled requests remain ignored. TypeScript/Vite production build and frontend
Prettier pass. This maintenance change preserves memory retrieval, storage, and
permissions. Native visual/accessibility and live model acceptance remain deferred.

## Memory artifact inspection

Validated on Windows on 2026-10-09: all 76 React/JSDOM tests pass. Thirteen new
checks cover on-demand multi-reference selection, notes without references,
Viewer reads without writes, escaped HTML/Markdown, recorded metadata and verified
download filename/path, keyboard preview focus and return, owner-mission navigation
outside filtered history, missing metadata/files, integrity and network failures,
and closing/reopening to retry. Delayed body/error responses cannot replace another
selection or reappear after close, search, unmount, note reload, or normal/demo
switch. Saving a new note remains the only write in the note-reload regression.
Earlier three-role workflows, result reviews, history, memory, dependency, and
refresh-order tests pass. TypeScript/Vite production build and frontend Prettier
pass. The existing backend artifact endpoint verifies content; metadata and text
must both succeed before the client exposes downloads. No API/schema, provider,
permission, or desktop capability changes were needed.

Ready for offline interaction testing in Workspace memory using saved artifact
references and the [Mission Control guide](mission-control.md#follow-saved-artifact-references).
Existing bounded lexical memory retrieval remains unchanged. Native/browser
visual, responsive, screen-reader, and download-dialog acceptance remain manual
under the existing browser restriction; live model quality testing is deferred.
