"""Bounded semantic ranking over source and storage interfaces."""

import asyncio
import math

from agentos.domain.memory import (
    Embedder,
    MemoryChunk,
    MemoryHit,
    MemoryIndex,
    MemoryIndexStorage,
    MemoryResults,
    MemorySearch,
    MemorySource,
    MemorySourceProvider,
)
from agentos.domain.missions import StateConflict


class SemanticMemory:
    def __init__(
        self, store: MemoryIndexStorage, corpus: MemorySourceProvider, embedder: Embedder | None
    ) -> None:
        self.store, self.corpus, self.embedder = store, corpus, embedder

    def status(self) -> dict[str, object]:
        index = self.store.read()
        return {
            "configured": self.embedder is not None,
            "generation": index.generation if index else 0,
            "indexed_chunks": len(index.chunks) if index else 0,
            "omitted_sources": index.omitted_sources if index else 0,
            "model": index.model if index else None,
            "model_digest": index.model_digest if index else None,
        }

    async def rebuild(self) -> dict[str, object]:
        try:
            return await asyncio.wait_for(self._rebuild(), timeout=300)
        except TimeoutError:
            raise StateConflict(
                "Semantic rebuild deadline exceeded; previous index preserved"
            ) from None

    async def _rebuild(self) -> dict[str, object]:
        if self.embedder is None:
            raise StateConflict("Local semantic embeddings are disabled or unavailable")
        previous = self.store.read()
        generation = previous.generation if previous else 0
        sources, invalid = self.corpus.sources()
        pending: list[tuple[MemorySource, int, int]] = []
        omitted = 0
        for source in sources.values():
            ranges = [
                (start, min(start + 1000, len(source.text)))
                for start in range(0, len(source.text), 872)
            ]
            # At most 24 batches under the unchanged 26-request policy ceiling.
            if len(pending) + len(ranges) > 768:
                omitted += 1
                continue
            pending.extend((source, start, end) for start, end in ranges)
        # An empty corpus needs no model call and retains a previous model identity.
        if not pending:
            if previous is not None:
                self.store.publish(
                    previous.model_copy(
                        update={
                            "generation": generation + 1,
                            "chunks": (),
                            "omitted_sources": omitted,
                        }
                    ),
                    generation,
                )
            return {**self.status(), "invalid_sources": invalid, "empty_corpus": True}
        chunks: list[MemoryChunk] = []
        identity: tuple[str, str, int] | None = None
        for offset in range(0, len(pending), 32):
            batch = pending[offset : offset + 32]
            embeddings = await self.embedder.embed(tuple(s.text[a:b] for s, a, b in batch))
            current = (embeddings.model, embeddings.model_digest, len(embeddings.vectors[0]))
            if identity is not None and identity != current:
                raise StateConflict("Embedding model changed during rebuild")
            if len(embeddings.vectors) != len(batch):
                raise StateConflict("Embedding count does not match source chunks")
            identity = current
            chunks.extend(
                MemoryChunk(source=s, start=a, end=b, vector=v)
                for (s, a, b), v in zip(batch, embeddings.vectors, strict=True)
            )
        assert identity is not None
        index = MemoryIndex(
            generation=generation + 1,
            model=identity[0],
            model_digest=identity[1],
            dimensions=identity[2],
            chunks=tuple(chunks),
            omitted_sources=omitted,
        )
        self.store.publish(index, generation)
        return {**self.status(), "invalid_sources": invalid, "empty_corpus": False}

    async def search(self, request: MemorySearch) -> MemoryResults:
        index = self.store.read()
        if index is None or not index.chunks:
            return MemoryResults(
                generation=index.generation if index else 0,
                indexed_chunks=0,
                omitted_sources=0,
                stale_sources=0,
                invalid_sources=0,
            )
        sources, invalid = self.corpus.sources()
        candidates = []
        stale: set[str] = set()
        for chunk in index.chunks:
            source = sources.get(chunk.source.key)
            if source is None or source != chunk.source:
                stale.add(chunk.source.key)
                continue
            if (
                (request.profile is not None and source.profile != request.profile)
                or (request.mission_id is not None and source.mission_id != request.mission_id)
                or (request.kind is not None and source.kind != request.kind)
            ):
                continue
            candidates.append(chunk)
        hits: list[MemoryHit] = []
        if candidates:
            if self.embedder is None:
                raise StateConflict("Local semantic embeddings are disabled or unavailable")
            result = await self.embedder.embed((request.query,))
            if (
                result.model != index.model
                or result.model_digest != index.model_digest
                or len(result.vectors) != 1
                or len(result.vectors[0]) != index.dimensions
            ):
                raise StateConflict("Query model does not match the persistent semantic index")
            query = result.vectors[0]
            # Awaiting inference must not allow changed/withdrawn evidence to escape.
            sources, invalid = self.corpus.sources()
            fresh = []
            for chunk in candidates:
                if sources.get(chunk.source.key) == chunk.source:
                    fresh.append(chunk)
                else:
                    stale.add(chunk.source.key)
            candidates = fresh
            scored = []
            for chunk in candidates:
                query_norm, chunk_norm = math.hypot(*query), math.hypot(*chunk.vector)
                score = sum(
                    (a / query_norm) * (b / chunk_norm)
                    for a, b in zip(query, chunk.vector, strict=True)
                )
                if score >= request.minimum_similarity:
                    scored.append((score, chunk))
            used: set[str] = set()
            for score, chunk in sorted(
                scored, key=lambda item: (-item[0], item[1].source.key, item[1].start)
            ):
                source = chunk.source
                if source.key in used:
                    continue
                used.add(source.key)
                hits.append(
                    MemoryHit(
                        kind=source.kind,
                        id=source.id,
                        title=source.title,
                        profile=source.profile,
                        mission_id=source.mission_id,
                        digest=source.digest,
                        evidence=source.evidence,
                        start=chunk.start,
                        end=chunk.end,
                        excerpt=source.text[chunk.start : chunk.end],
                        similarity=max(-1.0, min(1.0, score)),
                    )
                )
                if len(hits) >= request.limit:
                    break
        response = MemoryResults(
            generation=index.generation,
            hits=tuple(hits),
            indexed_chunks=len(index.chunks),
            omitted_sources=index.omitted_sources,
            stale_sources=len(stale),
            invalid_sources=invalid,
        )
        if len(response.model_dump_json().encode()) > 64000:
            raise StateConflict("Semantic memory response exceeds its limit")
        return response
