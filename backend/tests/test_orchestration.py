import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from agentos.adapters.artifacts import ArtifactStore
from agentos.adapters.sqlite import SQLiteMissionRepository
from agentos.domain.agents import AgentResult, ProviderConfig
from agentos.domain.artifacts import ArtifactDraft
from agentos.domain.governance import ApprovalDecision, PermissionDenied, RecoveryRequest, UserRole
from agentos.domain.missions import MissionCreate, StateConflict, TaskActionRequest, TaskStatus
from agentos.services.approvals import ApprovalService
from agentos.services.execution import ExecutorRegistry
from agentos.services.missions import MissionService
from agentos.services.orchestration import Orchestrator


def execution_workflow(review_task="fix"):
    data = {
        "goal": "Fixture workflow: verify orchestration, not actual AI work",
        "tasks": [
            {
                "id": "investigate",
                "title": "Investigate",
                "agent_id": "investigation",
                "inputs": {"goal": "Fixture issue"},
            },
            {
                "id": "fix",
                "title": "Fix",
                "agent_id": "code_helper",
                "dependencies": ["investigate"],
                "input_bindings": {
                    "findings": {"task_id": "investigate", "output_key": "findings"}
                },
            },
            {
                "id": "verify",
                "title": "Verify",
                "agent_id": "testing",
                "dependencies": ["fix"],
                "input_bindings": {"diff": {"task_id": "fix", "output_key": "diff"}},
            },
        ],
    }
    for task in data["tasks"]:
        task["review_required"] = task["id"] == review_task
    return data


class FixtureExecutor:
    """Explicit test fixture; never registered by the application factory."""

    def __init__(self):
        self.calls = []
        self.fail = False

    async def execute(self, agent, inputs, context):
        self.calls.append((agent.id, inputs, context.task_id))
        if self.fail:
            raise RuntimeError("Secret provider error: API_KEY=do-not-persist")
        if agent.id == "investigation":
            return AgentResult(outputs={"findings": "Fixture evidence"})
        if agent.id == "baseline_testing":
            return AgentResult(
                outputs={
                    "baseline_passed": False,
                    "baseline_report": "Fixture baseline",
                    "baseline_summary": "Fixture baseline failed",
                }
            )
        if agent.id == "code_helper":
            diff = "--- a/example.py\n+++ b/example.py\n@@ -1 +1 @@\n-old\n+new\n"
            return AgentResult(
                outputs={"diff": diff, "summary": "Fixture patch"},
                artifacts=(
                    ArtifactDraft(name="proposed.diff", media_type="text/x-diff", content=diff),
                ),
            )
        if context.planning_version == 2:
            return AgentResult(
                outputs={"passed": True, "report": "Fixture test evidence"},
                artifacts=(
                    ArtifactDraft(name="tested.diff", content=inputs["diff"]),
                    ArtifactDraft(name="test-report.txt", content="Fixture test evidence"),
                    ArtifactDraft(
                        name="reviewed-baseline-report.txt", content=inputs["baseline_report"]
                    ),
                ),
            )
        return AgentResult(
            outputs={"passed": True, "report": "Fixture test evidence"},
            artifacts=(
                ArtifactDraft(
                    name="test-report.md", media_type="text/markdown", content="# Fixture\n"
                ),
            ),
        )


def bindings(executor):
    registry = ExecutorRegistry()
    for agent_id in ("investigation", "code_helper", "testing", "baseline_testing"):
        registry.register_agent(agent_id, executor)
    return registry


@pytest.fixture
def runtime(registry, tmp_path):
    repository = SQLiteMissionRepository(tmp_path / "runtime.sqlite3")
    storage = ArtifactStore(tmp_path / "artifacts")
    executor = FixtureExecutor()
    return SimpleNamespace(
        registry=registry,
        repository=repository,
        storage=storage,
        executor=executor,
        executors=bindings(executor),
        lifecycle=MissionService(registry, repository),
        approvals=ApprovalService(repository, storage),
        runner=Orchestrator(registry, repository, bindings(executor), storage),
    )


def create(runtime, review_task="fix"):
    return runtime.lifecycle.create(MissionCreate(**execution_workflow(review_task)))


def run(runtime, mission):
    return asyncio.run(runtime.runner.run(mission.id, mission.version, UserRole.OPERATOR))


def decide(runtime, mission, decision="approve", **changes):
    approval = runtime.repository.approvals(mission.id)[0]
    request = ApprovalDecision(
        **{
            "expected_version": mission.version,
            "decision": decision,
            "payload_digest": approval.payload_digest,
            **changes,
        }
    )
    return runtime.approvals.decide(approval.id, request, UserRole.OPERATOR)


