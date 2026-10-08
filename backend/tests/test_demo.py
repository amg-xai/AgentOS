"""Offline demo integration uses actual Git, subprocess tests, and durable reviews."""

import json
import shutil
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from agentos.adapters.demo import DEMO_GOAL, DEMO_LABEL, SAMPLE_DIGESTS, demo_workspace
from agentos.adapters.diagnostics import diagnose
from agentos.api.app import create_app, create_demo_app
from agentos.cli import main
from agentos.domain.governance import UserRole
from agentos.domain.missions import StateConflict
from agentos.services.developer import developer_mission


@pytest.fixture
def demo_root(tmp_path, monkeypatch):
    project = Path(__file__).resolve().parents[2]
    shutil.copytree(project / "packages", tmp_path / "packages")
    shutil.copytree(project / "samples", tmp_path / "samples")
    state = tmp_path / ".agentos"
    state.mkdir()
    (state / "agentos.sqlite3").write_bytes(b"existing normal history")
    (state / "workspace.sqlite3").write_bytes(b"existing normal memory")
    (state / "workspace.json").write_text("user configuration", encoding="utf-8")
    assets = tmp_path / "frontend" / "dist" / "assets"
    assets.mkdir(parents=True)
    (assets / "demo.js").write_text("export {};", encoding="utf-8")
    (assets / "demo.css").write_text("body {}", encoding="utf-8")
    (assets.parent / "index.html").write_text(
        '<script src="/app/assets/demo.js"></script>'
        '<link rel="stylesheet" href="/app/assets/demo.css">',
        encoding="utf-8",
    )
    # Normal configuration must never redirect demo storage or instantiate a provider.
    monkeypatch.setenv("AGENTOS_DATABASE", str(state / "agentos.sqlite3"))
    monkeypatch.setenv("AGENTOS_ARTIFACTS", str(state / "normal-artifacts"))
    monkeypatch.setenv("AGENTOS_WORKSPACE_CONFIG", str(state / "workspace.json"))
    monkeypatch.setenv("AGENTOS_PACKAGES", str(tmp_path / "nonexistent-packages"))
    monkeypatch.setenv("AGENTOS_MODEL", "configured-live-model")
    monkeypatch.setenv("AGENTOS_MODEL_KEY", "private-key-must-stay-local")
    monkeypatch.setenv("AGENTOS_MODEL_URL", "invalid-even-if-parsed")
    monkeypatch.setenv("AGENTOS_USER_ROLE", "operator")

    def no_network(*args, **kwargs):
        pytest.fail("Offline demo must not construct a model HTTP client")

    monkeypatch.setattr(httpx, "AsyncClient", no_network)
    return tmp_path


def originals(root):
    return {
        p.relative_to(root): p.read_bytes()
        for p in root.rglob("*")
        if p.is_file() and not p.is_relative_to(root / ".agentos" / "demo")
    }


def run_demo(client):
    created = client.post("/workflows/developer", json={"goal": DEMO_GOAL})
    assert created.status_code == 201, created.text
    base = f"/missions/{created.json()['id']}"
    run = client.post(base + "/run", json={"expected_version": 1})
    assert run.status_code == 200, run.text
    result = run.json()
    assert result["status"] == "WAITING_APPROVAL", result
    assert result["tasks"][2]["outputs"]["passed"] is True
    report = result["tasks"][2]["outputs"]["report"]
    assert DEMO_LABEL in report and "Ran 3 tests" in report and "Exit code: 0" in report
    return base, result


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


