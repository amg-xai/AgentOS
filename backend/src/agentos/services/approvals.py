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
            or payload_digest(review_payload(task, mission)) != approval.payload_digest
        ):
            raise StateConflict("Approval is stale, already decided, or its payload does not match")
        for artifact_id in task.artifact_refs:
            artifact = self.repository.artifact(artifact_id)
            if artifact.mission_id != mission.id or artifact.task_id != task.id:
                raise StateConflict("Artifact scope does not match the approval")
            if request.decision == "approve":
                self.artifacts.read(artifact)
        from agentos.services.creator import (
            creator_review_evidence,
            has_sources,
            source_review_evidence,
        )
        from agentos.services.student import (
            has_study_plan,
            student_review_evidence,
            study_review_evidence,
        )

        if (
            request.decision == "approve"
            and mission.role_id == "student"
            and (mission.planning is not None or has_study_plan(mission))
        ):
            from agentos.services.student_sources import validate_source_artifacts

            validate_source_artifacts(mission, self.repository, self.artifacts)
            expected_study = (
                student_review_evidence(mission, task, task.outputs or {})
                if mission.planning
                else study_review_evidence(mission, task.outputs or {})
            )
            actual_study = {
                self.repository.artifact(ref).name: self.artifacts.read(
                    self.repository.artifact(ref)
                ).decode("utf-8")
                for ref in task.artifact_refs
            }
            if len(task.artifact_refs) != len(expected_study) or actual_study != expected_study:
                raise StateConflict("Student review evidence does not match its study inputs")

        if (
            request.decision == "approve"
            and mission.role_id == "creator"
            and (has_sources(mission) or mission.planning)
        ):
            actual_creator = {
                self.repository.artifact(ref).name: self.artifacts.read(
                    self.repository.artifact(ref)
                )
                for ref in task.artifact_refs
            }
            if mission.planning and mission.planning.contract_version == 2:
                from agentos.services.creator import thumbnail_review_evidence

                try:
                    frozen = (
                        actual_creator["thumbnail.png"],
                        actual_creator["thumbnail-layout.json"].decode("utf-8"),
                    )
                except (KeyError, UnicodeDecodeError):
                    raise StateConflict("Thumbnail frozen evidence is unavailable") from None
                expected_creator = thumbnail_review_evidence(
                    mission, task, task.outputs or {}, frozen=frozen
                )
            else:
                expected_creator = (
                    creator_review_evidence(mission, task, task.outputs or {})
                    if mission.planning
                    else source_review_evidence(mission, task.outputs or {})
                )
            expected_bytes = {
                name: value if isinstance(value, bytes) else value.encode("utf-8")
                for name, value in expected_creator.items()
            }
            if (
                len(task.artifact_refs) != len(expected_creator)
                or actual_creator != expected_bytes
                or any(
                    self.repository.artifact(ref).media_type
                    != (
                        "image/png"
                        if self.repository.artifact(ref).name == "thumbnail.png"
                        else "text/markdown"
                        if self.repository.artifact(ref).name.endswith(".md")
                        else "text/plain"
                    )
                    for ref in task.artifact_refs
                )
            ):
                raise StateConflict("Creator review evidence does not match its sources")
        if (
            request.decision == "approve"
            and mission.role_id == "developer"
            and mission.planning
            and mission.planning.contract_version in (2, 3)
        ):
            from agentos.services.planning import review_evidence, validate_issue_artifacts

            validate_issue_artifacts(mission, self.repository, self.artifacts)
            expected = review_evidence(mission, task, task.outputs or {})
            actual = {
                self.repository.artifact(ref).name: self.artifacts.read(
                    self.repository.artifact(ref)
                ).decode("utf-8")
                for ref in task.artifact_refs
            }
            if len(task.artifact_refs) != len(expected) or actual != expected:
                raise StateConflict("Review evidence does not match the tested result")
        now = datetime.now(UTC)
        approved = request.decision == "approve"
        if (
            approved
            and (
                task.requires_passed_tests
                or (
                    mission.role_id == "developer"
                    and mission.planning is not None
                    and mission.planning.contract_version in (2, 3)
                )
            )
            and (task.outputs is None or task.outputs.get("passed") is not True)
        ):
            raise StateConflict("Tests must explicitly pass before accepting this result")
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
