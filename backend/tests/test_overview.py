import asyncio
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_orchestration import create
from test_orchestration import runtime as runtime_fixture

from agentos.adapters.sqlite import SQLiteMissionRepository
from agentos.api.app import create_app
from agentos.domain.governance import ApprovalDecision, UserRole
from agentos.domain.missions import Mission, MissionStatus, Task, TaskStatus
from agentos.services.overview import workspace_overview

runtime = runtime_fixture


def snapshot(status=TaskStatus.PENDING, *, index=0, agent="investigation", role="developer"):
    time = datetime(2026, 10, 9, tzinfo=UTC) + timedelta(seconds=index)
    return Mission(
        id=str(uuid4()),
        goal="A supplied mission goal",
        role_id=role,
        workspace_id="local",
        version=1,
        created_at=time,
        updated_at=time,
        tasks=(
            Task(
                id="work",
                title="Work",
                agent_id=agent,
                status=status,
                inputs={"secret_input": "not-in-overview"},
                outputs={"secret_output": "not-in-overview"},
            ),
        ),
    )


def test_empty_overview_uses_installed_agents_without_claiming_availability(tmp_path, registry):
    repository = SQLiteMissionRepository(tmp_path / "state.sqlite3")
    result = workspace_overview(repository, registry, "live", 0)
    assert result.total_missions == result.pending_approvals == result.durable_claims == 0
    assert result.total_artifacts == result.local_active_runs == 0
    assert set(result.mission_counts) == set(MissionStatus)
    assert not any(result.mission_counts.values())
    assert result.recent_reviews == result.recent_artifacts == ()
    assert [a.agent_id for a in result.agent_activity] == [a.id for a in registry.agents()]
    assert all(
        not a.recent_tasks and not any(a.task_counts.values()) for a in result.agent_activity
    )


@pytest.mark.parametrize("status", list(TaskStatus))
def test_all_task_states_use_domain_mission_status(tmp_path, status):
    repository = SQLiteMissionRepository(tmp_path / "state.sqlite3")
    mission = repository.create(snapshot(status), [])
    result = repository.overview(("investigation",))
    assert result.total_missions == 1
    assert result.mission_counts[mission.status] == 1
    assert sum(result.mission_counts.values()) == 1
    activity = result.agent_activity[0]
    assert activity.task_counts[status] == 1
    assert activity.recent_tasks[0].status == status


def test_large_mixed_history_is_exact_bounded_deterministic_and_read_only(tmp_path, registry):
    repository = SQLiteMissionRepository(tmp_path / "state.sqlite3")
    waiting = []
    for index in range(125):
        role, agent = (
            ("developer", "investigation"),
            ("creator", "creator_script"),
            ("student", "student_quiz"),
        )[index % 3]
        mission = repository.create(
            snapshot(TaskStatus.WAITING_APPROVAL, index=index, role=role, agent=agent), []
        )
        waiting.append(mission)
    removed = repository.create(snapshot(agent="removed_agent"), [])
    claim = repository.acquire_claim(waiting[-1].id, 1, "local")
    before_events = repository.events(waiting[-1].id)
    result = workspace_overview(repository, registry, "demo", 0)
    assert result.total_missions == 126
    assert result.mission_counts[MissionStatus.WAITING_APPROVAL] == 125
    assert result.durable_claims == 1 and result.local_active_runs == 0
    assert len(result.recent_reviews) == 10
    assert [r.id for r in result.recent_reviews] == [m.id for m in reversed(waiting[-10:])]
    assert result.recent_reviews[0].has_claim
    assert "removed_agent" not in {a.agent_id for a in result.agent_activity}
    assert removed.id not in {t.mission_id for a in result.agent_activity for t in a.recent_tasks}
    assert all(len(a.recent_tasks) <= 5 for a in result.agent_activity)
    assert sum(sum(a.task_counts.values()) for a in result.agent_activity) == 125
    encoded = result.model_dump_json()
    assert claim.token not in encoded
    assert "secret_input" not in encoded and "secret_output" not in encoded
    assert repository.claim(waiting[-1].id) == claim
    assert repository.events(waiting[-1].id) == before_events
    restarted = SQLiteMissionRepository(repository.path).overview(
        tuple(a.id for a in registry.agents())
    )
    assert restarted.model_dump(exclude={"observed_at"}) == result.model_dump(
        exclude={"observed_at", "execution_mode", "local_active_runs"}
    )


