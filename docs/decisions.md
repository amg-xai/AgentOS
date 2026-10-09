# Decisions and baseline

## 2026-10-08: Start from the supplied plan

Inspection of D:\AgentOS found only PLAN.md. There is no existing frontend,
backend, LangGraph runtime, test suite, or Git repository. Therefore Phase 0
application execution, baseline screenshots, and tests are not applicable yet.
No application tests have passed or failed; none exist.

Available tools: Git 2.53.0.windows.1, Python 3.11.9, and Node 24.21.0.
GitHub CLI (`gh`) is unavailable. No GitHub repository URL was supplied.

## 2026-10-08: Version history

Initialize main with the supplied roadmap, then use development branches and
small reviewed commits. Use the configured identity:
Ajitamani <ajitamani.gupta25@gmail.com>. No Codex signatures or commit trailers.
GitHub synchronization requires a remote repository and working authentication;
local commits must not be described as pushed until verified.

## 2026-10-08: First milestone proposal

Use the recommended Python/FastAPI and React/TypeScript direction. Start with
agent and role contracts and registry loading. No existing stack is present to
reuse. Defer LangGraph, vector storage, and Electron until needed. Implementation
proposals and review notes are local ignored documents rather than deliverables.

## 2026-10-08: Presentation and review material

Keep implementation proposals and review notes out of new commits. Retain
architecture, product contracts, setup instructions, and validation evidence as
project documentation. Each implementation commit must form a coherent,
reviewed milestone with relevant checks passing.

## 2026-10-08: First local product workflow

Use a configured Responses-compatible provider with strict structured outputs,
selected immutable source snapshots, and registered local tools. Keep test argv
arrays in server-side configuration; do not give models shell access. Scratch
directories protect patch targets but are not an OS sandbox. The source project
is preserved, and review accepts a result without applying or publishing it.

Store workspace notes and source snapshots in a separately versioned SQLite
database to preserve the mission database contract. Use explicit lexical memory
retrieval first. Serve the built React client from the same loopback FastAPI
origin. Keep local configuration, credentials, runtime data, and review material
ignored; commit the client lockfile, launcher, sample project, and setup guide.

## 2026-10-08: Explicit offline acceptance mode

Live model testing is deferred by the user. Add an opt-in Calculator demo with
scripted generation, real scoped Git/test execution, the existing mission engine,
and digest-bound review. Keep its history/memory/artifacts in `.agentos/demo/`
and label the UI and persisted results. Require the fixed sample goal and exact
normalized source fingerprints. Ignore live provider/storage configuration in
demo startup; never silently select fixtures when normal configuration is absent.
This supports local interaction testing without claiming live AI acceptance.

## 2026-10-09: Creator on the shared engine

Add two tool-free Creator agents for a supplied brief, outline, and short script.
Reuse the existing graph, artifact, review, and persistence services with no schema
migration. Bind approval to the script and an exact copy of its input outline.
Keep source files and unrelated workspace memory out of Creator model requests.
Expose readiness per installed supported workflow so missing or invalid Developer
workspace settings do not block content work. Retain legacy Developer status fields.

Extend the explicit isolated demo with a fixed Creator scenario and persistent
fixture labels. Content missions do not execute tests or display a test-pass badge.
Live AI verification remains deferred; research, media production, publication,
Student, and Electron remain outside this milestone.

## 2026-10-09: Student study bundle

Add two manifest-loaded, tool-free agents for supplied study material → notes →
quiz and answer key → human review. Use structured questions with bounded text,
exactly four choices, and a valid answer index, then render separate question and
answer files. Bind review to both files plus the exact input notes; retain the
existing database schema and permission/approval services.

Student normal execution requires the configured provider but no Developer source
or test runner. Add a fixed labelled stacks-and-queues scenario in explicit demo
mode without constructing a model. Preserve all three roles' histories. Review
does not establish independent correctness or exam readiness. Interactive scoring,
web research, scheduling, and desktop packaging remain deferred.

