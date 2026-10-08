"""Real filesystem/Git/subprocess integration; only the model transport is mocked."""

import asyncio
import json
import sqlite3

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from agentos.adapters.local_tools import LocalWorkspaceTools, minimal_environment
from agentos.adapters.provider import ModelSettings, ResponsesExecutor
from agentos.adapters.workspace import WorkspaceStore
from agentos.api.app import create_app
from agentos.domain.agents import ExecutionContext
from agentos.domain.missions import StateConflict
from agentos.domain.workspace import MemoryCreate, WorkspaceSettings

PATCH = """diff --git a/calculator.py b/calculator.py
--- a/calculator.py
+++ b/calculator.py
@@ -1,2 +1,2 @@
 def add(a, b):
-    return a - b
+    return a + b
"""


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    (root / "calculator.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (root / "test_calculator.py").write_text(
        "import unittest\nfrom calculator import add\n"
        "class TestAdd(unittest.TestCase):\n"
        "    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n",
        encoding="utf-8",
    )
    return WorkspaceSettings(
        name="Test project",
        repository=root,
        files=("calculator.py", "test_calculator.py"),
        test_commands=(("python", "-m", "unittest", "discover"),),
    )


def model_transport(request):
    body = json.loads(request.content)
    inputs = json.loads(body["input"])
    assert "calculator.py" in inputs["source_files"]
    agent = body["text"]["format"]["name"]
    outputs = (
        {"findings": "calculator.py subtracts instead of adding"}
        if agent == "investigation"
        else {"diff": PATCH, "summary": "Correct addition without changing tests"}
    )
    return httpx.Response(
        200,
        json={
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": json.dumps(outputs)}],
                }
            ],
        },
    )


def configured_app(tmp_path, workspace, transport=model_transport):
    model = ResponsesExecutor(
        ModelSettings(model="mocked-transport"), transport=httpx.MockTransport(transport)
    )
    return create_app(db_path=tmp_path / "missions.sqlite3", workspace=workspace, model=model)


