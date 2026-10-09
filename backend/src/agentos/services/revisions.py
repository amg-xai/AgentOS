"""Explicit patch replacement on the existing graph; no tools or models run here."""

import hashlib
from datetime import UTC, datetime

from agentos.domain.governance import (
    Approval,
    ApprovalStatus,
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
    PatchRevisionRequest,
    StateConflict,
    Task,
    TaskSpec,
    TaskStatus,
)
from agentos.domain.revisions import DeveloperRevision, PatchRevisionContext, PatchRevisionStatus
from agentos.services.execution import ExecutorRegistry
from agentos.services.missions import refresh_dependencies
from agentos.services.planning import developer_kind, review_evidence, validate_planned_mission
from agentos.services.registry import AgentRegistry
from agentos.services.runtime import ArtifactStorage, RuntimeRepository


def plan_digest(mission: Mission) -> str:
    return payload_digest(
        {
            "goal": mission.goal,
            "planning": mission.planning.model_dump(mode="json") if mission.planning else None,
            "tasks": [
                t.model_dump(mode="json", include=set(TaskSpec.model_fields)) for t in mission.tasks
            ],
        }
    )


class PatchRevisionService:
    def __init__(
        self,
        registry: AgentRegistry,
        repository: RuntimeRepository,
        executors: ExecutorRegistry,
        artifacts: ArtifactStorage,
        *,
        demo: bool = False,
    ) -> None:
        self.registry, self.repository = registry, repository
        self.executors, self.artifacts, self.demo = executors, artifacts, demo

    def _tasks(self, mission: Mission) -> tuple[Task, Task]:
        if (
            self.demo
            or mission.role_id != "developer"
            or not mission.planning
            or mission.planning.contract_version != 2
        ):
            raise StateConflict("Patch revision requires a normal version-2 Developer mission")
        validate_planned_mission(mission, self.registry, self.executors)
        patch = next(
            t
            for t in mission.tasks
            if developer_kind(self.registry.agent(t.agent_id)) == "developer_patch"
        )
        test = next(
            t
            for t in mission.tasks
            if developer_kind(self.registry.agent(t.agent_id)) == "developer_test"
        )
        return patch, test

    def _evidence(self, mission: Mission, test: Task, approval: Approval) -> dict[str, str]:
        outputs = approval.payload.get("outputs")
        refs = approval.payload.get("artifact_refs")
        if (
            approval.mission_id != mission.id
            or approval.task_id != test.id
            or approval.status != ApprovalStatus.DENIED
            or payload_digest(approval.payload) != approval.payload_digest
            or not isinstance(outputs, dict)
            or outputs.get("passed") is not False
            or not isinstance(refs, list)
            or len(refs) != 3
            or any(not isinstance(ref, str) for ref in refs)
            or len(set(refs)) != 3
        ):
            raise StateConflict("Revision needs an explicitly denied failed-test result")
        contents: dict[str, str] = {}
        for ref in refs:
            artifact = self.repository.artifact(ref)
            if (
                artifact.mission_id != mission.id
                or artifact.task_id != test.id
                or artifact.name in contents
            ):
                raise StateConflict("Revision artifact scope does not match its denied result")
            contents[artifact.name] = self.artifacts.read(artifact).decode("utf-8")
        baseline_binding = test.input_bindings["baseline_report"]
        baseline = next(t for t in mission.tasks if t.id == baseline_binding.task_id)
        if (
            set(contents) != {"tested.diff", "test-report.txt", "reviewed-baseline-report.txt"}
            or not contents["tested.diff"]
            or contents["test-report.txt"] != outputs.get("report")
            or baseline.outputs is None
            or contents["reviewed-baseline-report.txt"] != baseline.outputs.get("baseline_report")
        ):
            raise StateConflict("Revision needs intact exact test and baseline evidence")
        return contents

    def validate(self, mission: Mission) -> None:
        if not mission.developer_revisions:
            return
        patch, test = self._tasks(mission)
        previous_patch = previous_test = 0
        approvals: set[str] = set()
        for number, record in enumerate(mission.developer_revisions, 1):
            approval = self.repository.approval(record.approval_id)
            if (
                record.number != number
                or record.patch_task_id != patch.id
                or record.test_task_id != test.id
                or record.plan_digest != plan_digest(mission)
                or record.patch_attempt <= previous_patch
                or record.test_attempt <= previous_test
                or patch.attempts < record.patch_attempt
                or test.attempts < record.test_attempt
                or approval.task_attempt != record.test_attempt
                or approval.payload_digest != record.payload_digest
                or record.approval_id in approvals
                or tuple(approval.payload.get("artifact_refs", [])) != record.artifact_refs
                or set(record.artifact_hashes) != set(record.artifact_refs)
            ):
                raise StateConflict("Persisted patch revision does not match its plan or attempt")
            self._evidence(mission, test, approval)
            if any(
                self.repository.artifact(ref).sha256 != record.artifact_hashes[ref]
                for ref in record.artifact_refs
            ):
                raise StateConflict("Revision artifact digest changed")
            previous_patch, previous_test = record.patch_attempt, record.test_attempt
            approvals.add(record.approval_id)

    def _eligible(self, mission: Mission) -> tuple[Task, Task, Approval]:
        patch, test = self._tasks(mission)
        self.validate(mission)
        if len(mission.developer_revisions) >= 2:
            raise StateConflict(
                "The two patch revision cycles have been used; create a new mission"
            )
        if (
            mission.status != MissionStatus.FAILED
            or patch.status != TaskStatus.COMPLETED
            or test.status != TaskStatus.FAILED
            or not test.outputs
            or test.outputs.get("passed") is not False
            or any(t.status != TaskStatus.COMPLETED for t in mission.tasks if t.id != test.id)
            or self.repository.claim(mission.id) is not None
            or self.repository.approvals(mission.id)
        ):
            raise StateConflict(
                "Inspect and deny the failed-test result before requesting a revision"
            )
        candidates = [
            a
            for a in self.repository.approvals(mission.id, pending_only=False)
            if a.task_id == test.id
            and a.task_attempt == test.attempts
            and a.status == ApprovalStatus.DENIED
        ]
        if len(candidates) != 1:
            raise StateConflict("The current failed attempt has no unique human denial")
        approval = candidates[0]
        if approval.payload != review_payload(test):
            raise StateConflict("The current failed result differs from its denial")
        contents = self._evidence(mission, test, approval)
        if contents != review_evidence(mission, test, test.outputs):
            raise StateConflict("The denied evidence differs from the current patch")
        return patch, test, approval

    def status(self, mission: Mission) -> PatchRevisionStatus:
        try:
            _, _, approval = self._eligible(mission)
        except (ValueError, KeyError, StopIteration, MissionNotFound):
            return PatchRevisionStatus(
                allowed=False,
                remaining=max(0, 2 - len(mission.developer_revisions)),
                reason="Revision unavailable. Check the denied test evidence and revision limit.",
            )
        return PatchRevisionStatus(
            allowed=True,
            remaining=2 - len(mission.developer_revisions),
            approval_id=approval.id,
            payload_digest=approval.payload_digest,
        )

    def request(
        self, mission_id: str, request: PatchRevisionRequest, role: UserRole, actor: str = "local"
    ) -> Mission:
        require_operator(role)
        mission = self.repository.get(mission_id)
        if mission.version != request.expected_version:
            raise StateConflict("Mission version is stale")
        patch, test, approval = self._eligible(mission)
        if request.approval_id != approval.id or request.payload_digest != approval.payload_digest:
            raise StateConflict("Revision request does not match the current denied result")
        now = datetime.now(UTC)
        record = DeveloperRevision(
            number=len(mission.developer_revisions) + 1,
            feedback=request.feedback,
            requested_at=now,
            requested_by=actor,
            patch_task_id=patch.id,
            test_task_id=test.id,
            patch_attempt=patch.attempts,
            test_attempt=test.attempts,
            approval_id=approval.id,
            payload_digest=approval.payload_digest,
            plan_digest=plan_digest(mission),
            artifact_refs=test.artifact_refs,
            artifact_hashes={
                ref: self.repository.artifact(ref).sha256 for ref in test.artifact_refs
            },
        )
        tasks = refresh_dependencies(
            tuple(
                t.model_copy(
                    update={
                        "status": TaskStatus.PENDING,
                        "outputs": None,
                        "artifact_refs": (),
                        "error": None,
                    }
                )
                if t.id in {patch.id, test.id}
                else t
                for t in mission.tasks
            )
        )
        updated = mission.model_copy(
            update={
                "tasks": tasks,
                "version": mission.version + 1,
                "updated_at": now,
                "developer_revisions": (*mission.developer_revisions, record),
            }
        )
        events = [
            NewEvent(
                timestamp=now,
                actor=actor,
                action="patch_revision_requested",
                task_id=patch.id,
                details={
                    "number": record.number,
                    "approval_id": approval.id,
                    "patch_attempt": patch.attempts,
                    "test_attempt": test.attempts,
                    "feedback_sha256": hashlib.sha256(request.feedback.encode()).hexdigest(),
                },
            )
        ]
        events.extend(
            NewEvent(
                timestamp=now,
                actor=actor,
                action="task_state_changed",
                task_id=after.id,
                details={"from": before.status, "to": after.status, "attempts": after.attempts},
            )
            for before, after in zip(mission.tasks, tasks, strict=True)
            if before.status != after.status
        )
        return self.repository.save(updated, mission.version, events)

    def context(self, mission: Mission, task: Task) -> PatchRevisionContext | None:
        if (
            not mission.developer_revisions
            or mission.developer_revisions[-1].patch_task_id != task.id
        ):
            return None
        self.validate(mission)
        record = mission.developer_revisions[-1]
        approval = self.repository.approval(record.approval_id)
        test = next(t for t in mission.tasks if t.id == record.test_task_id)
        evidence = self._evidence(mission, test, approval)
        return PatchRevisionContext(
            number=record.number, feedback=record.feedback, previous_diff=evidence["tested.diff"]
        )
