"""Deterministic planning plus real scoped tools; no live transport is permitted."""

import asyncio
import copy
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_developer import PATCH, configured_app, model_transport, plan_data
from test_developer import workspace as workspace_fixture
from test_orchestration import FixtureExecutor, bindings

from agentos.adapters.artifacts import ArtifactStore
from agentos.adapters.provider import ModelSettings, ProviderFailure, ResponsesExecutor
from agentos.adapters.sqlite import SQLiteMissionRepository
from agentos.api.app import create_app
from agentos.domain.agents import AgentResult, Permission
from agentos.domain.governance import UserRole
from agentos.domain.missions import MissionValidationError, StateConflict, TaskSpec
from agentos.services.execution import ExecutorRegistry
from agentos.services.missions import MissionService
from agentos.services.orchestration import Orchestrator
from agentos.services.planning import (
    DeveloperPlan,
    compile_plan,
    developer_kind,
    validate_planned_mission,
)
from agentos.services.registry import AgentRegistry

workspace = workspace_fixture


def compiled(registry, data=None, executors=None):
    return compile_plan(
        "Fix addition; preserve negative sums",
        DeveloperPlan.model_validate(data or plan_data()),
        "developer_planner",
        registry,
        executors or bindings(FixtureExecutor()),
    )


def test_valid_unsorted_plan_preserves_goal_constraints_objectives_and_bindings(registry):
    data = plan_data(refine=True)
    data["tasks"] = list(reversed(data["tasks"]))
    result = compiled(registry, data)
    assert result.goal == "Fix addition; preserve negative sums"
    assert len(result.tasks) == 5 and result.planning.rationale == data["rationale"]
    for task in result.tasks:
        if task.agent_id != "testing":
            assert task.inputs["goal"] == result.goal
            assert task.inputs["constraints"] == data["constraints"]
            assert task.inputs["objective"] == result.planning.objectives[task.id]
    test = next(task for task in result.tasks if task.agent_id == "testing")
    assert test.review_required and test.requires_passed_tests and not test.inputs


@pytest.mark.parametrize("task_count", [5, 8])
def test_branching_plans_deliver_distinct_evidence_to_one_tested_patch(
    tmp_path, workspace, task_count
):
    data = plan_data()
    investigate, patch, baseline, test = data["tasks"]
    context = investigate | {
        "id": "inspect_tests",
        "objective": "Inspect test intent independently",
    }
    investigations = [investigate, context]
    upstream = investigate["id"]
    for index in range(task_count - 5):
        task = investigate | {
            "id": f"refine_{index}",
            "objective": f"Refine source evidence {index}",
            "dependencies": [upstream],
            "bindings": [{"input_key": "context", "task_id": upstream, "output_key": "findings"}],
        }
        investigations.append(task)
        upstream = task["id"]
    patch["dependencies"] = [upstream, context["id"], "baseline"]
    patch["bindings"] = [
        {"input_key": "findings", "task_id": upstream, "output_key": "findings"},
        {"input_key": "context", "task_id": context["id"], "output_key": "findings"},
        {"input_key": "baseline_summary", "task_id": "baseline", "output_key": "baseline_summary"},
    ]
    data["tasks"] = list(reversed([*investigations, patch, baseline, test]))
    requests = []

    def transport(request):
        body = json.loads(request.content)
        inputs = json.loads(body["input"])
        name = body["text"]["format"]["name"]
        requests.append((name, inputs))
        if name == "developer_planner":
            return reply(data)
        if name == "investigation":
            return reply({"findings": inputs["objective"]})
        assert inputs["context"] == context["objective"]
        assert inputs["findings"] == next(
            task["objective"] for task in investigations if task["id"] == upstream
        )
        assert inputs["goal"] == "Fix addition without changing tests"
        assert inputs["constraints"] == data["constraints"]
        return reply({"diff": PATCH, "summary": "Fix the operator, preserve test intent"})

    originals = {name: (workspace.repository / name).read_bytes() for name in workspace.files}
    with TestClient(configured_app(tmp_path, workspace, transport)) as client:
        mission = client.post(
            "/workflows/developer", json={"goal": "Fix addition without changing tests"}
        ).json()
        result = client.post(f"/missions/{mission['id']}/run", json={"expected_version": 1}).json()
        assert result["status"] == "WAITING_APPROVAL" and len(result["tasks"]) == task_count
        review = next(task for task in result["tasks"] if task["id"] == "verify")
        assert review["outputs"]["passed"] is True
        assert sum(name == "investigation" for name, _ in requests) == task_count - 3
        assert len(client.get(f"/missions/{mission['id']}/approvals").json()) == 1
    assert originals == {
        name: (workspace.repository / name).read_bytes() for name in workspace.files
    }