def test_complete_workflow_real_tools_restart_and_approval(tmp_path, workspace, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-reach-tests")
    originals = {path: (workspace.repository / path).read_bytes() for path in workspace.files}
    with TestClient(configured_app(tmp_path, workspace)) as client:
        assert client.get("/status").json()["workflow_ready"] is True
        note = client.post(
            "/memory", json={"title": "Addition", "content": "Preserve negative sums"}
        )
        assert note.status_code == 201
        mission = client.post("/workflows/developer", json={"goal": "Fix addition"}).json()
        base = f"/missions/{mission['id']}"
        run = client.post(base + "/run", json={"expected_version": 1})
        assert run.status_code == 200, run.text
        result = run.json()
        assert result["status"] == "WAITING_APPROVAL", result
        assert result["tasks"][2]["outputs"]["passed"] is True
        assert "Exit code: 0" in result["tasks"][2]["outputs"]["report"]
        artifacts = client.get(base + "/artifacts").json()
        assert len(artifacts) == 4
        diff = next(a for a in artifacts if a["name"] == "proposed.diff")
        assert client.get(f"/artifacts/{diff['id']}/content").text == PATCH
        assert (
            client.post(
                "/memory",
                json={
                    "title": "Fixed addition",
                    "content": "Patch tested",
                    "artifact_refs": [diff["id"]],
                },
            ).status_code
            == 201
        )
        events = client.get(base + "/events").json()
        assert sum(e["action"] == "tool_completed" for e in events) == 4
        assert "must-not-reach-tests" not in json.dumps(events)
    with TestClient(configured_app(tmp_path, workspace)) as client:
        assert len(client.get("/memory?query=addition").json()) == 2
        approval = client.get(base + "/approvals").json()[0]
        approved = client.post(
            f"/approvals/{approval['id']}/decision",
            json={
                "expected_version": result["version"],
                "decision": "approve",
                "payload_digest": approval["payload_digest"],
            },
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "COMPLETED"
        assert client.get(base + "/artifacts").json() == artifacts
    assert originals == {
        path: (workspace.repository / path).read_bytes() for path in workspace.files
    }
    assert "OPENAI_API_KEY" not in minimal_environment()


def test_provider_failure_retry_then_deny(tmp_path, workspace):
    failing = True

    def transport(request):
        return httpx.Response(401, text="secret") if failing else model_transport(request)

    with TestClient(configured_app(tmp_path, workspace, transport)) as client:
        mission = client.post("/workflows/developer", json={"goal": "Fix addition"}).json()
        base = f"/missions/{mission['id']}"
        mission = client.post(base + "/run", json={"expected_version": 1}).json()
        assert mission["status"] == "FAILED"
        assert "secret" not in json.dumps(mission)
        failing = False
        mission = client.post(
            base + "/tasks/investigate/actions",
            json={"expected_version": mission["version"], "action": "retry"},
        ).json()
        mission = client.post(base + "/run", json={"expected_version": mission["version"]}).json()
        approval = client.get(base + "/approvals").json()[0]
        denied = client.post(
            f"/approvals/{approval['id']}/decision",
            json={
                "expected_version": mission["version"],
                "decision": "deny",
                "payload_digest": approval["payload_digest"],
            },
        ).json()
        assert denied["status"] == "FAILED"


@pytest.mark.parametrize("file", ["../outside.py", ".env", "C:/secret", ".git/config", "key.pem"])
def test_rejects_unsafe_scope(workspace, file):
    with pytest.raises(ValidationError):
        WorkspaceSettings(**(workspace.model_dump() | {"files": [file]}))


@pytest.mark.parametrize(
    "command", [["cmd", "/c", "echo hi"], ["python", "-c", "evil"], [], ["node", "--eval", "evil"]]
)
def test_rejects_shell_and_inline_commands(workspace, command):
    with pytest.raises(ValidationError):
        WorkspaceSettings(**(workspace.model_dump() | {"test_commands": [command]}))


def test_immutable_snapshot_and_patch_scope(tmp_path, workspace):
    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    context = ExecutionContext(workspace_id="local", mission_id="mission", task_id="fix")
    tools = LocalWorkspaceTools(workspace, store, tmp_path / "scratch")
    before = asyncio.run(tools.read({}, context))
    (workspace.repository / "calculator.py").write_text("changed later", encoding="utf-8")
    assert asyncio.run(tools.read({}, context)) == before
    assert asyncio.run(tools.patch({"diff": PATCH}, context))["checked"] is True
    for diff in (
        PATCH.replace("calculator.py", "../outside.py"),
        PATCH + "new mode 120000\n",
        "",
        PATCH.replace("calculator.py", "unselected.py"),
    ):
        with pytest.raises((StateConflict, ValueError)):
            asyncio.run(tools.patch({"diff": diff}, context))


def test_memory_persists_and_lexical_search_is_bounded(tmp_path):
    path = tmp_path / "workspace.sqlite3"
    store = WorkspaceStore(path)
    store.add_note(MemoryCreate(title="Café sums", content="Negative addition"))
    store.add_note(MemoryCreate(title="Other", content="Unrelated subject"))
    reopened = WorkspaceStore(path)
    assert len(reopened.notes("addition café")) == 1
    assert reopened.notes("nonexistent") == []
    assert len(reopened.notes(limit=1)) == 1


def test_browser_origin_host_and_content_type_protection(tmp_path, workspace):
    with TestClient(configured_app(tmp_path, workspace)) as client:
        assert client.get("/status", headers={"Origin": "https://evil.example"}).status_code == 403
        assert client.get("/status", headers={"Host": "evil.example"}).status_code == 400
        assert (
            client.post("/memory", data={"title": "unsafe", "content": "unsafe"}).status_code == 415
        )
        assert (
            client.post(
                "/memory",
                json={"title": "safe", "content": "safe"},
                headers={"Origin": "http://testserver"},
            ).status_code
            == 201
        )
        assert client.get("/status").headers["x-content-type-options"] == "nosniff"


def test_unconfigured_workflow_and_missing_artifact_refs(tmp_path):
    with TestClient(create_app(db_path=tmp_path / "missions.sqlite3")) as client:
        assert client.get("/status").json()["workflow_ready"] is False
        assert client.post("/workflows/developer", json={"goal": "Fix"}).status_code == 409
        assert (
            client.post(
                "/memory", json={"title": "x", "content": "y", "artifact_refs": ["missing"]}
            ).status_code
            == 404
        )


@pytest.mark.parametrize(
    "script,expected",
    [
        (
            "import os\nassert 'OPENAI_API_KEY' not in os.environ\nprint('clean environment')\n",
            True,
        ),
        ("raise SystemExit(7)\n", False),
        ("import time\ntime.sleep(30)\n", False),
        ("print('x' * 2000000)\n", False),
    ],
)
def test_actual_test_exit_timeout_environment_and_output_limit(
    tmp_path, workspace, monkeypatch, script, expected
):
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    (workspace.repository / "runner.py").write_text(script, encoding="utf-8")
    config = WorkspaceSettings(
        **(
            workspace.model_dump()
            | {
                "files": workspace.files + ("runner.py",),
                "test_commands": (("python", "runner.py"),),
                "test_timeout_seconds": 1,
            }
        )
    )
    tools = LocalWorkspaceTools(
        config, WorkspaceStore(tmp_path / "workspace.sqlite3"), tmp_path / "scratch"
    )
    result = asyncio.run(
        tools.test(
            {"diff": PATCH},
            ExecutionContext(workspace_id="local", mission_id="test", task_id="verify"),
        )
    )
    assert result["passed"] is expected
    assert len(result["report"]) < 33000
    assert "secret" not in result["report"]
    if "sleep" in script:
        assert "Timed out: True" in result["report"]


def test_snapshot_corruption_and_unknown_schema_fail_closed(tmp_path, workspace):
    path = tmp_path / "workspace.sqlite3"
    store = WorkspaceStore(path)
    store.snapshot("mission", workspace)
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE snapshots SET payload = '{}' WHERE mission_id = 'mission'")
    with pytest.raises(StateConflict):
        store.snapshot("mission", workspace)
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA user_version = 99")
    with pytest.raises(RuntimeError):
        WorkspaceStore(path)


def test_selected_symlink_is_rejected(tmp_path, workspace):
    link = workspace.repository / "link.py"
    try:
        link.symlink_to(workspace.repository / "calculator.py")
    except OSError:
        pytest.skip("Symlink creation is unavailable on this host")
    config = WorkspaceSettings(**(workspace.model_dump() | {"files": ("link.py",)}))
    with pytest.raises(StateConflict):
        WorkspaceStore(tmp_path / "workspace.sqlite3").snapshot("mission", config)
