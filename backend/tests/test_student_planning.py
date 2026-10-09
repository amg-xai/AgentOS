"""Time-budgeted Student execution uses the existing persisted review boundary."""

import json
from copy import deepcopy

import httpx
import pytest
from fastapi.testclient import TestClient
from student_plan_fixture import student_plan
from test_demo import demo_root as demo_fixture
from test_student import GOAL, NOTES, decide

from agentos.adapters.provider import ModelSettings, ResponsesExecutor
from agentos.adapters.student import STUDENT_DEMO_GOAL, STUDENT_DEMO_QUESTIONS, StudentExecutor
from agentos.api.app import create_app
from agentos.domain.agents import AgentResult, Permission
from agentos.domain.governance import UserRole
from agentos.domain.missions import StateConflict
from agentos.domain.student import StudySettings
from agentos.services.execution import ExecutorRegistry
from agentos.services.registry import AgentRegistry
from agentos.services.student import student_mission, validate_study_mission

demo_root = demo_fixture
SETTINGS = {"total_minutes": 60, "max_session_minutes": 25}
PLAN = {
    "summary": "Review and practice stacks and queues.",
    "blocks": [
        {
            "activity": "review_notes",
            "objective": "Compare removal order.",
            "minutes": 20,
            "question_refs": [1, 2],
        },
        {
            "activity": "practice_quiz",
            "objective": "Attempt every question.",
            "minutes": 25,
            "question_refs": [1, 2, 3],
        },
    ],
    "limitations": ["Supplied material only; not independently checked."],
}


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTOS_WORKSPACE_CONFIG", str(tmp_path / "missing.json"))
    outputs = {
        "student_notes": {"notes": NOTES},
        "student_quiz": {"questions": deepcopy(STUDENT_DEMO_QUESTIONS)},
        "student_focus": deepcopy(PLAN),
    }
    calls = []

    def transport(request):
        body = json.loads(request.content)
        agent = body["text"]["format"]["name"]
        if agent == "student_planner":
            calls.append(agent)
            return httpx.Response(
                200,
                json={
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {"type": "output_text", "text": json.dumps(student_plan())}
                            ],
                        }
                    ],
                },
            )
        expected = {"goal": GOAL}
        if agent != "student_notes":
            expected["notes"] = NOTES
        if agent == "student_focus":
            expected.update(study_settings=SETTINGS, questions=outputs["student_quiz"]["questions"])
        assert json.loads(body["input"]) == expected
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
        return create_app(model=model, db_path=tmp_path / "missions.sqlite3", **kwargs)

    return app, calls, outputs, tmp_path


def start(client):
    response = client.post(
        "/missions", json=student_mission(GOAL, StudySettings(**SETTINGS)).model_dump(mode="json")
    )
    assert response.status_code == 201, response.text
    base = f"/missions/{response.json()['id']}"
    response = client.post(base + "/run", json={"expected_version": 1})
    assert response.status_code == 200, response.text
    return base, response.json()


def retry(client, base, mission, task="study_plan"):
    response = client.post(
        base + f"/tasks/{task}/actions",
        json={"expected_version": mission["version"], "action": "retry"},
    )
    assert response.status_code == 200, response.text
    response = client.post(base + "/run", json={"expected_version": response.json()["version"]})
    assert response.status_code == 200, response.text
    return response.json()


