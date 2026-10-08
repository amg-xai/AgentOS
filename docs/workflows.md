# Missions and workflows

Tasks use the PLAN.md states: PENDING, READY, RUNNING, WAITING_APPROVAL,
BLOCKED, FAILED, COMPLETED, and CANCELLED. Specify legal transitions and validate
acyclic dependencies before execution. Failures must block dependent tasks.

The first workflow is investigate -> propose fix -> test -> human review ->
approved result. The review includes the exact proposed diff and test evidence.
An approval is scoped to a pending action, not blanket permission for a mission.

Later milestones add persisted retry, cancellation, restart/resume, workspace
memory, and audit history. Tests must exercise complete missions and approval
resumption, including failure paths and unauthorized actions.

Creator and Student workflows reuse the engine; they do not create separate
applications or alternate permission paths.
