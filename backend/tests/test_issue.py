"""Developer v3 contracts and real scoped journeys using injected models only."""

import asyncio
import copy
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_developer import ISSUE, PATCH, configured_app, issue_plan, model_transport, plan_data
from test_developer import workspace as workspace_fixture
from test_orchestration import FixtureExecutor, bindings
from test_planning import reply
from test_revisions import BAD_PATCH, deny, revision_body, run, transport_for

from agentos.adapters.artifacts import ArtifactStore
from agentos.adapters.developer import DeveloperExecutor
from agentos.adapters.sqlite import SQLiteMissionRepository
from agentos.adapters.workspace import WorkspaceStore
from agentos.domain.agents import AgentResult, ExecutionContext, Permission
from agentos.domain.artifacts import ArtifactDraft
from agentos.domain.governance import ApprovalDecision, UserRole
from agentos.domain.issue import IssueSpec, issue_evidence
from agentos.domain.missions import MissionValidationError, StateConflict
from agentos.services.approvals import ApprovalService
from agentos.services.missions import MissionService
from agentos.services.orchestration import Orchestrator
from agentos.services.planning import DeveloperPlan, compile_plan, developer_kind
from agentos.services.tools import ToolRegistry

workspace = workspace_fixture


def compile_issue(registry, data=None):
    executors = bindings(FixtureExecutor())
    executors.register_agent("issue_specification", FixtureExecutor())
    return compile_plan(
        "Fix addition; preserve negative sums",
        DeveloperPlan.model_validate(data if data is not None else issue_plan()),
        "developer_planner",
        registry,
        executors,
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("title", ""),
        ("title", "x" * 161),
        ("problem", 42),
        ("expected_behavior", "x" * 4001),
        ("suggested_reproduction_steps", []),
        ("suggested_reproduction_steps", ["x"] * 9),
        ("proposed_acceptance_criteria", ["x" * 1001]),
        ("limitations", [None]),
        ("passed", True),
        ("title", "   "),
    ],
)
def test_issue_strict_bounds(field, value):
    with pytest.raises(ValidationError):
        IssueSpec.model_validate(ISSUE | {field: value})


@pytest.mark.parametrize("change", ["tools", "permissions", "input", "output"])
def test_issue_capability_is_tool_free_read_only_exact_schema(registry, change):
    agent = registry.agent("issue_specification")
    if change == "tools":
        updated = agent.model_copy(update={"tools": ("filesystem",)})
    elif change == "permissions":
        updated = agent.model_copy(update={"permissions": (Permission.READ, Permission.WRITE)})
    else:
        key = change + "_schema"
        schema = copy.deepcopy(getattr(agent, key))
        if change == "input":
            schema["properties"]["command"] = {"type": "string"}
        else:
            schema["properties"]["issue"]["properties"]["title"]["maxLength"] = 10000
        updated = agent.model_copy(update={key: schema})
    with pytest.raises(MissionValidationError):
        developer_kind(updated)


@pytest.mark.parametrize(
    "case",
    [
        "legacy",
        "missing_issue",
        "duplicate_issue",
        "missing_patch_issue",
        "wrong_output",
        "wrong_source",
        "different_findings",
        "early_review",
        "no_review",
        "cycle",
        "orphan",
        "context_on_patch",
        "wrong_role",
        "unsupported_assignment",
        "duplicate_binding",
    ],
)
def test_invalid_issue_plan_rejected_before_persistence(registry, case):
    data = issue_plan()
    by_id = {task["id"]: task for task in data["tasks"]}
    issue, patch, test = (by_id[key] for key in ("specify", "fix", "verify"))
    if case == "legacy":
        data = plan_data()
    elif case == "missing_issue":
        data["tasks"].remove(issue)
    elif case == "duplicate_issue":
        data["tasks"].append(issue | {"id": "extra_issue"})
    elif case == "missing_patch_issue":
        patch["bindings"] = patch["bindings"][:-1]
        patch["dependencies"].remove("specify")
    elif case == "wrong_output":
        test["bindings"][-1]["output_key"] = "findings"
    elif case == "wrong_source":
        test["bindings"][-1]["task_id"] = "fix"
    elif case == "different_findings":
        data["tasks"].append(by_id["investigate"] | {"id": "other"})
        issue["dependencies"][0] = "other"
        issue["bindings"][0]["task_id"] = "other"
    elif case == "early_review":
        issue["review_required"] = True
    elif case == "no_review":
        test["review_required"] = False
    elif case == "cycle":
        issue["dependencies"][0] = "fix"
        issue["bindings"][0]["task_id"] = "fix"
    elif case == "orphan":
        data["tasks"].append(by_id["investigate"] | {"id": "orphan"})
    elif case == "context_on_patch":
        patch["bindings"][0]["input_key"] = "context"
    elif case == "wrong_role":
        issue["agent_id"] = "creator_script"
    elif case == "unsupported_assignment":
        issue["agent_id"] = "developer_planner"
    else:
        issue["bindings"].append(copy.deepcopy(issue["bindings"][0]))
    with pytest.raises((MissionValidationError, ValidationError, StateConflict)):
        compile_issue(registry, data)


