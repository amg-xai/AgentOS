"""Sourced planning contracts, real execution, provenance and exact review boundaries."""

import copy
import json
import sqlite3

import httpx
import pytest
from fastapi.testclient import TestClient
from student_source_fixture import SOURCE, output_for, sourced_plan
from test_demo import demo_root as demo_root
from test_student import decide

from agentos.adapters.provider import ModelSettings, ResponsesExecutor
from agentos.api.app import create_app
from agentos.domain.agents import Permission
from agentos.domain.creator import SourceText as CreatorSource
from agentos.domain.governance import UserRole
from agentos.domain.missions import StateConflict
from agentos.domain.sources import SourceText
from agentos.domain.student_sources import StudentSourcePlan
from agentos.domain.workspace import StudentMissionCreate
from agentos.services.execution import ExecutorRegistry
from agentos.services.registry import AgentRegistry
from agentos.services.student_planning import compile_student_plan


def runtime(tmp_path, *, change_plan=None, invalid=None, registry=None):
    calls = []

    def transport(request):
        body = json.loads(request.content)
        agent = body["text"]["format"]["name"]
        inputs = json.loads(body["input"])
        calls.append((agent, inputs))
        capability = registry.agent(agent).capability if registry else agent
        canonical = "student_source_planner" if capability == "student_source_plan" else capability
        if canonical == "student_source_planner":
            ids = (
                {a.capability: a.id for a in registry.role_agents("student")} if registry else None
            )
            output = sourced_plan(focus=inputs["study_settings"] is not None, refine=True, ids=ids)
            if change_plan:
                change_plan(output)
        else:
            output = output_for(canonical, inputs)
            if invalid:
                invalid(agent, output)
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

    model = ResponsesExecutor(
        ModelSettings(model="injected-only", allow_live_calls=False),
        transport=httpx.MockTransport(transport),
    )

    def app(**kwargs):
        return create_app(
            db_path=tmp_path / "missions.sqlite3",
            artifact_root=tmp_path / "artifacts",
            registry=registry,
            model=model,
            **kwargs,
        )

    return app, calls


def test_source_contracts_are_shared_and_preserve_text():
    assert SourceText is CreatorSource
    assert StudentMissionCreate(goal="Study", sources=[SOURCE]).sources[0].body == SOURCE["body"]
    with pytest.raises(ValueError):
        StudentMissionCreate(goal="Study", sources=[SOURCE, SOURCE])
    from agentos.domain.student_sources import source_input_schema

    schema = source_input_schema("student_summary")
    schema["properties"].clear()
    assert "research" in source_input_schema("student_summary")["properties"]


@pytest.mark.parametrize("focus", [False, True])
def test_sourced_journey_review_retry_restart(tmp_path, focus):
    app, calls = runtime(tmp_path)
    brief = {
        "goal": "Prepare my DSA exam",
        "sources": [SOURCE],
        "study_settings": {"total_minutes": 60, "max_session_minutes": 25} if focus else None,
    }
    with TestClient(app()) as client:
        created = client.post("/workflows/student", json=brief)
        assert created.status_code == 201, created.text
        mission = created.json()
        base = f"/missions/{mission['id']}"
        assert mission["planning"]["contract_version"] == 2
        assert calls[0][1]["sources"] == [{"id": SOURCE["id"], "label": SOURCE["label"]}]
        result = client.post(base + "/run", json={"expected_version": mission["version"]})
        assert result.status_code == 200, result.text
        mission = result.json()
        assert mission["status"] == "WAITING_APPROVAL", mission
        assert all(
            inputs["sources"] == [SOURCE] and inputs["goal"] == brief["goal"]
            for _, inputs in calls[1:]
        )
        assert all("passed" not in (t["outputs"] or {}) for t in mission["tasks"])
        approval = client.get(base + "/approvals").json()[0]
        assert "plan_digest" in approval["payload"]
        artifacts = client.get(base + "/artifacts").json()
        owned = {
            a["name"]: client.get(f"/artifacts/{a['id']}/content").text
            for a in artifacts
            if a["id"] in approval["payload"]["artifact_refs"]
        }
        assert len(owned) == (11 if focus else 8)
        assert json.loads(owned["reviewed-sources.json"]) == [SOURCE]
        assert json.loads(owned["reviewed-quiz-provenance.json"]) == [[1], [1], [1]]
    with TestClient(app()) as client:
        assert client.get(base).json() == mission
        denied = decide(client, approval, mission, "deny").json()
        final = next(t for t in denied["tasks"] if t["review_required"])
        retried = client.post(
            base + f"/tasks/{final['id']}/actions",
            json={"expected_version": denied["version"], "action": "retry"},
        ).json()
        before = len(calls)
        result = client.post(base + "/run", json={"expected_version": retried["version"]}).json()
        assert result["status"] == "WAITING_APPROVAL" and len(calls) == before + 1
        assert decide(client, approval, result).status_code == 409
        approval = client.get(base + "/approvals").json()[-1]
        accepted = decide(client, approval, result)
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["status"] == "COMPLETED"
    with TestClient(app()) as client:
        assert client.get(base).json() == accepted.json()


