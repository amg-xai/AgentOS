import pytest
from fastapi.testclient import TestClient

from agentos.adapters.manifests import ManifestError
from agentos.api.app import create_app


def test_discovery_api(registry, tmp_path):
    with TestClient(create_app(registry, db_path=tmp_path / "api.sqlite3")) as client:
        assert client.get("/health").json() == {"status": "ok", "capability": "discovery"}
        agents = client.get("/agents").json()
        assert {a["id"] for a in agents} == {
            "investigation",
            "code_helper",
            "testing",
            "creator_research",
            "creator_outline",
            "creator_script",
            "student_focus",
            "student_notes",
            "student_quiz",
            "developer_planner",
            "baseline_testing",
        }
        assert {r["id"] for r in client.get("/roles").json()} == {"developer", "creator", "student"}
        assert client.get("/roles/developer").json()["agents"] == [
            "investigation",
            "code_helper",
            "testing",
            "developer_planner",
            "baseline_testing",
        ]
        assert client.get("/agents/testing").json()["permissions"] == ["READ", "EXECUTE"]
        for path in ("/agents/missing", "/roles/missing"):
            assert client.get(path).status_code == 404
        assert client.get("/openapi.json").status_code == 200
        assert client.post("/agents/testing", json={}).status_code == 405


def test_explicit_manifest_root(tmp_path):
    from conftest import PACKAGES

    with TestClient(create_app(package_root=PACKAGES, db_path=tmp_path / "api.sqlite3")) as client:
        assert client.get("/agents").status_code == 200


def test_initialization_fails_on_bad_manifests(tmp_path):
    with pytest.raises(ManifestError):
        create_app(package_root=tmp_path)


def test_environment_package_root(monkeypatch, tmp_path):
    from conftest import PACKAGES

    monkeypatch.setenv("AGENTOS_PACKAGES", str(PACKAGES))
    monkeypatch.setenv("AGENTOS_DATABASE", str(tmp_path / "api.sqlite3"))
    with TestClient(create_app()) as client:
        assert len(client.get("/agents").json()) == 11