def test_complete_demo_restart_memory_and_source_preservation(demo_root, monkeypatch):
    before = originals(demo_root)
    monkeypatch.chdir(demo_root)
    with TestClient(create_demo_app()) as client:
        status = client.get("/status").json()
        assert status["execution_mode"] == "demo"
        assert status["execution_label"] == DEMO_LABEL
        assert status["demo_goal"] == DEMO_GOAL
        assert status["provider_configured"] is False and status["model"] is None
        assert status["workflow_ready"] is True
        assert client.get("/app/").status_code == 200
        assert "private-key" not in json.dumps(status)
        base, mission = run_demo(client)
        artifacts = client.get(base + "/artifacts").json()
        assert len(artifacts) == 8
        assert sum(a["name"] == "offline-demo.txt" for a in artifacts) == 3
        for item in artifacts:
            content = client.get(f"/artifacts/{item['id']}/content").text
            if not item["name"].endswith(".diff"):
                assert DEMO_LABEL in content
        patch = next(a for a in artifacts if a["name"] == "tested.diff")
        assert "+    return left + right" in client.get(f"/artifacts/{patch['id']}/content").text
        saved = client.post(
            "/memory",
            json={
                "title": "Demo review",
                "content": "Tested fixture",
                "artifact_refs": [patch["id"]],
            },
        )
        assert saved.status_code == 201
        events = client.get(base + "/events?limit=1000").json()
        assert sum(e["action"] == "tool_completed" for e in events) == 4
        assert "private-key" not in json.dumps(events)
    with TestClient(create_demo_app()) as client:
        assert client.get(base).json() == mission
        assert client.get("/memory").json()[0]["artifact_refs"] == [patch["id"]]
        accepted = decide(client, base, mission, "approve")
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["status"] == "COMPLETED"
        assert client.get(base + "/artifacts").json() == artifacts
    assert before == originals(demo_root)
    assert not (demo_root / ".agentos" / "normal-artifacts").exists()


def test_demo_denial_retry_and_integrity_gate(demo_root):
    with TestClient(create_app(demo_root=demo_root)) as client:
        base, mission = run_demo(client)
        denied = decide(client, base, mission, "deny").json()
        assert denied["status"] == "FAILED"
        retry = client.post(
            base + "/tasks/verify/actions",
            json={"expected_version": denied["version"], "action": "retry"},
        ).json()
        mission = client.post(base + "/run", json={"expected_version": retry["version"]}).json()
        assert mission["tasks"][0]["attempts"] == 1
        assert mission["tasks"][1]["attempts"] == 1
        assert mission["tasks"][2]["attempts"] == 2
        approval = client.get(base + "/approvals").json()[0]
        artifacts = client.get(base + "/artifacts").json()
        tested = next(
            a
            for a in artifacts
            if a["name"] == "tested.diff" and a["id"] in approval["payload"]["artifact_refs"]
        )
        # Same storage convention used by ArtifactStore: generated id only.
        storage = demo_root / ".agentos" / "demo" / "artifacts"
        paths = list(storage.rglob(tested["id"] + "*"))
        assert len(paths) == 1
        paths[0].write_text("damaged", encoding="utf-8")
        assert decide(client, base, mission, "approve").status_code == 409
        assert decide(client, base, mission, "deny").json()["status"] == "FAILED"


@pytest.mark.parametrize("name", list(SAMPLE_DIGESTS))
def test_modified_sample_refused_before_any_demo_state_is_created(demo_root, name):
    path = demo_root / "samples" / "calculator" / name
    path.write_text("unrecognized source", encoding="utf-8")
    with pytest.raises(StateConflict, match="unchanged bundled"):
        create_app(demo_root=demo_root)
    assert not (demo_root / ".agentos" / "demo").exists()


def test_demo_rejects_custom_goals_and_rechecks_source_at_creation(demo_root):
    with TestClient(create_app(demo_root=demo_root)) as client:
        assert (
            client.post("/workflows/developer", json={"goal": "Fix my other app"}).status_code
            == 409
        )
        assert (
            client.post(
                "/missions", json=developer_mission(DEMO_GOAL).model_dump(mode="json")
            ).status_code
            == 409
        )
        mission = client.post("/workflows/developer", json={"goal": DEMO_GOAL}).json()
        base = f"/missions/{mission['id']}"
        assert (
            client.post(
                base + "/tasks/investigate/actions", json={"expected_version": 1, "action": "start"}
            ).status_code
            == 409
        )
        source = demo_root / "samples" / "calculator" / "calculator.py"
        source.write_text("changed", encoding="utf-8")
        assert client.post("/workflows/developer", json={"goal": DEMO_GOAL}).status_code == 409
        assert len(client.get("/missions").json()) == 1


def test_demo_viewer_cannot_create_run_or_save(demo_root):
    with TestClient(create_app(demo_root=demo_root, user_role=UserRole.VIEWER)) as client:
        assert client.get("/status").json()["user_role"] == "viewer"
        assert client.post("/workflows/developer", json={"goal": DEMO_GOAL}).status_code == 403
        assert (
            client.post("/memory", json={"title": "No", "content": "Read only"}).status_code == 403
        )


