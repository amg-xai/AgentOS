# Bounded Developer planning

Normal `POST /workflows/developer` uses the registered, tool-free planner to turn
the original natural-language goal into 3–8 dependency-linked tasks. It selects
agent IDs from installed Developer capability descriptions and IO contracts.
There is no fallback to the demo or fixed decomposition if planning fails.

Supported plans contain investigation evidence feeding exactly one patch task
and exactly one final test/result review task. Investigation can consume another
investigation's `findings` as `context`. Patch generation requires `findings` and
can also consume a second investigation as `context`. Testing consumes the patch's
`diff`. Every dependency must provide an input binding, and every task must lead
to the final review. Multiple investigations can target different aspects of a
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

The mission snapshot stores `planning` evidence: planner ID, rationale,
constraints, and task objectives. Task records store the actual assignments,
dependencies, bindings, and required test boundary. Creation records a
`mission_planned` audit event. Mission Control exposes the evidence under
**Inspect validated Developer plan**, with assignments in Tasks and events in
Activity. Evidence survives restart without a database schema migration.

Final testing runs the configured subprocess commands in fresh scratch and
records explicit boolean `passed` and the actual report. `requires_passed_tests`
requires human review: failed tests remain inspectable in `WAITING_APPROVAL`,
but acceptance returns 409 unless `passed` is exactly `true`. Denial remains
available; explicit retry reruns testing against the same patch and source
snapshot. To change the patch or goal, create a new mission. Missing or malformed
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
