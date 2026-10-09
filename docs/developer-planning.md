# Bounded Developer planning

Normal `POST /workflows/developer` uses the registered, tool-free planner to turn
the original natural-language goal into 4–8 dependency-linked tasks. It selects
agent IDs from installed Developer capability descriptions and IO contracts.
There is no fallback to the demo or fixed decomposition if planning fails.

New plans use server-controlled `contract_version: 2`. Version-1 saved missions
default to their existing 3–8 task contract. The model cannot select the version.

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
To change the patch or goal, create a new mission. Missing or malformed
test outcomes fail execution without a result approval. Manual actions cannot
replace planned executor results; only retry is allowed.

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
