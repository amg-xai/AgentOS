"""Student integration tests use real persistence/review and mocked model transport."""

import json
from copy import deepcopy

import httpx
import pytest
from fastapi.testclient import TestClient
from test_demo import demo_root as demo_fixture
from test_demo import originals, run_demo

from agentos.adapters.creator import CREATOR_DEMO_GOAL
from agentos.adapters.demo import DEMO_LABEL
from agentos.adapters.diagnostics import diagnose
from agentos.adapters.provider import ModelSettings, ResponsesExecutor
from agentos.adapters.student import STUDENT_DEMO_GOAL, STUDENT_DEMO_QUESTIONS
from agentos.api.app import create_app
from agentos.domain.governance import UserRole
from agentos.services.execution import ExecutorRegistry
from agentos.services.student import student_mission

demo_root = demo_fixture
GOAL = "Summarize and quiz me: stacks are LIFO; queues are FIFO."
NOTES = "# Notes\nStacks remove newest first; queues remove earliest first."


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTOS_WORKSPACE_CONFIG", str(tmp_path / "missing.json"))
    calls = []
    outputs = {
        "student_notes": {"notes": NOTES},
        "student_quiz": {"questions": deepcopy(STUDENT_DEMO_QUESTIONS)},
    }

    def transport(request):
        body = json.loads(request.content)
        agent = body["text"]["format"]["name"]
        assert json.loads(body["input"]) == (
            {"goal": GOAL} if agent == "student_notes" else {"goal": GOAL, "notes": NOTES}
        )
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
        ModelSettings(model="mocked-student"), transport=httpx.MockTransport(transport)
    )

    def app(role=UserRole.OPERATOR):
        return create_app(db_path=tmp_path / "missions.sqlite3", model=model, user_role=role)

    return app, calls, outputs, tmp_path


def start(client):
    response = client.post("/missions", json=student_mission(GOAL).model_dump(mode="json"))
    assert response.status_code == 201, response.text
    base = f"/missions/{response.json()['id']}"
    run = client.post(base + "/run", json={"expected_version": 1})
    assert run.status_code == 200, run.text
    return base, run.json()


def decide(client, approval, mission, decision="approve"):
    return client.post(
        f"/approvals/{approval['id']}/decision",
        json={
            "expected_version": mission["version"],
            "decision": decision,
            "payload_digest": approval["payload_digest"],
        },
    )


def retry(client, base, mission):
    result = client.post(
        base + "/tasks/quiz/actions",
        json={"expected_version": mission["version"], "action": "retry"},
    )
    assert result.status_code == 200, result.text
    return client.post(base + "/run", json={"expected_version": result.json()["version"]}).json()


def test_student_rendering_review_restart_memory_and_replay(runtime):
    app, calls, _, _ = runtime
    with TestClient(app()) as client:
        status = client.get("/status").json()
        assert {w["role_id"]: w["ready"] for w in status["workflows"]} == {
            "developer": False,
            "creator": True,
            "student": True,
        }
        assert not status["workflow_ready"] and not status["workspace_configured"]
        base, mission = start(client)
        assert mission["status"] == "WAITING_APPROVAL"
        artifacts = client.get(base + "/artifacts").json()
        content = {a["name"]: client.get(f"/artifacts/{a['id']}/content").text for a in artifacts}
        assert content["reviewed-notes.md"] == content["notes.md"] == NOTES
        assert "A. Most recently added" in content["quiz.md"]
        assert "B. FIFO" in content["quiz.md"] and "D. Dequeue" in content["quiz.md"]
        assert "A — Most recently added" in content["answer-key.md"]
        assert "B — FIFO" in content["answer-key.md"] and "D — Dequeue" in content["answer-key.md"]
        for question in STUDENT_DEMO_QUESTIONS:
            assert question["explanation"] in content["answer-key.md"]
            assert question["explanation"] not in content["quiz.md"]
        approval = client.get(base + "/approvals").json()[0]
        assert {
            a["name"] for a in artifacts if a["id"] in approval["payload"]["artifact_refs"]
        } == {"quiz.md", "answer-key.md", "reviewed-notes.md"}
        for item in artifacts:
            response = client.get(f"/artifacts/{item['id']}/content")
            assert (
                response.headers["content-disposition"] == f'attachment; filename="{item["name"]}"'
            )
        assert not any(e["action"].startswith("tool_") for e in client.get(base + "/events").json())
        assert (
            client.post(
                "/memory",
                json={
                    "title": "Student bundle",
                    "content": "Review notes and quiz",
                    "artifact_refs": [artifacts[0]["id"]],
                },
            ).status_code
            == 201
        )
    with TestClient(app()) as client:
        assert client.get(base).json() == mission
        assert client.get(base + "/artifacts").json() == artifacts
        assert len(client.get("/memory").json()) == 1
        accepted = decide(client, approval, mission).json()
        assert accepted["status"] == "COMPLETED"
        assert decide(client, approval, accepted).status_code == 409
        assert calls == ["student_notes", "student_quiz"]


