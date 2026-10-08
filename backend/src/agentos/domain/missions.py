"""Mission contracts, dependency validation, and derived status."""

from datetime import datetime
from enum import StrEnum
from typing import Any, Self

from pydantic import Field, computed_field, model_validator

from agentos.domain.agents import Definition, Identifier, Text


class MissionValidationError(ValueError):
    """Invalid workflow definition or action payload."""


class StateConflict(ValueError):
    """A stale version or illegal lifecycle action."""


class MissionNotFound(LookupError):
    """A mission or task does not exist."""


class TaskStatus(StrEnum):
    PENDING = "PENDING"
    READY = "READY"
    RUNNING = "RUNNING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class MissionStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class TaskSpec(Definition):
    id: Identifier
    title: Text
    agent_id: Identifier
    dependencies: tuple[Identifier, ...] = ()
    inputs: dict[str, Any] = Field(default_factory=dict)


def dependency_order(tasks: tuple[TaskSpec, ...]) -> list[str]:
    """Validate the graph and return a stable topological ordering."""
    by_id = {task.id: task for task in tasks}
    if len(by_id) != len(tasks):
        raise MissionValidationError("Task ids must be unique")
    for task in tasks:
        if len(set(task.dependencies)) != len(task.dependencies):
            raise MissionValidationError(f"Task {task.id}: dependencies must be unique")
        if task.id in task.dependencies:
            raise MissionValidationError(f"Task {task.id}: cannot depend on itself")
        missing = set(task.dependencies) - by_id.keys()
        if missing:
            raise MissionValidationError(f"Task {task.id}: unknown dependencies {sorted(missing)}")
    remaining = dict(by_id)
    ordered: list[str] = []
    resolved: set[str] = set()
    while remaining:
        ready = [key for key, task in remaining.items() if set(task.dependencies) <= resolved]
        if not ready:
            raise MissionValidationError("Task dependency graph contains a cycle")
        for key in ready:
            ordered.append(key)
            resolved.add(key)
            del remaining[key]
    return ordered


class MissionCreate(Definition):
    goal: Text
    role_id: Identifier = "developer"
    workspace_id: Identifier = "local"
    tasks: tuple[TaskSpec, ...] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def valid_graph(self) -> Self:
        dependency_order(self.tasks)
        return self


class Task(TaskSpec):
    status: TaskStatus = TaskStatus.PENDING
    attempts: int = Field(default=0, ge=0)
    outputs: dict[str, Any] | None = None
    error: str | None = None


class Mission(Definition):
    id: Text
    goal: Text
    role_id: Identifier
    workspace_id: Identifier
    tasks: tuple[Task, ...] = Field(min_length=1)
    version: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def status(self) -> MissionStatus:
        states = {task.status for task in self.tasks}
        if states == {TaskStatus.COMPLETED}:
            return MissionStatus.COMPLETED
        if TaskStatus.CANCELLED in states:
            return MissionStatus.CANCELLED
        if TaskStatus.FAILED in states:
            return MissionStatus.FAILED
        if TaskStatus.WAITING_APPROVAL in states:
            return MissionStatus.WAITING_APPROVAL
        if TaskStatus.RUNNING in states or TaskStatus.COMPLETED in states:
            return MissionStatus.RUNNING
        if TaskStatus.BLOCKED in states:
            return MissionStatus.BLOCKED
        return MissionStatus.PENDING


class TaskAction(StrEnum):
    START = "start"
    COMPLETE = "complete"
    FAIL = "fail"
    WAIT_APPROVAL = "wait_approval"
    RETRY = "retry"


class VersionRequest(Definition):
    expected_version: int = Field(ge=1, strict=True)


class TaskActionRequest(VersionRequest):
    action: TaskAction
    outputs: dict[str, Any] | None = None
    error: Text | None = None

    @model_validator(mode="after")
    def payload_matches_action(self) -> Self:
        if self.action == TaskAction.COMPLETE:
            if self.outputs is None or self.error is not None:
                raise ValueError("complete requires outputs and forbids error")
        elif self.action == TaskAction.FAIL:
            if self.error is None or self.outputs is not None:
                raise ValueError("fail requires error and forbids outputs")
        elif self.outputs is not None or self.error is not None:
            raise ValueError("This action does not accept outputs or error")
        return self


class NewEvent(Definition):
    timestamp: datetime
    actor: Text
    action: Text
    task_id: Identifier | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class MissionEvent(NewEvent):
    sequence: int
    mission_id: Text
