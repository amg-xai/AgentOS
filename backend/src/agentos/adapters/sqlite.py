"""SQLite mission snapshots and append-only events, written atomically."""

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from agentos.domain.artifacts import Artifact
from agentos.domain.governance import (
    Approval,
    ApprovalStatus,
    RunClaim,
    payload_digest,
    review_payload,
)
from agentos.domain.missions import (
    Mission,
    MissionEvent,
    MissionNotFound,
    MissionStatus,
    NewEvent,
    StateConflict,
    TaskStatus,
)
from agentos.domain.overview import AgentActivity, MissionSummary, PersistedOverview, TaskSummary
from agentos.domain.tools import ToolCallEvent


class SQLiteMissionRepository:
    SCHEMA_VERSION = 2

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, self.SCHEMA_VERSION):
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
            if version < 2:
                self._migrate_v2(connection)

    @staticmethod
    def _migrate_v2(connection: sqlite3.Connection) -> None:
        connection.execute(
            "CREATE TABLE run_claims (mission_id TEXT PRIMARY KEY REFERENCES missions(id), "
            "payload TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE artifacts (id TEXT PRIMARY KEY, "
            "mission_id TEXT NOT NULL REFERENCES missions(id), payload TEXT NOT NULL)"
        )
        connection.execute("CREATE INDEX artifacts_by_mission ON artifacts(mission_id)")
        connection.execute(
            "CREATE TABLE approvals (id TEXT PRIMARY KEY, "
            "mission_id TEXT NOT NULL REFERENCES missions(id), "
            "status TEXT NOT NULL, payload TEXT NOT NULL)"
        )
        connection.execute("CREATE INDEX approvals_by_mission ON approvals(mission_id, status)")
        connection.execute("PRAGMA user_version = 2")

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

    def list_missions(
        self,
        limit: int = 50,
        offset: int = 0,
        *,
        query: str = "",
        role_id: str | None = None,
        status: MissionStatus | None = None,
    ) -> list[Mission]:
        search = query.strip().casefold()
        if search or role_id is not None or status is not None:
            result: list[Mission] = []
            skipped = 0
            with closing(self._connect()) as connection:
                for row in connection.execute(
                    "SELECT payload FROM missions ORDER BY created_at DESC, id"
                ):
                    mission = Mission.model_validate_json(row[0])
                    if (
                        (search and search not in mission.goal.casefold())
                        or (role_id is not None and mission.role_id != role_id)
                        or (status is not None and mission.status != status)
                    ):
                        continue
                    if skipped < offset:
                        skipped += 1
                        continue
                    result.append(mission)
                    if len(result) >= limit:
                        break
            return result
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT payload FROM missions ORDER BY created_at DESC, id LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [Mission.model_validate_json(row[0]) for row in rows]

    def overview(self, agent_ids: tuple[str, ...]) -> PersistedOverview:
        counts = dict.fromkeys(MissionStatus, 0)
        task_counts = {agent: dict.fromkeys(TaskStatus, 0) for agent in agent_ids}
        activity: dict[str, list[TaskSummary]] = {agent: [] for agent in agent_ids}
        reviews: list[MissionSummary] = []
        # One read snapshot for all persisted evidence; no full-history list retained.
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN")
            observed_at = datetime.now(UTC)
            for row in connection.execute(
                "SELECT missions.payload, run_claims.mission_id IS NOT NULL "
                "FROM missions LEFT JOIN run_claims ON missions.id = run_claims.mission_id"
            ):
                mission = Mission.model_validate_json(row[0])
                claimed = bool(row[1])
                counts[mission.status] += 1
                if mission.status == MissionStatus.WAITING_APPROVAL:
                    reviews.append(
                        MissionSummary(
                            id=mission.id,
                            goal=mission.goal[:240],
                            role_id=mission.role_id,
                            status=mission.status,
                            updated_at=mission.updated_at,
                            has_claim=claimed,
                        )
                    )
                    reviews.sort(key=lambda item: (item.updated_at, item.id), reverse=True)
                    del reviews[10:]
                for task in mission.tasks:
                    if task.agent_id not in activity:
                        continue
                    task_counts[task.agent_id][task.status] += 1
                    recent = activity[task.agent_id]
                    recent.append(
                        TaskSummary(
                            mission_id=mission.id,
                            mission_goal=mission.goal[:240],
                            task_id=task.id,
                            title=task.title[:240],
                            status=task.status,
                            mission_updated_at=mission.updated_at,
                            has_claim=claimed,
                        )
                    )
                    recent.sort(
                        key=lambda item: (item.mission_updated_at, item.mission_id, item.task_id),
                        reverse=True,
                    )
                    del recent[5:]
            pending = connection.execute(
                "SELECT COUNT(*) FROM approvals WHERE status = 'PENDING'"
            ).fetchone()[0]
            claims = connection.execute("SELECT COUNT(*) FROM run_claims").fetchone()[0]
            artifacts = connection.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0]
            recent_artifacts = tuple(
                Artifact.model_validate_json(row[0])
                for row in connection.execute(
                    "SELECT payload FROM artifacts ORDER BY rowid DESC LIMIT 10"
                )
            )
        return PersistedOverview(
            observed_at=observed_at,
            total_missions=sum(counts.values()),
            mission_counts=counts,
            pending_approvals=pending,
            durable_claims=claims,
            total_artifacts=artifacts,
            recent_reviews=tuple(reviews),
            recent_artifacts=recent_artifacts,
            agent_activity=tuple(
                AgentActivity(
                    agent_id=agent,
                    task_counts=task_counts[agent],
                    recent_tasks=tuple(activity[agent]),
                )
                for agent in agent_ids
            ),
        )

    @staticmethod
    def _check_claim(connection: sqlite3.Connection, mission_id: str, token: str | None) -> None:
        row = connection.execute(
            "SELECT payload FROM run_claims WHERE mission_id = ?", (mission_id,)
        ).fetchone()
        if row is None:
            if token is not None:
                raise StateConflict("Execution claim was revoked")
        elif RunClaim.model_validate_json(row[0]).token != token:
            raise StateConflict("Mission has an active execution claim")

    def _update_snapshot(
        self,
        connection: sqlite3.Connection,
        mission: Mission,
        expected_version: int,
        claim_token: str | None,
    ) -> None:
        if mission.version != expected_version + 1:
            raise StateConflict("Mission version must increment by one")
        self._check_claim(connection, mission.id, claim_token)
        cursor = connection.execute(
            "UPDATE missions SET version = ?, payload = ? WHERE id = ? AND version = ?",
            (mission.version, self._payload(mission), mission.id, expected_version),
        )
        if cursor.rowcount != 1:
            if (
                connection.execute("SELECT 1 FROM missions WHERE id = ?", (mission.id,)).fetchone()
                is None
            ):
                raise MissionNotFound(f"Mission {mission.id} not found")
            raise StateConflict("Mission was changed; reload and retry with its current version")

    @staticmethod
    def _invalidate_approvals(connection: sqlite3.Connection, mission: Mission) -> None:
        tasks = {task.id: task for task in mission.tasks}
        for row in connection.execute(
            "SELECT payload FROM approvals WHERE mission_id = ? AND status = 'PENDING'",
            (mission.id,),
        ).fetchall():
            approval = Approval.model_validate_json(row[0])
            task = tasks.get(approval.task_id)
            if (
                task is None
                or task.status != TaskStatus.WAITING_APPROVAL
                or task.attempts != approval.task_attempt
                or payload_digest(review_payload(task)) != approval.payload_digest
            ):
                connection.execute(
                    "UPDATE approvals SET status = 'STALE' WHERE id = ?", (approval.id,)
                )

    def save(
        self,
        mission: Mission,
        expected_version: int,
        events: list[NewEvent],
        *,
        claim_token: str | None = None,
        artifacts: tuple[Artifact, ...] = (),
        approval: Approval | None = None,
        decision: Approval | None = None,
    ) -> Mission:
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            self._update_snapshot(connection, mission, expected_version, claim_token)
            for artifact in artifacts:
                if artifact.mission_id != mission.id or artifact.task_id not in {
                    task.id for task in mission.tasks
                }:
                    raise StateConflict("Artifact scope does not match the mission")
                connection.execute(
                    "INSERT INTO artifacts(id, mission_id, payload) VALUES (?, ?, ?)",
                    (artifact.id, mission.id, artifact.model_dump_json()),
                )
            if approval is not None:
                task = next((t for t in mission.tasks if t.id == approval.task_id), None)
                if (
                    approval.mission_id != mission.id
                    or task is None
                    or task.status != TaskStatus.WAITING_APPROVAL
                    or approval.task_attempt != task.attempts
                    or approval.status != ApprovalStatus.PENDING
                    or payload_digest(approval.payload) != approval.payload_digest
                    or payload_digest(review_payload(task)) != approval.payload_digest
                ):
                    raise StateConflict("Approval scope or payload does not match the waiting task")
                connection.execute(
                    "INSERT INTO approvals(id, mission_id, status, payload) VALUES (?, ?, ?, ?)",
                    (approval.id, mission.id, approval.status, approval.model_dump_json()),
                )
            if decision is not None:
                stored = self._get_approval(connection, decision.id)
                if (
                    stored.status != ApprovalStatus.PENDING
                    or stored.mission_id != mission.id
                    or stored.payload_digest != decision.payload_digest
                    or stored.task_id != decision.task_id
                    or stored.task_attempt != decision.task_attempt
                    or stored.payload != decision.payload
                    or decision.status not in {ApprovalStatus.APPROVED, ApprovalStatus.DENIED}
                ):
                    raise StateConflict("Approval has already been decided or no longer matches")
                connection.execute(
                    "UPDATE approvals SET status = ?, payload = ? WHERE id = ?",
                    (decision.status, decision.model_dump_json(), decision.id),
                )
            self._invalidate_approvals(connection, mission)
            self._append_events(connection, mission.id, events)
        return mission

    @staticmethod
    def _get_approval(connection: sqlite3.Connection, approval_id: str) -> Approval:
        row = connection.execute(
            "SELECT status, payload FROM approvals WHERE id = ?", (approval_id,)
        ).fetchone()
        if row is None:
            raise MissionNotFound("Approval not found")
        return Approval.model_validate_json(row[1]).model_copy(
            update={"status": ApprovalStatus(row[0])}
        )

    def approval(self, approval_id: str) -> Approval:
        with closing(self._connect()) as connection:
            return self._get_approval(connection, approval_id)

    def approvals(self, mission_id: str, pending_only: bool = True) -> list[Approval]:
        self.get(mission_id)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT id FROM approvals WHERE mission_id = ? "
                "AND (? = 0 OR status = 'PENDING') ORDER BY rowid",
                (mission_id, pending_only),
            ).fetchall()
            return [self._get_approval(connection, row[0]) for row in rows]

    def artifact(self, artifact_id: str) -> Artifact:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT payload FROM artifacts WHERE id = ?", (artifact_id,)
            ).fetchone()
        if row is None:
            raise MissionNotFound("Artifact not found")
        return Artifact.model_validate_json(row[0])

    def artifacts(self, mission_id: str, limit: int = 100, offset: int = 0) -> list[Artifact]:
        self.get(mission_id)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT payload FROM artifacts WHERE mission_id = ? "
                "ORDER BY rowid LIMIT ? OFFSET ?",
                (mission_id, limit, offset),
            ).fetchall()
        return [Artifact.model_validate_json(row[0]) for row in rows]

    def claim(self, mission_id: str) -> RunClaim | None:
        self.get(mission_id)
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT payload FROM run_claims WHERE mission_id = ?", (mission_id,)
            ).fetchone()
        return RunClaim.model_validate_json(row[0]) if row else None

    def acquire_claim(self, mission_id: str, expected_version: int, actor: str) -> RunClaim:
        claim = RunClaim(
            mission_id=mission_id, token=uuid4().hex, actor=actor, created_at=datetime.now(UTC)
        )
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT version FROM missions WHERE id = ?", (mission_id,)
            ).fetchone()
            if row is None:
                raise MissionNotFound("Mission not found")
            if row[0] != expected_version:
                raise StateConflict("Mission version is stale")
            try:
                connection.execute(
                    "INSERT INTO run_claims VALUES (?, ?)", (mission_id, claim.model_dump_json())
                )
            except sqlite3.IntegrityError as exc:
                raise StateConflict("Mission has an active execution claim") from exc
            self._append_events(
                connection,
                mission_id,
                [
                    NewEvent(
                        timestamp=claim.created_at,
                        actor=actor,
                        action="run_claimed",
                    )
                ],
            )
        return claim

    def release_claim(self, claim: RunClaim) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            self._check_claim(connection, claim.mission_id, claim.token)
            connection.execute("DELETE FROM run_claims WHERE mission_id = ?", (claim.mission_id,))
            self._append_events(
                connection,
                claim.mission_id,
                [
                    NewEvent(
                        timestamp=datetime.now(UTC),
                        actor=claim.actor,
                        action="run_released",
                    )
                ],
            )

    def recover_claim(
        self, mission: Mission, expected_token: str, events: list[NewEvent]
    ) -> Mission:
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            self._update_snapshot(connection, mission, mission.version - 1, expected_token)
            self._invalidate_approvals(connection, mission)
            connection.execute("DELETE FROM run_claims WHERE mission_id = ?", (mission.id,))
            self._append_events(connection, mission.id, events)
        return mission

    def record_tool_event(self, event: ToolCallEvent) -> None:
        """Fail closed if the caller no longer owns a running task."""
        context = event.context
        if context.run_token is None:
            raise StateConflict("Tool audit requires an execution claim")
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            self._check_claim(connection, context.mission_id, context.run_token)
            row = connection.execute(
                "SELECT payload FROM missions WHERE id = ?", (context.mission_id,)
            ).fetchone()
            if row is None:
                raise MissionNotFound("Mission not found")
            mission = Mission.model_validate_json(row[0])
            task = next((task for task in mission.tasks if task.id == context.task_id), None)
            if (
                context.workspace_id != mission.workspace_id
                or task is None
                or task.status != TaskStatus.RUNNING
            ):
                raise StateConflict("Tool audit scope does not match a running task")
            self._append_events(
                connection,
                mission.id,
                [
                    NewEvent(
                        timestamp=event.timestamp,
                        actor="local",
                        action=f"tool_{event.outcome}",
                        task_id=task.id,
                        details={"tool_id": event.tool_id, "role": event.role},
                    )
                ],
            )

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