def test_student_denial_retry_keeps_notes_and_old_artifacts(runtime):
    app, calls, _, _ = runtime
    with TestClient(app()) as client:
        base, mission = start(client)
        previous = client.get(base + "/artifacts").json()
        approval = client.get(base + "/approvals").json()[0]
        denied = decide(client, approval, mission, "deny").json()
        result = retry(client, base, denied)
        assert result["status"] == "WAITING_APPROVAL"
        assert [t["attempts"] for t in result["tasks"]] == [1, 2]
        assert calls == ["student_notes", "student_quiz", "student_quiz"]
        assert decide(client, approval, result).status_code == 409
        current = client.get(base + "/artifacts").json()
        assert all(a in current for a in previous) and len(current) == 7
        assert (
            decide(client, client.get(base + "/approvals").json()[0], result).json()["status"]
            == "COMPLETED"
        )


@pytest.mark.parametrize("name", ["quiz.md", "answer-key.md", "reviewed-notes.md"])
def test_student_integrity_and_cancellation(runtime, name):
    app, _, _, root = runtime
    with TestClient(app()) as client:
        base, mission = start(client)
        artifact = next(a for a in client.get(base + "/artifacts").json() if a["name"] == name)
        (root / "artifacts" / f"{artifact['id']}.txt").write_text("tampered", encoding="utf-8")
        approval = client.get(base + "/approvals").json()[0]
        assert decide(client, approval, mission).status_code == 409
        cancelled = client.post(
            base + "/cancel", json={"expected_version": mission["version"]}
        ).json()
        assert cancelled["status"] == "CANCELLED"
        assert decide(client, approval, cancelled).status_code == 409


@pytest.mark.parametrize(
    "change",
    ["too_few", "too_many", "choices", "answer", "boolean", "extra", "prompt", "explanation"],
)
def test_student_invalid_quiz_fails_before_artifacts_and_can_retry(runtime, change):
    app, calls, outputs, _ = runtime
    questions = deepcopy(STUDENT_DEMO_QUESTIONS)
    if change == "too_few":
        questions = questions[:2]
    elif change == "too_many":
        questions = questions * 3
    elif change == "choices":
        questions[0]["choices"] = ["one", "two", "three"]
    elif change == "answer":
        questions[0]["answer_index"] = 4
    elif change == "boolean":
        questions[0]["answer_index"] = True
    elif change == "extra":
        questions[0]["unexpected"] = "field"
    elif change == "prompt":
        questions[0]["prompt"] = "x" * 601
    elif change == "explanation":
        questions[0]["explanation"] = ""
    outputs["student_quiz"] = {"questions": questions}
    with TestClient(app()) as client:
        base, mission = start(client)
        assert mission["status"] == "FAILED"
        assert {a["name"] for a in client.get(base + "/artifacts").json()} == {"notes.md"}
        assert not client.get(base + "/approvals").json()
        outputs["student_quiz"] = {"questions": deepcopy(STUDENT_DEMO_QUESTIONS)}
        result = retry(client, base, mission)
        assert result["status"] == "WAITING_APPROVAL" and result["tasks"][0]["attempts"] == 1
        assert calls == ["student_notes", "student_quiz", "student_quiz"]


@pytest.mark.parametrize("notes", ["", "x" * 24001, 42])
def test_student_invalid_notes_prevent_quiz(runtime, notes):
    app, calls, outputs, _ = runtime
    outputs["student_notes"] = {"notes": notes}
    with TestClient(app()) as client:
        base, mission = start(client)
        assert mission["status"] == "FAILED" and calls == ["student_notes"]
        assert not client.get(base + "/artifacts").json()


