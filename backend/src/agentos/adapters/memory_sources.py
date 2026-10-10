"""Shared semantic retrieval of authorized local evidence, with no implicit inference."""

import hashlib
import json
import sqlite3

from agentos.adapters.artifacts import ArtifactStore
from agentos.adapters.sqlite import SQLiteMissionRepository
from agentos.adapters.workspace import WorkspaceStore
from agentos.domain.governance import ApprovalStatus, payload_digest, review_payload
from agentos.domain.memory import MemorySource
from agentos.domain.missions import MissionStatus, StateConflict, TaskStatus
from agentos.services.approvals import ApprovalService


class MemoryCorpus:
    def __init__(
        self,
        workspace: WorkspaceStore,
        repository: SQLiteMissionRepository,
        artifacts: ArtifactStore,
    ) -> None:
        self.workspace, self.repository, self.artifacts = workspace, repository, artifacts
        self.approvals = ApprovalService(repository, artifacts)

    def sources(self) -> tuple[dict[str, MemorySource], int]:
        try:
            return self._sources()
        except (ValueError, OSError, sqlite3.Error):
            raise StateConflict(
                "Semantic memory source history is unavailable or malformed"
            ) from None

    def _sources(self) -> tuple[dict[str, MemorySource], int]:
        sources: dict[str, MemorySource] = {}
        notes, invalid = self.workspace.memory_notes()

        def add(**values: object) -> None:
            source = MemorySource.model_validate(values)
            sources[source.key] = source

        for note in notes:
            if note.workspace_id != "local":
                continue
            text = note.title + "\n" + note.content
            add(
                kind="note",
                id=note.id,
                title=note.title,
                text=text,
                digest=payload_digest(note.model_dump(mode="json")),
                evidence="user_note",
            )
        for mission in self.repository.list_missions(limit=200):
            if (
                mission.workspace_id != "local"
                or mission.role_id not in {"developer", "creator", "student"}
                or mission.status != MissionStatus.COMPLETED
            ):
                continue
            passed = [
                {"task_id": t.id, "passed": t.outputs.get("passed")}
                for t in mission.tasks
                if t.outputs is not None and "passed" in t.outputs
            ]
            reviews = self.repository.approvals(mission.id, pending_only=False)
            text = json.dumps(
                {
                    "goal": mission.goal,
                    "profile": mission.role_id,
                    "state": mission.status,
                    "test_outcomes": passed,
                    "reviews": [{"task": a.task_id, "status": a.status} for a in reviews],
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            if len(text) <= 64000:
                add(
                    kind="mission",
                    id=mission.id,
                    title=mission.goal[:160],
                    text=text,
                    profile=mission.role_id,
                    mission_id=mission.id,
                    digest=payload_digest(mission.model_dump(mode="json")),
                    evidence="stored_outcome",
                )
            else:
                invalid += 1
            for approval in reviews:
                task = next((t for t in mission.tasks if t.id == approval.task_id), None)
                if approval.status != ApprovalStatus.APPROVED:
                    continue
                try:
                    if (
                        task is None
                        or task.status != TaskStatus.COMPLETED
                        or task.attempts != approval.task_attempt
                        or payload_digest(approval.payload) != approval.payload_digest
                        or payload_digest(review_payload(task, mission)) != approval.payload_digest
                    ):
                        raise StateConflict("Stale review")
                    metadata = [self.repository.artifact(ref) for ref in task.artifact_refs]
                    if len(metadata) > 20 or sum(a.size for a in metadata) > 4_000_000:
                        raise StateConflict("Review bundle exceeds semantic verification bounds")
                    self.approvals.validate_evidence(mission, task)
                    for ref in task.artifact_refs:
                        artifact = self.repository.artifact(ref)
                        if artifact.media_type == "image/png":
                            continue
                        if artifact.size > 64000:
                            invalid += 1
                            continue
                        text = self.artifacts.read(artifact).decode("utf-8")
                        if not text.strip():
                            continue
                        add(
                            kind="artifact",
                            id=artifact.id,
                            title=artifact.name,
                            text=text,
                            profile=mission.role_id,
                            mission_id=mission.id,
                            digest=hashlib.sha256(
                                (
                                    artifact.sha256
                                    + approval.payload_digest
                                    + payload_digest(mission.model_dump(mode="json"))
                                ).encode()
                            ).hexdigest(),
                            evidence="approved_artifact",
                        )
                except (ValueError, LookupError, OSError, UnicodeError):
                    for ref in task.artifact_refs if task is not None else ():
                        sources.pop(f"artifact:{ref}", None)
                    invalid += 1
        return sources, invalid