def test_changed_input_contract_rejects_saved_plan_safely_before_execution(
    registry, tmp_path, workspace
):
    repository = SQLiteMissionRepository(tmp_path / "saved.sqlite3")
    request = compiled(registry)
    mission = MissionService(registry, repository).create(request)
    agent = registry.agent("investigation")
    schema = copy.deepcopy(agent.input_schema)
    schema["properties"]["goal"]["minLength"] = 8001
    catalog = AgentRegistry(
        [
            other.model_copy(update={"input_schema": schema}) if other.id == agent.id else other
            for other in registry.agents()
        ],
        registry.roles(),
        {"filesystem", "git", "terminal"},
    )

    def no_generation(request):
        pytest.fail("Invalid saved plan must be rejected before model dispatch")

    model = ResponsesExecutor(
        ModelSettings(model="injected-test"), transport=httpx.MockTransport(no_generation)
    )
    with TestClient(
        create_app(catalog, db_path=repository.path, workspace=workspace, model=model),
        raise_server_exceptions=False,
    ) as client:
        response = client.post(f"/missions/{mission.id}/run", json={"expected_version": 1})
        assert response.status_code == 422
        assert response.json()["detail"] == "Planned task inputs do not match the executor schema"
        assert mission.goal not in response.text
        assert client.get(f"/missions/{mission.id}").json()["version"] == 1
        assert client.get(f"/missions/{mission.id}/run").json() is None
        assert client.get(f"/missions/{mission.id}/artifacts").json() == []
        assert client.get(f"/missions/{mission.id}/approvals").json() == []


def invalid_data(case):
    data = copy.deepcopy(plan_data())
    investigate, patch, baseline, test = data["tasks"]
    if case == "cycle":
        investigate["dependencies"] = ["fix"]
        investigate["bindings"] = [{"input_key": "context", "task_id": "fix", "output_key": "diff"}]
    elif case == "unknown_dependency":
        patch["dependencies"] = ["absent"]
        patch["bindings"][0]["task_id"] = "absent"
    elif case == "duplicate_id":
        test["id"] = patch["id"]
    elif case == "unknown_agent":
        patch["agent_id"] = "missing"
    elif case == "wrong_role":
        patch["agent_id"] = "creator_script"
    elif case == "planner_as_executor":
        patch["agent_id"] = "developer_planner"
    elif case == "wrong_output":
        patch["bindings"][0]["output_key"] = "report"
    elif case == "wrong_input":
        patch["bindings"][0]["input_key"] = "command"
    elif case == "no_findings":
        patch["bindings"] = []
    elif case == "duplicate_binding":
        patch["bindings"].append(copy.deepcopy(patch["bindings"][0]))
    elif case == "no_review":
        test["review_required"] = False
    elif case == "early_review":
        patch["review_required"] = True
    elif case == "literal_diff":
        test["diff"] = PATCH
    elif case == "direct_source_test":
        test["dependencies"] = ["investigate"]
        test["bindings"][0].update(task_id="investigate", output_key="findings")
    elif case == "decorative_dependency":
        test["dependencies"].append("investigate")
    elif case == "orphan":
        data["tasks"].append(investigate | {"id": "orphan"})
    elif case == "multiple_patches":
        data["tasks"].append(patch | {"id": "extra_patch"})
    elif case == "multiple_tests":
        data["tasks"].append(test | {"id": "extra_test"})
    elif case == "too_many_tasks":
        data["tasks"] += [investigate | {"id": f"extra_{n}"} for n in range(6)]
    elif case == "too_few_tasks":
        data["tasks"] = [investigate, patch]
    elif case == "unsafe_objective_field":
        patch["permissions"] = ["DESTRUCTIVE"]
    elif case == "oversized_constraint":
        data["constraints"] = ["x" * 1001]
    return data