@pytest.mark.parametrize("decision", ["approve", "deny", "cancel"])
def test_actual_review_artifacts_and_decisions(runtime, decision):
    mission = asyncio.run(runtime.runner.run(create(runtime).id, 1, UserRole.OPERATOR))
    before = workspace_overview(runtime.repository, runtime.registry, "live", 0)
    assert before.pending_approvals == 1
    assert before.total_artifacts == len(runtime.repository.artifacts(mission.id)) > 0
    assert before.recent_artifacts[0] == runtime.repository.artifacts(mission.id)[-1]
    assert before.durable_claims == 0
    if decision == "cancel":
        runtime.lifecycle.cancel(mission.id, mission.version)
    else:
        approval = runtime.repository.approvals(mission.id)[0]
        runtime.approvals.decide(
            approval.id,
            ApprovalDecision(
                expected_version=mission.version,
                decision=decision,
                payload_digest=approval.payload_digest,
            ),
            UserRole.OPERATOR,
        )
    after = workspace_overview(runtime.repository, runtime.registry, "live", 0)
    assert after.pending_approvals == 0 and not after.recent_reviews
    assert after.total_artifacts == before.total_artifacts


def test_snapshot_counts_do_not_mix_in_concurrent_writes(tmp_path, monkeypatch):
    repository = SQLiteMissionRepository(tmp_path / "state.sqlite3")
    mission = repository.create(snapshot(), [])
    with sqlite3.connect(repository.path) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
    writer = SQLiteMissionRepository(repository.path)
    original_connect = repository._connect
    changed = False

    def connect():
        connection = original_connect()

        def trace(statement):
            nonlocal changed
            if "COUNT(*) FROM approvals" in statement and not changed:
                changed = True
                writer.create(snapshot(index=1), [])
                writer.acquire_claim(mission.id, 1, "concurrent")

        connection.set_trace_callback(trace)
        return connection

    monkeypatch.setattr(repository, "_connect", connect)
    result = repository.overview(("investigation",))
    assert changed
    assert result.total_missions == 1 and result.durable_claims == 0
    assert not result.agent_activity[0].recent_tasks[0].has_claim
    assert writer.overview(()).total_missions == 2
    assert writer.overview(()).durable_claims == 1


def test_recent_artifacts_are_bounded_and_reviews_have_stable_tie_order(runtime):
    ids = []
    for _ in range(12):
        mission = asyncio.run(runtime.runner.run(create(runtime).id, 1, UserRole.OPERATOR))
        ids.append(mission.id)
    result = runtime.repository.overview(("testing",))
    assert result.total_missions == result.pending_approvals == 12
    assert result.total_artifacts > 10 and len(result.recent_artifacts) == 10
    assert result.recent_artifacts[0].mission_id == ids[-1]
    assert len(result.recent_reviews) == 10
    # Equal timestamps use ids to resolve ordering, independent of insertion.
    newest = max(review.updated_at for review in result.recent_reviews)
    tied = [
        snapshot(TaskStatus.WAITING_APPROVAL).model_copy(
            update={"updated_at": newest + timedelta(seconds=1)}
        )
        for _ in range(2)
    ]
    for mission in tied:
        runtime.repository.create(mission, [])
    result = runtime.repository.overview(())
    assert [r.id for r in result.recent_reviews[:2]] == sorted([m.id for m in tied], reverse=True)


def test_viewer_overview_and_recorded_running_claim_survive_restart(
    tmp_path, registry, monkeypatch
):
    monkeypatch.delenv("AGENTOS_MODEL", raising=False)
    monkeypatch.setenv("AGENTOS_WORKSPACE_CONFIG", str(tmp_path / "missing.json"))
    repository = SQLiteMissionRepository(tmp_path / "state.sqlite3")
    mission = repository.create(snapshot(TaskStatus.RUNNING), [])
    claim = repository.acquire_claim(mission.id, 1, "local")
    with TestClient(
        create_app(registry, db_path=repository.path, user_role=UserRole.VIEWER)
    ) as client:
        response = client.get("/overview")
        assert response.status_code == 200
        result = response.json()
        assert result["execution_mode"] == "live" and result["local_active_runs"] == 0
        assert result["durable_claims"] == 1 and result["mission_counts"]["RUNNING"] == 1
        assert claim.token not in json.dumps(result)
        assert client.post("/overview", json={}).status_code == 405
        assert (
            client.post(f"/missions/{mission.id}/cancel", json={"expected_version": 1}).status_code
            == 403
        )
    assert repository.claim(mission.id) == claim
