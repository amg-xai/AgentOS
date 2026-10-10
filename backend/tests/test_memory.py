"""Shared retrieval contracts with injected vectors, never model-quality claims."""

import asyncio
import sqlite3
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from agentos.adapters.artifacts import ArtifactStore
from agentos.adapters.memory_index import MemoryIndexStore
from agentos.adapters.memory_sources import MemoryCorpus
from agentos.adapters.sqlite import SQLiteMissionRepository
from agentos.adapters.workspace import WorkspaceStore
from agentos.api.app import create_app
from agentos.domain.artifacts import ArtifactDraft
from agentos.domain.governance import (
    Approval,
    ApprovalDecision,
    UserRole,
    payload_digest,
    review_payload,
)
from agentos.domain.memory import Embeddings, MemorySearch
from agentos.domain.missions import Mission, StateConflict, Task, TaskStatus
from agentos.domain.workspace import MemoryCreate
from agentos.services.approvals import ApprovalService
from agentos.services.memory import SemanticMemory


class InjectedEmbeddings:
    def __init__(self):
        self.calls = []
        self.fail = False
        self.digest = "a" * 64

    async def embed(self, texts):
        self.calls.append(texts)
        if self.fail:
            raise RuntimeError("Injected failure")
        # Explicit test vectors, not a production language model or semantic fallback.
        return Embeddings(
            model="injected:1",
            model_digest=self.digest,
            vectors=tuple((1, 0) if "addition" in t or "sum" in t else (0, 1) for t in texts),
        )


@pytest.fixture
def memory(tmp_path):
    workspace = WorkspaceStore(tmp_path / "workspace.sqlite3")
    repository = SQLiteMissionRepository(tmp_path / "missions.sqlite3")
    artifacts = ArtifactStore(tmp_path / "artifacts")
    embedder = InjectedEmbeddings()
    service = SemanticMemory(
        MemoryIndexStore(workspace.path), MemoryCorpus(workspace, repository, artifacts), embedder
    )
    return service, workspace, repository, artifacts, embedder


def approved_mission(repository, artifacts, profile="developer", *, passed=True):
    now = datetime.now(UTC)
    artifact = artifacts.write(
        profile, "review", ArtifactDraft(name="result.md", content="addition evidence")
    )
    task = Task(
        id="review",
        title="Review",
        agent_id="code_helper",
        review_required=True,
        requires_passed_tests=profile == "developer",
        status=TaskStatus.WAITING_APPROVAL,
        attempts=1,
        outputs={"passed": passed},
        artifact_refs=(artifact.id,),
    )
    mission = Mission(
        id=profile,
        goal="addition goal",
        role_id=profile,
        workspace_id="local",
        tasks=(task,),
        version=1,
        created_at=now,
        updated_at=now,
    )
    repository.create(mission, [])
    approval = Approval(
        id=profile + "_review",
        mission_id=profile,
        task_id=task.id,
        task_attempt=1,
        payload=review_payload(task, mission),
        payload_digest=payload_digest(review_payload(task, mission)),
        created_at=now,
    )
    mission = repository.save(
        mission.model_copy(update={"version": 2}), 1, [], artifacts=(artifact,), approval=approval
    )
    return mission, artifact, approval


def accept(repository, artifacts, mission, approval):
    return ApprovalService(repository, artifacts).decide(
        approval.id,
        ApprovalDecision(
            expected_version=mission.version,
            decision="approve",
            payload_digest=approval.payload_digest,
        ),
        UserRole.OPERATOR,
    )


