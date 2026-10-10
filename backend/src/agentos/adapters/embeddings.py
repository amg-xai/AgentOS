"""Explicit local embeddings; no cloud, generation, download or fallback path."""

import asyncio
import json
import os
from pathlib import Path

import httpx
from pydantic import Field

from agentos.adapters.live_limits import LiveRequestLedger, LiveRequestPolicy
from agentos.adapters.ollama import OllamaExecutor
from agentos.adapters.provider import ModelSettings, ProviderFailure
from agentos.domain.memory import Digest, Embeddings


class EmbeddingSettings(ModelSettings):
    model_digest: Digest
    enabled: bool = Field(default=False, strict=True)

    @classmethod
    def from_environment(cls) -> "EmbeddingSettings | None":
        if os.environ.get("AGENTOS_ALLOW_LOCAL_EMBEDDINGS") != "1":
            return None
        model = os.environ.get("AGENTOS_EMBEDDING_MODEL", "")
        digest = os.environ.get("AGENTOS_EMBEDDING_DIGEST", "")
        policy = os.environ.get("AGENTOS_EMBEDDING_POLICY")
        ledger = os.environ.get("AGENTOS_EMBEDDING_LEDGER")
        if not model or not digest or not policy or not ledger:
            raise ValueError("Explicit local embedding model, digest, policy and ledger required")
        return cls(
            provider="ollama",
            model=model,
            model_digest=digest,
            base_url=os.environ.get("AGENTOS_EMBEDDING_URL", "http://127.0.0.1:11434"),
            enabled=True,
            live_policy_path=Path(policy),
            live_ledger_path=Path(ledger),
            allow_live_calls=False,
        )


class OllamaEmbeddings(OllamaExecutor):
    def __init__(
        self, settings: EmbeddingSettings, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        super().__init__(settings, transport=transport)
        self.embedding_settings = settings

    async def embed(self, texts: tuple[str, ...]) -> Embeddings:
        if self._transport is None and not self.embedding_settings.enabled:
            raise ProviderFailure("Local embeddings are disabled pending explicit authorization")
        if not 1 <= len(texts) <= 32 or any(not t.strip() or len(t) > 2000 for t in texts):
            raise ProviderFailure("Embedding batch or text exceeds its limit")
        try:
            return await asyncio.wait_for(self._embed(texts), self.settings.timeout_seconds)
        except TimeoutError:
            raise ProviderFailure("Embedding request deadline exceeded") from None
        except ProviderFailure:
            raise
        except Exception:
            raise ProviderFailure("Local embedding transport or vector validation failed") from None

    async def _embed(self, texts: tuple[str, ...]) -> Embeddings:
        encoded = json.dumps(
            {
                "model": self.settings.model,
                "input": texts,
                "truncate": False,
                "keep_alive": 0,
            },
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
        limit = 128000
        ledger = None
        if self._transport is None:
            try:
                if self.settings.live_policy_path is None or self.settings.live_ledger_path is None:
                    raise ValueError("Missing limits")
                policy = LiveRequestPolicy.model_validate_json(
                    self.settings.live_policy_path.read_bytes()
                )
                policy.check(self.settings.base_url, self.settings.model)
                ledger = LiveRequestLedger(self.settings.live_ledger_path, policy)
                ledger.validate(memory=True)
                limit = min(limit, policy.max_request_bytes)
            except Exception:
                raise ProviderFailure("Embedding policy or ledger is unavailable") from None
        if len(encoded) > limit:
            raise ProviderFailure("Embedding input exceeds the request limit")
        if ledger is not None:
            try:
                ledger.reserve("memory")
            except Exception:
                raise ProviderFailure("Embedding request allowance is unavailable") from None
        async with httpx.AsyncClient(
            transport=self._transport,
            timeout=self.settings.timeout_seconds,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            await self.preflight(client)
            result = await self.request_json(
                client,
                "POST",
                "/api/embed",
                content=encoded,
                headers={"Content-Type": "application/json"},
            )
        if (
            result.get("model") != self.settings.model
            or result.get("error")
            or any(result.get(key) not in (None, "") for key in ("remote_host", "remote_model"))
        ):
            raise ProviderFailure("Embedding response model does not match")
        vectors = result.get("embeddings")
        if (
            not isinstance(vectors, list)
            or len(vectors) != len(texts)
            or any(
                not isinstance(v, list) or any(type(n) not in (float, int) for n in v)
                for v in vectors
            )
        ):
            raise ProviderFailure("Embedding response has invalid vectors")
        return Embeddings(
            model=self.settings.model,
            model_digest=self.embedding_settings.model_digest,
            vectors=tuple(tuple(v) for v in vectors),
        )

    async def preflight(self, client: httpx.AsyncClient) -> None:
        await self.local_model_preflight(client, "embedding")
        tags = await self.request_json(client, "GET", "/api/tags")
        matches = [m for m in tags.get("models", []) if m.get("name") == self.settings.model]
        if len(matches) != 1 or matches[0].get("digest") != self.embedding_settings.model_digest:
            raise ProviderFailure("Installed embedding model digest does not match")
