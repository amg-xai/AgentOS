"""Durable acceptance request reservations; never authorizes generation or bills money."""

import hashlib
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator

from agentos.domain.base import Definition, Identifier


class LiveRequestPolicy(Definition):
    session_id: Identifier
    endpoint: str = Field(min_length=1, max_length=1000)
    model: str = Field(min_length=1, max_length=160)
    expires_at: datetime
    max_requests: int = Field(strict=True, ge=1, le=26)
    developer_requests: int = Field(default=0, strict=True, ge=0, le=9)
    creator_requests: int = Field(default=0, strict=True, ge=0, le=8)
    student_requests: int = Field(default=0, strict=True, ge=0, le=9)
    max_output_tokens: int = Field(strict=True, ge=256, le=8192)
    max_request_bytes: int = Field(strict=True, ge=1, le=1_000_000)
    provider_spend_control_confirmed: Literal[True]
    spend_control_reference: Annotated[str, Field(min_length=1, max_length=500)]

    @field_validator("provider_spend_control_confirmed", mode="before")
    @classmethod
    def explicit_confirmation(cls, value: object) -> object:
        if value is not True:
            raise ValueError("Provider spending control must be explicitly confirmed")
        return value

    @field_validator("expires_at")
    @classmethod
    def aware_expiry(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Acceptance expiry must include a timezone")
        return value.astimezone(UTC)

    def fingerprint(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()

    def check(self, endpoint: str, model: str) -> None:
        if self.expires_at <= datetime.now(UTC) or self.endpoint != endpoint or self.model != model:
            raise ValueError("Acceptance policy is expired or does not match the provider")


class LiveRequestLedger:
    """One explicit session per pre-provisioned file. Reservations are never refunded."""

    def __init__(self, path: Path, policy: LiveRequestPolicy) -> None:
        self.path, self.policy = path, policy

    @classmethod
    def initialize(cls, path: Path, policy: LiveRequestPolicy) -> None:
        # Explicit local provisioning after human authorization; never called by generation.
        with path.open("xb"):
            pass
        with closing(sqlite3.connect(path)) as conn, conn:
            conn.execute("CREATE TABLE policy (digest TEXT NOT NULL)")
            conn.execute("INSERT INTO policy VALUES (?)", (policy.fingerprint(),))
            conn.execute("CREATE TABLE reservations (role TEXT NOT NULL)")

    def _connect(self, mode: str) -> sqlite3.Connection:
        if self.path.is_symlink() or not self.path.is_file():
            raise ValueError("Acceptance ledger is missing or unsafe")
        return sqlite3.connect(self.path.resolve().as_uri() + f"?mode={mode}", uri=True)

    def _validate(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute("SELECT digest FROM policy").fetchall()
        if rows != [(self.policy.fingerprint(),)]:
            raise ValueError("Acceptance ledger policy does not match")
        if conn.execute(
            "SELECT COUNT(*) FROM reservations WHERE role NOT IN ('developer','creator','student')"
        ).fetchone()[0]:
            raise ValueError("Acceptance ledger contains invalid reservations")

    def validate(self) -> None:
        with closing(self._connect("ro")) as conn:
            self._validate(conn)
            if (
                conn.execute("SELECT COUNT(*) FROM reservations").fetchone()[0]
                >= self.policy.max_requests
            ):
                raise ValueError("Acceptance request allowance is exhausted")
            if not any(
                conn.execute(
                    "SELECT COUNT(*) FROM reservations WHERE role = ?", (role,)
                ).fetchone()[0]
                < limit
                for role, limit in (
                    ("developer", self.policy.developer_requests),
                    ("creator", self.policy.creator_requests),
                    ("student", self.policy.student_requests),
                )
            ):
                raise ValueError("Acceptance role allowances are exhausted")

    def reserve(self, role: str) -> None:
        limit = {
            "developer": self.policy.developer_requests,
            "creator": self.policy.creator_requests,
            "student": self.policy.student_requests,
        }.get(role, 0)
        with closing(self._connect("rw")) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            self._validate(conn)
            if self.policy.expires_at <= datetime.now(UTC):
                raise ValueError("Acceptance policy has expired")
            total = conn.execute("SELECT COUNT(*) FROM reservations").fetchone()[0]
            used = conn.execute(
                "SELECT COUNT(*) FROM reservations WHERE role = ?", (role,)
            ).fetchone()[0]
            if total >= self.policy.max_requests or used >= limit:
                raise ValueError(
                    "Acceptance request allowance is exhausted or role is unauthorized"
                )
            conn.execute("INSERT INTO reservations VALUES (?)", (role,))