def test_rank_filter_sources_and_restart(memory):
    service, workspace, repository, artifacts, embedder = memory
    note = workspace.add_note(MemoryCreate(title="addition", content="Preserve sums"))
    workspace.add_note(MemoryCreate(title="Unrelated", content="Photography"))
    for profile in ("developer", "creator", "student"):
        mission, artifact, approval = approved_mission(repository, artifacts, profile)
        accept(repository, artifacts, mission, approval)
    asyncio.run(service.rebuild())
    restarted = SemanticMemory(MemoryIndexStore(workspace.path), service.corpus, embedder)
    result = asyncio.run(restarted.search(MemorySearch(query="sum", limit=20)))
    assert note.id in {h.id for h in result.hits}
    assert all(h.similarity == 1 for h in result.hits)
    for profile in ("developer", "creator", "student"):
        result = asyncio.run(
            restarted.search(MemorySearch(query="sum", profile=profile, kind="artifact"))
        )
        assert len(result.hits) == 1
        assert result.hits[0].mission_id == profile
        assert result.hits[0].evidence == "approved_artifact"
        assert result.hits[0].start == 0
    assert asyncio.run(restarted.search(MemorySearch(query="sum", mission_id="missing"))).hits == ()
    assert restarted.status()["generation"] == 1


def test_pending_denied_failed_tests_and_damaged_approval_not_indexed(memory):
    service, _, repository, artifacts, _ = memory
    mission, artifact, approval = approved_mission(repository, artifacts, passed=False)
    sources, _ = service.corpus.sources()
    assert not sources
    with pytest.raises(StateConflict, match="Tests must explicitly pass"):
        accept(repository, artifacts, mission, approval)
    ApprovalService(repository, artifacts).decide(
        approval.id,
        ApprovalDecision(
            expected_version=mission.version,
            decision="deny",
            payload_digest=approval.payload_digest,
        ),
        UserRole.OPERATOR,
    )
    assert not service.corpus.sources()[0]


def test_corrupted_artifact_and_changed_source_never_return_cached_text(memory):
    service, workspace, repository, artifacts, embedder = memory
    note = workspace.add_note(MemoryCreate(title="addition", content="Original"))
    mission, artifact, approval = approved_mission(repository, artifacts)
    accept(repository, artifacts, mission, approval)
    asyncio.run(service.rebuild())
    (artifacts.root / f"{artifact.id}.txt").write_text("tampered")
    with sqlite3.connect(workspace.path) as conn:
        conn.execute(
            "UPDATE notes SET payload=? WHERE id=?",
            (note.model_copy(update={"content": "Changed"}).model_dump_json(), note.id),
        )
    result = asyncio.run(service.search(MemorySearch(query="sum")))
    assert all(h.kind == "mission" for h in result.hits)
    assert result.stale_sources == 2
    assert result.invalid_sources == 1


def test_failure_preserves_index_and_concurrent_publish_rejected(memory):
    service, workspace, _, _, embedder = memory
    workspace.add_note(MemoryCreate(title="addition", content="Original"))
    asyncio.run(service.rebuild())
    previous = service.store.read()
    embedder.fail = True
    with pytest.raises(RuntimeError):
        asyncio.run(service.rebuild())
    assert service.store.read() == previous
    with pytest.raises(StateConflict, match="changed during rebuild"):
        service.store.publish(previous.model_copy(update={"generation": 1}), 0)


def test_empty_disabled_malformed_and_foreign_notes(memory):
    service, workspace, _, _, embedder = memory
    assert asyncio.run(service.search(MemorySearch(query="sum"))).hits == ()
    assert embedder.calls == []
    assert asyncio.run(service.rebuild())["empty_corpus"] is True
    note = workspace.add_note(MemoryCreate(title="addition", content="Original"))
    with sqlite3.connect(workspace.path) as conn:
        conn.execute("INSERT INTO notes VALUES ('broken', 'not json')")
        conn.execute(
            "INSERT INTO notes VALUES ('foreign', ?)",
            (note.model_copy(update={"id": "foreign", "workspace_id": "other"}).model_dump_json(),),
        )
    assert len(service.corpus.sources()[0]) == 1
    assert service.corpus.sources()[1] == 1
    asyncio.run(service.rebuild())
    service.embedder = None
    with pytest.raises(StateConflict, match="disabled"):
        asyncio.run(service.search(MemorySearch(query="sum")))


