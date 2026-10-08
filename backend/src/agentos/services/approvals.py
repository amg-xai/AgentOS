"""Approve an immutable staged result without rerunning its executor."""

from datetime import UTC, datetime

from agentos.domain.governance import (
    ApprovalDecision,
    ApprovalStatus,
    UserRole,
    payload_digest,
    require_operator,
    review_payload,
)
from agentos.domain.missions import Mission, NewEvent, StateConflict, TaskStatus
from agentos.services.missions import refresh_dependencies
from agentos.services.runtime import ArtifactStorage, RuntimeRepository


class ApprovalService:
    def __init__(self, repository: RuntimeRepository, artifacts: ArtifactStorage) -> None:
        self.repository = repository
        self.artifacts = artifacts

    def decide(
        self, approval_id: str, request: ApprovalDecision, role: UserRole, actor: str = "local"
    ) -> Mission:
        require_operator(role)
        approval = self.repository.approval(approval_id)
        mission = self.repository.get(approval.mission_id)
        if mission.version != request.expected_version:
            raise StateConflict("Mission version is stale")
        task = next((t for t in mission.tasks if t.id == approval.task_id), None)
        if (
            approval.status != ApprovalStatus.PENDING
            or task is None
            or task.status != TaskStatus.WAITING_APPROVAL
            or task.attempts != approval.task_attempt
            or request.payload_digest != approval.payload_digest
            or payload_digest(approval.payload) != approval.payload_digest
            or payload_digest(review_payload(task)) != approval.payload_digest
        ):
            raise StateConflict("Approval is stale, already decided, or its payload does not match")
        for artifact_id in task.artifact_refs:
            artifact = self.repository.artifact(artifact_id)
            if artifact.mission_id != mission.id or artifact.task_id != task.id:
                raise StateConflict("Artifact scope does not match the approval")
            if request.decision == "approve":
                self.artifacts.read(artifact)
        now = datetime.now(UTC)
        approved = request.decision == "approve"
        decision = approval.model_copy(
            update={
                "status": ApprovalStatus.APPROVED if approved else ApprovalStatus.DENIED,
                "decided_at": now,
                "decided_by": actor,
            }
        )
        updated_task = task.model_copy(
            update={
                "status": TaskStatus.COMPLETED if approved else TaskStatus.FAILED,
                "error": None if approved else "Human review denied the staged result",
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
        events = [
            NewEvent(
                timestamp=now,
                actor=actor,
                action="approval_decided",
                task_id=task.id,
                details={
                    "approval_id": approval.id,
                    "decision": request.decision,
                    "payload_digest": approval.payload_digest,
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
                        details={
                            "from": before.status,
                            "to": after.status,
                            **({"error": after.error} if after.status == TaskStatus.FAILED else {}),
                        },
                    )
                )
        return self.repository.save(updated, mission.version, events, decision=decision)
