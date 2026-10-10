"""Atomic derived cache in the existing workspace database, never execution state."""

import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path

from agentos.domain.memory import MemoryIndex
from agentos.domain.missions import StateConflict

MAX_INDEX_BYTES = 32_000_000


class MemoryIndexStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def read(self) -> MemoryIndex | None:
        try:
            return self._read()
        except (sqlite3.Error, OSError):
            raise StateConflict("Semantic memory index is unavailable") from None

    def _read(self) -> MemoryIndex | None:
        with closing(sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
            row = conn.execute("SELECT payload, digest FROM memory_index WHERE id=1").fetchone()
        if row is None:
            return None
        payload, digest = row
        try:
            if (
                len(payload.encode()) > MAX_INDEX_BYTES
                or hashlib.sha256(payload.encode()).hexdigest() != digest
            ):
                raise ValueError("Invalid cache digest")
            return MemoryIndex.model_validate_json(payload)
        except (ValueError, TypeError):
            raise StateConflict("Semantic memory index failed its integrity check") from None

    def publish(self, index: MemoryIndex, expected_generation: int) -> None:
        try:
            self._publish(index, expected_generation)
        except (sqlite3.Error, OSError):
            raise StateConflict("Semantic memory index publication failed") from None

    def _publish(self, index: MemoryIndex, expected_generation: int) -> None:
        payload = index.model_dump_json()
        if len(payload.encode()) > MAX_INDEX_BYTES or index.generation != expected_generation + 1:
            raise StateConflict("Semantic memory index exceeds its limit or generation")
        digest = hashlib.sha256(payload.encode()).hexdigest()
        with (
            closing(sqlite3.connect(self.path.resolve().as_uri() + "?mode=rw", uri=True)) as conn,
            conn,
        ):
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT payload, digest FROM memory_index WHERE id=1").fetchone()
            if row and hashlib.sha256(row[0].encode()).hexdigest() != row[1]:
                raise StateConflict("Semantic memory index failed its integrity check")
            current = MemoryIndex.model_validate_json(row[0]).generation if row else 0
            if current != expected_generation:
                raise StateConflict("Semantic memory index changed during rebuild")
            conn.execute(
                "INSERT INTO memory_index VALUES (1, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET payload=excluded.payload, digest=excluded.digest",
                (payload, digest),
            )
