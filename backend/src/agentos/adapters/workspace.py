"""Separate workspace store: immutable mission inputs and explicit lexical memory."""

import hashlib
import json
import re
import shutil
import sqlite3
import stat
import sys
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from agentos.domain.missions import StateConflict
from agentos.domain.workspace import MemoryCreate, MemoryNote, WorkspaceSettings


def read_workspace_source(settings: WorkspaceSettings) -> dict[str, str]:
    """Validate and read selected text without creating or updating runtime state."""
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
    return files


def verification_evidence(files: dict[str, str], recipe: dict[str, Any]) -> dict[str, str]:
    """Absent metadata is legacy, never inferred from changed workspace settings."""
    if "verification" not in recipe:
        return {}
    evidence = recipe["verification"]
    if not isinstance(evidence, dict) or not evidence:
        raise StateConflict("Frozen verification evidence is malformed")
    for path, digest in evidence.items():
        if (
            path not in files
            or not isinstance(digest, str)
            or hashlib.sha256(files[path].encode()).hexdigest() != digest
        ):
            raise StateConflict("Frozen verification evidence does not match source")
    return evidence


class WorkspaceStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path)) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version not in {0, 1, 2, 3}:
                raise RuntimeError("Unsupported workspace database version")
            if version == 0:
                conn.execute("CREATE TABLE notes(id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
                conn.execute(
                    "CREATE TABLE snapshots(mission_id TEXT PRIMARY KEY, payload TEXT NOT NULL, "
                    "digest TEXT NOT NULL)"
                )
            if version < 2:
                conn.execute(
                    "CREATE TABLE recipes(mission_id TEXT PRIMARY KEY, payload TEXT NOT NULL, "
                    "digest TEXT NOT NULL, source_digest TEXT NOT NULL)"
                )
            if version < 3:
                conn.execute(
                    "CREATE TABLE memory_index (id INTEGER PRIMARY KEY CHECK (id=1), "
                    "payload TEXT NOT NULL, digest TEXT NOT NULL)"
                )
                conn.execute("PRAGMA user_version = 3")

    def execution_snapshot(
        self, mission_id: str, settings: WorkspaceSettings
    ) -> tuple[dict[str, str], dict[str, Any], str, str]:
        """Atomically freeze source and resolved argv; never repair partial/damaged evidence."""
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            source = conn.execute(
                "SELECT payload, digest FROM snapshots WHERE mission_id = ?", (mission_id,)
            ).fetchone()
            stored = conn.execute(
                "SELECT payload, digest, source_digest FROM recipes WHERE mission_id = ?",
                (mission_id,),
            ).fetchone()
            if source or stored:
                if not source or not stored:
                    raise StateConflict("Frozen execution evidence is incomplete")
                source_payload, source_digest = source
                payload, digest, linked_digest = stored
                if (
                    hashlib.sha256(source_payload.encode()).hexdigest() != source_digest
                    or linked_digest != source_digest
                    or hashlib.sha256((source_digest + payload).encode()).hexdigest() != digest
                ):
                    raise StateConflict("Frozen execution integrity check failed")
                files = json.loads(source_payload)
                recipe: dict[str, Any] = json.loads(payload)
                if recipe["files"] != sorted(files):
                    raise StateConflict("Frozen execution scope mismatch")
                verification_evidence(files, recipe)
                return files, recipe, source_digest, digest
            files = read_workspace_source(settings)
            commands = []
            for configured in settings.test_commands:
                runner = (
                    sys.executable
                    if configured[0] in {"python", "python3"}
                    else shutil.which(configured[0])
                )
                if not runner or not Path(runner).is_file():
                    raise StateConflict("Configured test runner is unavailable")
                commands.append([str(Path(runner).resolve(strict=True)), *configured[1:]])
            recipe = {
                "files": sorted(files),
                "commands": commands,
                "timeout_seconds": settings.test_timeout_seconds,
            }
            if settings.protected_files:
                recipe["verification"] = {
                    path: hashlib.sha256(files[path].encode()).hexdigest()
                    for path in sorted(settings.protected_files)
                }
            source_payload = json.dumps(files, ensure_ascii=False, sort_keys=True)
            source_digest = hashlib.sha256(source_payload.encode()).hexdigest()
            payload = json.dumps(recipe, ensure_ascii=False, sort_keys=True)
            digest = hashlib.sha256((source_digest + payload).encode()).hexdigest()
            conn.execute(
                "INSERT INTO snapshots VALUES (?, ?, ?)",
                (mission_id, source_payload, source_digest),
            )
            conn.execute(
                "INSERT INTO recipes VALUES (?, ?, ?, ?)",
                (mission_id, payload, digest, source_digest),
            )
            return files, recipe, source_digest, digest

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

    def memory_notes(self) -> tuple[list[MemoryNote], int]:
        """Bounded source scan; malformed rows never become retrieval evidence."""
        with closing(sqlite3.connect(self.path)) as conn:
            rows = conn.execute(
                "SELECT id, payload FROM notes ORDER BY rowid DESC LIMIT 1000"
            ).fetchall()
        notes = []
        invalid = 0
        for identity, payload in rows:
            try:
                if len(payload.encode()) > 64000:
                    raise ValueError("Note exceeds source bound")
                note = MemoryNote.model_validate_json(payload)
                if note.id != identity:
                    raise ValueError("Note identity mismatch")
                if note.workspace_id == "local":
                    notes.append(note)
            except (ValueError, TypeError):
                invalid += 1
        return notes, invalid

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
            files = read_workspace_source(settings)
            payload = json.dumps(files, ensure_ascii=False, sort_keys=True)
            conn.execute(
                "INSERT INTO snapshots VALUES (?, ?, ?)",
                (mission_id, payload, hashlib.sha256(payload.encode()).hexdigest()),
            )
            return files
