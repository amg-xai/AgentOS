"""Mission lifecycle operations. No providers or executable tools are called."""

from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from agentos.domain.missions import (
    Mission,
    MissionCreate,
    MissionEvent,
    MissionNotFound,
    MissionStatus,
    MissionValidationError,
    NewEvent,
    StateConflict,
    Task,
    TaskAction,
    TaskActionRequest,
    TaskStatus,
    dependency_order,
)
from agentos.services.registry import AgentRegistry


class MissionRepository(Protocol):
    def create(self, mission: Mission, events: list[NewEvent]) -> Mission: ...
    def get(self, mission_id: str) -> Mission: ...
    def list_missions(self, limit: int = 50, offset: int = 0) -> list[Mission]: ...
    def save(
        self,
        mission: Mission,
        expected_version: int,
        events: list[NewEvent],
        *,
        claim_token: str | None = None,
    ) -> Mission: ...
    def events(self, mission_id: str, after: int = 0, limit: int = 100) -> list[MissionEvent]: ...


def refresh_dependencies(tasks: tuple[Task, ...]) -> tuple[Task, ...]:
    by_id = {task.id: task for task in tasks}
    blocked = {TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.BLOCKED}
    for task_id in dependency_order(tasks):
        task = by_id[task_id]
        if task.status not in {TaskStatus.PENDING, TaskStatus.READY, TaskStatus.BLOCKED}:
            continue
        states = {by_id[key].status for key in task.dependencies}
        if states & blocked:
            status = TaskStatus.BLOCKED
        elif states <= {TaskStatus.COMPLETED}:
            status = TaskStatus.READY
        else:
            status = TaskStatus.PENDING
        by_id[task_id] = task.model_copy(update={"status": status})
    return tuple(by_id[task.id] for task in tasks)


class MissionService:
    def __init__(
        self,
        registry: AgentRegistry,
        repository: MissionRepository,
        *,
        claim_token: str | None = None,
    ) -> None:
        self.registry = registry
        self.repository = repository
        self.claim_token = claim_token

    def create(self, request: MissionCreate, actor: str = "local") -> Mission:
        if request.workspace_id != "local":
            raise MissionValidationError("Only the local workspace is supported")
        try:
            role = self.registry.role(request.role_id)
        except KeyError as exc:
            raise MissionValidationError(f"Unknown role: {request.role_id}") from exc
        for task in request.tasks:
            if task.agent_id not in role.agents:
                raise MissionValidationError(
                    f"Task {task.id}: agent {task.agent_id} is not in role {role.id}"
                )
        now = datetime.now(UTC)
        mission = Mission(
            id=str(uuid4()),
            goal=request.goal,
            role_id=request.role_id,
            workspace_id=request.workspace_id,
            tasks=refresh_dependencies(tuple(Task(**task.model_dump()) for task in request.tasks)),
            version=1,
            created_at=now,
            updated_at=now,
            planning=request.planning,
        )
        events = [NewEvent(timestamp=now, actor=actor, action="mission_created")]
        if request.planning:
            events.append(
                NewEvent(
                    timestamp=now,
                    actor=actor,
                    action="mission_planned",
                    details={
                        "planner_id": request.planning.planner_id,
                        "tasks": len(mission.tasks),
                    },
                )
            )
        events.extend(
            NewEvent(
                timestamp=now,
                actor=actor,
                action="task_created",
                task_id=task.id,
                details={"status": task.status, "agent_id": task.agent_id},
            )
            for task in mission.tasks
        )
        return self.repository.create(mission, events)

    def _current(self, mission_id: str, expected_version: int) -> Mission:
        mission = self.repository.get(mission_id)
        if mission.version != expected_version:
            raise StateConflict("Mission was changed; reload and retry with its current version")
        return mission

    def _save(
        self,
        old: Mission,
        tasks: tuple[Task, ...],
        action: str,
        actor: str,
        task_id: str | None = None,
    ) -> Mission:
        now = datetime.now(UTC)
        mission = old.model_copy(
            update={
                "tasks": tasks,
                "version": old.version + 1,
                "updated_at": now,
            }
        )
        events = [
            NewEvent(
                timestamp=now,
                actor=actor,
                action=action,
                task_id=task_id,
                details={"version": mission.version},
            )
        ]
        for before, after in zip(old.tasks, tasks, strict=True):
            if before.status != after.status:
                events.append(
                    NewEvent(
                        timestamp=now,
                        actor=actor,
                        action="task_state_changed",
                        task_id=after.id,
                        details={
                            "from": before.status,
                            "to": after.status,
                            "attempts": after.attempts,
                            **({"error": after.error} if after.status == TaskStatus.FAILED else {}),
                        },
                    )
                )
        return self.repository.save(mission, old.version, events, claim_token=self.claim_token)

    def act(
        self, mission_id: str, task_id: str, request: TaskActionRequest, actor: str = "local"
    ) -> Mission:
        mission = self._current(mission_id, request.expected_version)
        task = next((task for task in mission.tasks if task.id == task_id), None)
        if task is None:
            raise MissionNotFound(f"Task {task_id} not found")
        transitions = {
            TaskAction.START: (TaskStatus.READY, TaskStatus.RUNNING),
            TaskAction.COMPLETE: (TaskStatus.RUNNING, TaskStatus.COMPLETED),
            TaskAction.FAIL: (TaskStatus.RUNNING, TaskStatus.FAILED),
            TaskAction.WAIT_APPROVAL: (TaskStatus.RUNNING, TaskStatus.WAITING_APPROVAL),
            TaskAction.RETRY: (TaskStatus.FAILED, TaskStatus.READY),
        }
        required, target = transitions[request.action]
        if task.status != required:
            raise StateConflict(f"Cannot {request.action} task {task_id} in {task.status}")
        if request.action == TaskAction.COMPLETE and task.review_required:
            raise StateConflict("Reviewed tasks must complete through orchestration and approval")
        updated = task.model_copy(
            update={
                "status": target,
                "attempts": task.attempts + (request.action == TaskAction.START),
                "outputs": request.outputs,
                "error": request.error,
            }
        )
        tasks = refresh_dependencies(
            tuple(updated if item.id == task_id else item for item in mission.tasks)
        )
        return self._save(mission, tasks, f"task_{request.action}", actor, task_id)

    def cancel(self, mission_id: str, expected_version: int, actor: str = "local") -> Mission:
        mission = self._current(mission_id, expected_version)
        if mission.status in {MissionStatus.COMPLETED, MissionStatus.CANCELLED}:
            raise StateConflict(f"Cannot cancel a {mission.status} mission")
        tasks = tuple(
            task
            if task.status == TaskStatus.COMPLETED
            else task.model_copy(update={"status": TaskStatus.CANCELLED})
            for task in mission.tasks
        )
        return self._save(mission, tasks, "mission_cancelled", actor)
