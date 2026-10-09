"""Supplied-text provenance, executor preflight and owned human review evidence."""

import json

import httpx
import pytest
from creator_plan_fixture import creator_plan
from fastapi.testclient import TestClient
from test_creator import GOAL, OUTLINE, SCRIPT, decide

from agentos.adapters.provider import ModelSettings, ResponsesExecutor
from agentos.api.app import create_app
from agentos.domain.agents import Permission
from agentos.domain.creator import SourceText
from agentos.domain.missions import StateConflict
from agentos.domain.workspace import CreatorMissionCreate
from agentos.services.creator import creator_mission, validate_source_mission
from agentos.services.execution import ExecutorRegistry
from agentos.services.registry import AgentRegistry

SOURCE = {
    "id": "local_note",
    "label": "Local note",
    "body": "  AgentOS keeps local history.\nCafé 日本語\n",
}
RESEARCH = {
    "summary": "Local history",
    "evidence": [
        {"source_id": "local_note", "quote": "Café 日本語", "interpretation": "A supplied note"}
    ],
    "limitations": ["Not independently verified"],
}


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTOS_WORKSPACE_CONFIG", str(tmp_path / "missing.json"))
    calls = []
    outputs = {
        "creator_research": RESEARCH.copy(),
        "creator_outline": {"outline": OUTLINE},
        "creator_script": {"script": SCRIPT},
    }

    def transport(request):
        body = json.loads(request.content)
        agent = body["text"]["format"]["name"]
        inputs = json.loads(body["input"])
        if agent == "creator_planner":
            return httpx.Response(
                200,
                json={
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": json.dumps(
                                        creator_plan(sources=bool(inputs["sources"]))
                                    ),
                                }
                            ],
                        }
                    ],
                },
            )
        expected = {"goal": GOAL, "sources": [SOURCE]}
        if agent != "creator_research":
            expected.update(outputs["creator_research"])
        if agent == "creator_script":
            expected["outline"] = OUTLINE
        assert inputs == expected
        calls.append(agent)
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": json.dumps(outputs[agent])}],
                    }
                ],
            },
        )

    model = ResponsesExecutor(
        ModelSettings(model="mocked-only"), transport=httpx.MockTransport(transport)
    )

    def app(**kwargs):
        return create_app(db_path=tmp_path / "missions.sqlite3", model=model, **kwargs)

    return app, calls, outputs, tmp_path


def start(client):
    response = client.post(
        "/missions",
        json=creator_mission(GOAL, (SourceText.model_validate(SOURCE),)).model_dump(mode="json"),
    )
    assert response.status_code == 201, response.text
    base = f"/missions/{response.json()['id']}"
    response = client.post(base + "/run", json={"expected_version": 1})
    assert response.status_code == 200, response.text
    return base, response.json()


