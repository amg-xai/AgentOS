from fastapi.testclient import TestClient
from test_missions import workflow

from agentos.api.app import create_app


def test_mission_api_lifecycle_and_persistence(registry, tmp_path):
    database = tmp_path / "api.sqlite3"
    with TestClient(create_app(registry, db_path=database)) as client:
        response = client.post("/missions", json=workflow())
        assert response.status_code == 201
        mission = response.json()
        mission_id = mission["id"]
        assert mission["status"] == "PENDING"
        assert client.get("/missions").json() == [mission]
        base = f"/missions/{mission_id}"
        for action, extra in (("start", {}), ("complete", {"outputs": {"findings": "Bug"}})):
            response = client.post(
                f"{base}/tasks/inspect/actions",
                json={
                    "expected_version": mission["version"],
                    "action": action,
                    **extra,
                },
            )
            assert response.status_code == 200
            mission = response.json()
        assert mission["version"] == 3
        assert mission["tasks"][1]["status"] == "READY"
        events = client.get(f"{base}/events?limit=2").json()
        assert len(events) == 2
        later = client.get(f"{base}/events?after={events[-1]['sequence']}").json()
        assert all(event["sequence"] > events[-1]["sequence"] for event in later)
    with TestClient(create_app(registry, db_path=database)) as client:
        assert client.get(base).json() == mission
        response = client.post(f"{base}/cancel", json={"expected_version": 3})
        assert response.status_code == 200
        assert response.json()["status"] == "CANCELLED"
        assert response.json()["tasks"][2]["outputs"] == {"findings": "Bug"}


def test_api_error_contract(registry, tmp_path):
    with TestClient(create_app(registry, db_path=tmp_path / "api.sqlite3")) as client:
        for path in ("/missions/missing", "/missions/missing/events"):
            assert client.get(path).status_code == 404
        assert (
            client.post("/missions/missing/cancel", json={"expected_version": 1}).status_code == 404
        )
        assert client.post("/missions", json={"goal": "No tasks", "tasks": []}).status_code == 422
        assert client.post("/missions", json=workflow() | {"role_id": "missing"}).status_code == 422
        cyclic = workflow()
        cyclic["tasks"][2]["dependencies"] = ["test"]
        assert client.post("/missions", json=cyclic).status_code == 422
        mission = client.post("/missions", json=workflow()).json()
        base = f"/missions/{mission['id']}"
        assert (
            client.post(
                f"{base}/tasks/missing/actions",
                json={
                    "expected_version": 1,
                    "action": "start",
                },
            ).status_code
            == 404
        )
        assert (
            client.post(
                f"{base}/tasks/fix/actions",
                json={
                    "expected_version": 1,
                    "action": "start",
                },
            ).status_code
            == 409
        )
        for payload in (
            {"expected_version": 1, "action": "complete"},
            {"expected_version": 1, "action": "fail", "error": " "},
            {"expected_version": 1, "action": "start", "outputs": {}},
            {"expected_version": True, "action": "start"},
            {"expected_version": 1, "action": "resume"},
        ):
            assert client.post(f"{base}/tasks/inspect/actions", json=payload).status_code == 422
        assert (
            client.post(
                f"{base}/tasks/inspect/actions",
                json={
                    "expected_version": 1,
                    "action": "start",
                },
            ).status_code
            == 200
        )
        assert client.post(f"{base}/cancel", json={"expected_version": 1}).status_code == 409
        for path in ("/missions?limit=101", "/missions?offset=-1", f"{base}/events?after=-1"):
            assert client.get(path).status_code == 422