@pytest.mark.parametrize("refine", [False, True])
def test_unsorted_issue_plan_preserves_goal_and_server_version(registry, refine):
    data = issue_plan(plan_data(refine=refine))
    data["tasks"].reverse()
    mission = compile_issue(registry, data)
    assert mission.planning.contract_version == 3
    for task in mission.tasks:
        if task.agent_id != "testing":
            assert task.inputs["goal"] == mission.goal
            assert task.inputs["constraints"] == data["constraints"]
    assert {task.agent_id for task in mission.tasks} == {
        "investigation",
        "baseline_testing",
        "issue_specification",
        "code_helper",
        "testing",
    }


def test_missing_issue_executor_rejected(registry):
    with pytest.raises(StateConflict, match="No executor"):
        compile_plan(
            "Fix",
            DeveloperPlan.model_validate(issue_plan()),
            "developer_planner",
            registry,
            bindings(FixtureExecutor()),
        )


def test_issue_executor_does_not_fetch_files_memory_or_tools(registry, tmp_path):
    class Generator:
        async def generate(self, agent, inputs):
            assert set(inputs) == {
                "goal",
                "objective",
                "constraints",
                "findings",
                "baseline_summary",
            }
            return {"issue": ISSUE}

    executor = DeveloperExecutor(
        Generator(),
        ToolRegistry(lambda event: None),
        WorkspaceStore(tmp_path / "w.db"),
        UserRole.OPERATOR,
    )
    result = asyncio.run(
        executor.execute(
            registry.agent("issue_specification"),
            {
                "goal": "Fix",
                "objective": "Specify",
                "constraints": [],
                "findings": "Subtracts",
                "baseline_summary": "Failed",
            },
            ExecutionContext(
                workspace_id="local", mission_id="absent", task_id="issue", planning_version=3
            ),
        )
    )
    assert result.outputs == {"issue": ISSUE}
    assert {artifact.name: artifact.content for artifact in result.artifacts} == issue_evidence(
        ISSUE
    )
    assert "not proof" in result.artifacts[1].content


def test_invalid_issue_output_blocks_patch_and_review(tmp_path, workspace):
    calls = []

    def transport(request):
        name = json.loads(request.content)["text"]["format"]["name"]
        calls.append(name)
        return (
            reply({"issue": ISSUE | {"passed": True}})
            if name == "issue_specification"
            else model_transport(request)
        )

    with TestClient(configured_app(tmp_path, workspace, transport)) as client:
        mission = client.post("/workflows/developer", json={"goal": "Fix addition"}).json()
        result = run(client, f"/missions/{mission['id']}", mission)
        tasks = {task["id"]: task for task in result["tasks"]}
        assert tasks["specify"]["status"] == "FAILED"
        assert tasks["fix"]["status"] == tasks["verify"]["status"] == "BLOCKED"
        assert "code_helper" not in calls
        assert client.get(f"/missions/{mission['id']}/approvals").json() == []


