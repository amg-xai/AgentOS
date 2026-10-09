"""Offline planning and real persistence/review; no live transport or tools."""

import copy
import json
import sqlite3

import httpx
import pytest
from creator_plan_fixture import creator_plan
from fastapi.testclient import TestClient
from test_creator import GOAL, OUTLINE, SCRIPT, decide
from test_creator_research import RESEARCH, SOURCE

from agentos.adapters.creator import CreatorExecutor
from agentos.adapters.provider import ModelSettings, ResponsesExecutor
from agentos.api.app import create_app
from agentos.domain.agents import Permission
from agentos.domain.creator_planning import CreatorPlan
from agentos.domain.governance import UserRole
from agentos.domain.workspace import CreatorMissionCreate
from agentos.services.creator_planning import compile_creator_plan
from agentos.services.execution import ExecutorRegistry
from agentos.services.registry import AgentRegistry


def runtime(tmp_path, registry=None, *, refine=False, plan_change=None, invalid_quote=False):
    calls = []

    def transport(request):
        body = json.loads(request.content)
        name = body["text"]["format"]["name"]
        inputs = json.loads(body["input"])
        calls.append((name, inputs))
        if name == "creator_planner":
            assert all("body" not in s for s in inputs["sources"])
            ids = (
                {
                    a.capability: a.id
                    for a in registry.role_agents("creator")
                    if a.capability != "creator_plan"
                }
                if registry
                else None
            )
            result = creator_plan(sources=bool(inputs["sources"]), refine=refine, ids=ids)
            if plan_change:
                plan_change(result)
        elif name.endswith("research"):
            result = copy.deepcopy(RESEARCH)
            if invalid_quote:
                result["evidence"][0]["quote"] = "Invented quote"
        elif name.endswith("outline"):
            result = {
                "outline": OUTLINE + (" Refined for the audience." if "context" in inputs else "")
            }
        else:
            result = {"script": SCRIPT}
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": json.dumps(result)}],
                    }
                ],
            },
        )

    model = ResponsesExecutor(
        ModelSettings(model="injected-only"), transport=httpx.MockTransport(transport)
    )

    def app(role=UserRole.OPERATOR):
        return create_app(
            registry=registry, db_path=tmp_path / "missions.sqlite3", model=model, user_role=role
        )

    return app, calls


@pytest.mark.parametrize(
    "sources,refine", [(False, False), (False, True), (True, False), (True, True)]
)
def test_planned_creator_complete_journey_restart_retry(tmp_path, sources, refine):
    app, calls = runtime(tmp_path, refine=refine)
    with TestClient(app()) as client:
        mission = client.post(
            "/workflows/creator", json={"goal": GOAL, "sources": [SOURCE] if sources else []}
        ).json()
        assert mission["planning"]["contract_version"] == 1
        base = f"/missions/{mission['id']}"
        assert len(calls) == 1  # Creation plans but does not execute content.
        mission = client.post(base + "/run", json={"expected_version": 1}).json()
        assert mission["status"] == "WAITING_APPROVAL", mission
        assert all("passed" not in (t["outputs"] or {}) for t in mission["tasks"])
        for _name, inputs in calls[1:]:
            assert inputs["goal"] == GOAL
            assert inputs["constraints"] == ["Use only supplied facts"]
            assert inputs["objective"]
            if sources:
                assert inputs["sources"] == [SOURCE]
        approval = client.get(base + "/approvals").json()[0]
        artifacts = client.get(base + "/artifacts").json()
        owned = {
            a["name"]: client.get(f"/artifacts/{a['id']}/content").text
            for a in artifacts
            if a["id"] in approval["payload"]["artifact_refs"]
        }
        assert len(owned) == (4 if sources else 2)
        assert owned["reviewed-outline.md"] == calls[-1][1]["outline"]
        assert (
            client.post(
                base + "/tasks/deliver/actions",
                json={
                    "expected_version": mission["version"],
                    "action": "complete",
                    "outputs": {"script": SCRIPT},
                },
            ).status_code
            == 409
        )
    with TestClient(app()) as client:
        assert client.get(base).json() == mission
        denied = decide(client, base, mission, "deny").json()
        retried = client.post(
            base + "/tasks/deliver/actions",
            json={"expected_version": denied["version"], "action": "retry"},
        ).json()
        previous_calls = len(calls)
        mission = client.post(base + "/run", json={"expected_version": retried["version"]}).json()
        assert len(calls) == previous_calls + 1
        assert (
            client.post(
                f"/approvals/{approval['id']}/decision",
                json={
                    "expected_version": mission["version"],
                    "decision": "approve",
                    "payload_digest": approval["payload_digest"],
                },
            ).status_code
            == 409
        )
        assert decide(client, base, mission, "approve").json()["status"] == "COMPLETED"
        assert all(a in client.get(base + "/artifacts").json() for a in artifacts)


