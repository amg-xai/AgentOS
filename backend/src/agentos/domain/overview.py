"""Read-only workspace summaries; never include execution inputs or claim tokens."""

from datetime import datetime
from typing import Literal

from pydantic import Field

from agentos.domain.artifacts import Artifact
from agentos.domain.base import Definition, Identifier, Text
from agentos.domain.missions import MissionStatus, TaskStatus


class MissionSummary(Definition):
    id: Text
    goal: str = Field(max_length=240)
    role_id: Identifier
    status: MissionStatus
    updated_at: datetime
    has_claim: bool


class TaskSummary(Definition):
    mission_id: Text
    mission_goal: str = Field(max_length=240)
    task_id: Identifier
    title: str = Field(max_length=240)
    status: TaskStatus
    mission_updated_at: datetime
    has_claim: bool


class AgentActivity(Definition):
    agent_id: Identifier
    task_counts: dict[TaskStatus, int]
    recent_tasks: tuple[TaskSummary, ...] = Field(max_length=5)


class PersistedOverview(Definition):
    observed_at: datetime
    total_missions: int = Field(ge=0)
    mission_counts: dict[MissionStatus, int]
    pending_approvals: int = Field(ge=0)
    durable_claims: int = Field(ge=0)
    total_artifacts: int = Field(ge=0)
    recent_reviews: tuple[MissionSummary, ...] = Field(max_length=10)
    recent_artifacts: tuple[Artifact, ...] = Field(max_length=10)
    agent_activity: tuple[AgentActivity, ...]


class WorkspaceOverview(PersistedOverview):
    execution_mode: Literal["live", "demo"]
    local_active_runs: int = Field(ge=0)