def test_normal_startup_without_provider_does_not_enable_demo(demo_root, monkeypatch):
    monkeypatch.delenv("AGENTOS_MODEL")
    with TestClient(
        create_app(
            package_root=demo_root / "packages",
            db_path=demo_root / "normal.sqlite3",
            workspace=demo_workspace(demo_root),
        )
    ) as client:
        status = client.get("/status").json()
        assert status["execution_mode"] == "live" and status["demo_goal"] is None
        assert not status["workflow_ready"]
        assert client.post("/workflows/developer", json={"goal": DEMO_GOAL}).status_code == 409


def test_demo_diagnostics_are_read_only_and_ignore_provider_settings(demo_root):
    before = originals(demo_root)
    report = diagnose(demo_root, demo=True)
    assert report.configured_ready and report.execution_mode == "demo"
    assert not report.live_provider_verified
    assert "private-key" not in report.model_dump_json()
    assert before == originals(demo_root)
    assert not (demo_root / ".agentos" / "demo").exists()


def test_demo_cli_selects_explicit_factory_without_changing_configuration(demo_root, monkeypatch):
    before = originals(demo_root)
    calls = []
    monkeypatch.setattr("agentos.cli.uvicorn.run", lambda *a, **kw: calls.append((a, kw)))
    monkeypatch.chdir(demo_root)
    monkeypatch.setattr(sys, "argv", ["agentos", "serve", "--demo", "--port", "8765"])
    main()
    assert calls == [
        (("agentos.api.app:create_demo_app",), {"factory": True, "host": "127.0.0.1", "port": 8765})
    ]
    assert before == originals(demo_root)
    assert not (demo_root / ".agentos" / "demo").exists()


def test_demo_cannot_combine_with_sample_setup_or_custom_storage(demo_root, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["agentos", "setup-sample", "--demo"])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    with pytest.raises(ValueError, match="isolated startup"):
        create_app(demo_root=demo_root, db_path=demo_root / "normal.sqlite3")


def test_demo_never_constructs_a_provider_with_valid_live_credentials(demo_root, monkeypatch):
    monkeypatch.setenv("AGENTOS_MODEL_URL", "https://api.openai.com/v1")

    def no_provider(*args, **kwargs):
        pytest.fail("Demo must not construct a provider even when live settings are valid")

    monkeypatch.setattr("agentos.api.app.ResponsesExecutor", no_provider)
    with TestClient(create_app(demo_root=demo_root)) as client:
        run_demo(client)


def test_demo_refuses_changed_source_between_creation_and_run(demo_root):
    with TestClient(create_app(demo_root=demo_root)) as client:
        mission = client.post("/workflows/developer", json={"goal": DEMO_GOAL}).json()
        (demo_root / "samples" / "calculator" / "test_calculator.py").write_text(
            "import os\nraise AssertionError('unrecognized test')\n", encoding="utf-8"
        )
        base = f"/missions/{mission['id']}"
        result = client.post(base + "/run", json={"expected_version": 1}).json()
        assert result["status"] == "FAILED"
        assert "StateConflict" in result["tasks"][0]["error"]
        assert not client.get(base + "/artifacts").json()


def test_demo_storage_redirect_is_refused(demo_root):
    target = demo_root / "existing-normal-data"
    target.mkdir()
    marker = target / "agentos.sqlite3"
    marker.write_bytes(b"preserve")
    link = demo_root / ".agentos" / "demo"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("This account cannot create symlinks")
    with pytest.raises(StateConflict, match="must not redirect"):
        create_app(demo_root=demo_root)
    report = diagnose(demo_root, demo=True)
    assert not report.configured_ready
    assert not next(c for c in report.checks if c.id == "demo_storage").passed
    assert marker.read_bytes() == b"preserve"


def test_demo_doctor_cli_is_explicit_and_does_not_create_runtime_data(
    demo_root, monkeypatch, capsys
):
    monkeypatch.chdir(demo_root)
    monkeypatch.setattr(sys, "argv", ["agentos", "doctor", "--demo", "--json"])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["execution_mode"] == "demo"
    assert report["configured_ready"] is True
    assert not (demo_root / ".agentos" / "demo").exists()
