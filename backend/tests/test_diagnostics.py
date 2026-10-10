import json
import shutil
import sys
from pathlib import Path

import httpx
import pytest

from agentos.adapters.diagnostics import client_assets_valid, diagnose
from agentos.cli import main
from agentos.domain.workspace import WorkspaceSettings


@pytest.fixture
def configured_root(tmp_path, monkeypatch, live_policy_environment):
    project = Path(__file__).resolve().parents[2]
    shutil.copytree(project / "packages", tmp_path / "packages")
    source = tmp_path / "source"
    source.mkdir()
    (source / "calculator.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    config = WorkspaceSettings(
        name="Diagnostics sample",
        repository=source,
        files=("calculator.py",),
        test_commands=(("python", "-m", "unittest"),),
    )
    (tmp_path / ".agentos").mkdir()
    (tmp_path / ".agentos" / "workspace.json").write_text(
        config.model_dump_json(), encoding="utf-8"
    )
    client = tmp_path / "frontend" / "dist"
    (client / "assets").mkdir(parents=True)
    (client / "assets" / "main.js").write_text("export {};", encoding="utf-8")
    (client / "assets" / "main.css").write_text("body {}", encoding="utf-8")
    (client / "index.html").write_text(
        '<script src="/app/assets/main.js"></script>'
        '<link rel="stylesheet" href="/app/assets/main.css">',
        encoding="utf-8",
    )
    for name in (
        "AGENTOS_PACKAGES",
        "AGENTOS_WORKSPACE_CONFIG",
        "AGENTOS_MODEL",
        "AGENTOS_MODEL_KEY",
        "OPENAI_API_KEY",
        "AGENTOS_MODEL_URL",
        "AGENTOS_USER_ROLE",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AGENTOS_MODEL", "configured-model")
    monkeypatch.setenv("AGENTOS_MODEL_KEY", "private-server-key")
    monkeypatch.setenv("AGENTOS_ALLOW_LIVE_MODELS", "1")
    return tmp_path


def checks(report):
    return {check.id: check for check in report.checks}


def test_configured_provider_remains_blocked_without_live_authorization(
    configured_root, monkeypatch
):
    monkeypatch.delenv("AGENTOS_ALLOW_LIVE_MODELS")
    report = diagnose(configured_root)
    assert not report.configured_ready
    assert "disabled" in checks(report)["provider"].detail
    assert checks(report)["packages"].passed


def test_readiness_is_read_only_does_not_contact_model_or_expose_keys(configured_root, monkeypatch):
    before = {
        p.relative_to(configured_root): p.read_bytes()
        for p in configured_root.rglob("*")
        if p.is_file()
    }

    def no_provider(*args, **kwargs):
        pytest.fail("Readiness diagnostics must not contact the provider")

    monkeypatch.setattr(httpx, "AsyncClient", no_provider)
    report = diagnose(configured_root)
    assert report.configured_ready is True
    assert report.live_provider_verified is False
    assert "private-server-key" not in report.model_dump_json()
    after = {
        p.relative_to(configured_root): p.read_bytes()
        for p in configured_root.rglob("*")
        if p.is_file()
    }
    assert before == after
    assert not list(configured_root.rglob("*.sqlite3"))


def test_missing_provider_does_not_hide_available_checks(configured_root, monkeypatch):
    monkeypatch.delenv("AGENTOS_MODEL_KEY")
    report = diagnose(configured_root)
    assert not report.configured_ready
    assert not checks(report)["provider"].passed
    assert checks(report)["workspace"].passed
    assert checks(report)["client"].passed


@pytest.mark.parametrize(
    "case", ["source", "config", "manifests", "runner", "viewer", "role", "endpoint"]
)
def test_actionable_configuration_failures(configured_root, monkeypatch, case):
    expected = "workspace"
    if case == "source":
        (configured_root / "source" / "calculator.py").unlink()
    elif case == "config":
        (configured_root / ".agentos" / "workspace.json").write_text(
            '{"private-server-key": true}', encoding="utf-8"
        )
    elif case == "manifests":
        expected = "packages"
        (configured_root / "packages" / "developer" / "agents.json").write_text(
            "invalid-private-server-key", encoding="utf-8"
        )
    elif case == "runner":
        expected = "test_runners"
        path = configured_root / ".agentos" / "workspace.json"
        config = json.loads(path.read_text(encoding="utf-8"))
        config["test_commands"] = [[str(configured_root / "missing" / "python"), "-m", "unittest"]]
        path.write_text(json.dumps(config), encoding="utf-8")
    elif case in {"viewer", "role"}:
        expected = "permissions"
        monkeypatch.setenv(
            "AGENTOS_USER_ROLE", "viewer" if case == "viewer" else "invalid-private-server-key"
        )
    else:
        expected = "provider"
        monkeypatch.setenv("AGENTOS_MODEL_URL", "https://private-server-key@host/v1")
    report = diagnose(configured_root)
    assert not checks(report)[expected].passed
    assert "private-server-key" not in report.model_dump_json()


@pytest.mark.parametrize(
    "asset",
    ["/app/assets/missing.js", "/app/assets/../../../outside.js", "https://example.com/remote.js"],
)
def test_client_check_rejects_missing_escaping_and_remote_assets(configured_root, asset):
    client = configured_root / "frontend" / "dist"
    (client / "index.html").write_text(
        f'<script src="{asset}"></script><link rel="stylesheet" href="/app/assets/main.css">',
        encoding="utf-8",
    )
    assert not client_assets_valid(client)


@pytest.mark.parametrize("ready,exit_code", [(True, 0), (False, 1)])
def test_doctor_cli_loads_environment_reports_json_and_sets_exit_code(
    configured_root, monkeypatch, capsys, ready, exit_code
):
    monkeypatch.delenv("AGENTOS_MODEL_KEY")
    if ready:
        (configured_root / ".env").write_text(
            "AGENTOS_MODEL_KEY=private-server-key\n", encoding="utf-8"
        )
    monkeypatch.setattr(
        sys, "argv", ["agentos", "doctor", "--root", str(configured_root), "--json"]
    )
    monkeypatch.chdir(configured_root)
    with pytest.raises(SystemExit) as result:
        main()
    assert result.value.code == exit_code
    output = capsys.readouterr().out
    assert "private-server-key" not in output
    assert json.loads(output)["configured_ready"] is ready


def test_doctor_and_api_block_missing_limits_without_provisioning(configured_root, monkeypatch):
    from fastapi.testclient import TestClient

    from agentos.api.app import create_app

    monkeypatch.delenv("AGENTOS_LIVE_REQUEST_POLICY")
    missing = configured_root / "missing-allowance.db"
    monkeypatch.setenv("AGENTOS_LIVE_REQUEST_LEDGER", str(missing))
    report = diagnose(configured_root)
    assert not report.configured_ready
    assert not next(c for c in report.checks if c.id == "live_limits").passed
    with TestClient(create_app(db_path=configured_root / "missions.db")) as client:
        status = client.get("/status").json()
        assert not status["provider_configured"]
        assert not status["workflow_ready"]
    assert not missing.exists()