def test_workflow_pauses_reviews_resumes_and_persists(runtime):
    mission = run(runtime, create(runtime))
    assert mission.status == "WAITING_APPROVAL"
    assert [a for a, _, _ in runtime.executor.calls] == ["investigation", "code_helper"]
    assert runtime.executor.calls[1][1] == {"findings": "Fixture evidence"}
    assert runtime.repository.claim(mission.id) is None
    artifact = runtime.repository.artifacts(mission.id)[0]
    assert runtime.storage.read(artifact).decode() == mission.tasks[1].outputs["diff"]
    reopened = SQLiteMissionRepository(runtime.repository.path)
    assert reopened.approvals(mission.id) == runtime.repository.approvals(mission.id)
    assert reopened.artifacts(mission.id) == [artifact]
    approval = runtime.repository.approvals(mission.id)[0]
    mission = decide(runtime, mission)
    assert mission.tasks[1].status == "COMPLETED"
    assert mission.tasks[2].status == "READY"
    mission = run(runtime, mission)
    assert mission.status == "COMPLETED"
    assert len(runtime.executor.calls) == 3
    assert runtime.executor.calls[2][1]["diff"] == mission.tasks[1].outputs["diff"]
    assert reopened.approval(approval.id).status == "APPROVED"
    assert len(runtime.repository.artifacts(mission.id)) == 2
    actions = {event.action for event in runtime.repository.events(mission.id)}
    assert {
        "run_claimed",
        "run_released",
        "approval_requested",
        "approval_decided",
        "artifact_created",
    } <= actions


def test_final_review_completes_without_rerunning_executor(runtime):
    mission = run(runtime, create(runtime, "verify"))
    assert len(runtime.executor.calls) == 3
    mission = decide(runtime, mission)
    assert mission.status == "COMPLETED"
    assert len(runtime.executor.calls) == 3


def test_denial_retry_requires_new_approval(runtime):
    mission = run(runtime, create(runtime))
    old = runtime.repository.approvals(mission.id)[0]
    mission = decide(runtime, mission, "deny")
    assert mission.status == "FAILED"
    assert mission.tasks[2].status == "BLOCKED"
    assert runtime.repository.approval(old.id).status == "DENIED"
    mission = runtime.lifecycle.act(
        mission.id,
        "fix",
        TaskActionRequest(
            expected_version=mission.version,
            action="retry",
        ),
    )
    mission = run(runtime, mission)
    current = runtime.repository.approvals(mission.id)[0]
    assert current.id != old.id
    assert current.task_attempt == 2
    assert [agent for agent, _, _ in runtime.executor.calls].count("investigation") == 1
    with pytest.raises(StateConflict):
        runtime.approvals.decide(
            old.id,
            ApprovalDecision(
                expected_version=mission.version,
                decision="approve",
                payload_digest=old.payload_digest,
            ),
            UserRole.ADMIN,
        )


def test_approval_rejects_stale_version_digest_replay_and_viewer(runtime):
    mission = run(runtime, create(runtime))
    approval = runtime.repository.approvals(mission.id)[0]
    for changes in ({"expected_version": mission.version - 1}, {"payload_digest": "0" * 64}):
        with pytest.raises(StateConflict):
            decide(runtime, mission, **changes)
    with pytest.raises(PermissionDenied):
        runtime.approvals.decide(
            approval.id,
            ApprovalDecision(
                expected_version=mission.version,
                decision="approve",
                payload_digest=approval.payload_digest,
            ),
            UserRole.VIEWER,
        )
    mission = decide(runtime, mission)
    with pytest.raises(StateConflict):
        runtime.approvals.decide(
            approval.id,
            ApprovalDecision(
                expected_version=mission.version,
                decision="approve",
                payload_digest=approval.payload_digest,
            ),
            UserRole.OPERATOR,
        )


def test_cancellation_invalidates_pending_approval(runtime):
    mission = run(runtime, create(runtime))
    approval = runtime.repository.approvals(mission.id)[0]
    mission = runtime.lifecycle.cancel(mission.id, mission.version)
    assert runtime.repository.approvals(mission.id) == []
    assert runtime.repository.approval(approval.id).status == "STALE"
    with pytest.raises(StateConflict):
        runtime.approvals.decide(
            approval.id,
            ApprovalDecision(
                expected_version=mission.version,
                decision="approve",
                payload_digest=approval.payload_digest,
            ),
            UserRole.ADMIN,
        )