def test_equivalent_registered_ids_are_used(tmp_path, registry):
    mapping = {
        a.id: "alternate_" + a.id
        for a in registry.role_agents("creator")
        if a.capability != "creator_plan"
    }
    agents = [a.model_copy(update={"id": mapping.get(a.id, a.id)}) for a in registry.agents()]
    roles = [
        r.model_copy(update={"agents": tuple(mapping.get(i, i) for i in r.agents)})
        for r in registry.roles()
    ]
    alternate = AgentRegistry(agents, roles, {t for r in roles for t in r.tools})
    app, _ = runtime(tmp_path, alternate, refine=True)
    with TestClient(app()) as client:
        mission = client.post("/workflows/creator", json={"goal": GOAL, "sources": [SOURCE]}).json()
        assert all(t["agent_id"].startswith("alternate_") for t in mission["tasks"])
        result = client.post(f"/missions/{mission['id']}/run", json={"expected_version": 1})
        assert result.json()["status"] == "WAITING_APPROVAL", result.text


@pytest.mark.parametrize(
    "change",
    [
        "unknown",
        "foreign",
        "cycle",
        "missing_review",
        "early_review",
        "binding",
        "orphan",
        "duplicates",
        "bounds",
    ],
)
def test_invalid_plan_never_persists_or_executes(tmp_path, change):
    def mutate(plan):
        outline, script = plan["tasks"]
        if change in {"unknown", "foreign"}:
            outline["agent_id"] = "missing" if change == "unknown" else "testing"
        elif change == "cycle":
            outline["dependencies"] = ["deliver"]
            outline["bindings"] = [
                {"input_key": "context", "task_id": "deliver", "output_key": "script"}
            ]
        elif change == "missing_review":
            script["review_required"] = False
        elif change == "early_review":
            outline["review_required"] = True
        elif change == "binding":
            script["bindings"][0]["output_key"] = "script"
        elif change == "orphan":
            extra = copy.deepcopy(outline)
            extra["id"] = "unused"
            plan["tasks"].append(extra)
        elif change == "duplicates":
            script["id"] = outline["id"]
        else:
            plan["tasks"] = [outline] * 7

    app, calls = runtime(tmp_path, plan_change=mutate)
    with TestClient(app()) as client:
        response = client.post("/workflows/creator", json={"goal": GOAL})
        assert response.status_code == (502 if change == "bounds" else 422), response.text
        assert client.get("/missions").json() == []
        assert len(calls) == 1


@pytest.mark.parametrize("change", ["permissions", "schema", "executor"])
def test_unsupported_agents_and_missing_executor_rejected(registry, change):
    agents = registry.agents()
    if change != "executor":
        agents = [
            a.model_copy(
                update={"permissions": (Permission.WRITE,)}
                if change == "permissions"
                else {"input_schema": {"type": "string"}}
            )
            if a.id == "creator_outline"
            else a
            for a in agents
        ]
        registry = AgentRegistry(
            agents, registry.roles(), {t for r in registry.roles() for t in r.tools}
        )
    bindings = ExecutorRegistry()
    for agent in agents:
        if change != "executor" or agent.id != "creator_script":
            bindings.register_agent(agent.id, CreatorExecutor(None))
    with pytest.raises(ValueError):
        compile_creator_plan(
            CreatorMissionCreate(goal=GOAL),
            CreatorPlan.model_validate(creator_plan()),
            "creator_planner",
            registry,
            bindings,
        )


def test_bad_quotes_block_downstream_and_viewer_cannot_plan(tmp_path):
    app, calls = runtime(tmp_path, invalid_quote=True)
    with TestClient(app(UserRole.VIEWER)) as client:
        assert client.post("/workflows/creator", json={"goal": GOAL}).status_code == 403
        assert calls == []
    with TestClient(app()) as client:
        mission = client.post("/workflows/creator", json={"goal": GOAL, "sources": [SOURCE]}).json()
        base = f"/missions/{mission['id']}"
        result = client.post(base + "/run", json={"expected_version": 1}).json()
        assert result["status"] == "FAILED"
        assert len(calls) == 2
        assert client.get(base + "/approvals").json() == []


@pytest.mark.parametrize("damage", ["artifact", "goal", "binding"])
def test_damaged_review_and_preflight_rejected(tmp_path, damage):
    app, calls = runtime(tmp_path)
    with TestClient(app()) as client:
        mission = client.post("/workflows/creator", json={"goal": GOAL}).json()
        base = f"/missions/{mission['id']}"
        if damage == "binding":
            with sqlite3.connect(tmp_path / "missions.sqlite3") as conn:
                payload = json.loads(conn.execute("SELECT payload FROM missions").fetchone()[0])
                payload["tasks"][-1]["input_bindings"]["outline"]["output_key"] = "script"
                conn.execute("UPDATE missions SET payload = ?", (json.dumps(payload),))
            assert client.post(base + "/run", json={"expected_version": 1}).status_code == 409
            assert client.get(base + "/run").json() is None
            assert len(calls) == 1
            return
        mission = client.post(base + "/run", json={"expected_version": 1}).json()
        if damage == "artifact":
            ref = client.get(base + "/approvals").json()[0]["payload"]["artifact_refs"][0]
            (tmp_path / "artifacts" / f"{ref}.txt").write_text("damaged", encoding="utf-8")
        else:
            with sqlite3.connect(tmp_path / "missions.sqlite3") as conn:
                payload = json.loads(conn.execute("SELECT payload FROM missions").fetchone()[0])
                payload["goal"] = "Changed scope"
                conn.execute("UPDATE missions SET payload = ?", (json.dumps(payload),))
        assert decide(client, base, mission, "approve").status_code == 409
