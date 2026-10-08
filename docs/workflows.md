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
executor is invoked; integration with mission orchestration is a later milestone.

The first workflow is investigate -> propose fix -> test -> human review ->
approved result. The review includes the exact proposed diff and test evidence.
An approval is scoped to a pending action, not blanket permission for a mission.

WAITING_APPROVAL cannot be resumed through the current API. Action-scoped approval
and orchestration will provide that transition. Workspace memory and automatic
execution/resumption are also planned. A restart currently restores persisted
records and history without launching work.

Creator and Student workflows reuse the engine; they do not create separate
applications or alternate permission paths.
