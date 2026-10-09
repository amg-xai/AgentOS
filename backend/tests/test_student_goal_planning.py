"""Goal-driven Student integration uses injected transport, persistence and approvals."""

import copy
import json
import sqlite3

import httpx
import pytest
from fastapi.testclient import TestClient
from student_plan_fixture import student_plan
from test_student import GOAL, NOTES, decide
from test_student_planning import PLAN, SETTINGS

from agentos.adapters.provider import ModelSettings, ResponsesExecutor
from agentos.adapters.student import STUDENT_DEMO_QUESTIONS, StudentExecutor
from agentos.api.app import create_app
from agentos.domain.agents import AgentResult, Permission
from agentos.domain.governance import UserRole
from agentos.domain.student_planning import StudentPlan
from agentos.domain.workspace import StudentMissionCreate
from agentos.services.execution import ExecutorRegistry
from agentos.services.registry import AgentRegistry
from agentos.services.student_planning import compile_student_plan


def runtime(tmp_path, registry=None, *, refine=False, change=None, invalid=None):
    calls = []

    def transport(request):
        body = json.loads(request.content)
        agent = body["text"]["format"]["name"]
        inputs = json.loads(body["input"])
        calls.append((agent, inputs))
        if agent == "student_planner":
            ids = (
                {
                    a.capability: a.id
                    for a in registry.role_agents("student")
                    if a.capability != "student_plan"
                }
                if registry
                else None
            )
            output = student_plan(
                focus=inputs["study_settings"] is not None, refine=refine, ids=ids
            )
            if change:
                change(output)
        elif agent.endswith("notes"):
            output = {
                "notes": " "
                if invalid == "notes"
                else NOTES + (" Refined for the goal." if "context" in inputs else "")
            }
        elif agent.endswith("quiz"):
            output = {"questions": copy.deepcopy(STUDENT_DEMO_QUESTIONS)}
            if invalid == "quiz":
                output["questions"][0]["prompt"] = " "
        else:
            output = copy.deepcopy(PLAN)
            if invalid == "budget":
                output["blocks"][0]["minutes"] = 60
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
        ModelSettings(model="injected-only"), transport=httpx.MockTransport(transport)
    )

    def app(**kwargs):
        return create_app(
            db_path=tmp_path / "missions.sqlite3", registry=registry, model=model, **kwargs
        )

    return app, calls


@pytest.mark.parametrize(
    "focus,refine", [(False, False), (False, True), (True, False), (True, True)]
)
def test_complete_journey_goal_bindings_review_restart_retry(tmp_path, focus, refine):
    app, calls = runtime(tmp_path, refine=refine)
    # Prose mentioning a deadline never opts into Focus by itself.
    goal = GOAL if focus else "Prepare tomorrow's exam using only stacks LIFO and queues FIFO."
    settings = SETTINGS if focus else None
    with TestClient(app()) as client:
        response = client.post(
            "/workflows/student", json={"goal": goal, "study_settings": settings}
        )
        assert response.status_code == 201, response.text
        mission = response.json()
        base = f"/missions/{mission['id']}"
        assert len(calls) == 1 and calls[0][1]["goal"] == goal
        assert calls[0][1]["study_settings"] == settings
        assert {a["capability"] for a in calls[0][1]["agents"]} == {
            "student_notes",
            "student_quiz",
            "student_focus",
        }
        assert mission["planning"]["contract_version"] == 1
        response = client.post(base + "/run", json={"expected_version": 1})
        assert response.status_code == 200, response.text
        mission = response.json()
        assert mission["status"] == "WAITING_APPROVAL", mission
        assert all("passed" not in (t["outputs"] or {}) for t in mission["tasks"])
        for _agent, inputs in calls[1:]:
            assert inputs["goal"] == goal and inputs["study_settings"] == settings
            assert inputs["constraints"] == ["Use supplied material only"] and inputs["objective"]
        quiz_inputs = next(inputs for agent, inputs in calls if agent == "student_quiz")
        if refine:
            assert calls[2][1]["context"] == NOTES
            assert quiz_inputs["notes"].endswith("Refined for the goal.")
        if focus:
            assert calls[-1][1]["notes"] == quiz_inputs["notes"]
        approval = client.get(base + "/approvals").json()[0]
        artifacts = client.get(base + "/artifacts").json()
        owned = {
            a["name"]: client.get(f"/artifacts/{a['id']}/content").text
            for a in artifacts
            if a["id"] in approval["payload"]["artifact_refs"]
        }
        assert len(owned) == (6 if focus else 3)
        assert owned["reviewed-notes.md"] == quiz_inputs["notes"]
        final = "schedule" if focus else "questions"
        assert (
            client.post(
                base + f"/tasks/{final}/actions",
                json={
                    "expected_version": mission["version"],
                    "action": "complete",
                    "outputs": {},
                },
            ).status_code
            == 409
        )
    with TestClient(app()) as client:
        assert client.get(base).json() == mission
        denied = decide(client, approval, mission, "deny").json()
        retried = client.post(
            base + f"/tasks/{final}/actions",
            json={
                "expected_version": denied["version"],
                "action": "retry",
            },
        ).json()
        before = len(calls)
        result = client.post(base + "/run", json={"expected_version": retried["version"]}).json()
        assert result["status"] == "WAITING_APPROVAL" and len(calls) == before + 1
        assert decide(client, approval, result).status_code == 409
        current = client.get(base + "/approvals").json()[-1]
        assert decide(client, current, result).json()["status"] == "COMPLETED"
        assert all(a in client.get(base + "/artifacts").json() for a in artifacts)