def test_complete_review_restart_and_denial_retry(runtime):
    app, calls, _, _ = runtime
    with TestClient(app()) as client:
        assert next(
            w for w in client.get("/status").json()["workflows"] if w["role_id"] == "student"
        )["study_planning_ready"]
        base, mission = start(client)
        assert mission["status"] == "WAITING_APPROVAL"
        assert [t["status"] for t in mission["tasks"]] == [
            "COMPLETED",
            "COMPLETED",
            "WAITING_APPROVAL",
        ]
        assert mission["tasks"][-1]["dependencies"] == ["notes", "quiz"]
        assert not any("passed" in (t["outputs"] or {}) for t in mission["tasks"])
        approvals = client.get(base + "/approvals").json()
        assert len(approvals) == 1 and approvals[0]["task_id"] == "study_plan"
        refs = approvals[0]["payload"]["artifact_refs"]
        artifacts = {
            a["name"]: a for a in client.get(base + "/artifacts").json() if a["id"] in refs
        }
        assert set(artifacts) == {
            "study-plan.md",
            "study-plan.json",
            "reviewed-study-settings.json",
            "reviewed-notes.md",
            "quiz.md",
            "answer-key.md",
        }
        content = {
            name: client.get(f"/artifacts/{a['id']}/content").text for name, a in artifacts.items()
        }
        assert json.loads(content["study-plan.json"]) == PLAN
        assert json.loads(content["reviewed-study-settings.json"]) == SETTINGS
        assert content["reviewed-notes.md"] == NOTES
        assert "Proposed allocation: 45 minutes" in content["study-plan.md"]
        assert "Available: 60 minutes" in content["study-plan.md"]
        assert STUDENT_DEMO_QUESTIONS[0]["explanation"] in content["answer-key.md"]
        assert STUDENT_DEMO_QUESTIONS[0]["explanation"] not in content["quiz.md"]
        assert not any(e["action"].startswith("tool_") for e in client.get(base + "/events").json())
        assert (
            client.post(
                base + "/tasks/quiz/actions",
                json={"expected_version": mission["version"], "action": "complete", "outputs": {}},
            ).status_code
            == 409
        )
        assert client.post(base + "/run", json={"expected_version": 1}).status_code == 409
    with TestClient(app()) as client:
        assert client.get(base).json() == mission
        denied = decide(client, approvals[0], mission, "deny").json()
        result = retry(client, base, denied)
        assert [t["attempts"] for t in result["tasks"]] == [1, 1, 2]
        assert decide(client, approvals[0], result).status_code == 409
        approval = client.get(base + "/approvals").json()[0]
        accepted = decide(client, approval, result).json()
        assert accepted["status"] == "COMPLETED"
        assert decide(client, approval, accepted).status_code == 409
    assert calls == ["student_notes", "student_quiz", "student_focus", "student_focus"]


@pytest.mark.parametrize(
    "settings",
    [
        {"total_minutes": 9, "max_session_minutes": 25},
        {"total_minutes": 241, "max_session_minutes": 25},
        {"total_minutes": True, "max_session_minutes": 25},
        {"total_minutes": 60.0, "max_session_minutes": 25},
        {"total_minutes": 60, "max_session_minutes": 9},
        {"total_minutes": 60, "max_session_minutes": 61},
        {"total_minutes": 60, "max_session_minutes": 25, "extra": True},
        {},
    ],
)
def test_invalid_settings_are_rejected_before_persistence(runtime, settings):
    app, calls, _, _ = runtime
    with TestClient(app()) as client:
        assert (
            client.post(
                "/workflows/student", json={"goal": GOAL, "study_settings": settings}
            ).status_code
            == 422
        )
        assert client.get("/missions").json() == [] and calls == []


@pytest.mark.parametrize(
    "change",
    [
        "budget",
        "session",
        "unknown_ref",
        "uncovered",
        "duplicate_ref",
        "bool_ref",
        "bool_minutes",
        "fraction",
        "blank_objective",
        "blank_summary",
        "blank_limit",
        "extra",
        "empty",
        "too_many",
        "activity",
    ],
)
def test_invalid_plan_fails_without_review_and_retries(runtime, change):
    app, calls, outputs, _ = runtime
    plan = deepcopy(PLAN)
    if change == "budget":
        plan["blocks"] *= 2
    elif change == "session":
        plan["blocks"][0]["minutes"] = 26
    elif change == "unknown_ref":
        plan["blocks"][0]["question_refs"] = [4]
    elif change == "uncovered":
        plan["blocks"][1]["question_refs"] = [1, 2]
    elif change == "duplicate_ref":
        plan["blocks"][0]["question_refs"] = [1, 1]
    elif change == "bool_ref":
        plan["blocks"][0]["question_refs"] = [True]
    elif change == "bool_minutes":
        plan["blocks"][0]["minutes"] = True
    elif change == "fraction":
        plan["blocks"][0]["minutes"] = 20.0
    elif change == "blank_objective":
        plan["blocks"][0]["objective"] = " "
    elif change == "blank_summary":
        plan["summary"] = " "
    elif change == "blank_limit":
        plan["limitations"] = [" "]
    elif change == "extra":
        plan["unexpected"] = True
    elif change == "empty":
        plan["blocks"] = []
    elif change == "too_many":
        plan["blocks"] *= 7
    else:
        plan["blocks"][0]["activity"] = "calendar"
    outputs["student_focus"] = plan
    with TestClient(app()) as client:
        base, mission = start(client)
        assert mission["status"] == "FAILED"
        assert [t["status"] for t in mission["tasks"]] == ["COMPLETED", "COMPLETED", "FAILED"]
        if change == "budget":
            assert mission["tasks"][-1]["error"] == "Study plan exceeds the available time budget"
        if change == "session":
            assert mission["tasks"][-1]["error"] == "Study block exceeds the maximum session length"
        assert not client.get(base + "/approvals").json()
        assert not [
            a for a in client.get(base + "/artifacts").json() if a["task_id"] == "study_plan"
        ]
        outputs["student_focus"] = deepcopy(PLAN)
        result = retry(client, base, mission)
        assert result["status"] == "WAITING_APPROVAL"
        assert calls.count("student_notes") == calls.count("student_quiz") == 1


