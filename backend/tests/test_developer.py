"""Real filesystem/Git/subprocess integration; only the model transport is mocked."""

import asyncio
import difflib
import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

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


def plan_data(refine=False):
    tasks = [
        {
            "id": "investigate",
            "title": "Investigate goal",
            "agent_id": "investigation",
            "objective": "Gather source evidence",
            "dependencies": [],
            "bindings": [],
            "review_required": False,
        },
        {
            "id": "fix",
            "title": "Patch the identified issue",
            "agent_id": "code_helper",
            "objective": "Fix the issue without weakening tests",
            "dependencies": ["refine" if refine else "investigate"],
            "bindings": [
                {
                    "input_key": "findings",
                    "task_id": "refine" if refine else "investigate",
                    "output_key": "findings",
                }
            ],
            "review_required": False,
        },
        {
            "id": "verify",
            "title": "Test and review the patch",
            "agent_id": "testing",
            "objective": "Run configured tests and review the result",
            "dependencies": ["fix"],
            "bindings": [{"input_key": "diff", "task_id": "fix", "output_key": "diff"}],
            "review_required": True,
        },
    ]
    if refine:
        tasks.insert(
            1,
            {
                "id": "refine",
                "title": "Refine the evidence",
                "agent_id": "investigation",
                "objective": "Examine the constraint-sensitive behavior",
                "dependencies": ["investigate"],
                "bindings": [
                    {"input_key": "context", "task_id": "investigate", "output_key": "findings"}
                ],
                "review_required": False,
            },
        )
    return {
        "rationale": "Plan the requested investigation and a single reviewed patch",
        "constraints": ["Preserve existing test assertions"],
        "tasks": tasks,
    }


def model_transport(request):
    body = json.loads(request.content)
    inputs = json.loads(body["input"])
    agent = body["text"]["format"]["name"]
    if agent != "developer_planner":
        assert "calculator.py" in inputs["source_files"]
    outputs = (
        plan_data()
        if agent == "developer_planner"
        else {"findings": "calculator.py subtracts instead of adding"}
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
        assert len(artifacts) == 5
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
        planning = json.loads(request.content)["text"]["format"]["name"] == "developer_planner"
        return (
            httpx.Response(401, text="secret")
            if failing and not planning
            else model_transport(request)
        )

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


def test_review_binds_the_tested_patch_and_rejects_damage(tmp_path, workspace):
    with TestClient(configured_app(tmp_path, workspace)) as client:
        mission = client.post("/workflows/developer", json={"goal": "Fix addition"}).json()
        base = f"/missions/{mission['id']}"
        mission = client.post(base + "/run", json={"expected_version": 1}).json()
        approval = client.get(base + "/approvals").json()[0]
        artifacts = client.get(base + "/artifacts").json()
        covered = [a for a in artifacts if a["id"] in approval["payload"]["artifact_refs"]]
        assert {a["name"] for a in covered} == {"tested.diff", "test-report.txt"}
        tested = next(a for a in covered if a["name"] == "tested.diff")
        assert client.get(f"/artifacts/{tested['id']}/content").text == PATCH
        path = tmp_path / "artifacts" / f"{tested['id']}.txt"
        path.write_text("corrupted patch", encoding="utf-8")
        payload = {
            "expected_version": mission["version"],
            "decision": "approve",
            "payload_digest": approval["payload_digest"],
        }
        assert client.post(f"/approvals/{approval['id']}/decision", json=payload).status_code == 409
        assert client.get(base).json()["status"] == "WAITING_APPROVAL"
        denied = client.post(
            f"/approvals/{approval['id']}/decision", json=payload | {"decision": "deny"}
        )
        assert denied.status_code == 200
        assert denied.json()["status"] == "FAILED"


def test_bundled_acceptance_project_bug_fix_restart_and_source_preservation(tmp_path):
    source = Path(__file__).resolve().parents[2] / "samples" / "calculator"
    original = {
        name: (source / name).read_bytes()
        for name in ("calculator.py", "test_calculator.py", "README.md")
    }
    baseline = tmp_path / "baseline"
    shutil.copytree(source, baseline, ignore=shutil.ignore_patterns("__pycache__"))
    bug = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-v"],
        cwd=baseline,
        env=minimal_environment(),
        capture_output=True,
        timeout=15,
    )
    assert bug.returncode != 0
    assert "failures=2" in bug.stderr.decode()
    config = WorkspaceSettings(
        name="Bundled acceptance project",
        repository=source,
        files=tuple(original),
        test_commands=(("python", "-m", "unittest", "discover", "-v"),),
    )

    def transport(request):
        if json.loads(request.content)["text"]["format"]["name"] == "developer_planner":
            return model_transport(request)
        body = json.loads(request.content)
        inputs = json.loads(body["input"])
        text = inputs["source_files"]["calculator.py"]
        patch = "".join(
            difflib.unified_diff(
                text.splitlines(keepends=True),
                text.replace("return left - right", "return left + right").splitlines(
                    keepends=True
                ),
                fromfile="a/calculator.py",
                tofile="b/calculator.py",
            )
        )
        outputs = (
            {"findings": "The implementation subtracts; tests cover positive, negative, and zero."}
            if body["text"]["format"]["name"] == "investigation"
            else {"diff": patch, "summary": "Correct the operator without changing any tests."}
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

    with TestClient(configured_app(tmp_path, config, transport)) as client:
        mission = client.post(
            "/workflows/developer", json={"goal": "Fix the bundled sample without weakening tests"}
        ).json()
        base = f"/missions/{mission['id']}"
        mission = client.post(base + "/run", json={"expected_version": 1}).json()
        assert mission["status"] == "WAITING_APPROVAL", mission
        assert mission["tasks"][2]["outputs"]["passed"] is True
        assert "Ran 3 tests" in mission["tasks"][2]["outputs"]["report"]
    with TestClient(configured_app(tmp_path, config, transport)) as client:
        approval = client.get(base + "/approvals").json()[0]
        result = client.post(
            f"/approvals/{approval['id']}/decision",
            json={
                "expected_version": mission["version"],
                "decision": "approve",
                "payload_digest": approval["payload_digest"],
            },
        )
        assert result.status_code == 200
        assert result.json()["status"] == "COMPLETED"
    assert original == {name: (source / name).read_bytes() for name in original}