def test_equivalent_registered_agents(tmp_path, registry):
    mapping = {
        a.id: "alternate_" + a.id
        for a in registry.role_agents("student")
        if a.capability != "student_plan"
    }
    agents = [a.model_copy(update={"id": mapping.get(a.id, a.id)}) for a in registry.agents()]
    roles = [
        r.model_copy(update={"agents": tuple(mapping.get(i, i) for i in r.agents)})
        for r in registry.roles()
    ]
    registry = AgentRegistry(agents, roles, {t for r in roles for t in r.tools})
    app, calls = runtime(tmp_path, registry, refine=True)
    with TestClient(app()) as client:
        mission = client.post(
            "/workflows/student", json={"goal": GOAL, "study_settings": SETTINGS}
        ).json()
        assert all(t["agent_id"].startswith("alternate_") for t in mission["tasks"])
        base = f"/missions/{mission['id']}"
        result = client.post(base + "/run", json={"expected_version": 1}).json()
        assert result["status"] == "WAITING_APPROVAL", result
        assert calls[-1][0] == "alternate_student_focus"
        assert decide(client, client.get(base + "/approvals").json()[0], result).status_code == 200


@pytest.mark.parametrize(
    "damage",
    [
        "unknown",
        "foreign",
        "cycle",
        "duplicate",
        "duplicate_binding",
        "bounds",
        "orphan",
        "missing_dependency",
        "wrong_binding",
        "missing_review",
        "early_review",
        "invented_focus",
        "different_notes",
    ],
)
def test_invalid_plans_never_persist_or_execute(tmp_path, damage):
    def mutate(plan):
        notes, refined, quiz = plan["tasks"][:3]
        if damage in {"unknown", "foreign"}:
            notes["agent_id"] = "unknown" if damage == "unknown" else "testing"
        elif damage == "cycle":
            notes.update(
                dependencies=["refine"],
                bindings=[{"input_key": "context", "task_id": "refine", "output_key": "notes"}],
            )
        elif damage == "duplicate":
            quiz["id"] = notes["id"]
        elif damage == "duplicate_binding":
            quiz["bindings"].append(quiz["bindings"][0])
        elif damage == "bounds":
            plan["tasks"] *= 3
        elif damage == "orphan":
            extra = copy.deepcopy(notes)
            extra["id"] = "unused"
            plan["tasks"].append(extra)
        elif damage == "missing_dependency":
            quiz["dependencies"] = []
        elif damage == "wrong_binding":
            quiz["bindings"][0]["output_key"] = "questions"
        elif damage == "missing_review":
            plan["tasks"][-1]["review_required"] = False
        elif damage == "early_review":
            notes["review_required"] = True
        elif damage == "invented_focus":
            plan["tasks"] = student_plan(focus=True, refine=True)["tasks"]
        else:
            plan["tasks"][-1]["bindings"][0]["task_id"] = "draft"
            plan["tasks"][-1]["dependencies"][0] = "draft"

    focus = damage == "different_notes"
    app, calls = runtime(tmp_path, refine=True, change=mutate)
    with TestClient(app()) as client:
        response = client.post(
            "/workflows/student", json={"goal": GOAL, "study_settings": SETTINGS if focus else None}
        )
        assert response.status_code == (502 if damage == "bounds" else 422), response.text
        assert client.get("/missions").json() == [] and len(calls) == 1