def test_approval_cannot_accept_changed_outputs_or_artifacts(runtime):
    mission = run(runtime, create(runtime))
    artifact = runtime.repository.artifacts(mission.id)[0]
    (runtime.storage.root / f"{artifact.id}.txt").write_text("tampered", encoding="utf-8")
    with pytest.raises(StateConflict, match="integrity"):
        decide(runtime, mission)
    assert runtime.repository.approvals(mission.id)[0].status == "PENDING"
    # A denial remains possible when content is damaged.
    assert decide(runtime, mission, "deny").status == "FAILED"


def test_provider_failure_can_be_retried_without_leaking_error(runtime):
    runtime.executor.fail = True
    mission = run(runtime, create(runtime))
    assert mission.status == "FAILED"
    assert runtime.repository.claim(mission.id) is None
    persisted = mission.model_dump_json() + json.dumps(
        [event.model_dump(mode="json") for event in runtime.repository.events(mission.id)]
    )
    assert "API_KEY" not in persisted
    runtime.executor.fail = False
    mission = runtime.lifecycle.act(
        mission.id,
        "investigate",
        TaskActionRequest(
            expected_version=mission.version,
            action="retry",
        ),
    )
    assert run(runtime, mission).status == "WAITING_APPROVAL"


def test_missing_executor_has_no_state_changes(runtime):
    mission = create(runtime)
    runner = Orchestrator(runtime.registry, runtime.repository, ExecutorRegistry(), runtime.storage)
    with pytest.raises(StateConflict, match="No executor"):
        asyncio.run(runner.run(mission.id, mission.version, UserRole.OPERATOR))
    assert runtime.repository.get(mission.id) == mission
    assert runtime.repository.claim(mission.id) is None


def test_concurrent_runs_and_manual_mutations_cannot_duplicate_dispatch(runtime):
    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()

        class SlowExecutor(FixtureExecutor):
            async def execute(self, agent, inputs, context):
                if agent.id == "investigation":
                    started.set()
                    await release.wait()
                return await super().execute(agent, inputs, context)

        executor = SlowExecutor()
        runner = Orchestrator(
            runtime.registry, runtime.repository, bindings(executor), runtime.storage
        )
        mission = create(runtime)
        running = asyncio.create_task(runner.run(mission.id, mission.version, UserRole.OPERATOR))
        await asyncio.wait_for(started.wait(), 5)
        current = runtime.repository.get(mission.id)
        with pytest.raises(StateConflict):
            await runtime.runner.run(mission.id, current.version, UserRole.OPERATOR)
        with pytest.raises(StateConflict, match="claim"):
            runtime.lifecycle.cancel(mission.id, current.version)
        claim = runtime.repository.claim(mission.id)
        with pytest.raises(StateConflict, match="active local"):
            runner.recover(
                mission.id,
                RecoveryRequest(
                    expected_version=current.version,
                    claim_token=claim.token,
                    acknowledge_ambiguity=True,
                ),
                UserRole.ADMIN,
            )
        release.set()
        await asyncio.wait_for(running, 5)
        assert [agent for agent, _, _ in executor.calls].count("investigation") == 1

    asyncio.run(scenario())


def test_interrupted_claim_needs_explicit_admin_recovery(runtime):
    class Interrupted(BaseException):
        pass

    class CrashExecutor(FixtureExecutor):
        async def execute(self, agent, inputs, context):
            raise Interrupted()

    runner = Orchestrator(
        runtime.registry, runtime.repository, bindings(CrashExecutor()), runtime.storage
    )
    mission = create(runtime)
    with pytest.raises(Interrupted):
        asyncio.run(runner.run(mission.id, mission.version, UserRole.OPERATOR))
    mission = runtime.repository.get(mission.id)
    assert mission.tasks[0].status == TaskStatus.RUNNING
    claim = runtime.repository.claim(mission.id)
    request = RecoveryRequest(
        expected_version=mission.version,
        claim_token=claim.token,
        acknowledge_ambiguity=True,
    )
    for role in (UserRole.VIEWER, UserRole.OPERATOR):
        with pytest.raises(PermissionDenied):
            runtime.runner.recover(mission.id, request, role)
    with pytest.raises(StateConflict):
        runtime.runner.recover(
            mission.id, request.model_copy(update={"acknowledge_ambiguity": False}), UserRole.ADMIN
        )
    mission = runtime.runner.recover(mission.id, request, UserRole.ADMIN)
    assert mission.status == "FAILED"
    assert runtime.repository.claim(mission.id) is None
    with pytest.raises(StateConflict, match="revoked"):
        runtime.repository.save(
            mission.model_copy(update={"version": mission.version + 1}),
            mission.version,
            [],
            claim_token=claim.token,
        )
    assert runtime.executor.calls == []


