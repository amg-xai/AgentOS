# Local Developer workflow

The Developer package combines model-backed investigation and patch generation
with registered filesystem, Git, and terminal tools. Testing reports come from
the subprocess runner, not a model. The engine still uses manifest agent IDs,
dependency-linked tasks, durable claims, permission checks, artifacts, and
digest-bound result approvals.

## Explicit offline demo

`python -m agentos serve --demo` selects only the unchanged bundled Calculator
fixture. Findings and patches are deterministic scripted responses. The same
registered tools perform real source reads, Git checks, and subprocess tests;
the existing engine persists tasks, reviews, artifacts, and audit events.
Every task adds an `offline-demo.txt` provenance artifact, and text reports carry
the demo label. Patch files remain valid unified diffs with provenance alongside.
The final review bundle includes the exact tested diff, actual report, and label.

Demo startup ignores provider, package-path, workspace-path, database-path, and
artifact-path environment overrides. It uses checkout manifests and separate
`.agentos/demo/` storage; local role permissions still apply. It never constructs
a model provider, even if live credentials are present. Manual task completion
and custom missions are disabled in this mode; explicit retry, cancel, review,
and documented admin recovery retain their existing semantics. Normal startup
and normal workspace history are unchanged. Source text is fingerprinted before
startup/creation and again before scripted generation; altered fixtures fail
instead of receiving a canned result. Demo source checks normalize CRLF to LF.

Demo completion validates local workflow mechanics, not live model behavior.
See the [offline walkthrough](getting-started.md#offline-demo-without-a-model).

## Configured model workflow

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

`POST /workflows/developer` invokes bounded goal-driven planning against registered
Developer capabilities. See [planning contracts](developer-planning.md) for the
supported graph shapes, validation, preserved goal, and inspectable evidence.
The result stops for human approval after actual testing. Its review bundle owns
`tested.diff` and `test-report.txt`, so approval verifies the exact tested patch
as well as the report. The earlier `proposed.diff` remains investigation history.
Inspect `passed` and the report: new planned and demo results cannot be accepted
unless tests explicitly pass. Older/manual completion does not establish passing
tests. Denial fails the review task; retry reruns tests in fresh
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
