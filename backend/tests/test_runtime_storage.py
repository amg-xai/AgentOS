import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from pydantic import ValidationError
from test_orchestration import create, decide, run
from test_orchestration import runtime as runtime_fixture

from agentos.adapters.artifacts import ArtifactStore
from agentos.adapters.sqlite import SQLiteMissionRepository
from agentos.domain.artifacts import ArtifactDraft
from agentos.domain.missions import MissionCreate, StateConflict
from agentos.services.missions import MissionService

runtime = runtime_fixture


def create_v1_database(path):
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE missions (id TEXT PRIMARY KEY, version INTEGER NOT NULL, "
            "created_at TEXT NOT NULL, payload TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE mission_events (sequence INTEGER PRIMARY KEY AUTOINCREMENT, "
            "mission_id TEXT NOT NULL REFERENCES missions(id), payload TEXT NOT NULL)"
        )
        connection.execute("CREATE INDEX events_by_mission ON mission_events(mission_id, sequence)")
        connection.execute("PRAGMA user_version = 1")


def test_migration_preserves_v1_snapshots_and_events(registry, tmp_path):
    path = tmp_path / "v1.sqlite3"
    create_v1_database(path)
    repository = SQLiteMissionRepository(tmp_path / "source.sqlite3")
    mission = MissionService(registry, repository).create(
        MissionCreate(
            goal="Preserve a mission",
            tasks=({"id": "task", "title": "Task", "agent_id": "investigation"},),
        )
    )
    old_events = repository.events(mission.id)
    payload = mission.model_dump(mode="json", exclude={"status"})
    for task in payload["tasks"]:
        for key in ("input_bindings", "review_required", "artifact_refs"):
            task.pop(key)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO missions VALUES (?, ?, ?, ?)",
            (mission.id, mission.version, mission.created_at.isoformat(), json.dumps(payload)),
        )
        for event in old_events:
            connection.execute(
                "INSERT INTO mission_events VALUES (?, ?, ?)",
                (
                    event.sequence,
                    mission.id,
                    event.model_dump_json(exclude={"sequence", "mission_id"}),
                ),
            )
    migrated = SQLiteMissionRepository(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
    assert migrated.get(mission.id) == mission
    assert migrated.events(mission.id) == old_events


def test_failed_migration_is_atomic(tmp_path, monkeypatch):
    path = tmp_path / "v1.sqlite3"
    create_v1_database(path)
    migrate = SQLiteMissionRepository._migrate_v2

    def fail(connection):
        migrate(connection)
        raise RuntimeError("Interrupted migration")

    monkeypatch.setattr(SQLiteMissionRepository, "_migrate_v2", staticmethod(fail))
    with pytest.raises(RuntimeError, match="Interrupted migration"):
        SQLiteMissionRepository(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        tables = {
            r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert not tables & {"run_claims", "approvals", "artifacts"}


def test_failed_result_commit_removes_files_and_metadata(runtime, monkeypatch):
    append = runtime.repository._append_events

    def fail_result(connection, mission_id, events):
        append(connection, mission_id, events)
        if any(event.action == "approval_requested" for event in events):
            raise RuntimeError("Simulated result commit failure")

    monkeypatch.setattr(runtime.repository, "_append_events", fail_result)
    mission = run(runtime, create(runtime))
    assert mission.status == "FAILED"
    assert runtime.repository.artifacts(mission.id) == []
    assert runtime.repository.approvals(mission.id, False) == []
    assert list(runtime.storage.root.iterdir()) == []


def test_failed_decision_commit_preserves_pending_approval(runtime, monkeypatch):
    mission = run(runtime, create(runtime))
    append = runtime.repository._append_events

    def fail_decision(connection, mission_id, events):
        append(connection, mission_id, events)
        raise RuntimeError("Decision transaction failed")

    monkeypatch.setattr(runtime.repository, "_append_events", fail_decision)
    with pytest.raises(RuntimeError, match="Decision transaction failed"):
        decide(runtime, mission)
    assert runtime.repository.get(mission.id) == mission
    assert runtime.repository.approvals(mission.id)[0].status == "PENDING"


@pytest.mark.parametrize(
    "name", ["../secret", "..", "nested/report", "nested\\report", "bad\nname"]
)
def test_artifact_names_cannot_be_paths(name):
    with pytest.raises(ValidationError):
        ArtifactDraft(name=name, content="content")


def test_artifact_content_whitespace_integrity_and_scope(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    draft = ArtifactDraft(name="report.diff", content="  leading\ntrailing\n")
    artifact = store.write("mission", "task", draft)
    assert store.read(artifact) == b"  leading\ntrailing\n"
    with pytest.raises(ValidationError):
        type(artifact).model_validate(artifact.model_dump() | {"id": "../secret"})
    (store.root / f"{artifact.id}.txt").write_text("changed", encoding="utf-8")
    with pytest.raises(StateConflict, match="integrity"):
        store.read(artifact)


def test_artifact_symlink_is_rejected(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    artifact = store.write("mission", "task", ArtifactDraft(name="report", content="original"))
    path = store.root / f"{artifact.id}.txt"
    external = tmp_path / "external.txt"
    external.write_text("outside", encoding="utf-8")
    path.unlink()
    try:
        path.symlink_to(external)
    except OSError:
        pytest.skip("Creating symlinks requires Windows developer mode or elevated privileges")
    with pytest.raises(StateConflict, match="escapes"):
        store.read(artifact)


def test_claim_acquisition_cannot_race_a_manual_state_write(runtime, monkeypatch):
    mission = create(runtime)
    checked, release = Event(), Event()
    check_claim = runtime.repository._check_claim

    def pause_after_check(connection, mission_id, token):
        check_claim(connection, mission_id, token)
        checked.set()
        assert release.wait(5)

    monkeypatch.setattr(runtime.repository, "_check_claim", pause_after_check)
    competing = SQLiteMissionRepository(runtime.repository.path)

    def save():
        return runtime.repository.save(
            mission.model_copy(update={"version": 2}),
            mission.version,
            [],
        )

    def claim():
        with pytest.raises(StateConflict, match="version is stale"):
            competing.acquire_claim(mission.id, 1, "local")

    with ThreadPoolExecutor(max_workers=2) as pool:
        saving = pool.submit(save)
        assert checked.wait(5)
        claiming = pool.submit(claim)
        release.set()
        assert saving.result(timeout=5).version == 2
        claiming.result(timeout=5)
    assert competing.claim(mission.id) is None


def test_ambiguous_commit_does_not_remove_committed_artifacts(runtime, monkeypatch):
    save = runtime.repository.save

    def commit_then_interrupt(mission, version, events, **kwargs):
        saved = save(mission, version, events, **kwargs)
        if kwargs.get("approval") is not None:
            raise RuntimeError("Transport lost after commit")
        return saved

    monkeypatch.setattr(runtime.repository, "save", commit_then_interrupt)
    mission = create(runtime)
    with pytest.raises(StateConflict):
        run(runtime, mission)
    stored = runtime.repository.get(mission.id)
    assert stored.status == "WAITING_APPROVAL"
    artifact = runtime.repository.artifacts(mission.id)[0]
    assert runtime.storage.read(artifact)
    assert runtime.repository.claim(mission.id) is not None