@pytest.mark.parametrize("task", ["notes", "quiz"])
def test_upstream_failure_blocks_planner(runtime, task):
    app, calls, outputs, _ = runtime
    original = deepcopy(outputs[f"student_{task}"])
    outputs[f"student_{task}"] = (
        {"notes": " "}
        if task == "notes"
        else {"questions": [{**q, "prompt": " "} for q in STUDENT_DEMO_QUESTIONS]}
    )
    with TestClient(app()) as client:
        base, mission = start(client)
        assert mission["status"] == "FAILED" and mission["tasks"][-1]["status"] == "BLOCKED"
        assert "student_focus" not in calls
        outputs[f"student_{task}"] = original
        assert retry(client, base, mission, task)["status"] == "WAITING_APPROVAL"


@pytest.mark.parametrize(
    "name",
    [
        "study-plan.md",
        "study-plan.json",
        "reviewed-study-settings.json",
        "reviewed-notes.md",
        "quiz.md",
        "answer-key.md",
    ],
)
def test_every_final_artifact_is_integrity_checked(runtime, name):
    app, _, _, root = runtime
    with TestClient(app()) as client:
        base, mission = start(client)
        artifact = next(
            a
            for a in client.get(base + "/artifacts").json()
            if a["name"] == name and a["task_id"] == "study_plan"
        )
        (root / "artifacts" / f"{artifact['id']}.txt").write_text("tampered", encoding="utf-8")
        approval = client.get(base + "/approvals").json()[0]
        assert decide(client, approval, mission).status_code == 409
        cancelled = client.post(
            base + "/cancel", json={"expected_version": mission["version"]}
        ).json()
        assert cancelled["status"] == "CANCELLED"
        assert decide(client, approval, cancelled).status_code == 409


@pytest.mark.parametrize(
    "damage",
    ["missing", "wrong", "duplicate", "extra", "foreign_ref", "invalid_plan", "invalid_quiz"],
)
def test_injected_executor_cannot_bypass_completion_boundary(runtime, damage):
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
            if agent.id == "student_focus" and damage == "invalid_plan":
                return AgentResult(
                    outputs={**PLAN, "blocks": [{**PLAN["blocks"][0], "minutes": 60}]}
                )
            result = await super().execute(agent, inputs, context)
            if agent.id == "student_focus" and damage == "foreign_ref":
                return result.model_copy(update={"artifact_refs": ("not-owned-by-this-task",)})
            if agent.id == "student_focus" and damage in ("duplicate", "extra"):
                artifacts = (
                    (*result.artifacts[:-1], result.artifacts[0])
                    if damage == "duplicate"
                    else (*result.artifacts, result.artifacts[0])
                )
                return result.model_copy(update={"artifacts": artifacts})
            if agent.id == "student_focus" and damage in ("missing", "wrong"):
                artifacts = (
                    result.artifacts[:-1]
                    if damage == "missing"
                    else (
                        *result.artifacts[:-1],
                        result.artifacts[-1].model_copy(update={"content": "wrong key"}),
                    )
                )
                return result.model_copy(update={"artifacts": artifacts})
            return result

    app, _, _, _ = runtime
    bindings = ExecutorRegistry()
    for agent in ("student_notes", "student_quiz", "student_focus"):
        bindings.register_agent(agent, Damaged(Generator()))
    with TestClient(app(executors=bindings)) as client:
        base, mission = start(client)
        assert mission["status"] == "FAILED"
        assert not client.get(base + "/approvals").json()
        assert not [
            a for a in client.get(base + "/artifacts").json() if a["task_id"] == "study_plan"
        ]