@pytest.mark.parametrize(
    "change",
    [
        lambda p: p["tasks"][0].update(agent_id="creator_research"),
        lambda p: p["tasks"][1].update(dependencies=[]),
        lambda p: p["tasks"][-1].update(review_required=False),
        lambda p: p["tasks"][1]["bindings"][0].update(output_key="notes"),
        lambda p: p["tasks"][0].update(dependencies=["quiz"]),
        lambda p: p["tasks"].pop(1),
    ],
)
def test_invalid_plan_never_persists(tmp_path, change):
    app, _ = runtime(tmp_path, change_plan=change)
    with TestClient(app()) as client:
        response = client.post("/workflows/student", json={"goal": "Study", "sources": [SOURCE]})
        assert response.status_code == 422, response.text
        assert client.get("/missions").json() == []


@pytest.mark.parametrize(
    "kind,key,value,failed",
    [
        (
            "student_research",
            "research",
            {
                "summary": "X",
                "evidence": [{"source_id": "course", "quote": "invented", "interpretation": "X"}],
                "limitations": [],
            },
            "evidence",
        ),
        (
            "student_summary",
            "study_summary",
            {"topics": [{"text": "X", "evidence_refs": [8]}], "limitations": []},
            "summary",
        ),
        ("student_source_notes", "summary_refs", [8], "notes"),
        ("student_source_quiz", "question_refs", [[8], [1], [1]], "quiz"),
        ("student_source_quiz", "question_refs", [[1]], "quiz"),
    ],
)
def test_invalid_provenance_blocks_dependents_and_review(tmp_path, kind, key, value, failed):
    def invalid(agent, output):
        if agent == kind:
            output[key] = copy.deepcopy(value)

    app, _ = runtime(tmp_path, invalid=invalid)
    with TestClient(app()) as client:
        mission = client.post(
            "/workflows/student", json={"goal": "Study", "sources": [SOURCE]}
        ).json()
        base = f"/missions/{mission['id']}"
        result = client.post(base + "/run", json={"expected_version": 1}).json()
        assert next(t for t in result["tasks"] if t["id"] == failed)["status"] == "FAILED"
        assert client.get(base + "/approvals").json() == []


