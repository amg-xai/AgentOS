"""Same-mission correction with injected generation and actual Git/test tools."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from fastapi.testclient import TestClient
from test_demo import demo_root as demo_root_fixture
from test_developer import PATCH, configured_app, model_transport
from test_developer import workspace as workspace_fixture

from agentos.adapters.sqlite import SQLiteMissionRepository
from agentos.api.app import create_demo_app

workspace = workspace_fixture
demo_root = demo_root_fixture

BAD_PATCH = PATCH.replace("return a + b", "return a * b")


def transport_for(patches, calls):
    def transport(request):
        body = json.loads(request.content)
        if body["text"]["format"]["name"] != "code_helper":
            return model_transport(request)
        calls.append(json.loads(body["input"]))
        patch = patches[min(len(calls) - 1, len(patches) - 1)]
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(
                                    {"diff": patch, "summary": "Proposed correction"}
                                ),
                            }
                        ],
                    }
                ],
            },
        )

    return transport


def run(client, base, mission):
    result = client.post(base + "/run", json={"expected_version": mission["version"]})
    assert result.status_code == 200, result.text
    return result.json()


def deny(client, base, mission):
    approval = client.get(base + "/approvals").json()[0]
    result = client.post(
        f"/approvals/{approval['id']}/decision",
        json={
            "expected_version": mission["version"],
            "decision": "deny",
            "payload_digest": approval["payload_digest"],
        },
    )
    assert result.status_code == 200, result.text
    return result.json(), approval


def revision_body(mission, approval, feedback="Use addition, preserve the tests"):
    return {
        "expected_version": mission["version"],
        "approval_id": approval["id"],
        "payload_digest": approval["payload_digest"],
        "feedback": feedback,
    }


def test_revision_real_tests_restart_and_fresh_review(tmp_path, workspace):
    calls = []
    transport = transport_for([BAD_PATCH, PATCH], calls)
    originals = {name: (workspace.repository / name).read_bytes() for name in workspace.files}
    with TestClient(configured_app(tmp_path, workspace, transport)) as client:
        mission = client.post("/workflows/developer", json={"goal": "Fix addition"}).json()
        base = f"/missions/{mission['id']}"
        failed = run(client, base, mission)
        assert failed["tasks"][-1]["outputs"]["passed"] is False
        assert client.get(base + "/patch-revision").json()["allowed"] is False
        mission, old = deny(client, base, failed)
        evidence = client.get(base + "/artifacts").json()
    with TestClient(configured_app(tmp_path, workspace, transport)) as client:
        assert client.get(base + "/patch-revision").json()["allowed"] is True
        body = revision_body(mission, old)
        response = client.post(base + "/patch-revision", json=body)
        assert response.status_code == 200, response.text
        revised = response.json()
        assert len(calls) == 1  # Request never runs the model or tools.
        assert revised["planning"] == mission["planning"]
        assert revised["goal"] == mission["goal"]
        for before, after in zip(mission["tasks"], revised["tasks"], strict=True):
            if before["id"] not in {"fix", "verify"}:
                assert before == after
            else:
                assert after["outputs"] is None and after["artifact_refs"] == []
        assert client.post(base + "/patch-revision", json=body).status_code == 409
        assert client.get(base + "/artifacts").json() == evidence
    with TestClient(configured_app(tmp_path, workspace, transport)) as client:
        result = run(client, base, revised)
        assert result["status"] == "WAITING_APPROVAL"
        assert result["tasks"][-1]["outputs"]["passed"] is True
        context = calls[-1]["patch_revision"]
        assert context["previous_diff"] == BAD_PATCH.strip()
        assert context["feedback"] == body["feedback"]
        assert context["failed_tests"] is True
        assert "report" not in context and "test_commands" not in context
        assert calls[-1]["goal"] == "Fix addition"
        for key in ("constraints", "objective", "findings", "baseline_summary", "source_files"):
            assert calls[-1][key] == calls[0][key]
        for line in failed["tasks"][-1]["outputs"]["report"].splitlines():
            if line.startswith(("Source SHA-256:", "Recipe SHA-256:")):
                assert line in result["tasks"][-1]["outputs"]["report"]
        assert [t["attempts"] for t in result["tasks"]] == [1, 2, 1, 1, 2]
        replay = client.post(
            f"/approvals/{old['id']}/decision",
            json={
                "expected_version": result["version"],
                "decision": "approve",
                "payload_digest": old["payload_digest"],
            },
        )
        assert replay.status_code == 409
        fresh = client.get(base + "/approvals").json()[0]
        assert fresh["id"] != old["id"]
        accepted = client.post(
            f"/approvals/{fresh['id']}/decision",
            json={
                "expected_version": result["version"],
                "decision": "approve",
                "payload_digest": fresh["payload_digest"],
            },
        )
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["status"] == "COMPLETED"
        assert len(accepted.json()["developer_revisions"]) == 1
    assert originals == {
        name: (workspace.repository / name).read_bytes() for name in workspace.files
    }


def test_two_revision_limit_and_feedback_validation(tmp_path, workspace):
    calls = []
    with TestClient(
        configured_app(tmp_path, workspace, transport_for([BAD_PATCH], calls))
    ) as client:
        mission = client.post("/workflows/developer", json={"goal": "Fix addition"}).json()
        base = f"/missions/{mission['id']}"
        for number in range(3):
            mission = run(client, base, mission)
            mission, approval = deny(client, base, mission)
            body = revision_body(mission, approval)
            if number == 2:
                assert client.get(base + "/patch-revision").json()["remaining"] == 0
                assert client.post(base + "/patch-revision", json=body).status_code == 409
                break
            for feedback in ["", "   ", "x" * 2001]:
                assert (
                    client.post(
                        base + "/patch-revision", json={**body, "feedback": feedback}
                    ).status_code
                    == 422
                )
            assert (
                client.post(
                    base + "/patch-revision", json={**body, "payload_digest": "0" * 64}
                ).status_code
                == 409
            )
            assert (
                client.post(
                    base + "/patch-revision", json={**body, "approval_id": "wrong-result"}
                ).status_code
                == 409
            )
            response = client.post(base + "/patch-revision", json=body)
            assert response.status_code == 200, response.text
            mission = response.json()
        assert len(calls) == 3


@pytest.mark.parametrize("passes", [False, True])
def test_requires_denied_failed_tests(tmp_path, workspace, passes):
    with TestClient(
        configured_app(tmp_path, workspace, transport_for([PATCH if passes else BAD_PATCH], []))
    ) as client:
        mission = client.post("/workflows/developer", json={"goal": "Fix addition"}).json()
        base = f"/missions/{mission['id']}"
        mission = run(client, base, mission)
        approval = client.get(base + "/approvals").json()[0]
        assert (
            client.post(base + "/patch-revision", json=revision_body(mission, approval)).status_code
            == 409
        )
        if passes:
            mission, approval = deny(client, base, mission)
            assert (
                client.post(
                    base + "/patch-revision", json=revision_body(mission, approval)
                ).status_code
                == 409
            )


@pytest.mark.parametrize(
    "blocker", ["artifact", "claim", "viewer", "cancel", "agent", "outcome", "legacy"]
)
def test_revision_blockers_leave_state_untouched(tmp_path, workspace, monkeypatch, blocker):
    calls = []
    transport = transport_for([BAD_PATCH], calls)
    with TestClient(configured_app(tmp_path, workspace, transport)) as client:
        mission = client.post("/workflows/developer", json={"goal": "Fix addition"}).json()
        base = f"/missions/{mission['id']}"
        mission, approval = deny(client, base, run(client, base, mission))
        if blocker == "artifact":
            ref = approval["payload"]["artifact_refs"][0]
            (tmp_path / "artifacts" / f"{ref}.txt").write_text("damaged", encoding="utf-8")
        elif blocker == "claim":
            SQLiteMissionRepository(tmp_path / "missions.sqlite3").acquire_claim(
                mission["id"], mission["version"], "other"
            )
        elif blocker == "cancel":
            mission = client.post(
                base + "/cancel", json={"expected_version": mission["version"]}
            ).json()
        elif blocker == "viewer":
            monkeypatch.setenv("AGENTOS_USER_ROLE", "viewer")
        else:
            with sqlite3.connect(tmp_path / "missions.sqlite3") as connection:
                data = json.loads(connection.execute("SELECT payload FROM missions").fetchone()[0])
                if blocker == "agent":
                    next(t for t in data["tasks"] if t["id"] == "fix")["agent_id"] = "testing"
                elif blocker == "outcome":
                    next(t for t in data["tasks"] if t["id"] == "verify")["outputs"]["passed"] = (
                        "false"
                    )
                else:
                    data["planning"] = None
                connection.execute("UPDATE missions SET payload = ?", (json.dumps(data),))
    with TestClient(configured_app(tmp_path, workspace, transport)) as client:
        before = client.get(base).json()
        events = client.get(base + "/events").json()
        response = client.post(base + "/patch-revision", json=revision_body(mission, approval))
        assert response.status_code == (
            403 if blocker == "viewer" else (422 if blocker == "agent" else 409)
        ), response.text
        assert client.get(base).json() == before
        assert client.get(base + "/events").json() == events
        assert len(calls) == 1


def test_concurrent_requests_spend_one_slot(tmp_path, workspace):
    with TestClient(configured_app(tmp_path, workspace, transport_for([BAD_PATCH], []))) as client:
        mission = client.post("/workflows/developer", json={"goal": "Fix addition"}).json()
        base = f"/missions/{mission['id']}"
        mission, approval = deny(client, base, run(client, base, mission))
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(
                    lambda _: (
                        client.post(
                            base + "/patch-revision", json=revision_body(mission, approval)
                        ).status_code
                    ),
                    range(2),
                )
            )
        assert sorted(results) == [200, 409]
        assert len(client.get(base).json()["developer_revisions"]) == 1


@pytest.mark.parametrize(
    "damage", ["artifact", "goal", "digest", "approval_scope", "approval_attempt", "artifact_scope"]
)
def test_revision_preflight_rejects_damage_before_claim(tmp_path, workspace, damage):
    calls = []
    transport = transport_for([BAD_PATCH, PATCH], calls)
    with TestClient(configured_app(tmp_path, workspace, transport)) as client:
        mission = client.post("/workflows/developer", json={"goal": "Fix addition"}).json()
        base = f"/missions/{mission['id']}"
        mission, approval = deny(client, base, run(client, base, mission))
        mission = client.post(
            base + "/patch-revision", json=revision_body(mission, approval)
        ).json()
        if damage == "artifact":
            ref = approval["payload"]["artifact_refs"][0]
            (tmp_path / "artifacts" / f"{ref}.txt").write_text("damage", encoding="utf-8")
        elif damage in {"approval_scope", "approval_attempt", "artifact_scope"}:
            with sqlite3.connect(tmp_path / "missions.sqlite3") as connection:
                table = "artifacts" if damage == "artifact_scope" else "approvals"
                identifier = (
                    approval["payload"]["artifact_refs"][0]
                    if table == "artifacts"
                    else approval["id"]
                )
                data = json.loads(
                    connection.execute(
                        f"SELECT payload FROM {table} WHERE id = ?", (identifier,)
                    ).fetchone()[0]
                )
                if damage == "approval_attempt":
                    data["task_attempt"] += 1
                else:
                    data["mission_id"] = "different-mission"
                connection.execute(
                    f"UPDATE {table} SET payload = ? WHERE id = ?", (json.dumps(data), identifier)
                )
        else:
            with sqlite3.connect(tmp_path / "missions.sqlite3") as connection:
                data = json.loads(connection.execute("SELECT payload FROM missions").fetchone()[0])
                if damage == "goal":
                    data["goal"] = "Changed scope"
                else:
                    data["developer_revisions"][0]["plan_digest"] = "0" * 64
                connection.execute("UPDATE missions SET payload = ?", (json.dumps(data),))
        response = client.post(base + "/run", json={"expected_version": mission["version"]})
        assert response.status_code in {409, 422}, response.text
        assert client.get(base + "/run").json() is None
        assert len(calls) == 1


def test_fixed_demo_revision_disabled(demo_root, monkeypatch):
    monkeypatch.chdir(demo_root)
    with TestClient(create_demo_app()) as client:
        mission = client.post(
            "/workflows/developer", json={"goal": client.get("/status").json()["demo_goal"]}
        ).json()
        base = f"/missions/{mission['id']}"
        assert client.get(base + "/patch-revision").json()["allowed"] is False
        response = client.post(
            base + "/patch-revision",
            json={
                "expected_version": mission["version"],
                "approval_id": "unavailable",
                "payload_digest": "0" * 64,
                "feedback": "Do not run",
            },
        )
        assert response.status_code == 409


def test_revision_provider_failure_explicit_retry_preserves_context(tmp_path, workspace):
    calls = []
    failing = False
    generator = transport_for([BAD_PATCH, PATCH], calls)

    def transport(request):
        if failing and json.loads(request.content)["text"]["format"]["name"] == "code_helper":
            return httpx.Response(401, text="private provider failure")
        return generator(request)

    with TestClient(configured_app(tmp_path, workspace, transport)) as client:
        mission = client.post("/workflows/developer", json={"goal": "Fix addition"}).json()
        base = f"/missions/{mission['id']}"
        mission, approval = deny(client, base, run(client, base, mission))
        mission = client.post(
            base + "/patch-revision", json=revision_body(mission, approval)
        ).json()
        failing = True
        mission = run(client, base, mission)
        assert mission["status"] == "FAILED"
        assert "private provider failure" not in json.dumps(mission)
        assert len(mission["developer_revisions"]) == 1
        assert client.get(base + "/approvals").json() == []
        failing = False
        mission = client.post(
            base + "/tasks/fix/actions",
            json={
                "expected_version": mission["version"],
                "action": "retry",
            },
        ).json()
        mission = run(client, base, mission)
        assert mission["status"] == "WAITING_APPROVAL"
        assert mission["tasks"][-1]["outputs"]["passed"] is True
        assert calls[-1]["patch_revision"]["number"] == 1
