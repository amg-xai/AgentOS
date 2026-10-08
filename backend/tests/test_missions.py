import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier

import pytest
from pydantic import ValidationError

from agentos.adapters.sqlite import SQLiteMissionRepository
from agentos.domain.missions import (
    MissionCreate,
    MissionNotFound,
    MissionStatus,
    MissionValidationError,
    NewEvent,
    StateConflict,
    TaskActionRequest,
    TaskStatus,
)
from agentos.services.missions import MissionService


@pytest.fixture
def service(registry, tmp_path):
    return MissionService(registry, SQLiteMissionRepository(tmp_path / "state.sqlite3"))


def workflow():
    # Reverse order verifies that readiness is independent of manifest ordering.
    return {
        "goal": "Investigate and fix an issue",
        "tasks": [
            {"id": "test", "title": "Test", "agent_id": "testing", "dependencies": ["fix"]},
            {"id": "fix", "title": "Fix", "agent_id": "code_helper", "dependencies": ["inspect"]},
            {"id": "inspect", "title": "Inspect", "agent_id": "investigation"},
        ],
    }


def act(service, mission, task_id, action, **kwargs):
    return service.act(
        mission.id,
        task_id,
        TaskActionRequest(
            expected_version=mission.version,
            action=action,
            **kwargs,
        ),
    )


def states(mission):
    return {task.id: task.status for task in mission.tasks}


def test_complete_mission_and_restart(service, registry):
    mission = service.create(MissionCreate(**workflow()))
    assert states(mission) == {"inspect": "READY", "fix": "PENDING", "test": "PENDING"}
    assert mission.status == MissionStatus.PENDING
    assert mission.created_at.utcoffset().total_seconds() == 0
    for task_id in ("inspect", "fix", "test"):
        mission = act(service, mission, task_id, "start")
        assert mission.status == MissionStatus.RUNNING
        mission = act(service, mission, task_id, "complete", outputs={"report": task_id})
    assert mission.status == MissionStatus.COMPLETED
    assert mission.version == 7
    assert all(task.attempts == 1 for task in mission.tasks)
    restarted = MissionService(registry, SQLiteMissionRepository(service.repository.path))
    assert restarted.repository.get(mission.id) == mission
    events = restarted.repository.events(mission.id)
    assert len(events) == 18
    assert len({event.sequence for event in events}) == len(events)
    assert events == sorted(events, key=lambda event: event.sequence)
    assert {event.actor for event in events} == {"local"}
    assert events[0].action == "mission_created"
    assert restarted.repository.list_missions() == [mission]


def test_failure_blocks_transitively_and_retry_restores_readiness(service):
    mission = service.create(MissionCreate(**workflow()))
    mission = act(service, mission, "inspect", "start")
    mission = act(service, mission, "inspect", "fail", error="Provider timed out")
    assert states(mission) == {"inspect": "FAILED", "fix": "BLOCKED", "test": "BLOCKED"}
    assert mission.status == MissionStatus.FAILED
    mission = act(service, mission, "inspect", "retry")
    failures = [
        event
        for event in service.repository.events(mission.id)
        if event.details.get("to") == "FAILED"
    ]
    assert failures[0].details["error"] == "Provider timed out"
    assert states(mission) == {"inspect": "READY", "fix": "PENDING", "test": "PENDING"}
    mission = act(service, mission, "inspect", "start")
    mission = act(service, mission, "inspect", "complete", outputs={"findings": "Found bug"})
    assert states(mission) == {"inspect": "COMPLETED", "fix": "READY", "test": "PENDING"}
    assert next(t for t in mission.tasks if t.id == "inspect").attempts == 2


def test_retry_does_not_repeat_completed_work(service):
    mission = service.create(MissionCreate(**workflow()))
    mission = act(service, mission, "inspect", "start")
    mission = act(service, mission, "inspect", "complete", outputs={"evidence": "preserve"})
    completed = next(t for t in mission.tasks if t.id == "inspect")
    mission = act(service, mission, "fix", "start")
    mission = act(service, mission, "fix", "fail", error="Failure")
    mission = act(service, mission, "fix", "retry")
    assert next(t for t in mission.tasks if t.id == "inspect") == completed


def test_cancellation_preserves_completed_output(service):
    mission = service.create(MissionCreate(**workflow()))
    mission = act(service, mission, "inspect", "start")
    mission = act(service, mission, "inspect", "complete", outputs={"evidence": "preserve"})
    completed = next(t for t in mission.tasks if t.id == "inspect")
    mission = service.cancel(mission.id, mission.version)
    assert mission.status == MissionStatus.CANCELLED
    assert states(mission) == {"inspect": "COMPLETED", "fix": "CANCELLED", "test": "CANCELLED"}
    assert next(t for t in mission.tasks if t.id == "inspect") == completed
    with pytest.raises(StateConflict):
        service.cancel(mission.id, mission.version)
    with pytest.raises(StateConflict):
        act(service, mission, "fix", "retry")


def test_approval_state_cannot_be_bypassed(service):
    mission = service.create(MissionCreate(**workflow()))
    mission = act(service, mission, "inspect", "start")
    mission = act(service, mission, "inspect", "wait_approval")
    assert mission.status == MissionStatus.WAITING_APPROVAL
    assert states(mission)["fix"] == TaskStatus.PENDING
    for action, kwargs in (("start", {}), ("complete", {"outputs": {}}), ("retry", {})):
        with pytest.raises(StateConflict):
            act(service, mission, "inspect", action, **kwargs)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["tasks"].append(d["tasks"][0]),
        lambda d: d["tasks"][0].update(dependencies=["missing"]),
        lambda d: d["tasks"][0].update(dependencies=["test"]),
        lambda d: d["tasks"][2].update(dependencies=["test"]),
        lambda d: d["tasks"][0].update(dependencies=["fix", "fix"]),
        lambda d: d.update(tasks=[]),
    ],
)
def test_invalid_graphs(mutate):
    data = workflow()
    mutate(data)
    with pytest.raises(ValidationError):
        MissionCreate(**data)


