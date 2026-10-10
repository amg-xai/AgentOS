"""Approval and authorization contracts. Product packages are not user roles."""

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field

from agentos.domain.agents import Definition, Identifier, Text
from agentos.domain.missions import Mission, Task, TaskSpec, VersionRequest


class UserRole(StrEnum):
    VIEWER = "viewer"
    OPERATOR = "operator"
    ADMIN = "admin"


class PermissionDenied(PermissionError):
    """The local user's role or agent capability does not permit an action."""


def require_operator(role: UserRole) -> None:
    if role == UserRole.VIEWER:
        raise PermissionDenied("Viewer access is read-only")


def payload_digest(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def mission_plan_digest(mission: Mission) -> str:
    payload: dict[str, Any] = {
        "goal": mission.goal,
        "planning": mission.planning.model_dump(mode="json") if mission.planning else None,
        "tasks": [
            t.model_dump(mode="json", include=set(TaskSpec.model_fields)) for t in mission.tasks
        ],
    }
    if mission.planning and (
        mission.planning.contract_version == 3
        or (mission.role_id == "student" and mission.planning.contract_version == 2)
    ):
        payload.update(role_id=mission.role_id, workspace_id=mission.workspace_id)
    return payload_digest(payload)


def review_payload(task: Task, mission: Mission | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"outputs": task.outputs, "artifact_refs": list(task.artifact_refs)}
    if (
        mission
        and mission.planning
        and (
            (mission.role_id == "developer" and mission.planning.contract_version == 3)
            or (mission.role_id == "student" and mission.planning.contract_version == 2)
        )
    ):
        payload["plan_digest"] = mission_plan_digest(mission)
    return payload


class ApprovalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    STALE = "STALE"


class Approval(Definition):
    id: Text
    mission_id: Text
    task_id: Identifier
    task_attempt: int = Field(ge=1)
    action: Literal["review_result"] = "review_result"
    payload: dict[str, Any]
    payload_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: datetime
    decided_at: datetime | None = None
    decided_by: str | None = None


class ApprovalDecision(VersionRequest):
    decision: Literal["approve", "deny"]
    payload_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class RunClaim(Definition):
    mission_id: Text
    token: Text
    actor: Text
    created_at: datetime


class RecoveryRequest(VersionRequest):
    claim_token: Text
    acknowledge_ambiguity: bool = Field(strict=True)