@pytest.mark.parametrize(
    "damage", ["permission", "tools", "input", "output", "executor", "planner"]
)
def test_unsafe_or_unsupported_registered_contract_rejected(registry, damage):
    from agentos.adapters.student_sources import StudentSourceExecutor

    class Unused:
        async def generate(self, agent, inputs):
            raise AssertionError("Contract validation must not execute")

    updates = (
        {"permissions": (Permission.WRITE,)}
        if damage == "permission"
        else {"tools": ("filesystem",)}
        if damage == "tools"
        else {f"{damage}_schema": {"type": "string"}}
        if damage in {"input", "output"}
        else {}
    )
    agents = [
        a.model_copy(update=updates) if a.id == "student_summary" else a for a in registry.agents()
    ]
    if damage == "planner":
        agents = [
            a.model_copy(update={"input_schema": {"type": "object"}})
            if a.id == "student_source_planner"
            else a
            for a in agents
        ]
    roles = [
        r.model_copy(update={"tools": ("filesystem",)})
        if r.id == "student" and damage == "tools"
        else r
        for r in registry.roles()
    ]
    registry = AgentRegistry(agents, roles, {t for r in roles for t in r.tools})
    executors = ExecutorRegistry()
    for agent in registry.role_agents("student"):
        if damage != "executor" or agent.id != "student_summary":
            executors.register_agent(agent.id, StudentSourceExecutor(Unused()))
    with pytest.raises(StateConflict):
        compile_student_plan(
            StudentMissionCreate(goal="Study", sources=[SOURCE]),
            StudentSourcePlan.model_validate(sourced_plan()),
            "student_source_planner",
            registry,
            executors,
        )


def test_equivalent_registered_agents_execute_by_capability(tmp_path, registry):
    mapping = {
        a.id: f"alternate_{a.id}"
        for a in registry.role_agents("student")
        if a.capability
        and (
            a.capability.startswith("student_source")
            or a.capability in {"student_research", "student_summary"}
        )
    }
    agents = [a.model_copy(update={"id": mapping.get(a.id, a.id)}) for a in registry.agents()]
    roles = [
        r.model_copy(update={"agents": tuple(mapping.get(i, i) for i in r.agents)})
        for r in registry.roles()
    ]
    registry = AgentRegistry(agents, roles, {t for r in roles for t in r.tools})
    app, calls = runtime(tmp_path, registry=registry)
    with TestClient(app()) as client:
        created = client.post("/workflows/student", json={"goal": "Study", "sources": [SOURCE]})
        assert created.status_code == 201, created.text
        base = f"/missions/{created.json()['id']}"
        result = client.post(base + "/run", json={"expected_version": 1}).json()
        assert result["status"] == "WAITING_APPROVAL", result
        assert all(a.startswith("alternate_") for a, _ in calls)


@pytest.mark.parametrize(
    "damage",
    [
        "goal",
        "workspace",
        "sources",
        "research_output",
        "summary_output",
        "research_artifact",
        "summary_artifact",
        "review_artifact",
        "notes_refs",
        "quiz_refs",
    ],
)
def test_changed_review_or_retained_evidence_cannot_be_accepted(tmp_path, damage):
    app, _ = runtime(tmp_path)
    with TestClient(app()) as client:
        created = client.post(
            "/workflows/student", json={"goal": "Study", "sources": [SOURCE]}
        ).json()
        base = f"/missions/{created['id']}"
        mission = client.post(base + "/run", json={"expected_version": 1}).json()
        approval = client.get(base + "/approvals").json()[0]
        if damage.endswith("artifact"):
            artifacts = client.get(base + "/artifacts").json()
            name = {
                "research_artifact": "research.json",
                "summary_artifact": "study-summary.json",
                "review_artifact": "reviewed-sources.json",
            }[damage]
            artifact = next(a for a in artifacts if a["name"] == name)
            (tmp_path / "artifacts" / f"{artifact['id']}.txt").write_text(
                "damaged", encoding="utf-8"
            )
        else:
            with sqlite3.connect(tmp_path / "missions.sqlite3") as conn:
                payload = json.loads(conn.execute("SELECT payload FROM missions").fetchone()[0])
                if damage == "goal":
                    payload["goal"] = "Changed"
                elif damage == "workspace":
                    payload["workspace_id"] = "changed"
                elif damage == "sources":
                    for task in payload["tasks"]:
                        task["inputs"]["sources"][0]["body"] += "Changed"
                elif damage == "research_output":
                    payload["tasks"][0]["outputs"]["research"]["summary"] = "Changed"
                elif damage == "summary_output":
                    payload["tasks"][1]["outputs"]["study_summary"]["topics"][0]["text"] = "Changed"
                elif damage == "notes_refs":
                    payload["tasks"][3]["outputs"]["summary_refs"] = [8]
                else:
                    payload["tasks"][-1]["outputs"]["question_refs"] = [[8], [1], [1]]
                conn.execute("UPDATE missions SET payload=?", (json.dumps(payload),))
        assert decide(client, approval, mission).status_code == 409
        assert client.get(base).json()["status"] == "WAITING_APPROVAL"


