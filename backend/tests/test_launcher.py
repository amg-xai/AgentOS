import pytest
from fastapi.testclient import TestClient

from agentos.api.app import create_app
from agentos.cli import setup_sample
from agentos.domain.workspace import WorkspaceSettings


def test_sample_setup_is_valid_and_preserves_existing_configuration(tmp_path):
    (tmp_path / "samples" / "calculator").mkdir(parents=True)
    path = setup_sample(tmp_path)
    settings = WorkspaceSettings.model_validate_json(path.read_text(encoding="utf-8"))
    assert settings.repository == (tmp_path / "samples" / "calculator").resolve()
    assert settings.test_commands == (("python", "-m", "unittest", "discover", "-v"),)
    path.write_text("user configuration", encoding="utf-8")
    with pytest.raises(FileExistsError):
        setup_sample(tmp_path)
    assert path.read_text(encoding="utf-8") == "user configuration"


def test_serves_client_assets_with_browser_security_headers(tmp_path):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text(
        '<html lang="en"><title>Mission Control</title></html>', encoding="utf-8"
    )
    with TestClient(
        create_app(db_path=tmp_path / "missions.sqlite3", frontend_root=frontend)
    ) as client:
        response = client.get("/app/")
        assert response.status_code == 200
        assert "Mission Control" in response.text
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
        assert response.headers["x-frame-options"] == "DENY"
        assert client.get("/app/missing.js").status_code == 404
        assert client.get("/docs").status_code == 200


def test_loads_explicit_workspace_configuration_without_exposing_keys(monkeypatch, tmp_path):
    (tmp_path / "samples" / "calculator").mkdir(parents=True)
    path = setup_sample(tmp_path)
    monkeypatch.setenv("AGENTOS_WORKSPACE_CONFIG", str(path))
    monkeypatch.setenv("AGENTOS_MODEL", "configured-model")
    monkeypatch.setenv("AGENTOS_MODEL_KEY", "private-server-key")
    with TestClient(create_app(db_path=tmp_path / "missions.sqlite3")) as client:
        response = client.get("/status")
        assert response.json()["workflow_ready"] is True
        assert "private-server-key" not in response.text
