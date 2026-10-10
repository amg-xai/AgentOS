"""Local embeddings tested through injected HTTP, never downloads or real inference."""

import asyncio
import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from agentos.adapters.embeddings import EmbeddingSettings, OllamaEmbeddings
from agentos.adapters.live_limits import LiveRequestLedger, LiveRequestPolicy
from agentos.adapters.provider import ProviderFailure

DIGEST = "a" * 64


def settings(**values):
    return EmbeddingSettings(
        provider="ollama",
        model="embed:1",
        model_digest=DIGEST,
        base_url="http://127.0.0.1:11434",
        **values,
    )


def handler(request):
    if request.url.path == "/api/status":
        data = {"cloud": {"disabled": True}}
    elif request.url.path == "/api/tags":
        data = {"models": [{"name": "embed:1", "digest": DIGEST, "size": 100}]}
    elif request.url.path == "/api/show":
        data = {"capabilities": ["embedding"], "model_info": {"architecture": "test"}}
    elif request.url.path == "/api/embed":
        body = json.loads(request.content)
        assert body["truncate"] is False
        assert body["keep_alive"] == 0
        assert "Authorization" not in request.headers
        assert request.headers["Content-Type"] == "application/json"
        data = {"model": "embed:1", "embeddings": [[1, 0] for _ in body["input"]]}
    else:
        pytest.fail(f"Unexpected endpoint: {request.url.path}")
    return httpx.Response(200, json=data)


def run(transport, texts=("query",), **values):
    return asyncio.run(
        OllamaEmbeddings(settings(**values), transport=httpx.MockTransport(transport)).embed(texts)
    )


def test_disabled_before_http_and_separate_environment(monkeypatch):
    def forbidden(**kwargs):
        pytest.fail("Disabled embeddings reached HTTP")

    monkeypatch.setattr(httpx, "AsyncClient", forbidden)
    monkeypatch.setenv("AGENTOS_ALLOW_LIVE_MODELS", "1")
    monkeypatch.delenv("AGENTOS_ALLOW_LOCAL_EMBEDDINGS", raising=False)
    assert EmbeddingSettings.from_environment() is None
    with pytest.raises(ProviderFailure, match="disabled"):
        asyncio.run(OllamaEmbeddings(settings()).embed(("query",)))


def test_embedding_capability_and_wire_contract():
    result = run(handler, ("one", "two"))
    assert result.model_digest == DIGEST
    assert result.vectors == ((1, 0), (1, 0))


@pytest.mark.parametrize(
    "path,data",
    [
        ("/api/status", {"cloud": {"disabled": False}}),
        ("/api/tags", {"models": []}),
        ("/api/tags", {"models": [{"name": "embed:1", "digest": "b" * 64, "size": 100}]}),
        ("/api/show", {"capabilities": ["completion"], "model_info": {"x": 1}}),
        (
            "/api/show",
            {"capabilities": ["embedding"], "model_info": {"x": 1}, "remote_host": "cloud"},
        ),
        ("/api/embed", {"model": "other:1", "embeddings": [[1, 0]]}),
        ("/api/embed", {"model": "embed:1", "embeddings": []}),
        ("/api/embed", {"model": "embed:1", "embeddings": [[0, 0]]}),
        ("/api/embed", {"model": "embed:1", "embeddings": [[True, 0]]}),
        ("/api/embed", {"model": "embed:1", "embeddings": [["1", 0]]}),
        ("/api/embed", {"model": "embed:1", "embeddings": [[1] * 4097]}),
        ("/api/embed", {"model": "embed:1", "embeddings": [[1, 0]], "remote_model": "cloud"}),
    ],
)
def test_unavailable_unsafe_or_invalid_embedding_rejected(path, data):
    def invalid(request):
        return httpx.Response(200, json=data) if request.url.path == path else handler(request)

    with pytest.raises(ProviderFailure):
        run(invalid)


@pytest.mark.parametrize("code", [404, 307, 500])
def test_http_errors_do_not_fallback(code):
    calls = []

    def failed(request):
        calls.append(request.url.path)
        return httpx.Response(code, headers={"Location": "https://paid.example"})

    with pytest.raises(ProviderFailure):
        run(failed)
    assert calls == ["/api/status"]


