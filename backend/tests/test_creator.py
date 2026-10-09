import json

import httpx
import pytest
from fastapi.testclient import TestClient
from test_demo import demo_root as demo_fixture
from test_demo import originals

from agentos.adapters.creator import CREATOR_DEMO_GOAL
from agentos.adapters.demo import DEMO_LABEL
from agentos.adapters.diagnostics import diagnose
from agentos.adapters.provider import ModelSettings, ResponsesExecutor
from agentos.api.app import create_app
from agentos.domain.governance import UserRole
from agentos.services.execution import ExecutorRegistry

demo_root = demo_fixture
GOAL = "Draft a video script using these facts: AgentOS keeps local mission history."
OUTLINE = "# Outline\nIntroduce a local mission, then show its durable history."
SCRIPT = (
    "# Script\nA goal becomes a mission. Inspect its local history before reviewing its result."
)


@pytest.fixture
def creator_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTOS_WORKSPACE_CONFIG", str(tmp_path / "missing.json"))
    calls = []
    outputs = {"creator_outline": {"outline": OUTLINE}, "creator_script": {"script": SCRIPT}}

    def transport(request):
        body = json.loads(request.content)
        agent = body["text"]["format"]["name"]
        inputs = json.loads(body["input"])
        assert inputs == (
            {"goal": GOAL} if agent == "creator_outline" else {"goal": GOAL, "outline": OUTLINE}
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
        ModelSettings(model="mocked-creator"), transport=httpx.MockTransport(transport)
    )

    def app(role=UserRole.OPERATOR):
        return create_app(db_path=tmp_path / "missions.sqlite3", model=model, user_role=role)

    return app, calls, outputs, tmp_path


def start(client):
    response = client.post("/workflows/creator", json={"goal": GOAL})
    assert response.status_code == 201, response.text
    mission = response.json()
    base = f"/missions/{mission['id']}"
    response = client.post(base + "/run", json={"expected_version": 1})
    assert response.status_code == 200, response.text
    return base, response.json()


def decide(client, base, mission, decision):
    approval = client.get(base + "/approvals").json()[0]
    return client.post(
        f"/approvals/{approval['id']}/decision",
        json={
            "expected_version": mission["version"],
            "decision": decision,
            "payload_digest": approval["payload_digest"],
        },
    )


def test_creator_without_developer_workspace_restart_review_memory(creator_runtime):
    app, calls, _, _ = creator_runtime
    with TestClient(app()) as client:
        status = client.get("/status").json()
        readiness = {w["role_id"]: w["ready"] for w in status["workflows"]}
        assert readiness == {"developer": False, "creator": True, "student": True}
        assert status["workflow_ready"] is False  # Legacy field still means Developer.
        assert not status["workspace_configured"]
        assert client.post("/workflows/developer", json={"goal": "Fix code"}).status_code == 409
        base, mission = start(client)
        assert mission["status"] == "WAITING_APPROVAL"
        assert all("passed" not in (t["outputs"] or {}) for t in mission["tasks"])
        artifacts = client.get(base + "/artifacts").json()
        approval = client.get(base + "/approvals").json()[0]
        reviewed = [a for a in artifacts if a["id"] in approval["payload"]["artifact_refs"]]
        assert {a["name"] for a in reviewed} == {"script.md", "reviewed-outline.md"}
        for item in reviewed:
            content = client.get(f"/artifacts/{item['id']}/content")
            assert content.text == (SCRIPT if item["name"] == "script.md" else OUTLINE)
            assert (
                content.headers["content-disposition"] == f'attachment; filename="{item["name"]}"'
            )
        assert not any(e["action"].startswith("tool_") for e in client.get(base + "/events").json())
        assert (
            client.post(
                "/memory",
                json={
                    "title": "Creator result",
                    "content": "Reviewed brief",
                    "artifact_refs": [reviewed[0]["id"]],
                },
            ).status_code
            == 201
        )
    with TestClient(app()) as client:
        assert client.get(base).json() == mission
        assert len(client.get("/memory").json()) == 1
        accepted = decide(client, base, mission, "approve")
        assert accepted.json()["status"] == "COMPLETED"
        assert (
            client.post(
                f"/approvals/{approval['id']}/decision",
                json={
                    "expected_version": accepted.json()["version"],
                    "decision": "approve",
                    "payload_digest": approval["payload_digest"],
                },
            ).status_code
            == 409
        )
        assert calls == ["creator_outline", "creator_script"]


def test_creator_denial_retry_preserves_outline(creator_runtime):
    app, calls, _, _ = creator_runtime
    with TestClient(app()) as client:
        base, mission = start(client)
        denied = decide(client, base, mission, "deny").json()
        retry = client.post(
            base + "/tasks/script/actions",
            json={"expected_version": denied["version"], "action": "retry"},
        ).json()
        result = client.post(base + "/run", json={"expected_version": retry["version"]}).json()
        assert result["status"] == "WAITING_APPROVAL"
        assert result["tasks"][0]["attempts"] == 1 and result["tasks"][1]["attempts"] == 2
        assert calls == ["creator_outline", "creator_script", "creator_script"]
        assert decide(client, base, result, "approve").json()["status"] == "COMPLETED"