def test_source_graph_restart_deny_retry_and_review(runtime):
    app, calls, _, _ = runtime
    with TestClient(app()) as client:
        assert next(
            w for w in client.get("/status").json()["workflows"] if w["role_id"] == "creator"
        )["source_research_ready"]
        base, mission = start(client)
        assert mission["status"] == "WAITING_APPROVAL"
        assert [t["id"] for t in mission["tasks"]] == ["research", "outline", "script"]
        assert mission["tasks"][2]["dependencies"] == ["outline", "research"]
        assert not any("passed" in (t["outputs"] or {}) for t in mission["tasks"])
        refs = client.get(base + "/approvals").json()[0]["payload"]["artifact_refs"]
        artifacts = {
            a["name"]: a for a in client.get(base + "/artifacts").json() if a["id"] in refs
        }
        assert set(artifacts) == {
            "script.md",
            "reviewed-outline.md",
            "reviewed-research.json",
            "reviewed-sources.json",
        }
        for name, expected in [
            ("reviewed-research.json", RESEARCH),
            ("reviewed-sources.json", [SOURCE]),
        ]:
            assert client.get(f"/artifacts/{artifacts[name]['id']}/content").json() == expected
        assert not any(e["action"].startswith("tool_") for e in client.get(base + "/events").json())
        assert (
            client.post(
                base + "/tasks/script/actions",
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
        assert client.post(base + "/run", json={"expected_version": 1}).status_code == 409
        denied = decide(client, base, mission, "deny").json()
        retry = client.post(
            base + "/tasks/script/actions",
            json={"expected_version": denied["version"], "action": "retry"},
        ).json()
        reviewed = client.post(base + "/run", json={"expected_version": retry["version"]}).json()
        assert [t["attempts"] for t in reviewed["tasks"]] == [1, 1, 2]
        approval = client.get(base + "/approvals").json()[0]
        accepted = decide(client, base, reviewed, "approve").json()
        assert accepted["status"] == "COMPLETED"
        assert (
            client.post(
                f"/approvals/{approval['id']}/decision",
                json={
                    "expected_version": accepted["version"],
                    "decision": "approve",
                    "payload_digest": approval["payload_digest"],
                },
            ).status_code
            == 409
        )
    assert calls == ["creator_research", "creator_outline", "creator_script", "creator_script"]


@pytest.mark.parametrize(
    "evidence",
    [
        [],
        [{"source_id": "unknown", "quote": "Café", "interpretation": "Note"}],
        [{"source_id": "local_note", "quote": "Cafe", "interpretation": "Note"}],
        [{"source_id": "local_note", "quote": " ", "interpretation": "Note"}],
    ],
)
def test_invalid_research_blocks_dependents(runtime, evidence):
    app, calls, outputs, _ = runtime
    outputs["creator_research"] = {**RESEARCH, "evidence": evidence}
    with TestClient(app()) as client:
        base, mission = start(client)
        assert mission["status"] == "FAILED"
        assert mission["tasks"][0]["status"] == "FAILED"
        assert calls == ["creator_research"]
        assert not client.get(base + "/approvals").json()
        assert not client.get(base + "/artifacts").json()


@pytest.mark.parametrize(
    "name", ["script.md", "reviewed-outline.md", "reviewed-research.json", "reviewed-sources.json"]
)
def test_damaged_review_copy_cannot_be_accepted(runtime, name):
    app, _, _, root = runtime
    with TestClient(app()) as client:
        base, mission = start(client)
        artifact = next(a for a in client.get(base + "/artifacts").json() if a["name"] == name)
        (root / "artifacts" / f"{artifact['id']}.txt").write_text("damaged", encoding="utf-8")
        assert decide(client, base, mission, "approve").status_code == 409


@pytest.mark.parametrize(
    "sources",
    [
        [{**SOURCE, "body": " "}],
        [{**SOURCE, "label": " "}],
        [{**SOURCE, "extra": True}],
        [SOURCE, SOURCE],
        [{**SOURCE, "body": "x" * 12001}],
        [{**SOURCE, "id": f"s{i}", "body": "x" * 12000} for i in range(5)],
        [{**SOURCE, "id": f"s{i}"} for i in range(9)],
    ],
)
def test_source_bounds_before_persistence(runtime, sources):
    app, calls, _, _ = runtime
    with TestClient(app()) as client:
        assert (
            client.post("/workflows/creator", json={"goal": GOAL, "sources": sources}).status_code
            == 422
        )
        assert client.get("/missions").json() == []
        assert not calls


def test_missing_research_executor_preserves_brief_only(runtime):
    from agentos.adapters.creator import CreatorExecutor

    app, _, _, _ = runtime

    class Unused:
        async def generate(self, agent, inputs):
            raise AssertionError("No execution expected")

    bindings = ExecutorRegistry()
    for agent in ("creator_outline", "creator_script"):
        bindings.register_agent(agent, CreatorExecutor(Unused()))
    with TestClient(app(executors=bindings)) as client:
        status = next(
            w for w in client.get("/status").json()["workflows"] if w["role_id"] == "creator"
        )
        assert status["ready"] and not status["source_research_ready"]
        assert (
            client.post("/workflows/creator", json={"goal": GOAL, "sources": [SOURCE]}).status_code
            == 409
        )
        assert client.get("/missions").json() == []
        assert client.post("/workflows/creator", json={"goal": GOAL}).status_code == 201


@pytest.mark.parametrize(
    "change", ["permission", "output", "input", "review", "binding", "dependency"]
)
def test_unsafe_contract_or_graph_rejected(registry, change):
    from agentos.adapters.creator import CreatorDemoGenerator, CreatorExecutor

    mission = creator_mission(GOAL, CreatorMissionCreate(goal=GOAL, sources=[SOURCE]).sources)
    bindings = ExecutorRegistry()
    for agent in registry.role("creator").agents:
        bindings.register_agent(agent, CreatorExecutor(CreatorDemoGenerator()))
    agents = registry.agents()
    if change in ("permission", "input", "output"):
        updates = (
            {"permissions": (Permission.WRITE,)}
            if change == "permission"
            else {f"{change}_schema": {"type": "string"}}
        )
        agents = [a.model_copy(update=updates) if a.id == "creator_research" else a for a in agents]
        registry = AgentRegistry(
            agents, registry.roles(), {tool for role in registry.roles() for tool in role.tools}
        )
    else:
        script = mission.tasks[-1]
        updates = (
            {"review_required": False}
            if change == "review"
            else {"input_bindings": {}}
            if change == "binding"
            else {"dependencies": ("outline",)}
        )
        mission = mission.model_copy(
            update={"tasks": (*mission.tasks[:-1], script.model_copy(update=updates))}
        )
    with pytest.raises(StateConflict):
        validate_source_mission(mission, registry, bindings)


def test_source_body_is_preserved_exactly():
    assert SourceText.model_validate(SOURCE).body == SOURCE["body"]


@pytest.mark.parametrize(
    "change",
    [
        {"summary": " "},
        {"summary": "x" * 2001},
        {"limitations": [" "]},
        {"limitations": ["x" * 501]},
        {"extra": True},
    ],
)
def test_research_output_bounds_and_nonblank_values(runtime, change):
    app, calls, outputs, _ = runtime
    outputs["creator_research"] = {**RESEARCH, **change}
    with TestClient(app()) as client:
        base, mission = start(client)
        assert mission["status"] == "FAILED"
        assert calls == ["creator_research"]
        assert not client.get(base + "/approvals").json()


@pytest.mark.parametrize("damage", ["missing", "wrong"])
def test_injected_executor_cannot_stage_incomplete_review(runtime, damage):
    from agentos.adapters.creator import CreatorExecutor

    class Generator:
        async def generate(self, agent, inputs):
            return {
                "creator_research": RESEARCH,
                "creator_outline": {"outline": OUTLINE},
                "creator_script": {"script": SCRIPT},
            }[agent.id]

    class Damaged(CreatorExecutor):
        async def execute(self, agent, inputs, context):
            result = await super().execute(agent, inputs, context)
            if agent.id == "creator_script":
                artifacts = (
                    result.artifacts[:-1]
                    if damage == "missing"
                    else (
                        *result.artifacts[:-1],
                        result.artifacts[-1].model_copy(update={"content": "different sources"}),
                    )
                )
                return result.model_copy(update={"artifacts": artifacts})
            return result

    app, calls, _, _ = runtime
    bindings = ExecutorRegistry()
    for agent in ("creator_research", "creator_outline", "creator_script"):
        bindings.register_agent(agent, Damaged(Generator()))
    with TestClient(app(executors=bindings)) as client:
        base, mission = start(client)
        assert mission["status"] == "FAILED"
        assert mission["tasks"][-1]["status"] == "FAILED"
        assert not client.get(base + "/approvals").json()
        assert not [a for a in client.get(base + "/artifacts").json() if a["task_id"] == "script"]
        assert not calls


def test_legacy_package_without_research_keeps_brief_workflow(runtime, registry):
    app, _, _, _ = runtime
    agents = [a for a in registry.agents() if a.id != "creator_research"]
    roles = [
        r.model_copy(update={"agents": tuple(a for a in r.agents if a != "creator_research")})
        if r.id == "creator"
        else r
        for r in registry.roles()
    ]
    legacy = AgentRegistry(agents, roles, {tool for r in roles for tool in r.tools})
    with TestClient(app(registry=legacy)) as client:
        status = next(
            w for w in client.get("/status").json()["workflows"] if w["role_id"] == "creator"
        )
        assert status["ready"] and not status["source_research_ready"]
        assert (
            client.post("/workflows/creator", json={"goal": GOAL, "sources": [SOURCE]}).status_code
            == 409
        )
        assert client.post("/workflows/creator", json={"goal": GOAL}).status_code == 201