def test_deadline_and_nonfinite_response():
    async def slow(request):
        await asyncio.sleep(0.1)
        return handler(request)

    with pytest.raises(ProviderFailure, match="deadline"):
        run(slow, timeout_seconds=0.01)

    def invalid(request):
        if request.url.path == "/api/embed":
            return httpx.Response(200, content=b'{"model":"embed:1","embeddings":[[NaN,1]]}')
        return handler(request)

    with pytest.raises(ProviderFailure):
        run(invalid)


def test_legacy_fingerprint_memory_allowance_and_no_refunds(tmp_path, monkeypatch):
    policy = LiveRequestPolicy(
        session_id="embedding_test",
        endpoint="http://127.0.0.1:11434",
        model="embed:1",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        max_requests=2,
        max_output_tokens=256,
        max_request_bytes=128000,
        provider_spend_control_confirmed=True,
        spend_control_reference="Injected transport only",
    )
    legacy_digest = hashlib.sha256(
        policy.model_dump_json(exclude={"memory_requests"}).encode()
    ).hexdigest()
    assert policy.fingerprint() == legacy_digest
    legacy_path = tmp_path / "legacy.sqlite3"
    LiveRequestLedger.initialize(legacy_path, policy)
    with pytest.raises(ValueError):
        LiveRequestLedger(legacy_path, policy).reserve("memory")
    policy = policy.model_copy(update={"memory_requests": 2})
    ledger_path, policy_path = tmp_path / "ledger.sqlite3", tmp_path / "policy.json"
    policy_path.write_text(policy.model_dump_json(), encoding="utf-8")
    LiveRequestLedger.initialize(ledger_path, policy)
    ledger = LiveRequestLedger(ledger_path, policy)
    ledger.validate(memory=True)
    with pytest.raises(ValueError):
        ledger.validate()
    client = httpx.AsyncClient
    calls = []

    def unavailable(request):
        calls.append(request.url.path)
        return httpx.Response(404)

    def isolated_client(**kwargs):
        assert kwargs.pop("transport") is None
        return client(transport=httpx.MockTransport(unavailable), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", isolated_client)
    executor = OllamaEmbeddings(
        settings(enabled=True, live_policy_path=policy_path, live_ledger_path=ledger_path)
    )
    for _ in range(2):
        with pytest.raises(ProviderFailure):
            asyncio.run(executor.embed(("query",)))
    with sqlite3.connect(ledger_path) as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM reservations WHERE role='memory'").fetchone()[0] == 2
        )
    with pytest.raises(ProviderFailure, match="policy or ledger"):
        asyncio.run(executor.embed(("query",)))
    assert len(calls) == 2


@pytest.mark.parametrize("texts", [(), ("",), ("x" * 2001,), ("query",) * 33])
def test_batch_limits_before_http(texts):
    with pytest.raises(ProviderFailure, match="limit"):
        run(handler, texts)


def test_utf8_byte_limit_and_network_failure_are_safe():
    def forbidden(request):
        pytest.fail("Oversize embedding input reached HTTP")

    with pytest.raises(ProviderFailure, match="request limit"):
        run(forbidden, ("\U0001f600" * 2000,) * 32)

    def disconnected(request):
        raise httpx.ConnectError("secret transport detail")

    with pytest.raises(ProviderFailure) as failure:
        run(disconnected)
    assert "secret" not in str(failure.value)


def test_local_environment_requires_explicit_model_without_generation(monkeypatch):
    monkeypatch.setenv("AGENTOS_ALLOW_LOCAL_EMBEDDINGS", "1")
    for name in (
        "AGENTOS_EMBEDDING_MODEL",
        "AGENTOS_EMBEDDING_DIGEST",
        "AGENTOS_EMBEDDING_POLICY",
        "AGENTOS_EMBEDDING_LEDGER",
    ):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValueError, match="Explicit"):
        EmbeddingSettings.from_environment()
    monkeypatch.setenv("AGENTOS_EMBEDDING_MODEL", "embed:1")
    monkeypatch.setenv("AGENTOS_EMBEDDING_DIGEST", DIGEST)
    monkeypatch.setenv("AGENTOS_EMBEDDING_POLICY", "policy.json")
    monkeypatch.setenv("AGENTOS_EMBEDDING_LEDGER", "ledger.sqlite3")
    result = EmbeddingSettings.from_environment()
    assert result.enabled is True and result.allow_live_calls is False
    monkeypatch.setenv("AGENTOS_EMBEDDING_URL", "https://paid.example")
    with pytest.raises(ValueError):
        EmbeddingSettings.from_environment()