@pytest.mark.parametrize(
    "case",
    [
        "cycle",
        "unknown_dependency",
        "duplicate_id",
        "unknown_agent",
        "wrong_role",
        "planner_as_executor",
        "wrong_output",
        "wrong_input",
        "no_findings",
        "duplicate_binding",
        "no_review",
        "early_review",
        "literal_diff",
        "direct_source_test",
        "decorative_dependency",
        "orphan",
        "multiple_patches",
        "multiple_tests",
        "too_many_tasks",
        "too_few_tasks",
        "unsafe_objective_field",
        "oversized_constraint",
    ],
)
def test_invalid_plans_fail_before_execution(registry, case):
    executor = FixtureExecutor()
    with pytest.raises((MissionValidationError, ValidationError, StateConflict)):
        compiled(registry, invalid_data(case), bindings(executor))
    assert executor.calls == []


@pytest.mark.parametrize(
    "change", ["schema", "permissions", "capability", "output", "tools", "boolean_schema"]
)
def test_unsafe_or_unsupported_registered_capabilities_are_rejected(registry, change):
    agent = registry.agent("code_helper")
    if change == "schema":
        agent = agent.model_copy(update={"input_schema": {"type": "object"}})
    if change == "permissions":
        agent = agent.model_copy(
            update={"permissions": (*agent.permissions, Permission.DESTRUCTIVE)}
        )
    if change == "capability":
        agent = agent.model_copy(update={"capability": "shell"})
    if change == "output":
        schema = copy.deepcopy(agent.output_schema)
        schema["properties"]["diff"]["type"] = "integer"
        agent = agent.model_copy(update={"output_schema": schema})
    if change == "tools":
        agent = agent.model_copy(update={"tools": (*agent.tools, "terminal")})
    if change == "boolean_schema":
        schema = copy.deepcopy(agent.input_schema)
        schema["properties"]["goal"] = True
        agent = agent.model_copy(update={"input_schema": schema})
    with pytest.raises(MissionValidationError):
        developer_kind(agent)


def reply(output):
    return httpx.Response(
        200,
        json={
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": json.dumps(output)}],
                }
            ],
        },
    )


def test_goals_change_decomposition_and_persist_planning_evidence(tmp_path, workspace):
    requests = []

    def transport(request):
        body = json.loads(request.content)
        requests.append(body)
        if body["text"]["format"]["name"] == "developer_planner":
            inputs = json.loads(body["input"])
            assert {agent["capability"] for agent in inputs["agents"]} == {
                "developer_investigate",
                "developer_patch",
                "developer_test",
                "developer_baseline",
            }
            assert "source_files" not in inputs and "repository" not in inputs
            return reply(plan_data(refine="negative" in inputs["goal"]))
        return model_transport(request)

    with TestClient(configured_app(tmp_path, workspace, transport)) as client:
        simple = client.post("/workflows/developer", json={"goal": "Fix addition"}).json()
        refined = client.post(
            "/workflows/developer", json={"goal": "Fix addition preserving negative sums"}
        ).json()
        assert len(simple["tasks"]) == 4 and len(refined["tasks"]) == 5
        base = f"/missions/{refined['id']}"
        result = client.post(base + "/run", json={"expected_version": 1}).json()
        assert result["status"] == "WAITING_APPROVAL"
        assert result["tasks"][-1]["outputs"]["passed"] is True
        patch_request = next(
            body for body in requests if body["text"]["format"]["name"] == "code_helper"
        )
        inputs = json.loads(patch_request["input"])
        assert (
            inputs["goal"] == refined["goal"]
            and inputs["constraints"] == refined["planning"]["constraints"]
        )
        assert any(
            event["action"] == "mission_planned" and event["details"]["contract_version"] == 2
            for event in client.get(base + "/events").json()
        )
    reopened = SQLiteMissionRepository(tmp_path / "missions.sqlite3").get(refined["id"])
    assert reopened.planning.model_dump(mode="json") == refined["planning"]


