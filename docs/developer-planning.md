# Bounded Developer planning

Normal `POST /workflows/developer` uses the registered, tool-free planner to turn
the original natural-language goal into 5–8 dependency-linked tasks. It selects
agent IDs from installed Developer capability descriptions and IO contracts.
There is no fallback to the demo or fixed decomposition if planning fails.

New plans use server-controlled `contract_version: 3`. Saved version-1 and version-2
missions retain their 3–8 and 4–8 task contracts. The model cannot select the version.

Version 3 adds exactly one registered, tool-free READ-only `developer_issue` task
between investigation and patch generation. It binds primary findings and baseline
summary, optionally a second investigation's findings as context. Patch binds the
same primary findings and baseline summary plus the issue; final testing binds
patch diff, the same baseline report and the same issue. There are 1–4 investigations,
one baseline, one issue, one patch and one final tested review, with at most three
bindings per task. Task and agent IDs remain planner-selected; all tasks feed review.

The Issue Agent uses only supplied goal/constraints/objective and bound evidence,
without file, memory, web or tool enrichment. Its strict `IssueSpec` bounds title to
160 characters, problem/observed/expected behavior to 4,000 each, suggested reproduction
and proposed acceptance criteria to 1–8 entries of 1,000 characters, and limitations
to 0–8 entries of 1,000 characters. Extra fields/non-text outputs fail execution.
Local `issue.json` and `issue.md` are proposals, not proof of reproduction, test
coverage, correctness or passing tests. No external ticket is created.

Final v3 review owns five exact files: `tested.diff`, `test-report.txt`,
`reviewed-baseline-report.txt`, `reviewed-issue.json`, and `reviewed-issue.md`.
Staging and acceptance compare dependency-bound contents, scope, integrity, attempt
and payload digest. V3 payloads additionally bind the goal, workspace/role, planning
evidence and task definitions through a plan digest. V2 keeps its three-file bundle
and previous payload shape. Final acceptance always requires explicit `passed: true`.

Supported version-2 plans contain exactly one baseline task and investigation
evidence feeding exactly one patch task and exactly one final test/result review
task. Investigation can consume another
investigation's `findings` as `context`. Patch generation requires `findings` and
can also consume a second investigation as `context`. It also binds `baseline_summary`
from the baseline. Testing consumes the patch's `diff` and the baseline's
`baseline_report`. Baseline has no dependencies and runs configured tests locally,
without calling a model. Every dependency must provide an input binding, and every
task must lead to the final review. Multiple investigations can target different aspects of a
goal; the existing orchestrator still executes ready tasks sequentially.

The compiler validates unique IDs, bounds, acyclic dependencies, role membership,
agent capabilities, supported executor schemas, available executor bindings,
typed direct-dependency outputs, and the mandatory final review. It rejects
unsupported tools, elevated permissions, orphan tasks, multiple patches/tests,
and early review boundaries. Models cannot select commands or grant permissions.
Input schemas are checked before persistence and again with actual dependency
outputs before dispatch. The whole plan is revalidated before a run claim.

The server carries the unchanged original goal, extracted constraints, and each
task's objective into investigation and patch inputs. Constraints are a model
interpretation of the goal; the original goal remains available for inspection
and execution. Planning sees the capability catalog and selected file names,
without reading source text or running tools. Execution reads the existing scoped
immutable workspace snapshot and uses the same permission-checked local tools.

The mission snapshot stores `planning` evidence: contract version, planner ID, rationale,
constraints, and task objectives. Task records store the actual assignments,
dependencies, bindings, and required test boundary. Creation records a
`mission_planned` audit event. Mission Control exposes the evidence under
**Inspect validated Developer plan**, with a constraint list and the planner ID.
Tasks show individual objectives, exact assigned agent IDs, and dependency inputs.
Source-task links move focus to the task that supplies each bound output without
executing work. Raw planning data remains available for detailed inspection;
events appear in Activity. Planning evidence survives restart in the mission snapshot.