@pytest.mark.parametrize("damage", ["permission", "tool", "schema", "executor"])
def test_unsupported_capabilities_before_execution(registry, damage):
    updates = (
        {"permissions": (Permission.WRITE,)}
        if damage == "permission"
        else {"tools": ("filesystem",)}
        if damage == "tool"
        else {"input_schema": {"type": "string"}}
    )
    agents = [
        a.model_copy(update=updates) if a.id == "student_notes" and damage != "executor" else a
        for a in registry.agents()
    ]
    roles = [
        r.model_copy(update={"tools": ("filesystem",)})
        if r.id == "student" and damage == "tool"
        else r
        for r in registry.roles()
    ]
    registry = AgentRegistry(agents, roles, {t for r in roles for t in r.tools})

    class Unused:
        async def generate(self, agent, inputs):
            raise AssertionError("Validation must never execute")

    bindings = ExecutorRegistry()
    for a in agents:
        if a.id != "student_quiz" or damage != "executor":
            bindings.register_agent(a.id, StudentExecutor(Unused()))
    with pytest.raises(ValueError):
        compile_student_plan(
            StudentMissionCreate(goal=GOAL),
            StudentPlan.model_validate(student_plan()),
            "student_planner",
            registry,
            bindings,
        )


@pytest.mark.parametrize("invalid", ["notes", "quiz", "budget"])
def test_output_failures_block_dependents_and_review(tmp_path, invalid):
    app, calls = runtime(tmp_path, invalid=invalid)
    with TestClient(app()) as client:
        mission = client.post(
            "/workflows/student", json={"goal": GOAL, "study_settings": SETTINGS}
        ).json()
        base = f"/missions/{mission['id']}"
        result = client.post(base + "/run", json={"expected_version": 1}).json()
        assert result["status"] == "FAILED"
        assert len(calls) == {"notes": 2, "quiz": 3, "budget": 4}[invalid]
        assert client.get(base + "/approvals").json() == []


@pytest.mark.parametrize("damage", ["goal", "settings", "binding", "artifact"])
def test_changed_evidence_cannot_run_or_be_accepted(tmp_path, damage):
    app, calls = runtime(tmp_path)
    with TestClient(app()) as client:
        mission = client.post("/workflows/student", json={"goal": GOAL}).json()
        base = f"/missions/{mission['id']}"
        if damage == "binding":
            with sqlite3.connect(tmp_path / "missions.sqlite3") as conn:
                payload = json.loads(conn.execute("SELECT payload FROM missions").fetchone()[0])
                payload["tasks"][-1]["input_bindings"]["notes"]["output_key"] = "questions"
                conn.execute("UPDATE missions SET payload = ?", (json.dumps(payload),))
            assert client.post(base + "/run", json={"expected_version": 1}).status_code == 409
            assert client.get(base + "/run").json() is None and len(calls) == 1
            return
        mission = client.post(base + "/run", json={"expected_version": 1}).json()
        approval = client.get(base + "/approvals").json()[0]
        if damage == "artifact":
            ref = approval["payload"]["artifact_refs"][0]
            (tmp_path / "artifacts" / f"{ref}.txt").write_text("damaged", encoding="utf-8")
        else:
            with sqlite3.connect(tmp_path / "missions.sqlite3") as conn:
                payload = json.loads(conn.execute("SELECT payload FROM missions").fetchone()[0])
                if damage == "goal":
                    payload["goal"] = "Changed goal"
                else:
                    payload["tasks"][0]["inputs"]["study_settings"] = SETTINGS
                conn.execute("UPDATE missions SET payload = ?", (json.dumps(payload),))
        assert decide(client, approval, mission).status_code == 409