def test_corrupt_index_and_wrong_model_fail_closed(memory):
    service, workspace, _, _, embedder = memory
    workspace.add_note(MemoryCreate(title="addition", content="Original"))
    asyncio.run(service.rebuild())
    embedder.digest = "b" * 64
    with pytest.raises(StateConflict, match="does not match"):
        asyncio.run(service.search(MemorySearch(query="sum")))
    with sqlite3.connect(workspace.path) as conn:
        conn.execute("UPDATE memory_index SET payload='{}'")
    with pytest.raises(StateConflict, match="integrity"):
        service.status()
    with pytest.raises(StateConflict, match="integrity"):
        asyncio.run(service.rebuild())


@pytest.mark.parametrize(
    "vectors", [((0, 0),), ((float("nan"), 1),), ((float("inf"), 1),), ((1, 0), (1,))]
)
def test_invalid_vectors_rejected(vectors):
    with pytest.raises(ValidationError):
        Embeddings(model="test:1", model_digest="a" * 64, vectors=vectors)


@pytest.mark.parametrize("version", [0, 1, 2])
def test_workspace_migration_preserves_old_tables(tmp_path, version):
    path = tmp_path / "workspace.sqlite3"
    if version:
        with sqlite3.connect(path) as conn:
            conn.execute("CREATE TABLE notes(id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
            conn.execute(
                "CREATE TABLE snapshots(mission_id TEXT PRIMARY KEY, payload TEXT, digest TEXT)"
            )
            conn.execute("INSERT INTO snapshots VALUES ('mission', 'original', 'digest')")
            if version == 2:
                conn.execute(
                    "CREATE TABLE recipes(mission_id TEXT PRIMARY KEY, payload TEXT, "
                    "digest TEXT, source_digest TEXT)"
                )
                conn.execute("INSERT INTO recipes VALUES ('mission', 'recipe', 'digest', 'digest')")
            conn.execute(f"PRAGMA user_version={version}")
    store = WorkspaceStore(path)
    assert MemoryIndexStore(store.path).read() is None
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
        if version:
            assert conn.execute("SELECT payload FROM snapshots").fetchone()[0] == "original"
        if version == 2:
            assert conn.execute("SELECT payload FROM recipes").fetchone()[0] == "recipe"


def test_memory_api_permissions_disabled_validation_and_restart(tmp_path):
    path = tmp_path / "missions.sqlite3"
    embedding = InjectedEmbeddings()
    with TestClient(create_app(db_path=path, embedder=embedding)) as client:
        note = client.post("/memory", json={"title": "addition", "content": "Preserve sums"}).json()
        assert client.get("/memory/semantic/status").json()["generation"] == 0
        assert embedding.calls == []
        assert client.post("/memory/semantic/index", json={"unexpected": True}).status_code == 422
        assert embedding.calls == []
        assert client.post("/memory/semantic/index", json={}).status_code == 200
        assert (
            client.post("/memory/semantic/search", json={"query": "sum"}).json()["hits"][0]["id"]
            == note["id"]
        )
        assert client.get(f"/memory/notes/{note['id']}").json() == note
        assert client.get("/memory/notes/missing").status_code == 404
        for body in (
            {"query": " "},
            {"query": "sum", "profile": "admin"},
            {"query": "sum", "limit": 21},
        ):
            assert client.post("/memory/semantic/search", json=body).status_code == 422
        assert client.get("/memory?query=addition").json()[0] == note
        assert client.get("/status").json()["provider_configured"] is False
    with TestClient(
        create_app(db_path=path, embedder=embedding, user_role=UserRole.VIEWER)
    ) as client:
        assert client.get("/memory/semantic/status").json()["generation"] == 1
        assert client.post("/memory/semantic/index", json={}).status_code == 403
        assert client.post("/memory/semantic/search", json={"query": "sum"}).status_code == 200
        assert client.post("/memory", json={"title": "new", "content": "no"}).status_code == 403
    with TestClient(create_app(db_path=path)) as client:
        assert client.post("/memory/semantic/index", json={}).status_code == 409
        response = client.post("/memory/semantic/search", json={"query": "sum"})
        assert response.status_code == 409
        assert "disabled" in response.json()["detail"]


def test_corruption_during_query_is_excluded(memory):
    service, workspace, _, _, embedding = memory
    note = workspace.add_note(MemoryCreate(title="addition", content="Old"))
    asyncio.run(service.rebuild())

    async def change(texts):
        with sqlite3.connect(workspace.path) as conn:
            conn.execute("DELETE FROM notes WHERE id=?", (note.id,))
        return await embedding.embed(texts)

    class ChangingEmbedding:
        embed = staticmethod(change)

    service.embedder = ChangingEmbedding()
    result = asyncio.run(service.search(MemorySearch(query="sum")))
    assert result.hits == ()
    assert result.stale_sources == 1
    asyncio.run(service.rebuild())
    assert service.status()["indexed_chunks"] == 0


def test_source_cap_is_reported_and_long_notes_have_exact_chunk_ranges(memory):
    service, workspace, _, _, _ = memory
    for i in range(100):
        workspace.add_note(MemoryCreate(title=f"addition {i}", content="x" * 8000))
    asyncio.run(service.rebuild())
    index = service.store.read()
    assert len(index.chunks) <= 768
    assert index.omitted_sources > 0
    assert all(c.end - c.start <= 1000 for c in index.chunks)
    assert (
        index.chunks[0]
        .source.text[index.chunks[0].start : index.chunks[0].end]
        .startswith("addition")
    )


def test_foreign_mission_and_stale_review_evidence_excluded(memory):
    service, _, repository, artifacts, _ = memory
    mission, artifact, approval = approved_mission(repository, artifacts)
    mission = accept(repository, artifacts, mission, approval)
    asyncio.run(service.rebuild())
    task = mission.tasks[0].model_copy(update={"attempts": 2})
    mission = repository.save(
        mission.model_copy(update={"tasks": (task,), "version": mission.version + 1}),
        mission.version,
        [],
    )
    result = asyncio.run(service.search(MemorySearch(query="sum", kind="artifact")))
    assert result.hits == ()
    assert result.invalid_sources == 1
    repository.save(
        mission.model_copy(update={"workspace_id": "other", "version": mission.version + 1}),
        mission.version,
        [],
    )
    assert service.corpus.sources()[0] == {}


def test_malformed_history_is_explicit_failure_preserving_index(memory):
    service, workspace, repository, _, _ = memory
    workspace.add_note(MemoryCreate(title="addition", content="Original"))
    asyncio.run(service.rebuild())
    previous = service.store.read()
    with sqlite3.connect(repository.path) as conn:
        conn.execute(
            "INSERT INTO missions(id, payload, version, created_at) "
            "VALUES ('broken', '{}', 1, 'now')"
        )
    with pytest.raises(StateConflict, match="history is unavailable"):
        asyncio.run(service.rebuild())
    assert service.store.read() == previous


def test_concurrent_rebuilds_publish_one_complete_generation(memory):
    service, workspace, _, _, embedding = memory
    workspace.add_note(MemoryCreate(title="addition", content="Original"))

    class YieldingEmbedding:
        async def embed(self, texts):
            await asyncio.sleep(0)
            return await embedding.embed(texts)

    service.embedder = YieldingEmbedding()

    async def rebuild_twice():
        return await asyncio.gather(service.rebuild(), service.rebuild(), return_exceptions=True)

    results = asyncio.run(rebuild_twice())
    assert sum(isinstance(r, StateConflict) for r in results) == 1
    assert service.store.read().generation == 1
    assert len(service.store.read().chunks) == 1


def test_index_read_does_not_recreate_missing_database(memory):
    service, workspace, _, _, _ = memory
    workspace.path.unlink()
    with pytest.raises(StateConflict, match="unavailable"):
        service.status()
    assert not workspace.path.exists()