## 2026-10-09: First desktop shell

Wrap existing Mission Control with a small checkout-based Electron project rather
than another execution engine. Pin Electron 44.7.0, install its runtime explicitly,
and keep Python/backend prerequisites separate. The main process owns its backend,
checks a per-launch identity, and closes a private stdin pipe to request shutdown.
No HTTP shutdown, privileged renderer bridge, or automatic claim recovery is added.

A real Windows process test found that Git inherited the desktop control pipe and
stalled workflow execution. Git now uses DEVNULL stdin, matching configured test
processes. Keep this regression in real Python/HTTP desktop checks on both OSes.
Preserve sandbox/context isolation, CSP, local request/navigation restrictions,
native save prompts, existing RBAC, and the three role histories. Native rendering
and dialogs remain manual acceptance under the existing browser restriction.

## 2026-10-09: Read-only workspace overview

Add workspace-wide counts and bounded review/artifact/task summaries without
another state store or schema migration. Stream snapshots and reuse Mission.status
instead of duplicating its precedence in SQL. Read persisted evidence in one
transaction; accept history-proportional read cost for this local MVP.

Keep local active-run observation separate from persisted claims and RUNNING
states. Agent cards describe recorded tasks, without inferring executor readiness
or worker liveness. Open existing mission detail for inspection and integrity
checks. Prevent obsolete frontend refreshes and old-mode creation responses from
restoring earlier history. The desktop policy allows only the new GET endpoint;
existing permission, review, and process ownership boundaries remain in force.

## 2026-10-09: Search persisted mission history

Extend the existing GET `/missions` array contract with optional bounded goal
query, role id, and derived mission state filters. Match before pagination using
literal Unicode case folding and the existing domain status rules. Historical
role lookup does not depend on currently installed manifests. Keep unfiltered SQL
paging unchanged; accept history-proportional scan cost without a schema/status
cache. Explicitly submit UI filters and preserve selected mission inspection,
global overview totals, and independent workflow creation. Failed queries remain
unavailable, failed polls label retained results, and mode changes clear filters.

## 2026-10-09: Bounded goal-driven Developer planning

Implement original PLAN.md Phase 5 with a manifest-loaded tool-free planner,
declared Developer executor capabilities, and a server-validated 3–8 task graph.
Support investigation evidence chains feeding one patch and one final tested
human review. Preserve original goal, constraints, objectives, assignments, and
bindings in durable mission evidence and audit events. Reuse the orchestrator,
scoped tools, artifact store, and approvals; keep the offline preset explicit.

Reject invalid graphs, unsupported schemas/permissions, and missing executor
bindings before work. New Developer results require explicit passing tests for
acceptance; failed test evidence can be inspected and denied. Preserve old/manual
API semantics without inferring test success from completion. Disable live
transport by default until separately authorized. Defer Result Review History;
the next product proof is live vertical-slice acceptance with baseline failure,
actual patched tests, human review, and restart evidence. Original PLAN.md and
the full Developer, Creator, and Student product scope remain unchanged.

## 2026-10-09: Developer baseline and frozen test evidence

Extend new normal plans to a server-controlled version-2 contract with 4–8 tasks:
one deterministic baseline, investigation evidence, one patch, and one final tested
human review. Retain version-1 saved graphs and the explicit offline preset. Reuse
registered agents/tools, orchestrator, artifacts, and approvals. A failed baseline
is valid completed evidence; only explicit passing patched tests permit acceptance.

Atomically freeze selected source and resolved test recipes in an additive
workspace-store migration. Link recipe integrity to the source digest; retries use
stored scope, argv, runner paths, and deadlines. Send only bounded exit/outcome
summary to patch generation. Final review owns and checks exact baseline, patched
report, and tested-diff contents. Raw baseline logs stay local.

This improves offline evidence while live acceptance remains separately gated.
Frozen recipes do not freeze dependencies, binaries, host state, or test intent;
scratch remains trusted-code execution rather than OS isolation. Original PLAN.md
and the full role roadmap are unchanged; Result Review History stays deferred.