def test_viewer_and_cancellation(tmp_path):
    app, calls = runtime(tmp_path)
    with TestClient(app(user_role=UserRole.VIEWER)) as client:
        assert client.post("/workflows/student", json={"goal": GOAL}).status_code == 403
        assert calls == []
    with TestClient(app()) as client:
        mission = client.post("/workflows/student", json={"goal": GOAL}).json()
        base = f"/missions/{mission['id']}"
        cancelled = client.post(base + "/cancel", json={"expected_version": 1}).json()
        assert cancelled["status"] == "CANCELLED"
        assert (
            client.post(base + "/run", json={"expected_version": cancelled["version"]}).status_code
            == 409
        )
        assert len(calls) == 1


@pytest.mark.parametrize("focus", [False, True])
@pytest.mark.parametrize("damage", ["missing", "wrong", "duplicate", "foreign", "invalid_quiz"])
def test_injected_executor_cannot_bypass_planned_review(tmp_path, focus, damage):
    class Generator:
        async def generate(self, agent, inputs):
            return {
                "student_notes": {"notes": NOTES},
                "student_quiz": {"questions": STUDENT_DEMO_QUESTIONS},
                "student_focus": PLAN,
            }[agent.id]

    class Damaged(StudentExecutor):
        async def execute(self, agent, inputs, context):
            if agent.id == "student_quiz" and damage == "invalid_quiz":
                return AgentResult(
                    outputs={"questions": [{**q, "prompt": " "} for q in STUDENT_DEMO_QUESTIONS]}
                )
            result = await super().execute(agent, inputs, context)
            if agent.id != ("student_focus" if focus else "student_quiz"):
                return result
            if damage == "foreign":
                return result.model_copy(update={"artifact_refs": ("foreign",)})
            artifacts = (
                result.artifacts[:-1]
                if damage == "missing"
                else (*result.artifacts[:-1], result.artifacts[0])
                if damage == "duplicate"
                else (
                    *result.artifacts[:-1],
                    result.artifacts[-1].model_copy(update={"content": "wrong"}),
                )
            )
            return result.model_copy(update={"artifacts": artifacts})

    app, _ = runtime(tmp_path)
    bindings = ExecutorRegistry()
    for agent in ("student_notes", "student_quiz", "student_focus"):
        bindings.register_agent(agent, Damaged(Generator()))
    with TestClient(app(executors=bindings)) as client:
        mission = client.post(
            "/workflows/student",
            json={
                "goal": GOAL,
                "study_settings": SETTINGS if focus else None,
            },
        ).json()
        base = f"/missions/{mission['id']}"
        result = client.post(base + "/run", json={"expected_version": 1}).json()
        assert result["status"] == "FAILED", result
        assert client.get(base + "/approvals").json() == []


def test_missing_mission_planner_disables_normal_creation(tmp_path, registry):
    roles = [
        r.model_copy(update={"agents": tuple(i for i in r.agents if i != "student_planner")})
        if r.id == "student"
        else r
        for r in registry.roles()
    ]
    registry = AgentRegistry(
        [a for a in registry.agents() if a.id != "student_planner"],
        roles,
        {t for r in roles for t in r.tools},
    )
    app, calls = runtime(tmp_path, registry)
    with TestClient(app()) as client:
        response = client.post("/workflows/student", json={"goal": GOAL})
        assert response.status_code == 409 and calls == []
        assert client.get("/missions").json() == []