@pytest.mark.parametrize(
    "damage",
    [
        "tested.diff",
        "test-report.txt",
        "reviewed-baseline-report.txt",
        "reviewed-issue.json",
        "reviewed-issue.md",
        "issue_output",
        "invalid_issue_output",
        "goal",
        "binding",
        "version",
    ],
)
def test_exact_review_evidence_and_plan_integrity_on_restart(tmp_path, workspace, damage):
    with TestClient(configured_app(tmp_path, workspace)) as client:
        mission = client.post("/workflows/developer", json={"goal": "Fix addition"}).json()
        base = f"/missions/{mission['id']}"
        result = run(client, base, mission)
        approval = client.get(base + "/approvals").json()[0]
        artifacts = client.get(base + "/artifacts").json()
        owned = [a for a in artifacts if a["id"] in approval["payload"]["artifact_refs"]]
        assert len(owned) == 5
        expected = issue_evidence(ISSUE, reviewed=True)
        for artifact in owned:
            if artifact["name"] in expected:
                assert (
                    client.get(f"/artifacts/{artifact['id']}/content").text
                    == expected[artifact["name"]]
                )
        assert approval["payload"]["plan_digest"]
    if damage.endswith((".diff", ".txt", ".json", ".md")):
        artifact = next(a for a in owned if a["name"] == damage)
        path = tmp_path / "artifacts" / (artifact["id"] + ".txt")
        # Use the same existing artifact layout as configured_app.
        if not path.exists():
            path = next(tmp_path.rglob(artifact["id"] + ".txt"))
        path.write_text("tampered", encoding="utf-8")
    else:
        if damage == "goal":
            result["goal"] = "Changed goal"
        elif damage == "issue_output":
            next(t for t in result["tasks"] if t["id"] == "specify")["outputs"]["issue"][
                "title"
            ] = "Changed issue"
        elif damage == "invalid_issue_output":
            next(t for t in result["tasks"] if t["id"] == "specify")["outputs"]["issue"] = (
                "Invalid issue"
            )
        elif damage == "binding":
            next(t for t in result["tasks"] if t["id"] == "verify")["input_bindings"]["issue"][
                "output_key"
            ] = "other"
        else:
            result["planning"]["contract_version"] = 2
        with sqlite3.connect(tmp_path / "missions.sqlite3") as connection:
            result.pop("status")
            connection.execute("UPDATE missions SET payload = ?", (json.dumps(result),))
    with TestClient(configured_app(tmp_path, workspace), raise_server_exceptions=False) as client:
        response = client.post(
            f"/approvals/{approval['id']}/decision",
            json={
                "expected_version": result["version"],
                "decision": "approve",
                "payload_digest": approval["payload_digest"],
            },
        )
        assert response.status_code in (409, 422), response.text


def test_saved_version_two_revision_remains_supported(tmp_path, workspace, registry):
    from test_planning import compiled

    request = compiled(registry)
    repository = SQLiteMissionRepository(tmp_path / "missions.sqlite3")
    mission = MissionService(registry, repository).create(request)
    calls = []
    with TestClient(
        configured_app(tmp_path, workspace, transport_for([BAD_PATCH, PATCH], calls))
    ) as client:
        base = f"/missions/{mission.id}"
        result = run(client, base, mission.model_dump(mode="json"))
        assert len(client.get(base + "/approvals").json()[0]["payload"]["artifact_refs"]) == 3
        failed, approval = deny(client, base, result)
        revised = client.post(base + "/patch-revision", json=revision_body(failed, approval)).json()
        passed = run(client, base, revised)
        assert passed["planning"]["contract_version"] == 2
        assert passed["tasks"][-1]["outputs"]["passed"] is True
        assert "issue" not in calls[-1]


def test_v3_preflight_rejects_tampered_goal_before_claim(registry, tmp_path):
    request = compile_issue(registry)
    repository = SQLiteMissionRepository(tmp_path / "m.db")
    mission = MissionService(registry, repository).create(
        request.model_copy(update={"goal": "Other"})
    )
    executor = FixtureExecutor()
    executors = bindings(executor)
    executors.register_agent("issue_specification", executor)
    runner = Orchestrator(registry, repository, executors, ArtifactStore(tmp_path / "artifacts"))
    with pytest.raises(MissionValidationError):
        asyncio.run(runner.run(mission.id, 1, UserRole.OPERATOR))
    assert not executor.calls and repository.claim(mission.id) is None