@pytest.mark.parametrize(
    "change",
    [
        "permissions",
        "tools",
        "input_schema",
        "output_schema",
        "review",
        "binding",
        "settings",
        "goal",
        "assignment",
        "dependency",
    ],
)
def test_preflight_rejects_unsupported_graph_or_capability(registry, change):
    from agentos.adapters.student import StudentDemoGenerator

    bindings = ExecutorRegistry()
    for agent in registry.role("student").agents:
        bindings.register_agent(agent, StudentExecutor(StudentDemoGenerator()))
    mission = student_mission(GOAL, StudySettings(**SETTINGS))
    if change in ("permissions", "tools", "input_schema", "output_schema"):
        updates = (
            {"permissions": (Permission.READ, Permission.WRITE)}
            if change == "permissions"
            else {"tools": ("filesystem",)}
            if change == "tools"
            else {change: {"type": "object"}}
        )
        agents = [
            a.model_copy(update=updates) if a.id == "student_focus" else a
            for a in registry.agents()
        ]
        roles = [
            r.model_copy(update={"tools": ("filesystem",)})
            if r.id == "student" and change == "tools"
            else r
            for r in registry.roles()
        ]
        registry = AgentRegistry(agents, roles, {t for r in roles for t in r.tools})
    else:
        task = mission.tasks[-1]
        updates = (
            {"review_required": False}
            if change == "review"
            else {"input_bindings": {}}
            if change == "binding"
            else {"dependencies": ("quiz",)}
            if change == "dependency"
            else {"agent_id": "student_notes"}
            if change == "assignment"
            else {"inputs": {**task.inputs, "study_settings": {**SETTINGS, "total_minutes": True}}}
            if change == "settings"
            else {"inputs": {**task.inputs, "goal": "Altered goal"}}
        )
        mission = mission.model_copy(
            update={"tasks": (*mission.tasks[:-1], task.model_copy(update=updates))}
        )
    with pytest.raises(StateConflict):
        validate_study_mission(mission, registry, bindings)


@pytest.mark.parametrize("missing", ["agent", "executor"])
def test_missing_optional_support_preserves_legacy_creation(runtime, registry, missing):
    app, calls, _, _ = runtime
    kwargs = {}
    if missing == "agent":
        roles = [
            r.model_copy(update={"agents": tuple(a for a in r.agents if a != "student_focus")})
            if r.id == "student"
            else r
            for r in registry.roles()
        ]
        kwargs["registry"] = AgentRegistry(
            [a for a in registry.agents() if a.id != "student_focus"],
            roles,
            {t for r in roles for t in r.tools},
        )
    else:

        class Unused:
            async def generate(self, agent, inputs):
                raise AssertionError("No model call expected")

        bindings = ExecutorRegistry()
        for agent in ("student_notes", "student_quiz"):
            bindings.register_agent(agent, StudentExecutor(Unused()))
        kwargs["executors"] = bindings
    with TestClient(app(**kwargs)) as client:
        workflow = next(
            w for w in client.get("/status").json()["workflows"] if w["role_id"] == "student"
        )
        assert workflow["ready"] and not workflow["study_planning_ready"]
        assert (
            client.post(
                "/workflows/student", json={"goal": GOAL, "study_settings": SETTINGS}
            ).status_code
            == 409
        )
        assert client.get("/missions").json() == []
        for settings in ({}, {"study_settings": None}):
            assert (
                client.post("/workflows/student", json={"goal": GOAL, **settings}).status_code
                == 201
            )
        assert calls == ["student_planner", "student_planner"]


def test_viewer_can_inspect_but_cannot_create_run_or_review(runtime):
    app, _, _, _ = runtime
    with TestClient(app()) as client:
        base, mission = start(client)
        approval = client.get(base + "/approvals").json()[0]
    with TestClient(app(user_role=UserRole.VIEWER)) as client:
        assert client.get(base).json() == mission
        assert (
            client.post(
                "/workflows/student", json={"goal": GOAL, "study_settings": SETTINGS}
            ).status_code
            == 403
        )
        assert (
            client.post(base + "/run", json={"expected_version": mission["version"]}).status_code
            == 403
        )
        assert decide(client, approval, mission).status_code == 403


def test_demo_rejects_custom_settings(demo_root):
    with TestClient(create_app(demo_root=demo_root)) as client:
        assert not next(
            w for w in client.get("/status").json()["workflows"] if w["role_id"] == "student"
        )["study_planning_ready"]
        assert (
            client.post(
                "/workflows/student", json={"goal": STUDENT_DEMO_GOAL, "study_settings": SETTINGS}
            ).status_code
            == 409
        )