def test_viewer_cannot_create_sourced_mission(tmp_path):
    app, calls = runtime(tmp_path)
    with TestClient(app(user_role=UserRole.VIEWER)) as client:
        assert (
            client.post(
                "/workflows/student", json={"goal": "Study", "sources": [SOURCE]}
            ).status_code
            == 403
        )
        assert calls == []


def test_demo_rejects_custom_study_sources(demo_root):
    demo = create_app(demo_root=demo_root)
    with TestClient(demo) as client:
        from agentos.adapters.student import STUDENT_DEMO_GOAL

        assert (
            client.post(
                "/workflows/student", json={"goal": STUDENT_DEMO_GOAL, "sources": [SOURCE]}
            ).status_code
            == 409
        )


def test_legacy_package_keeps_normal_student_readiness(tmp_path, registry):
    removed = {
        a.id
        for a in registry.role_agents("student")
        if a.capability
        and (
            a.capability.startswith("student_source")
            or a.capability in {"student_research", "student_summary"}
        )
    }
    roles = [
        r.model_copy(update={"agents": tuple(i for i in r.agents if i not in removed)})
        for r in registry.roles()
    ]
    legacy = AgentRegistry(
        [a for a in registry.agents() if a.id not in removed],
        roles,
        {t for r in roles for t in r.tools},
    )
    app, calls = runtime(tmp_path / "legacy", registry=legacy)
    with TestClient(app()) as client:
        status = next(
            w for w in client.get("/status").json()["workflows"] if w["role_id"] == "student"
        )
        assert status["ready"] and not status["source_research_ready"]
        assert (
            client.post(
                "/workflows/student", json={"goal": "Study", "sources": [SOURCE]}
            ).status_code
            == 409
        )
        assert calls == []


@pytest.mark.parametrize("version", [None, 1, 3])
def test_sourced_assignments_cannot_bypass_v2_preflight(tmp_path, version):
    app, calls = runtime(tmp_path)
    with TestClient(app()) as client:
        created = client.post(
            "/workflows/student", json={"goal": "Study", "sources": [SOURCE]}
        ).json()
        from agentos.domain.missions import Mission, MissionCreate, TaskSpec

        mission = Mission.model_validate(
            {key: value for key, value in created.items() if key != "status"}
        )
        request = MissionCreate(
            goal=mission.goal,
            role_id="student",
            tasks=tuple(
                TaskSpec.model_validate(t.model_dump(include=set(TaskSpec.model_fields)))
                for t in mission.tasks
            ),
            planning=mission.planning,
        ).model_dump(mode="json")
        if version is None:
            request["planning"] = None
        else:
            request["planning"]["contract_version"] = version
        assert client.post("/missions", json=request).status_code == 409
        with sqlite3.connect(tmp_path / "missions.sqlite3") as conn:
            payload = json.loads(conn.execute("SELECT payload FROM missions").fetchone()[0])
            payload["planning"] = request["planning"]
            conn.execute("UPDATE missions SET payload=?", (json.dumps(payload),))
        base = f"/missions/{mission.id}"
        assert client.post(base + "/run", json={"expected_version": 1}).status_code == 409
        assert client.get(base + "/run").json() is None
        assert len(calls) == 1
