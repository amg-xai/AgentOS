"""Explicit sequential runs with durable claims and staged result review."""

import copy
from datetime import UTC, datetime
from uuid import uuid4

from agentos.domain.agents import AgentResult, ExecutionContext
from agentos.domain.artifacts import Artifact
from agentos.domain.governance import (
    Approval,
    PermissionDenied,
    RecoveryRequest,
    UserRole,
    payload_digest,
    require_operator,
    review_payload,
)
from agentos.domain.missions import (
    Mission,
    MissionNotFound,
    MissionStatus,
    NewEvent,
    StateConflict,
    Task,
    TaskAction,
    TaskActionRequest,
    TaskStatus,
    dependency_order,
)
from agentos.services.execution import ExecutorRegistry, execute_agent
from agentos.services.missions import MissionService, refresh_dependencies
from agentos.services.registry import AgentRegistry
from agentos.services.runtime import ArtifactStorage, RuntimeRepository


class Orchestrator:
    def __init__(
        self,
        registry: AgentRegistry,
        repository: RuntimeRepository,
        executors: ExecutorRegistry,
        artifacts: ArtifactStorage,
    ) -> None:
        self.registry = registry
        self.repository = repository
        self.executors = executors
        self.artifacts = artifacts
        self._active: set[str] = set()

    @property
    def active_run_count(self) -> int:
        return len(self._active)

    async def run(
        self, mission_id: str, expected_version: int, role: UserRole, actor: str = "local"
    ) -> Mission:
        require_operator(role)
        mission = self.repository.get(mission_id)
        if mission.planning is not None:
            from agentos.services.planning import validate_planned_mission

            validate_planned_mission(mission, self.registry, self.executors)
        if mission.version != expected_version:
            raise StateConflict("Mission version is stale")
        if mission.status in {
            MissionStatus.COMPLETED,
            MissionStatus.CANCELLED,
            MissionStatus.FAILED,
            MissionStatus.WAITING_APPROVAL,
        } or any(task.status == TaskStatus.RUNNING for task in mission.tasks):
            raise StateConflict("Mission needs review, retry, or recovery before running")
        for pending in mission.tasks:
            if pending.status != TaskStatus.COMPLETED:
                self.executors.resolve(self.registry.agent(pending.agent_id))
        claim = self.repository.acquire_claim(mission_id, expected_version, actor)
        self._active.add(claim.token)
        lifecycle = MissionService(self.registry, self.repository, claim_token=claim.token)
        clean_exit = False
        try:
            while True:
                mission = self.repository.get(mission_id)
                by_id = {task.id: task for task in mission.tasks}
                task = next(
                    (
                        by_id[key]
                        for key in dependency_order(mission.tasks)
                        if by_id[key].status == TaskStatus.READY
                    ),
                    None,
                )
                if task is None:
                    break
                mission = lifecycle.act(
                    mission.id,
                    task.id,
                    TaskActionRequest(
                        expected_version=mission.version,
                        action=TaskAction.START,
                    ),
                    actor,
                )
                task = next(t for t in mission.tasks if t.id == task.id)
                try:
                    inputs = copy.deepcopy(task.inputs)
                    for key, binding in task.input_bindings.items():
                        dependency = next(t for t in mission.tasks if t.id == binding.task_id)
                        if (
                            dependency.outputs is None
                            or binding.output_key not in dependency.outputs
                        ):
                            raise ValueError("Dependency output binding is unavailable")
                        inputs[key] = copy.deepcopy(dependency.outputs[binding.output_key])
                    executor = self.executors.resolve(self.registry.agent(task.agent_id))
                    result = await execute_agent(
                        self.registry,
                        task.agent_id,
                        executor,
                        inputs,
                        ExecutionContext(
                            workspace_id=mission.workspace_id,
                            mission_id=mission.id,
                            task_id=task.id,
                            run_token=claim.token,
                            planning_version=(
                                mission.planning.contract_version if mission.planning else 1
                            ),
                        ),
                    )
                    mission = self._finish(mission, task, result, claim.token, actor)
                except Exception as exc:
                    # Keep raw provider errors/inputs (which may contain secrets) out of audit logs.
                    mission = lifecycle.act(
                        mission.id,
                        task.id,
                        TaskActionRequest(
                            expected_version=mission.version,
                            action=TaskAction.FAIL,
                            error=f"Execution failed ({type(exc).__name__}); check configuration",
                        ),
                        actor,
                    )
                    break
                if task.review_required:
                    break
            clean_exit = True
            return mission
        finally:
            self._active.discard(claim.token)
            if clean_exit:
                self.repository.release_claim(claim)

    def _finish(
        self, mission: Mission, task: Task, result: AgentResult, token: str, actor: str
    ) -> Mission:
        created: list[Artifact] = []
        if task.requires_passed_tests and type(result.outputs.get("passed")) is not bool:
            raise StateConflict("Test execution must record an explicit boolean outcome")
        if mission.planning and mission.planning.contract_version == 2 and task.review_required:
            from agentos.services.planning import review_evidence

            expected = review_evidence(mission, task, result.outputs)
            if (
                result.artifact_refs
                or len(result.artifacts) != len(expected)
                or {draft.name: draft.content for draft in result.artifacts} != expected
            ):
                raise StateConflict(
                    "Tested review must own the exact baseline, diff and test report"
                )
        try:
            for artifact_id in result.artifact_refs:
                existing = self.repository.artifact(artifact_id)
                if existing.mission_id != mission.id or existing.task_id != task.id:
                    raise StateConflict("Executor returned an artifact outside its task")
            for draft in result.artifacts:
                created.append(self.artifacts.write(mission.id, task.id, draft))
            refs = tuple(dict.fromkeys((*result.artifact_refs, *(a.id for a in created))))
            now = datetime.now(UTC)
            updated_task = task.model_copy(
                update={
                    "outputs": result.outputs,
                    "artifact_refs": refs,
                    "status": TaskStatus.WAITING_APPROVAL
                    if task.review_required
                    else TaskStatus.COMPLETED,
                }
            )
            tasks = refresh_dependencies(
                tuple(updated_task if t.id == task.id else t for t in mission.tasks)
            )
            updated = mission.model_copy(
                update={
                    "tasks": tasks,
                    "version": mission.version + 1,
                    "updated_at": now,
                }
            )
            approval = None
            if task.review_required:
                payload = review_payload(updated_task)
                approval = Approval(
                    id=uuid4().hex,
                    mission_id=mission.id,
                    task_id=task.id,
                    task_attempt=task.attempts,
                    payload=payload,
                    payload_digest=payload_digest(payload),
                    created_at=now,
                )
            events = [
                NewEvent(
                    timestamp=now,
                    actor=actor,
                    action="approval_requested" if approval else "task_executed",
                    task_id=task.id,
                    details={
                        "artifact_refs": refs,
                        **({"approval_id": approval.id} if approval else {}),
                    },
                )
            ]
            for before, after in zip(mission.tasks, tasks, strict=True):
                if before.status != after.status:
                    events.append(
                        NewEvent(
                            timestamp=now,
                            actor=actor,
                            action="task_state_changed",
                            task_id=after.id,
                            details={"from": before.status, "to": after.status},
                        )
                    )
            events.extend(
                NewEvent(
                    timestamp=now,
                    actor=actor,
                    action="artifact_created",
                    task_id=task.id,
                    details={"artifact_id": a.id, "sha256": a.sha256},
                )
                for a in created
            )
            return self.repository.save(
                updated,
                mission.version,
                events,
                claim_token=token,
                artifacts=tuple(created),
                approval=approval,
            )
        except BaseException:
            for artifact in created:
                try:
                    self.repository.artifact(artifact.id)
                except MissionNotFound:
                    self.artifacts.remove_uncommitted(artifact)
                except Exception:
                    # If commit outcome cannot be checked, retain the file for recovery.
                    pass
            raise

    def recover(
        self, mission_id: str, request: RecoveryRequest, role: UserRole, actor: str = "local"
    ) -> Mission:
        if role != UserRole.ADMIN:
            raise PermissionDenied("Only Admin may recover an interrupted run")
        if not request.acknowledge_ambiguity:
            raise StateConflict(
                "Confirm the old worker has stopped and review possible side effects"
            )
        claim = self.repository.claim(mission_id)
        if claim is None or claim.token != request.claim_token or claim.token in self._active:
            raise StateConflict("Claim is missing, changed, or belongs to an active local run")
        mission = self.repository.get(mission_id)
        if mission.version != request.expected_version:
            raise StateConflict("Mission version is stale")
        now = datetime.now(UTC)
        tasks = refresh_dependencies(
            tuple(
                task.model_copy(
                    update={
                        "status": TaskStatus.FAILED,
                        "error": "Interrupted run; review possible side effects before retry",
                    }
                )
                if task.status == TaskStatus.RUNNING
                else task
                for task in mission.tasks
            )
        )
        updated = mission.model_copy(
            update={
                "tasks": tasks,
                "version": mission.version + 1,
                "updated_at": now,
            }
        )
        events = [NewEvent(timestamp=now, actor=actor, action="run_recovered")]
        events.extend(
            NewEvent(
                timestamp=now,
                actor=actor,
                action="task_state_changed",
                task_id=after.id,
                details={"from": before.status, "to": after.status, "error": after.error},
            )
            for before, after in zip(mission.tasks, tasks, strict=True)
            if before.status != after.status
        )
        return self.repository.recover_claim(updated, claim.token, events)
