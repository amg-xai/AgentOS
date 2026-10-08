# Local Developer workflow

The Developer package combines model-backed investigation and patch generation
with registered filesystem, Git, and terminal tools. Testing reports come from
the subprocess runner, not a model. The engine still uses manifest agent IDs,
dependency-linked tasks, durable claims, permission checks, artifacts, and
digest-bound result approvals.

Workspace configuration is server-side JSON in `.agentos/workspace.json` (or
`AGENTOS_WORKSPACE_CONFIG`). It selects a directory, explicit source file paths,
and test argv arrays. There is no shell command field and models cannot select
commands. Only Python/pytest and Node/npm runner executables are accepted; inline
evaluation and shell executables are rejected. Credentials are stripped from
child environments. Tests have time and output limits. Existing absolute runner
paths can be configured when a project needs its own installed environment.

The first source read captures at most 64 UTF-8 files, 100 KB per file and 512 KB
total, with CRLF normalized to LF. Symlinks, junctions, binary data, traversal,
Git metadata, and common credential paths are rejected. The immutable snapshot
is stored in the separately versioned `workspace.sqlite3`, preserving the existing
mission database format. Retries and restarts use the same snapshot. Select a
new mission to inspect updated source files.

Patches can modify only existing selected text files. New files, deletions,
renames, modes, binary patches, and links are unsupported. Git checks and applies
the patch in a new application-owned scratch directory. Each test attempt gets a
fresh directory from the snapshot. Source files are never targeted by patch
application. Scratch directories are retained locally for inspection.

**Scratch execution is not an OS security sandbox.** Tests and generated code run
with the server user's privileges and can access the host. Select trusted projects
and inspect configured commands. Network/process isolation and automatic scratch
cleanup are deferred. This scope does not enable arbitrary model-driven commands,
publishing, deployments, or changes to the original checkout.

`POST /workflows/developer` builds the investigation → patch → tests/review graph.
The result stops for human approval after actual testing. Its review bundle owns
`tested.diff` and `test-report.txt`, so approval verifies the exact tested patch
as well as the report. The earlier `proposed.diff` remains investigation history.
Inspect `passed` and
the report: accepting a result records human acceptance, and does not convert a
failing test into a pass. Denial fails the review task; retry reruns tests in fresh
scratch. Existing recovery rules apply after interrupted runs.

`GET/POST /memory` stores workspace notes with validated artifact references.
Retrieval matches words against the most recent 1,000 notes; results are bounded,
Unicode-aware, and ordered by overlap then recency. It is **lexical**, not semantic
search. Investigation sends up to five relevant notes and selected source files
to the configured model endpoint. Add only context you intend to share there.

The browser client and API use one loopback origin. Host validation, strict
origin checks, JSON-only writes, and no CORS protect against browser cross-origin
requests. This is a local single-user service, without remote/multi-user auth.
Do not expose it through a network bind or reverse proxy.
