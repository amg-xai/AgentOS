"""Bounded, source-linked semantic memory contracts; similarity is not truth."""

import math
from typing import Annotated, Literal, Protocol, Self

from pydantic import ConfigDict, Field, model_validator

from agentos.domain.base import Definition

Profile = Literal["developer", "creator", "student"]
SourceKind = Literal["note", "mission", "artifact"]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class MemorySource(Definition):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)
    kind: SourceKind
    id: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=160)
    workspace_id: Literal["local"] = "local"
    profile: Profile | None = None
    mission_id: str | None = Field(default=None, max_length=160)
    text: str = Field(min_length=1, max_length=64000)
    digest: Digest
    evidence: Literal["user_note", "stored_outcome", "approved_artifact"]

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.id}"


class MemoryChunk(Definition):
    source: MemorySource
    start: int = Field(strict=True, ge=0)
    end: int = Field(strict=True, gt=0)
    vector: tuple[float, ...] = Field(min_length=1, max_length=4096)

    @model_validator(mode="after")
    def valid_chunk(self) -> Self:
        if not self.start < self.end <= len(self.source.text) or self.end - self.start > 1000:
            raise ValueError("Invalid memory chunk range")
        if any(not math.isfinite(v) for v in self.vector) or (
            not math.isfinite(math.hypot(*self.vector)) or math.hypot(*self.vector) == 0
        ):
            raise ValueError("Memory vectors must be finite and nonzero")
        return self


class Embeddings(Definition):
    model: str = Field(min_length=1, max_length=160)
    model_digest: Digest
    vectors: tuple[tuple[float, ...], ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def consistent_vectors(self) -> Self:
        size = len(self.vectors[0])
        if not 1 <= size <= 4096 or any(
            len(v) != size
            or any(not math.isfinite(n) for n in v)
            or not math.isfinite(math.hypot(*v))
            or math.hypot(*v) == 0
            for v in self.vectors
        ):
            raise ValueError("Invalid embedding dimensions or values")
        return self


class Embedder(Protocol):
    async def embed(self, texts: tuple[str, ...]) -> Embeddings: ...


class MemoryIndex(Definition):
    version: Literal[1] = 1
    generation: int = Field(strict=True, ge=1)
    model: str = Field(min_length=1, max_length=160)
    model_digest: Digest
    dimensions: int = Field(strict=True, ge=1, le=4096)
    chunks: tuple[MemoryChunk, ...] = Field(max_length=1000)
    omitted_sources: int = Field(strict=True, ge=0)

    @model_validator(mode="after")
    def consistent_index(self) -> Self:
        if any(len(c.vector) != self.dimensions for c in self.chunks):
            raise ValueError("Memory index dimensions differ")
        return self


class MemorySearch(Definition):
    query: str = Field(min_length=1, max_length=2000)
    profile: Profile | None = None
    mission_id: str | None = Field(default=None, min_length=1, max_length=160)
    kind: SourceKind | None = None
    limit: int = Field(default=5, strict=True, ge=1, le=20)
    minimum_similarity: float = Field(default=0.25, ge=0, le=1, allow_inf_nan=False)


class MemoryRebuild(Definition):
    """Explicit empty command; malformed or extra input cannot initiate inference."""


class MemoryHit(Definition):
    kind: SourceKind
    id: str
    title: str
    profile: Profile | None
    mission_id: str | None
    digest: Digest
    evidence: str
    start: int
    end: int
    excerpt: str
    similarity: float


class MemoryResults(Definition):
    strategy: Literal["semantic"] = "semantic"
    generation: int = Field(ge=0)
    hits: tuple[MemoryHit, ...] = ()
    indexed_chunks: int = Field(ge=0)
    omitted_sources: int = Field(ge=0)
    stale_sources: int = Field(ge=0)
    invalid_sources: int = Field(ge=0)


class MemoryIndexStorage(Protocol):
    def read(self) -> MemoryIndex | None: ...
    def publish(self, index: MemoryIndex, expected_generation: int) -> None: ...


class MemorySourceProvider(Protocol):
    def sources(self) -> tuple[dict[str, MemorySource], int]: ...
