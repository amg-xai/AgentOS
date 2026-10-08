"""SQLite mission snapshots and append-only events, written atomically."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from agentos.domain.missions import (
    Mission,
    MissionEvent,
    MissionNotFound,
    NewEvent,
    StateConflict,
)


class SQLiteMissionRepository:
    SCHEMA_VERSION = 1

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, self.SCHEMA_VERSION):
                raise RuntimeError(f"Unsupported database schema version: {version}")
            if version == 0:
                connection.execute(
                    "CREATE TABLE missions (id TEXT PRIMARY KEY, version INTEGER NOT NULL, "
                    "created_at TEXT NOT NULL, payload TEXT NOT NULL)"
                )
                connection.execute(
                    "CREATE TABLE mission_events (sequence INTEGER PRIMARY KEY AUTOINCREMENT, "
                    "mission_id TEXT NOT NULL REFERENCES missions(id), payload TEXT NOT NULL)"
                )
                connection.execute(
                    "CREATE INDEX events_by_mission ON mission_events(mission_id, sequence)"
                )
                connection.execute("PRAGMA user_version = 1")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @staticmethod
    def _payload(mission: Mission) -> str:
        return mission.model_dump_json(exclude={"status"})

    @staticmethod
    def _append_events(
        connection: sqlite3.Connection, mission_id: str, events: list[NewEvent]
    ) -> None:
        for event in events:
            connection.execute(
                "INSERT INTO mission_events(mission_id, payload) VALUES (?, ?)",
                (mission_id, event.model_dump_json()),
            )

    def create(self, mission: Mission, events: list[NewEvent]) -> Mission:
        if mission.version != 1:
            raise StateConflict("A new mission must start at version 1")
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "INSERT INTO missions(id, version, created_at, payload) VALUES (?, ?, ?, ?)",
                (
                    mission.id,
                    mission.version,
                    mission.created_at.isoformat(),
                    self._payload(mission),
                ),
            )
            self._append_events(connection, mission.id, events)
        return mission

    def get(self, mission_id: str) -> Mission:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT payload FROM missions WHERE id = ?", (mission_id,)
            ).fetchone()
        if row is None:
            raise MissionNotFound(f"Mission {mission_id} not found")
        return Mission.model_validate_json(row[0])

    def list_missions(self, limit: int = 50, offset: int = 0) -> list[Mission]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT payload FROM missions ORDER BY created_at DESC, id LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [Mission.model_validate_json(row[0]) for row in rows]

    def save(self, mission: Mission, expected_version: int, events: list[NewEvent]) -> Mission:
        if mission.version != expected_version + 1:
            raise StateConflict("Mission version must increment by one")
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                "UPDATE missions SET version = ?, payload = ? WHERE id = ? AND version = ?",
                (mission.version, self._payload(mission), mission.id, expected_version),
            )
            if cursor.rowcount != 1:
                if (
                    connection.execute(
                        "SELECT 1 FROM missions WHERE id = ?", (mission.id,)
                    ).fetchone()
                    is None
                ):
                    raise MissionNotFound(f"Mission {mission.id} not found")
                raise StateConflict(
                    "Mission was changed; reload and retry with its current version"
                )
            self._append_events(connection, mission.id, events)
        return mission

    def events(self, mission_id: str, after: int = 0, limit: int = 100) -> list[MissionEvent]:
        self.get(mission_id)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT sequence, payload FROM mission_events "
                "WHERE mission_id = ? AND sequence > ? ORDER BY sequence LIMIT ?",
                (mission_id, after, limit),
            ).fetchall()
        return [
            MissionEvent(sequence=row[0], mission_id=mission_id, **json.loads(row[1]))
            for row in rows
        ]
