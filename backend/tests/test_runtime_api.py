from fastapi.testclient import TestClient
from test_orchestration import execution_workflow
from test_orchestration import runtime as runtime_fixture

from agentos.api.app import create_app
from agentos.domain.governance import UserRole

runtime = runtime_fixture


def client_app(runtime, role=UserRole.OPERATOR, with_executors=True):
    return create_app(
        runtime.registry,
        db_path=runtime.repository.path,
        artifact_root=runtime.storage.root,
        executors=runtime.executors if with_executors else None,
        user_role=role,
    )


def test_http_workflow_review_artifact_and_resume(runtime):
    with TestClient(client_app(runtime)) as client:
        mission = client.post("/missions", json=execution_workflow()).json()
        base = f"/missions/{mission['id']}"
        response = client.post(f"{base}/run", json={"expected_version": mission["version"]})
        assert response.status_code == 200, response.text
        mission = response.json()
        assert mission["status"] == "WAITING_APPROVAL"
        assert client.get(f"{base}/run").json() is None
        approval = client.get(f"{base}/approvals").json()[0]
        assert client.get(f"/approvals/{approval['id']}").json() == approval
        artifact = client.get(f"{base}/artifacts").json()[0]
        assert client.get(f"/artifacts/{artifact['id']}").json() == artifact
        content = client.get(f"/artifacts/{artifact['id']}/content")
        assert content.status_code == 200
        assert content.text == mission["tasks"][1]["outputs"]["diff"]
        assert content.headers["content-disposition"] == 'attachment; filename="proposed.diff"'
        decision = {
            "expected_version": mission["version"],
            "decision": "approve",
            "payload_digest": approval["payload_digest"],
        }
        assert (
            client.post(
                f"/approvals/{approval['id']}/decision",
                json=decision
                | {
                    "payload_digest": "0" * 64,
                },
            ).status_code
            == 409
        )
        response = client.post(f"/approvals/{approval['id']}/decision", json=decision)
        assert response.status_code == 200
        mission = response.json()
        assert (
            client.post(f"/approvals/{approval['id']}/decision", json=decision).status_code == 409
        )
        response = client.post(f"{base}/run", json={"expected_version": mission["version"]})
        assert response.status_code == 200
        assert response.json()["status"] == "COMPLETED"
        assert len(runtime.executor.calls) == 3


def test_viewer_is_read_only_and_request_headers_do_not_grant_roles(runtime):
    with TestClient(client_app(runtime)) as client:
        mission = client.post("/missions", json=execution_workflow()).json()
        mission = client.post(f"/missions/{mission['id']}/run", json={"expected_version": 1}).json()
        approval = client.get(f"/missions/{mission['id']}/approvals").json()[0]
    with TestClient(client_app(runtime, UserRole.VIEWER)) as viewer:
        base = f"/missions/{mission['id']}"
        assert viewer.get(base).status_code == 200
        assert viewer.get(f"{base}/artifacts").status_code == 200
        requests = [
            ("/missions", execution_workflow()),
            (f"{base}/cancel", {"expected_version": mission["version"]}),
            (f"{base}/run", {"expected_version": mission["version"]}),
            (
                f"{base}/tasks/verify/actions",
                {"expected_version": mission["version"], "action": "start"},
            ),
            (
                f"/approvals/{approval['id']}/decision",
                {
                    "expected_version": mission["version"],
                    "decision": "approve",
                    "payload_digest": approval["payload_digest"],
                },
            ),
        ]
        for url, payload in requests:
            assert (
                viewer.post(url, json=payload, headers={"X-User-Role": "admin"}).status_code == 403
            )


def test_default_api_does_not_run_implicit_fixtures(runtime):
    with TestClient(client_app(runtime, with_executors=False)) as client:
        mission = client.post("/missions", json=execution_workflow()).json()
        response = client.post(f"/missions/{mission['id']}/run", json={"expected_version": 1})
        assert response.status_code == 409
        assert "No executor configured" in response.json()["detail"]
        assert runtime.executor.calls == []


def test_runtime_api_missing_records_and_recovery_permissions(runtime):
    with TestClient(client_app(runtime)) as client:
        for url in (
            "/approvals/missing",
            "/artifacts/missing",
            "/artifacts/missing/content",
            "/missions/missing/artifacts",
            "/missions/missing/approvals",
            "/missions/missing/run",
        ):
            assert client.get(url).status_code == 404
        assert (
            client.post(
                "/missions/missing/recover",
                json={
                    "expected_version": 1,
                    "claim_token": "missing",
                    "acknowledge_ambiguity": True,
                },
            ).status_code
            == 403
        )