Baseline outputs record explicit `baseline_passed`, actual `baseline_report`, and
a bounded `baseline_summary` containing exit statuses and timeout/output-limit
flags. Only that summary reaches patch generation; raw test logs and command argv
stay local. A failed baseline can complete as valid evidence; completion never
implies tests passed. Mission Control labels baseline and patched outcomes separately.
Passing baselines are supported too; tests do not establish independent correctness.

Final testing runs the configured subprocess commands in fresh scratch and
records explicit boolean `passed` and the actual report. `requires_passed_tests`
requires human review: failed tests remain inspectable in `WAITING_APPROVAL`,
but acceptance returns 409 unless `passed` is exactly `true`. Denial remains
available; explicit retry reruns testing against the same patch and source
snapshot and frozen test recipe. The final review owns `tested.diff`, `test-report.txt`,
and an exact `reviewed-baseline-report.txt` copy. Staging and acceptance validate
their contents against dependency-bound evidence and the final report. Damaged
artifacts cannot be accepted; denial and retry retain history.
To change the goal or source, create a new mission. Missing or malformed
test outcomes fail execution without a result approval. Manual actions cannot
replace planned executor results; only retry is allowed.

For normal version-2/3 missions, an Operator/Admin can explicitly deny a failed-test
result and request **Revise patch** with nonblank feedback (at most 2,000 characters).
Two revision cycles are allowed after the initial patch. `GET /missions/{id}/patch-revision`
reports eligibility; POST requires the current mission version, denied approval ID,
payload digest, and feedback. Pending review, active claims, stale attempts, damaged
evidence, passing-but-denied results, legacy/manual missions, and demo graphs are
ineligible. The request runs no model or tools; select **Run mission** separately.

Only patch and final testing are reopened. Investigation, baseline, issue in v3, original goal,
constraints, graph, assignments, source snapshot, and frozen test recipe are retained.
The registered patch agent receives the exact prior diff and feedback as untrusted
context, alongside the original inputs. Raw test logs and runner arguments stay local.
It generates a full replacement diff against the original source, not a stacked patch.
Existing permission-checked Git/testing tools run again in fresh scratch. A distinct
approval requires explicit passing tests; an old decision cannot accept the replacement.

Bounded `developer_revisions` records retain previous attempts, feedback, denied approval,
artifact references/hashes, and plan digest. Original artifacts and decisions remain
inspectable after restart. Revision requests and state changes are audited atomically
with the existing version/claim checks. Run preflight verifies retained revision evidence
before taking a claim. Provider/tool failure uses explicit task retry; no automatic loop
or additional revision slot is spent. This adds no storage migration or new workflow engine.

Older/manual mission records retain their existing API behavior. Their task or
mission completion is lifecycle evidence, not proof of passing tests. Inspect
recorded outcomes and reports. New offline Developer demo results also require
passing tests, while retaining the explicitly labelled preset scenario.

Live transport is disabled by default. Only after explicit live acceptance
authorization should `AGENTOS_ALLOW_LIVE_MODELS=1` be set locally alongside the
provider configuration. Injected test transports exercise model wire contracts;
they do not establish live model quality or endpoint compatibility.

This implements a bounded part of original PLAN.md Phase 5. The full Developer,
Creator, and Student roadmap remains unchanged. Multiple patch composition,
automatic edits to the original checkout, PR publication, and deployment are
outside this milestone. Result Review History remains deferred. The next
acceptance milestone needs a trusted project, a failing baseline, an authorized
live goal-driven run, actual passing patched tests, human review, and restart
inspection. Neither automated mocks nor the offline demo complete that claim.

## Continuous UI/API acceptance

`npm --prefix frontend run test:integration` renders the actual React application
in JSDOM against a real isolated loopback backend with injected model transport.
It exercises normal v3 creation, actual baseline/patched tests, exact five-file
review evidence, failed-test rejection, two explicit revisions, acceptance and
restart inspection with unchanged source files. It does not add a production
fixture mode or establish live AI quality or native rendering. See
[validation setup](getting-started.md#continuous-offline-integration-validation).
