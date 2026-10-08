"""Separate workspace store: immutable mission inputs and explicit lexical memory."""

import hashlib
import json
import re
import sqlite3
import stat
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from agentos.domain.missions import StateConflict
from agentos.domain.workspace import MemoryCreate, MemoryNote, WorkspaceSettings


class WorkspaceStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path)) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version not in {0, 1}:
                raise RuntimeError("Unsupported workspace database version")
            if version == 0:
                conn.execute("CREATE TABLE notes(id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
                conn.execute(
                    "CREATE TABLE snapshots(mission_id TEXT PRIMARY KEY, payload TEXT NOT NULL, "
                    "digest TEXT NOT NULL)"
                )
                conn.execute("PRAGMA user_version = 1")

    def add_note(self, request: MemoryCreate) -> MemoryNote:
        note = MemoryNote(**request.model_dump(), id=uuid4().hex, created_at=datetime.now(UTC))
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("INSERT INTO notes VALUES (?, ?)", (note.id, note.model_dump_json()))
        return note

    def notes(self, query: str = "", limit: int = 20) -> list[MemoryNote]:
        # Bound corpus size; this is keyword matching, not semantic/vector retrieval.
        with closing(sqlite3.connect(self.path)) as conn:
            rows = conn.execute(
                "SELECT payload FROM notes ORDER BY rowid DESC LIMIT 1000"
            ).fetchall()
        notes = [MemoryNote.model_validate_json(row[0]) for row in rows]
        tokens = set(re.findall(r"\w+", query.casefold()))
        if not tokens:
            return notes[:limit]
        scored = [
            (len(tokens & set(re.findall(r"\w+", (n.title + " " + n.content).casefold()))), n)
            for n in notes
        ]
        return [note for score, note in sorted(scored, key=lambda x: -x[0]) if score > 0][:limit]

    def snapshot(self, mission_id: str, settings: WorkspaceSettings) -> dict[str, str]:
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT payload, digest FROM snapshots WHERE mission_id = ?", (mission_id,)
            ).fetchone()
            if row:
                payload, digest = row
                if hashlib.sha256(payload.encode()).hexdigest() != digest:
                    raise StateConflict("Workspace snapshot integrity check failed")
                files: dict[str, str] = json.loads(payload)
                return files
            root = settings.repository.resolve(strict=True)
            files = {}
            total = 0
            for relative in settings.files:
                path = root / relative
                current = path
                while current != root:
                    if current.is_symlink() or (
                        getattr(current.lstat(), "st_file_attributes", 0)
                        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
                    ):
                        raise StateConflict("Workspace symlinks and junctions are not supported")
                    current = current.parent
                if not path.resolve(strict=True).is_relative_to(root):
                    raise StateConflict("Workspace file escapes repository")
                if path.stat().st_size > 100_000:
                    raise StateConflict("Workspace file exceeds 100 KB")
                data = path.read_bytes()
                total += len(data)
                if total > 512_000 or b"\x00" in data:
                    raise StateConflict("Workspace exceeds 512 KB or contains binary files")
                files[relative] = data.decode("utf-8").replace("\r\n", "\n")
            payload = json.dumps(files, ensure_ascii=False, sort_keys=True)
            conn.execute(
                "INSERT INTO snapshots VALUES (?, ?, ?)",
                (mission_id, payload, hashlib.sha256(payload.encode()).hexdigest()),
            )
            return files