def test_renamed_registered_agents_route_by_capability_not_hardcoded_ids(
    tmp_path, workspace, registry
):
    rename = {id: f"renamed_{id}" for id in registry.role("developer").agents}
    agents = [
        agent.model_copy(update={"id": rename.get(agent.id, agent.id)})
        for agent in registry.agents()
    ]
    roles = [
        role.model_copy(update={"agents": tuple(rename.get(id, id) for id in role.agents)})
        for role in registry.roles()
    ]
    catalog = AgentRegistry(agents, roles, {"filesystem", "git", "terminal"})

    def transport(request):
        body = json.loads(request.content)
        name = body["text"]["format"]["name"]
        if name == rename["developer_planner"]:
            data = plan_data()
            for task in data["tasks"]:
                task["agent_id"] = rename[task["agent_id"]]
            return reply(data)
        return reply(
            {"findings": "The implementation subtracts"}
            if name == rename["investigation"]
            else {"diff": PATCH, "summary": "Fix the operator"}
        )

    model = ResponsesExecutor(
        ModelSettings(model="injected-test"), transport=httpx.MockTransport(transport)
    )
    with TestClient(
        create_app(catalog, db_path=tmp_path / "state.sqlite3", workspace=workspace, model=model)
    ) as client:
        assert client.get("/status").json()["workflow_ready"] is True
        mission = client.post("/workflows/developer", json={"goal": "Fix addition"}).json()
        assert {task["agent_id"] for task in mission["tasks"]} == set(rename.values()) - {
            rename["developer_planner"]
        }
        result = client.post(f"/missions/{mission['id']}/run", json={"expected_version": 1}).json()
        assert (
            result["status"] == "WAITING_APPROVAL"
            and result["tasks"][-1]["outputs"]["passed"] is True
        )


@pytest.mark.parametrize("mode,status", [("invalid", 422), ("provider", 502)])
def test_failed_planning_creates_no_mission_or_tool_effect(tmp_path, workspace, mode, status):
    def transport(request):
        return (
            reply(invalid_data("no_review"))
            if mode == "invalid"
            else httpx.Response(401, text="private-key")
        )

    with TestClient(configured_app(tmp_path, workspace, transport)) as client:
        response = client.post("/workflows/developer", json={"goal": "Fix"})
        assert response.status_code == status and "private-key" not in response.text
        assert client.get("/missions").json() == []
        assert client.get("/overview").json()["total_artifacts"] == 0


def test_failed_tests_cannot_be_accepted_but_evidence_can_be_denied(tmp_path, workspace):
    (workspace.repository / "test_calculator.py").write_text(
        "import unittest\nclass TestFail(unittest.TestCase):\n"
        " def test_fail(self): self.assertTrue(False)\n"
    )
    with TestClient(configured_app(tmp_path, workspace)) as client:
        mission = client.post("/workflows/developer", json={"goal": "Fix addition"}).json()
        base = f"/missions/{mission['id']}"
        result = client.post(base + "/run", json={"expected_version": 1}).json()
        assert (
            result["status"] == "WAITING_APPROVAL"
            and result["tasks"][-1]["outputs"]["passed"] is False
        )
        approval = client.get(base + "/approvals").json()[0]
        payload = {
            "expected_version": result["version"],
            "payload_digest": approval["payload_digest"],
            "decision": "approve",
        }
        assert client.post(f"/approvals/{approval['id']}/decision", json=payload).status_code == 409
        assert client.get(base).json()["tasks"][-1]["outputs"]["passed"] is False
        assert (
            client.post(
                f"/approvals/{approval['id']}/decision", json=payload | {"decision": "deny"}
            ).json()["status"]
            == "FAILED"
        )


def test_dependency_failure_blocks_patch_tests_and_review(tmp_path, workspace):
    def transport(request):
        if json.loads(request.content)["text"]["format"]["name"] == "developer_planner":
            return model_transport(request)
        return httpx.Response(429)

    with TestClient(configured_app(tmp_path, workspace, transport)) as client:
        mission = client.post("/workflows/developer", json={"goal": "Fix"}).json()
        base = f"/missions/{mission['id']}"
        result = client.post(base + "/run", json={"expected_version": 1}).json()
        assert [task["status"] for task in result["tasks"]] == [
            "FAILED",
            "BLOCKED",
            "READY",
            "BLOCKED",
        ]
        assert client.get(base + "/approvals").json() == []
        assert client.get(base + "/artifacts").json() == []