@pytest.mark.parametrize("name", ["script.md", "reviewed-outline.md"])
def test_creator_review_integrity_and_cancellation(creator_runtime, name):
    app, _, _, root = creator_runtime
    with TestClient(app()) as client:
        base, mission = start(client)
        item = next(a for a in client.get(base + "/artifacts").json() if a["name"] == name)
        (root / "artifacts" / f"{item['id']}.txt").write_text("damaged", encoding="utf-8")
        assert decide(client, base, mission, "approve").status_code == 409
        assert (
            client.post(base + "/cancel", json={"expected_version": mission["version"]}).status_code
            == 200
        )
        approval = client.get(base + "/approvals?pending_only=false").json()[0]
        assert (
            client.post(
                f"/approvals/{approval['id']}/decision",
                json={
                    "expected_version": mission["version"] + 1,
                    "decision": "approve",
                    "payload_digest": approval["payload_digest"],
                },
            ).status_code
            == 409
        )


@pytest.mark.parametrize("output", ["", "x" * 24001, 42])
def test_creator_output_bounds_are_enforced(creator_runtime, output):
    app, _, outputs, _ = creator_runtime
    outputs["creator_outline"] = {"outline": output}
    with TestClient(app()) as client:
        base, mission = start(client)
        assert mission["status"] == "FAILED"
        assert not client.get(base + "/artifacts").json()


def test_creator_viewer_cannot_create_run_or_approve(creator_runtime):
    app, _, _, _ = creator_runtime
    with TestClient(app()) as client:
        base, mission = start(client)
    with TestClient(app(UserRole.VIEWER)) as viewer:
        assert viewer.get(base).status_code == 200
        assert viewer.post("/workflows/creator", json={"goal": GOAL}).status_code == 403
        assert (
            viewer.post(base + "/run", json={"expected_version": mission["version"]}).status_code
            == 403
        )
        assert decide(viewer, base, mission, "approve").status_code == 403


def test_creator_missing_provider_and_invalid_workspace_are_separate(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENTOS_MODEL", raising=False)
    config = tmp_path / "invalid.json"
    config.write_text("invalid workspace", encoding="utf-8")
    monkeypatch.setenv("AGENTOS_WORKSPACE_CONFIG", str(config))
    with TestClient(create_app(db_path=tmp_path / "missions.sqlite3")) as client:
        assert all(not w["ready"] for w in client.get("/status").json()["workflows"])
        assert client.post("/workflows/creator", json={"goal": GOAL}).status_code == 409
    model = ResponsesExecutor(ModelSettings(model="configured-only"))
    with TestClient(create_app(db_path=tmp_path / "missions.sqlite3", model=model)) as client:
        status = client.get("/status").json()
        assert status["workspace_error"] and not status["workspace_configured"]
        assert next(w for w in status["workflows"] if w["role_id"] == "creator")["ready"]


def test_creator_demo_is_labelled_persisted_and_never_uses_a_model(demo_root):
    before = originals(demo_root)
    with TestClient(create_app(demo_root=demo_root)) as client:
        assert client.post("/workflows/creator", json={"goal": "Other brief"}).status_code == 409
        mission = client.post("/workflows/creator", json={"goal": CREATOR_DEMO_GOAL}).json()
        base = f"/missions/{mission['id']}"
        result = client.post(base + "/run", json={"expected_version": 1}).json()
        assert result["status"] == "WAITING_APPROVAL"
        artifacts = client.get(base + "/artifacts").json()
        assert len(artifacts) == 5
        for item in artifacts:
            assert DEMO_LABEL in client.get(f"/artifacts/{item['id']}/content").text
            assert "test-report" not in item["name"]
        assert not any("passed" in (t["outputs"] or {}) for t in result["tasks"])
    with TestClient(create_app(demo_root=demo_root)) as client:
        assert decide(client, base, result, "approve").json()["status"] == "COMPLETED"
    assert before == originals(demo_root)


def test_creator_diagnostics_do_not_require_developer_configuration(demo_root, monkeypatch):
    monkeypatch.setenv("AGENTOS_ALLOW_LIVE_MODELS", "1")
    monkeypatch.setenv("AGENTOS_PACKAGES", str(demo_root / "packages"))
    monkeypatch.setenv("AGENTOS_MODEL_URL", "https://api.openai.com/v1")
    report = diagnose(demo_root, workflow="creator")
    assert report.configured_ready and report.workflow == "creator"
    assert not {"git", "workspace", "test_runners"} & {c.id for c in report.checks}
    assert not report.live_provider_verified
    assert diagnose(demo_root, demo=True, workflow="creator").configured_ready


def test_creator_readiness_rejects_missing_package_or_executor(tmp_path, monkeypatch):
    from conftest import PACKAGES

    monkeypatch.setenv("AGENTOS_WORKSPACE_CONFIG", str(tmp_path / "missing.json"))
    model = ResponsesExecutor(ModelSettings(model="configured-only"))
    with TestClient(
        create_app(
            package_root=PACKAGES / "developer",
            model=model,
            db_path=tmp_path / "missing-package.sqlite3",
        )
    ) as client:
        assert {w["role_id"] for w in client.get("/status").json()["workflows"]} == {"developer"}
        assert client.post("/workflows/creator", json={"goal": GOAL}).status_code == 409
    with TestClient(
        create_app(
            model=model,
            executors=ExecutorRegistry(),
            db_path=tmp_path / "missing-executors.sqlite3",
        )
    ) as client:
        assert not next(
            w for w in client.get("/status").json()["workflows"] if w["role_id"] == "creator"
        )["ready"]
        assert client.post("/workflows/creator", json={"goal": GOAL}).status_code == 409


@pytest.mark.parametrize("goal", ["", "x" * 8001])
def test_creator_brief_bounds(creator_runtime, goal):
    app, _, _, _ = creator_runtime
    with TestClient(app()) as client:
        assert client.post("/workflows/creator", json={"goal": goal}).status_code == 422
