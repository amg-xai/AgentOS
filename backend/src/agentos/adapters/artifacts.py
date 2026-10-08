"""Workspace-bounded artifact files. Metadata is committed with task state."""

import hashlib
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from agentos.domain.artifacts import Artifact, ArtifactDraft
from agentos.domain.missions import StateConflict


class ArtifactStore:
    def __init__(self, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True)
        self.root = root.resolve()

    def _path(self, artifact: Artifact) -> Path:
        path = self.root / f"{artifact.id}.txt"
        if path.is_symlink() or not path.resolve().is_relative_to(self.root):
            raise StateConflict("Artifact path escapes storage")
        return path

    def write(self, mission_id: str, task_id: str, draft: ArtifactDraft) -> Artifact:
        content = draft.content.encode("utf-8")
        artifact = Artifact(
            id=uuid4().hex,
            mission_id=mission_id,
            task_id=task_id,
            name=draft.name,
            media_type=draft.media_type,
            sha256=hashlib.sha256(content).hexdigest(),
            size=len(content),
            created_at=datetime.now(UTC),
        )
        with self._path(artifact).open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        return artifact

    def read(self, artifact: Artifact) -> bytes:
        try:
            content = self._path(artifact).read_bytes()
        except OSError as exc:
            raise StateConflict("Artifact content is unavailable") from exc
        if len(content) != artifact.size or hashlib.sha256(content).hexdigest() != artifact.sha256:
            raise StateConflict("Artifact content failed its integrity check")
        return content

    def remove_uncommitted(self, artifact: Artifact) -> None:
        self._path(artifact).unlink(missing_ok=True)