def test_preexecution_revalidation_rejects_tampered_goal_without_executor_calls(registry):
    executor = FixtureExecutor()
    request = compiled(registry)
    with pytest.raises(MissionValidationError):
        validate_planned_mission(
            request.model_copy(update={"goal": "Changed goal"}), registry, bindings(executor)
        )
    assert executor.calls == []


def test_preexecution_validation_rejects_persisted_boundary_change_before_claim(registry, tmp_path):
    executor = FixtureExecutor()
    repository = SQLiteMissionRepository(tmp_path / "state.sqlite3")
    mission = MissionService(registry, repository).create(compiled(registry))
    tasks = tuple(
        task.model_copy(update={"requires_passed_tests": False})
        if task.agent_id == "testing"
        else task
        for task in mission.tasks
    )
    repository.save(mission.model_copy(update={"tasks": tasks, "version": 2}), 1, [])
    runner = Orchestrator(
        registry, repository, bindings(executor), ArtifactStore(tmp_path / "files")
    )
    with pytest.raises(MissionValidationError):
        asyncio.run(runner.run(mission.id, 2, UserRole.OPERATOR))
    assert executor.calls == [] and repository.claim(mission.id) is None


def test_plan_requires_registered_executor_bindings(registry):
    with pytest.raises(StateConflict, match="No executor"):
        compiled(registry, executors=ExecutorRegistry())


@pytest.mark.parametrize(
    "outputs", [{"report": "No outcome"}, {"passed": "true", "report": "Invalid"}]
)
def test_nonboolean_test_outcome_fails_without_creating_approval(registry, tmp_path, outputs):
    class InvalidTests(FixtureExecutor):
        async def execute(self, agent, inputs, context):
            if agent.capability == "developer_test":
                return AgentResult(outputs=outputs)
            return await super().execute(agent, inputs, context)

    executor = InvalidTests()
    executors = bindings(executor)
    repository = SQLiteMissionRepository(tmp_path / "state.sqlite3")
    mission = MissionService(registry, repository).create(compiled(registry, executors=executors))
    runner = Orchestrator(registry, repository, executors, ArtifactStore(tmp_path / "files"))
    result = asyncio.run(runner.run(mission.id, 1, UserRole.OPERATOR))
    assert result.status == "FAILED" and result.tasks[-1].outputs is None
    assert repository.approvals(mission.id) == []


def test_planned_tasks_cannot_be_manually_started_or_completed(tmp_path, workspace):
    with TestClient(configured_app(tmp_path, workspace)) as client:
        mission = client.post("/workflows/developer", json={"goal": "Fix addition"}).json()
        base = f"/missions/{mission['id']}/tasks/investigate/actions"
        for action in ["start", "complete"]:
            payload = {"expected_version": 1, "action": action}
            if action == "complete":
                payload["outputs"] = {"findings": "Invented"}
            assert client.post(base, json=payload).status_code == 409
        assert client.get(f"/missions/{mission['id']}").json()["version"] == 1


def test_unsupported_planner_contract_reports_unavailable_before_generation(
    registry, tmp_path, workspace
):
    agents = [
        agent.model_copy(update={"permissions": (Permission.EXECUTE,)})
        if agent.capability == "developer_plan"
        else agent
        for agent in registry.agents()
    ]
    catalog = AgentRegistry(agents, registry.roles(), {"filesystem", "git", "terminal"})

    def no_generation(request):
        pytest.fail("Unsupported planner must fail before provider dispatch")

    model = ResponsesExecutor(
        ModelSettings(model="injected-test"), transport=httpx.MockTransport(no_generation)
    )
    with TestClient(
        create_app(catalog, db_path=tmp_path / "state.sqlite3", workspace=workspace, model=model)
    ) as client:
        assert client.get("/status").json()["workflow_ready"] is False
        assert client.post("/workflows/developer", json={"goal": "Fix"}).status_code == 409
        assert client.get("/missions").json() == []


def test_boundary_cannot_drop_review_and_live_transport_defaults_disabled(registry):
    with pytest.raises(ValidationError):
        TaskSpec(id="test", title="Test", agent_id="testing", requires_passed_tests=True)
    provider = ResponsesExecutor(ModelSettings(model="no-network"))
    with pytest.raises(ProviderFailure, match="disabled"):
        asyncio.run(
            provider.generate(registry.agent("investigation"), {"goal": "Do not contact a model"})
        )
