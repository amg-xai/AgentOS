# Missions and workflows

Tasks use the PLAN.md states: PENDING, READY, RUNNING, WAITING_APPROVAL,
BLOCKED, FAILED, COMPLETED, and CANCELLED. Mission creation validates unique
task ids, acyclic dependencies, and agent membership in the selected role.
One workspace, `local`, is currently supported.

## Implemented lifecycle

| Action | Required state | Result |
| --- | --- | --- |
| start | READY | RUNNING; increment attempt count |
| complete | RUNNING | COMPLETED; persist outputs |
| fail | RUNNING | FAILED; persist failure reason |
| retry | FAILED | READY; clear current error, retain failure in history |
| wait_approval | RUNNING | WAITING_APPROVAL |
| cancel mission | Any unfinished mission | CANCELLED for every unfinished task |

A task becomes READY only when all dependencies are COMPLETED. Otherwise it is
PENDING, or BLOCKED if any dependency is FAILED, CANCELLED, or BLOCKED. Resolve
dependencies in topological order, independent of input ordering. Retrying a
failure refreshes downstream states without repeating completed tasks. Unrelated
branches can continue after a failure. Completed and cancelled tasks are terminal.

Mission status is derived from tasks, in this precedence: all completed ->
COMPLETED; any cancelled -> CANCELLED; any failed -> FAILED; any waiting approval
-> WAITING_APPROVAL; any running or completed -> RUNNING; any blocked -> BLOCKED;
otherwise PENDING. READY tasks leave the mission PENDING until work starts.

All mutations require the current mission version. State changes and event writes
commit atomically; stale versions and illegal actions return 409. Missing records
return 404, and malformed graphs/action payloads return 422. Events have global
monotonic sequence numbers, UTC timestamps, local actor identity, task references,
and transition details. Paginate with `after` and `limit` on the events endpoint.

Manual lifecycle actions do not invoke an agent or validate execution outputs
against agent schemas. The execution service performs that validation when an
executor is invoked by the explicit orchestrator described below.

The first workflow is investigate -> propose fix -> test -> human review ->
approved result. The review includes the exact proposed diff and test evidence.
An approval is scoped to a pending action, not blanket permission for a mission.

## Explicit orchestration and review

ExecutorRegistry binds an agent id or provider id to an execution interface.
There are no default model executors or fixture fallbacks. A task can declare
`input_bindings: {"field": {"task_id": "dependency", "output_key": "output"}}`.
Bindings may reference only direct dependencies and cannot overwrite explicit
inputs. Resolve bindings and validate IO against the registered agent schemas.

POST `/missions/{id}/run` claims a mission and executes ready tasks sequentially.
Each start and result persists independently. Completed tasks are not rerun.
Failure records a sanitized error, blocks dependants, and stops that run. Explicit
retry is required before trying again. Runs also stop at review-required results.

For `review_required: true`, store outputs and artifact references before entering
WAITING_APPROVAL. The approval binds mission, task, attempt, `review_result` action,
and a SHA-256 digest of the canonical payload. Decisions require the current
mission version and matching digest. Reject replayed, denied, stale, or mismatched
approvals. Cancellation invalidates pending approvals. Check artifact integrity
before accepting a result; damaged artifacts can still be denied.

Approving transitions the staged task from WAITING_APPROVAL to COMPLETED, without
rerunning its executor. Downstream tasks become ready and can be resumed by an
explicit run. Denial transitions it to FAILED. Retry keeps previous artifacts in
history but generates a fresh result and approval. Only ApprovalService may accept
an orchestrated waiting result; manual completion cannot bypass review_required.

Legacy manual `wait_approval` only records a waiting state, without generating a
result approval. New executable workflows should use `review_required` instead.
Result approval does not authorize a tool call, deployment, or publication.

Normal Developer creation compiles a [bounded goal-driven plan](developer-planning.md)
before persistence, then revalidates it before execution. New planned and offline
Developer test results declare `requires_passed_tests: true`; accepting them
requires explicit boolean `passed: true` in addition to the existing review
integrity checks. Completion alone never establishes test success for historical
or manually managed missions.

Version-2 normal Developer plans also require baseline execution, bound baseline
summary for patch generation, and bound baseline report for final review. A baseline
task can complete with `baseline_passed: false`; final acceptance still requires
`passed: true` from patched tests. Both outcomes and both reports remain inspectable.
The review owns exact copies of the tested diff, baseline report, and patched report,
and validates their contents before staging and accepting them. Version-1 saved
plans and the offline preset retain their previous contracts.

## Interrupted run recovery

GET `/missions/{id}/run` to inspect a durable claim. A normal run releases it;
an interrupted/ambiguous run retains it. Automatic expiry is deliberately absent,
so another process cannot silently redispatch uncertain work.

An Admin can POST to `/missions/{id}/recover` with `expected_version`,
`claim_token`, and `acknowledge_ambiguity: true`. First stop the old worker and
inspect any possible side effects. Recovery rejects a known active local run,
stale versions, or changed tokens. It revokes the claim and marks RUNNING tasks
FAILED, preserving completed results. It does not retry anything. Explicit retry
may repeat an external side effect; exactly-once execution is not guaranteed.

The API is a single trusted local-user service. Server configuration selects the
user role; request headers cannot elevate it. Viewer is read-only, Operator may
run/review work, and Admin additionally handles recovery. Remote authentication,
distributed workers, and background scheduling are outside the current scope.

Creator and Student workflows reuse the engine; they do not create separate
applications or alternate permission paths.
