"""Bounded, persisted user requests to replace a failed Developer patch."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from agentos.domain.base import Definition, Identifier, Text

Feedback = Annotated[str, Field(min_length=1, max_length=2000)]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class DeveloperRevision(Definition):
    number: int = Field(strict=True, ge=1, le=2)
    feedback: Feedback
    requested_at: datetime
    requested_by: Text
    patch_task_id: Identifier
    test_task_id: Identifier
    patch_attempt: int = Field(strict=True, ge=1)
    test_attempt: int = Field(strict=True, ge=1)
    approval_id: Text
    payload_digest: Digest
    plan_digest: Digest
    artifact_refs: tuple[Text, ...] = Field(min_length=3, max_length=3)
    artifact_hashes: dict[str, Digest]


class PatchRevisionContext(Definition):
    number: int = Field(strict=True, ge=1, le=2)
    feedback: Feedback
    previous_diff: str = Field(min_length=1, max_length=1_000_000)
    failed_tests: Literal[True] = True


class PatchRevisionStatus(Definition):
    allowed: bool
    remaining: int = Field(ge=0, le=2)
    reason: str = ""
    approval_id: str | None = None
    payload_digest: Digest | None = None
