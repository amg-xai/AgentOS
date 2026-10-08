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