## 2026-10-09: Creator supplied-source evidence

Extend Creator with optional pasted-source research using a tool-free registered
agent. Preserve brief-only and fixed demo graphs. Source-backed missions reuse
the orchestrator, persistence, retries, artifacts, and approval service. Reject
unsupported contracts, permissions, or evidence graphs before persistence/run.
Exact quote checks release dependents only after source provenance validation;
they do not verify truth or model interpretations.

Final script review owns exact source, research, outline, and script copies.
Staging and acceptance check bundle contents, scope, attempt, hashes, and approval
digest. Source text remains exact, bounded, and inspectable after restart. Denied
script retries preserve completed research/outline. Live acceptance remains gated;
no source fetching, media production, or publication is added. Original PLAN.md
and full role scope are preserved; Result Review History remains deferred.

## 2026-10-09: Optional bounded Student study planning

Implement original PLAN.md's Focus/Study Planner as an optional tool-free manifest
agent. New opted-in missions use notes → quiz → study_plan with one final review;
legacy notes/quiz requests, saved missions, and fixed demos retain their contracts.
Time settings are explicit, strict and persisted; no deadline is inferred. Validate
session/total effort, unique valid references and full quiz-question coverage before
staging. Completion establishes content evidence, not tests or exam readiness.

Preflight enforces graph, assignments, permissions, bindings and supported schemas.
Final review owns exact notes, quiz/key, structured/readable plan and settings copies;
acceptance combines evidence comparison with existing artifact/attempt/digest checks.
Reuse current execution, persistence, retry/recovery and review services. Add no
calendar, timer, notifications, grading, research access, or database migration.
Live AI/native visual acceptance remains pending; Result Review History stays deferred
and original full role scope remains intact.

## 2026-10-09: Explicit bounded Developer patch replacement

After human denial of an intact failed-test result, normal version-2 Developer
missions allow two explicit patch revision cycles with bounded user feedback.
Reset only patch/testing in the existing graph, recording prior attempts, denied
approval, artifacts/hashes and immutable plan digest in the mission snapshot.
Reuse repository transactions, version/claim checks and audit events; no migration
or parallel workflow engine is needed. Requesting a revision does not execute it.

The registered patch executor receives the prior exact diff and untrusted feedback
alongside original goal/constraints/findings. Generate a full replacement against
the frozen source, rerun actual tests with the frozen recipe, and require a new
passing-test human approval. Keep raw logs/argv local, preserve all old evidence,
and fail preflight on damaged revision references. Provider failure remains an
explicit retry; there is no automatic correction loop. Demo/legacy graphs keep
their behavior. Original PLAN.md and all three roles retain their intended scope;
live acceptance is still disabled pending separate authorization.

## 2026-10-09: Bounded goal-driven Creator planning

Replace fixed normal Creator creation with a tool-free registered planner and
capability-selected research/outline/script assignments on the existing engine.
Bound plans to 2–6 tasks, one final script review, one to four outlines/refinements,
and exactly one research task when sources are supplied. Preserve original goal,
constraints, objectives and exact source text. Planning sees source IDs/labels;
content agents receive the bodies they require, without workspace enrichment.

Move shared plan binding/task primitives to the domain without changing Developer
contracts. Creator planning version 1 uses existing persisted evidence; role-aware
preflight and review keep Developer tests distinct from content acceptance. Validate
schema/capability/permissions, every dependency binding, mandatory review and exact
owned evidence before staging/acceptance. Reuse approvals, claims, retries, artifacts
and audit; no migration or second engine. Legacy graphs and fixed demos persist.

Live model acceptance remains separately gated. Image/thumbnail artifacts, broader
Student work, semantic memory and other original PLAN.md requirements remain pending;
full Developer/Creator/Student scope is unchanged. Result Review History and Developer
memory-context evidence stay deferred.