@pytest.mark.parametrize(
    "change",
    [
        {"role_id": "missing"},
        {"workspace_id": "other"},
        {"tasks": [{"id": "bad", "title": "Bad", "agent_id": "missing"}]},
    ],
)
def test_invalid_registration_rejected(service, change):
    with pytest.raises(MissionValidationError):
        service.create(MissionCreate(**(workflow() | change)))
    assert service.repository.list_missions() == []


def test_illegal_and_stale_actions_do_not_write_events(service):
    mission = service.create(MissionCreate(**workflow()))
    original_events = service.repository.events(mission.id)
    for task_id, action, kwargs in (
        ("fix", "start", {}),
        ("inspect", "complete", {"outputs": {}}),
        ("inspect", "retry", {}),
    ):
        with pytest.raises(StateConflict):
            act(service, mission, task_id, action, **kwargs)
    with pytest.raises(MissionNotFound):
        act(service, mission, "missing", "start")
    assert service.repository.events(mission.id) == original_events
    updated = act(service, mission, "inspect", "start")
    with pytest.raises(StateConflict):
        act(service, mission, "inspect", "start")
    assert service.repository.get(mission.id) == updated


def test_transaction_rolls_back_snapshot_and_events(service, monkeypatch):
    mission = service.create(MissionCreate(**workflow()))
    original = service.repository.events(mission.id)
    append = service.repository._append_events

    def fail_after_append(connection, mission_id, events):
        append(connection, mission_id, events)
        raise RuntimeError("Simulated write failure")

    monkeypatch.setattr(service.repository, "_append_events", fail_after_append)
    with pytest.raises(RuntimeError, match="Simulated write failure"):
        act(service, mission, "inspect", "start")
    assert service.repository.get(mission.id) == mission
    assert service.repository.events(mission.id) == original
    with pytest.raises(RuntimeError):
        service.create(MissionCreate(**workflow()))
    assert service.repository.list_missions() == [mission]


def test_concurrent_updates_only_one_wins(service, registry):
    mission = service.create(MissionCreate(**workflow()))
    barrier = Barrier(2)

    def update():
        repository = SQLiteMissionRepository(service.repository.path)
        current = repository.get(mission.id)
        candidate = current.model_copy(update={"version": 2})
        barrier.wait(timeout=5)
        try:
            repository.save(
                candidate,
                1,
                [
                    NewEvent(
                        timestamp=datetime.now(UTC),
                        actor="local",
                        action="concurrency_test",
                    )
                ],
            )
            return "saved"
        except StateConflict:
            return "conflict"

    before = len(service.repository.events(mission.id))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: update(), range(2)))
    assert sorted(results) == ["conflict", "saved"]
    assert service.repository.get(mission.id).version == 2
    assert len(service.repository.events(mission.id)) == before + 1


def test_schema_version_and_foreign_keys(tmp_path):
    path = tmp_path / "state.sqlite3"
    repository = SQLiteMissionRepository(path)
    connection = repository._connect()
    try:
        with connection, pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO mission_events(mission_id, payload) VALUES ('missing', '{}')"
            )
    finally:
        connection.close()
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        connection.execute("PRAGMA user_version = 99")
    with pytest.raises(RuntimeError, match="Unsupported database schema"):
        SQLiteMissionRepository(path)


def test_pagination_and_missing_records(service):
    first = service.create(MissionCreate(**workflow()))
    second = service.create(MissionCreate(**workflow()))
    assert service.repository.list_missions(limit=1) == [second]
    assert service.repository.list_missions(limit=1, offset=1) == [first]
    events = service.repository.events(first.id, limit=2)
    remaining = service.repository.events(first.id, after=events[-1].sequence)
    assert len(events + remaining) == 4
    with pytest.raises(MissionNotFound):
        service.repository.events("missing")


def test_branching_dependencies_require_all_prerequisites(service):
    mission = service.create(
        MissionCreate(
            goal="Parallel investigation",
            tasks=(
                {"id": "left", "title": "Inspect left", "agent_id": "investigation"},
                {"id": "right", "title": "Inspect right", "agent_id": "investigation"},
                {
                    "id": "join",
                    "title": "Fix both",
                    "agent_id": "code_helper",
                    "dependencies": ["left", "right"],
                },
            ),
        )
    )
    mission = act(service, mission, "left", "start")
    mission = act(service, mission, "left", "fail", error="Unavailable")
    assert states(mission)["join"] == TaskStatus.BLOCKED
    assert states(mission)["right"] == TaskStatus.READY
    mission = act(service, mission, "right", "start")
    mission = act(service, mission, "right", "complete", outputs={})
    mission = act(service, mission, "left", "retry")
    assert states(mission)["join"] == TaskStatus.PENDING
    mission = act(service, mission, "left", "start")
    mission = act(service, mission, "left", "complete", outputs={})
    assert states(mission)["join"] == TaskStatus.READY


def test_completed_mission_is_terminal(service):
    mission = service.create(
        MissionCreate(
            goal="Single task",
            tasks=({"id": "inspect", "title": "Inspect", "agent_id": "investigation"},),
        )
    )
    mission = act(service, mission, "inspect", "start")
    mission = act(service, mission, "inspect", "complete", outputs={})
    for action, kwargs in (("start", {}), ("retry", {}), ("complete", {"outputs": {}})):
        with pytest.raises(StateConflict):
            act(service, mission, "inspect", action, **kwargs)
    with pytest.raises(StateConflict):
        service.cancel(mission.id, mission.version)