def test_student_viewer_cannot_mutate(runtime):
    app, _, _, _ = runtime
    with TestClient(app()) as client:
        base, mission = start(client)
        artifact = client.get(base + "/artifacts").json()[0]
        approval = client.get(base + "/approvals").json()[0]
    with TestClient(app(UserRole.VIEWER)) as client:
        assert client.get(f"/artifacts/{artifact['id']}/content").status_code == 200
        assert client.post("/workflows/student", json={"goal": GOAL}).status_code == 403
        for path, payload in [
            ("/run", {}),
            ("/cancel", {}),
            ("/tasks/quiz/actions", {"action": "retry"}),
        ]:
            assert (
                client.post(
                    base + path, json={"expected_version": mission["version"], **payload}
                ).status_code
                == 403
            )
        assert decide(client, approval, mission).status_code == 403


def test_student_missing_provider_package_executor_and_invalid_workspace(tmp_path, monkeypatch):
    from conftest import PACKAGES

    config = tmp_path / "workspace.json"
    config.write_text("invalid", encoding="utf-8")
    monkeypatch.setenv("AGENTOS_WORKSPACE_CONFIG", str(config))
    monkeypatch.delenv("AGENTOS_MODEL", raising=False)
    model = ResponsesExecutor(ModelSettings(model="configured-only"))
    for options, ready in [
        ({}, False),
        ({"model": model}, True),
        ({"model": model, "executors": ExecutorRegistry()}, False),
        ({"model": model, "package_root": PACKAGES / "creator"}, False),
    ]:
        with TestClient(create_app(db_path=tmp_path / "missions.sqlite3", **options)) as client:
            status = client.get("/status").json()
            assert status["workspace_error"] and not status["workspace_configured"]
            student = next((w for w in status["workflows"] if w["role_id"] == "student"), None)
            assert bool(student and student["ready"]) is ready
            assert client.post("/workflows/student", json={"goal": GOAL}).status_code == (
                502 if ready else 409
            )


@pytest.mark.parametrize("goal", ["", "x" * 8001])
def test_student_brief_bounds(runtime, goal):
    app, _, _, _ = runtime
    with TestClient(app()) as client:
        assert client.post("/workflows/student", json={"goal": goal}).status_code == 422


def test_all_demo_roles_coexist_without_models_or_normal_changes(demo_root):
    before = originals(demo_root)
    with TestClient(create_app(demo_root=demo_root)) as client:
        developer, dev = run_demo(client)
        creator = client.post("/workflows/creator", json={"goal": CREATOR_DEMO_GOAL}).json()
        creator_base = f"/missions/{creator['id']}"
        assert (
            client.post(creator_base + "/run", json={"expected_version": 1}).json()["status"]
            == "WAITING_APPROVAL"
        )
        assert client.post("/workflows/student", json={"goal": "custom"}).status_code == 409
        mission = client.post("/workflows/student", json={"goal": STUDENT_DEMO_GOAL}).json()
        base = f"/missions/{mission['id']}"
        result = client.post(base + "/run", json={"expected_version": 1}).json()
        assert result["status"] == "WAITING_APPROVAL"
        assert not any("passed" in (t["outputs"] or {}) for t in result["tasks"])
        artifacts = client.get(base + "/artifacts").json()
        assert len(artifacts) == 6
        for a in artifacts:
            assert DEMO_LABEL in client.get(f"/artifacts/{a['id']}/content").text
        approval = client.get(base + "/approvals").json()[0]
    with TestClient(create_app(demo_root=demo_root)) as client:
        assert decide(client, approval, result).json()["status"] == "COMPLETED"
        assert client.get(developer).json() == dev
        assert {m["role_id"] for m in client.get("/missions").json()} == {
            "developer",
            "creator",
            "student",
        }
    assert originals(demo_root) == before


def test_student_diagnostics_skip_developer_requirements(demo_root, monkeypatch):
    monkeypatch.setenv("AGENTOS_ALLOW_LIVE_MODELS", "1")
    monkeypatch.setenv("AGENTOS_PACKAGES", str(demo_root / "packages"))
    monkeypatch.setenv("AGENTOS_MODEL_URL", "https://api.openai.com/v1")
    for demo in (False, True):
        report = diagnose(demo_root, demo=demo, workflow="student")
        assert report.configured_ready and report.workflow == "student"
        assert not report.live_provider_verified
        assert not {"git", "workspace", "test_runners"} & {c.id for c in report.checks}
