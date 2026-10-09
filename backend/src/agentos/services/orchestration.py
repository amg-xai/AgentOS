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
        from agentos.services.revisions import PatchRevisionService

        revisions = PatchRevisionService(
            self.registry, self.repository, self.executors, self.artifacts
        )
        revisions.validate(mission)
        if any(
            t.agent_id
            in {a.id for a in self.registry.agents() if a.capability == "developer_issue"}
            for t in mission.tasks
        ) and not (
            mission.role_id == "developer"
            and mission.planning
            and mission.planning.contract_version == 3
        ):
            raise StateConflict("Local issues require a validated version-3 Developer plan")
        if any(
            t.agent_id
            in {a.id for a in self.registry.agents() if a.capability == "creator_thumbnail"}
            for t in mission.tasks
        ) and not (
            mission.role_id == "creator"
            and mission.planning
            and mission.planning.contract_version == 2
        ):
            raise StateConflict("Graphic thumbnails require an explicit validated Creator plan")
        if mission.planning is not None:
            if mission.role_id == "creator":
                from agentos.services.creator_planning import validate_creator_plan

                validate_creator_plan(mission, self.registry, self.executors)
            elif mission.role_id == "student":
                from agentos.services.student_planning import validate_student_plan

                validate_student_plan(mission, self.registry, self.executors)
            else:
                from agentos.services.planning import validate_planned_mission

                validate_planned_mission(mission, self.registry, self.executors)
                from agentos.services.planning import validate_issue_artifacts

                validate_issue_artifacts(mission, self.repository, self.artifacts)
        from agentos.services.creator import has_sources, validate_source_mission

        if has_sources(mission) and mission.planning is None:
            validate_source_mission(mission, self.registry, self.executors)
        from agentos.services.student import has_study_plan, validate_study_mission

        if has_study_plan(mission) and mission.planning is None:
            validate_study_mission(mission, self.registry, self.executors)
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
                    from agentos.services.planning import validate_issue_artifacts

                    validate_issue_artifacts(mission, self.repository, self.artifacts)
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
                            patch_revision=revisions.context(mission, task),
                        ),
                    )
                    mission = self._finish(mission, task, result, claim.token, actor)
                except Exception as exc:
                    # Keep raw provider errors/inputs (which may contain secrets) out of audit logs.
                    from agentos.domain.student import StudyPlanningError
                    from agentos.domain.thumbnail import ThumbnailRenderingError

                    mission = lifecycle.act(
                        mission.id,
                        task.id,
                        TaskActionRequest(
                            expected_version=mission.version,
                            action=TaskAction.FAIL,
                            error=exc.safe_message
                            if isinstance(exc, (StudyPlanningError, ThumbnailRenderingError))
                            else f"Execution failed ({type(exc).__name__}); check configuration",
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
        from agentos.services.student import has_study_plan, study_review_evidence

        if (
            mission.role_id == "developer"
            and mission.planning
            and mission.planning.contract_version == 3
            and self.registry.agent(task.agent_id).capability == "developer_issue"
        ):
            from agentos.domain.issue import issue_evidence

            expected_issue = issue_evidence(result.outputs.get("issue"))
            if (
                result.artifact_refs
                or len(result.artifacts) != len(expected_issue)
                or {draft.name: draft.content for draft in result.artifacts} != expected_issue
            ):
                raise StateConflict("Issue must own exact structured and text evidence")
        if mission.role_id == "student" and mission.planning is not None:
            from agentos.services.student import student_review_evidence
            from agentos.services.student_planning import student_kind, validate_student_output

            validate_student_output(
                student_kind(self.registry.agent(task.agent_id)), result.outputs
            )
            if task.review_required:
                expected_study = student_review_evidence(mission, task, result.outputs)
                if (
                    result.artifact_refs
                    or len(result.artifacts) != len(expected_study)
                    or {a.name: a.content for a in result.artifacts} != expected_study
                ):
                    raise StateConflict(
                        "Student review must own the exact complete evidence bundle"
                    )
        elif has_study_plan(mission):
            from agentos.domain.student import Quiz

            if task.id == "notes":
                notes = result.outputs.get("notes")
                if not isinstance(notes, str) or not notes.strip() or len(notes) > 24000:
                    raise StateConflict("Study planning requires bounded nonblank notes")
            if task.id == "quiz":
                Quiz.model_validate(result.outputs)
            if task.review_required:
                expected_study = study_review_evidence(mission, result.outputs)
                if (
                    result.artifact_refs
                    or len(result.artifacts) != len(expected_study)
                    or {draft.name: draft.content for draft in result.artifacts} != expected_study
                ):
                    raise StateConflict("Study review must own the exact complete evidence bundle")
        if task.requires_passed_tests and type(result.outputs.get("passed")) is not bool:
            raise StateConflict("Test execution must record an explicit boolean outcome")
        from agentos.services.creator import (
            creator_review_evidence,
            has_sources,
            source_review_evidence,
        )

        if has_sources(mission) and (
            task.id == "research"
            if mission.planning is None
            else self.registry.agent(task.agent_id).capability == "creator_research"
        ):
            from agentos.domain.creator import ResearchResult
            from agentos.domain.workspace import CreatorMissionCreate

            ResearchResult.model_validate(result.outputs).verify(
                CreatorMissionCreate(goal=mission.goal, sources=task.inputs["sources"]).sources
            )
        if (
            mission.role_id == "creator"
            and task.review_required
            and (has_sources(mission) or mission.planning)
        ):
            expected_creator = (
                creator_review_evidence(mission, task, result.outputs)
                if mission.planning
                else source_review_evidence(mission, result.outputs)
            )
            if (
                result.artifact_refs
                or len(result.artifacts) != len(expected_creator)
                or {draft.name: draft.content for draft in result.artifacts} != expected_creator
                or any(
                    draft.media_type
                    != (
                        "image/png"
                        if draft.name == "thumbnail.png"
                        else "text/markdown"
                        if draft.name.endswith(".md")
                        else "text/plain"
                    )
                    for draft in result.artifacts
                )
            ):
                raise StateConflict("Creator review must own exact source and research evidence")
        if (
            mission.role_id == "developer"
            and mission.planning
            and mission.planning.contract_version in (2, 3)
            and task.review_required
        ):
            from agentos.services.planning import review_evidence, validate_issue_artifacts

            validate_issue_artifacts(mission, self.repository, self.artifacts)
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
                payload = review_payload(updated_task, updated)
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
