import asyncio
import io
import sys
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from test_demo import demo_root as demo_fixture
from test_orchestration import create
from test_orchestration import runtime as runtime_fixture

from agentos.adapters.desktop import watch_parent
from agentos.api.app import create_app
from agentos.cli import main
from agentos.domain.governance import UserRole

demo_root = demo_fixture
runtime = runtime_fixture


def test_parent_eof_requests_shutdown_without_http_actions():
    server = SimpleNamespace(should_exit=False)
    watch_parent(server, io.StringIO("parent pipe"))
    assert server.should_exit


@pytest.mark.parametrize("session", ["", "invalid", "A" * 32, "a" * 31])
def test_desktop_cli_requires_explicit_valid_session(monkeypatch, session):
    monkeypatch.setenv("AGENTOS_DESKTOP_SESSION", session)
    monkeypatch.setattr(sys, "argv", ["agentos", "serve", "--desktop"])
    with pytest.raises(SystemExit) as result:
        main()
    assert result.value.code == 2


@pytest.mark.parametrize("demo", [False, True])
def test_owned_cli_identity_does_not_grant_shutdown_or_role_bypass(demo_root, monkeypatch, demo):
    token = "a" * 32
    monkeypatch.setenv("AGENTOS_DESKTOP_SESSION", token)
    monkeypatch.setenv("AGENTOS_USER_ROLE", "viewer")
    if not demo:
        monkeypatch.setenv("AGENTOS_PACKAGES", str(demo_root / "packages"))
        monkeypatch.delenv("AGENTOS_MODEL", raising=False)
        monkeypatch.setenv(
            "AGENTOS_DATABASE", str(demo_root / ".agentos/desktop-normal/missions.sqlite3")
        )
        monkeypatch.setenv("AGENTOS_WORKSPACE_CONFIG", str(demo_root / "missing-workspace.json"))
    monkeypatch.setattr(
        sys,
        "argv",
        ["agentos", "serve", "--desktop", "--root", str(demo_root), "--port", "8767"]
        + (["--demo"] if demo else []),
    )

    def capture(app, port):
        assert port == 8767
        with TestClient(app) as client:
            status = client.get("/status").json()
            assert status["desktop_session"] == token
            assert status["execution_mode"] == ("demo" if demo else "live")
            assert status["active_runs"] == 0
            assert client.post("/workflows/student", json={"goal": "study"}).status_code == 403
            assert client.post("/shutdown", json={"desktop_session": token}).status_code == 404

    monkeypatch.setattr("agentos.cli.serve_desktop", capture)
    main()


def test_web_startup_ignores_desktop_environment_identity(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTOS_DESKTOP_SESSION", "a" * 32)
    monkeypatch.delenv("AGENTOS_MODEL", raising=False)
    monkeypatch.setenv("AGENTOS_WORKSPACE_CONFIG", str(tmp_path / "missing.json"))
    with TestClient(create_app(db_path=tmp_path / "missions.sqlite3")) as client:
        status = client.get("/status").json()
        assert status["desktop_session"] is None and status["active_runs"] == 0


def test_active_run_count_and_interrupted_claim_are_preserved(runtime):
    async def scenario():
        mission = create(runtime)
        started = asyncio.Event()

        async def blocked(*args):
            started.set()
            await asyncio.Event().wait()

        runtime.executor.execute = blocked
        task = asyncio.create_task(
            runtime.runner.run(mission.id, mission.version, UserRole.OPERATOR)
        )
        await started.wait()
        assert runtime.runner.active_run_count == 1
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert runtime.runner.active_run_count == 0
        assert runtime.repository.claim(mission.id) is not None
        assert runtime.repository.get(mission.id).tasks[0].status.value == "RUNNING"

    asyncio.run(scenario())