def test_invalid_bindings_and_schema_outputs_fail_before_completion(runtime):
    data = execution_workflow()
    data["tasks"][1]["input_bindings"]["findings"]["task_id"] = "verify"
    with pytest.raises(ValidationError, match="direct dependencies"):
        MissionCreate(**data)
    data = execution_workflow()
    data["tasks"][1]["input_bindings"]["findings"]["output_key"] = "missing"
    mission = runtime.lifecycle.create(MissionCreate(**data))
    mission = run(runtime, mission)
    assert mission.tasks[1].status == "FAILED"
    assert len(runtime.executor.calls) == 1


def test_executor_provider_resolution_and_duplicate_bindings(registry):
    executor = FixtureExecutor()
    configured = registry.agent("investigation").model_copy(
        update={
            "provider": ProviderConfig(provider="example", model="example"),
        }
    )
    catalog = ExecutorRegistry()
    catalog.register_provider("example", executor)
    assert catalog.resolve(configured) is executor
    with pytest.raises(ValueError, match="Duplicate provider"):
        catalog.register_provider("example", executor)
    catalog.register_agent("investigation", executor)
    with pytest.raises(ValueError, match="Duplicate executor"):
        catalog.register_agent("investigation", executor)


def test_tool_calls_have_persisted_audit_scope(runtime):
    from test_tools import ToyTool, tool

    from agentos.services.tools import ToolRegistry

    catalog = ToolRegistry(runtime.repository.record_tool_event)
    catalog.register(tool(), ToyTool())

    class AuditedExecutor(FixtureExecutor):
        async def execute(self, agent, inputs, context):
            if agent.id == "investigation":
                await catalog.execute(
                    "filesystem", agent, UserRole.OPERATOR, {"value": "fixture"}, context
                )
            return await super().execute(agent, inputs, context)

    executor = AuditedExecutor()
    runtime.runner = Orchestrator(
        runtime.registry, runtime.repository, bindings(executor), runtime.storage
    )
    mission = run(runtime, create(runtime))
    events = [e for e in runtime.repository.events(mission.id) if e.action.startswith("tool_")]
    assert [e.action for e in events] == ["tool_started", "tool_completed"]
    assert {e.task_id for e in events} == {"investigate"}
    assert events[0].details == {"tool_id": "filesystem", "role": "operator"}
    assert "run_token" not in events[0].model_dump_json()


def test_invalid_executor_output_fails_the_task(runtime):
    class InvalidExecutor(FixtureExecutor):
        async def execute(self, agent, inputs, context):
            return AgentResult(outputs={"findings": 123})

    runtime.runner = Orchestrator(
        runtime.registry, runtime.repository, bindings(InvalidExecutor()), runtime.storage
    )
    mission = run(runtime, create(runtime))
    assert mission.tasks[0].status == "FAILED"
    assert runtime.repository.approvals(mission.id) == []


def test_executor_cannot_attach_another_missions_artifact(runtime):
    first = run(runtime, create(runtime))
    artifact = runtime.repository.artifacts(first.id)[0]

    class WrongScopeExecutor(FixtureExecutor):
        async def execute(self, agent, inputs, context):
            result = await super().execute(agent, inputs, context)
            if agent.id == "code_helper":
                return AgentResult(outputs=result.outputs, artifact_refs=(artifact.id,))
            return result

    runtime.runner = Orchestrator(
        runtime.registry, runtime.repository, bindings(WrongScopeExecutor()), runtime.storage
    )
    second = run(runtime, create(runtime))
    assert second.tasks[1].status == "FAILED"
    assert runtime.repository.artifacts(second.id) == []
    assert runtime.storage.read(artifact)


def test_concurrent_approval_decisions_only_one_commits(runtime):
    mission = run(runtime, create(runtime))
    approval = runtime.repository.approvals(mission.id)[0]

    def decide_once():
        try:
            runtime.approvals.decide(
                approval.id,
                ApprovalDecision(
                    expected_version=mission.version,
                    decision="approve",
                    payload_digest=approval.payload_digest,
                ),
                UserRole.OPERATOR,
            )
            return "approved"
        except StateConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: decide_once(), range(2))) == ["approved", "conflict"]
    assert (
        len(
            [
                event
                for event in runtime.repository.events(mission.id)
                if event.action == "approval_decided"
            ]
        )
        == 1
    )


def test_manual_completion_cannot_bypass_required_review(runtime):
    mission = create(runtime, "investigate")
    mission = runtime.lifecycle.act(
        mission.id,
        "investigate",
        TaskActionRequest(
            expected_version=mission.version,
            action="start",
        ),
    )
    with pytest.raises(StateConflict, match="orchestration and approval"):
        runtime.lifecycle.act(
            mission.id,
            "investigate",
            TaskActionRequest(
                expected_version=mission.version,
                action="complete",
                outputs={"findings": "bypass"},
            ),
        )