@pytest.mark.parametrize(
    "mode",
    [
        "missing_issue",
        "changed_issue",
        "missing_review",
        "changed_review",
        "false_outcome",
        "missing_outcome",
    ],
)
def test_issue_and_test_evidence_required_at_staging(registry, tmp_path, mode):
    class V3Executor(FixtureExecutor):
        async def execute(self, agent, inputs, context):
            if agent.capability == "developer_issue":
                evidence = issue_evidence(ISSUE)
                if mode == "missing_issue":
                    evidence.pop("issue.json")
                if mode == "changed_issue":
                    evidence["issue.md"] = "Other issue"
                return AgentResult(
                    outputs={"issue": ISSUE},
                    artifacts=tuple(
                        ArtifactDraft(name=name, content=text) for name, text in evidence.items()
                    ),
                )
            result = await super().execute(
                agent,
                inputs,
                context.model_copy(update={"planning_version": 2})
                if agent.capability == "developer_test"
                else context,
            )
            if agent.capability != "developer_test":
                return result
            evidence = issue_evidence(inputs["issue"], reviewed=True)
            if mode == "missing_review":
                evidence.pop("reviewed-issue.json")
            if mode == "changed_review":
                evidence["reviewed-issue.md"] = "Another issue"
            outputs = dict(result.outputs)
            if mode == "false_outcome":
                outputs["passed"] = False
            if mode == "missing_outcome":
                outputs.pop("passed")
            return AgentResult(
                outputs=outputs,
                artifacts=(
                    *result.artifacts,
                    *(ArtifactDraft(name=name, content=text) for name, text in evidence.items()),
                ),
            )

    executor = V3Executor()
    executors = bindings(executor)
    executors.register_agent("issue_specification", executor)
    repository = SQLiteMissionRepository(tmp_path / "m.db")
    store = ArtifactStore(tmp_path / "artifacts")
    mission = MissionService(registry, repository).create(compile_issue(registry))
    result = asyncio.run(
        Orchestrator(registry, repository, executors, store).run(mission.id, 1, UserRole.OPERATOR)
    )
    approvals = repository.approvals(mission.id)
    if mode == "false_outcome":
        assert result.status == "WAITING_APPROVAL" and len(approvals) == 1
        approval = approvals[0]
        with pytest.raises(StateConflict, match="explicitly pass"):
            ApprovalService(repository, store).decide(
                approval.id,
                ApprovalDecision(
                    expected_version=result.version,
                    decision="approve",
                    payload_digest=approval.payload_digest,
                ),
                UserRole.OPERATOR,
            )
    else:
        assert result.status == "FAILED" and not approvals
        if mode.endswith("issue"):
            assert not any(call[0] == "code_helper" for call in executor.calls)


@pytest.mark.parametrize("role", ["creator", "student"])
def test_other_roles_reject_developer_version_three(registry, tmp_path, workspace, role):
    request = compile_issue(registry).model_dump(mode="json")
    request["role_id"] = role
    with TestClient(configured_app(tmp_path, workspace)) as client:
        response = client.post("/missions", json=request)
        assert response.status_code in (409, 422)
        assert client.get("/missions").json() == []


def test_malformed_api_plan_and_manual_issue_rejected_before_persistence(
    registry, tmp_path, workspace
):
    request = compile_issue(registry).model_dump(mode="json")
    with TestClient(configured_app(tmp_path, workspace)) as client:
        request["goal"] = "Changed original goal"
        assert client.post("/missions", json=request).status_code == 422
        request["planning"] = None
        assert client.post("/missions", json=request).status_code == 409
        assert client.get("/missions").json() == []


def test_revision_retains_issue_and_recipe_after_settings_changes(tmp_path, workspace):
    calls = []
    transport = transport_for([BAD_PATCH, PATCH], calls)
    with TestClient(configured_app(tmp_path, workspace, transport)) as client:
        mission = client.post("/workflows/developer", json={"goal": "Fix addition"}).json()
        base = f"/missions/{mission['id']}"
        failed = run(client, base, mission)
        denied, approval = deny(client, base, failed)
        revised = client.post(base + "/patch-revision", json=revision_body(denied, approval)).json()
        original_issue = next(t for t in failed["tasks"] if t["id"] == "specify")
    from agentos.domain.workspace import WorkspaceSettings

    changed = WorkspaceSettings(
        **(
            workspace.model_dump()
            | {
                "files": ("calculator.py",),
                "test_commands": (("python", "missing.py"),),
                "test_timeout_seconds": 1,
            }
        )
    )
    (workspace.repository / "calculator.py").write_text("Changed source\n", encoding="utf-8")
    with TestClient(configured_app(tmp_path, changed, transport)) as client:
        result = run(client, base, revised)
        assert result["tasks"][-1]["outputs"]["passed"] is True
        assert next(t for t in result["tasks"] if t["id"] == "specify") == original_issue
        assert calls[0]["issue"] == calls[1]["issue"] == ISSUE
        assert calls[0]["source_files"] == calls[1]["source_files"]
        for line in failed["tasks"][-1]["outputs"]["report"].splitlines():
            if line.startswith(("Source SHA-256:", "Recipe SHA-256:")):
                assert line in result["tasks"][-1]["outputs"]["report"]
