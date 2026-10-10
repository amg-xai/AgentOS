"""Local-provider contracts, entirely in memory; no runner, downloads or sockets."""

import asyncio
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from agentos.adapters.live_limits import LiveRequestLedger, LiveRequestPolicy
from agentos.adapters.ollama import OllamaExecutor, create_model_executor
from agentos.adapters.provider import ModelSettings, ProviderFailure, ResponsesExecutor
from agentos.api.app import create_app

MODEL = "qwen3:4b"
ENDPOINT = "http://127.0.0.1:11434"


def local_settings(**values):
    return ModelSettings(provider="ollama", model=MODEL, base_url=ENDPOINT, **values)


def reply(content='{"findings":"Evidence"}', **values):
    return httpx.Response(
        200,
        json={
            "model": MODEL,
            "done": True,
            "done_reason": "stop",
            "message": {"role": "assistant", "content": content},
            **values,
        },
    )


def handler(request):
    assert request.url.host == "127.0.0.1"
    assert "authorization" not in request.headers
    if request.url.path == "/api/status":
        return httpx.Response(200, json={"cloud": {"disabled": True}})
    if request.url.path == "/api/tags":
        return httpx.Response(
            200, json={"models": [{"name": MODEL, "size": 2_500_000_000, "digest": "a" * 64}]}
        )
    if request.url.path == "/api/show":
        assert json.loads(request.content) == {"model": MODEL}
        return httpx.Response(
            200,
            json={"capabilities": ["completion"], "model_info": {"general.architecture": "qwen3"}},
        )
    assert request.url.path == "/api/chat"
    return reply()


def generate(registry, route=handler, **settings):
    return asyncio.run(
        create_model_executor(
            local_settings(**settings), transport=httpx.MockTransport(route)
        ).generate(registry.agent("investigation"), {"goal": "fix"})
    )


def test_explicit_selection_keeps_responses_default_and_no_implicit_local_fallback():
    assert type(create_model_executor(ModelSettings(model="model"))) is ResponsesExecutor
    assert type(create_model_executor(local_settings())) is OllamaExecutor
    with pytest.raises(ValueError, match="does not match"):
        ResponsesExecutor(local_settings())


def test_environment_selection_ignores_cloud_keys_and_remains_disabled(monkeypatch):
    monkeypatch.setenv("AGENTOS_MODEL_PROVIDER", "ollama")
    monkeypatch.setenv("AGENTOS_MODEL", MODEL)
    monkeypatch.setenv("AGENTOS_MODEL_KEY", "must-never-be-transmitted")
    monkeypatch.setenv("OPENAI_API_KEY", "must-never-be-transmitted")
    monkeypatch.delenv("AGENTOS_MODEL_URL", raising=False)
    monkeypatch.delenv("AGENTOS_ALLOW_LIVE_MODELS", raising=False)
    settings = ModelSettings.from_environment()
    assert settings.provider == "ollama" and settings.base_url == ENDPOINT
    assert settings.api_key is None and not settings.allow_live_calls
    monkeypatch.setenv("AGENTOS_MODEL_PROVIDER", "unknown")
    with pytest.raises(ValueError, match="Unknown model provider"):
        ModelSettings.from_environment()


@pytest.mark.parametrize(
    "url",
    [
        "https://ollama.com",
        "http://remote.example:11434",
        "http://localhost:11434",
        "http://127.0.0.1:11434/v1",
        "http://user@127.0.0.1:11434",
        "http://127.0.0.1:11434?key=x",
    ],
)
def test_only_literal_loopback_root_allowed(url):
    with pytest.raises(ValidationError):
        ModelSettings(provider="ollama", model=MODEL, base_url=url)


@pytest.mark.parametrize(
    "model",
    [
        "qwen3",
        "qwen3:cloud",
        "local:my-cloud-alias",
        "org/model:tag",
        "https://host/model",
        "MODEL:4b",
    ],
)
def test_rejects_implicit_remote_or_unqualified_model(model):
    with pytest.raises(ValidationError):
        ModelSettings(provider="ollama", model=model, base_url=ENDPOINT)


def test_local_settings_reject_any_api_key():
    with pytest.raises(ValidationError):
        local_settings(api_key=SecretStr("unused-key"))


def test_disabled_generation_performs_no_availability_or_inference_calls(registry, monkeypatch):
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **_: pytest.fail("Generation must stay disabled")
    )
    with pytest.raises(ProviderFailure, match="disabled"):
        asyncio.run(
            create_model_executor(local_settings()).generate(
                registry.agent("investigation"), {"goal": "fix"}
            )
        )


@pytest.mark.parametrize(
    "agent_id,output",
    [
        ("investigation", {"findings": "Evidence"}),
        ("creator_outline", {"outline": "Outline"}),
        ("student_notes", {"notes": "Notes"}),
    ],
)
def test_all_three_profiles_use_actual_schemas_and_original_inputs(registry, agent_id, output):
    agent = registry.agent(agent_id)
    inputs = {"goal": "Original goal", "constraints": ["Keep evidence"]}
    paths = []

    def route(request):
        paths.append(request.url.path)
        if request.url.path != "/api/chat":
            return handler(request)
        body = json.loads(request.content)
        assert body["messages"] == [
            {"role": "system", "content": agent.instructions},
            {"role": "user", "content": json.dumps(inputs, ensure_ascii=False)},
        ]
        assert body["format"] == agent.output_schema
        assert body["options"] == {"temperature": 0, "num_predict": 8192, "num_ctx": 8192}
        assert body["stream"] is False and body["think"] is False
        assert body["truncate"] is False and body["shift"] is False
        assert body["keep_alive"] == 0 and "tools" not in body
        return reply(json.dumps(output))

    result = asyncio.run(
        create_model_executor(local_settings(), transport=httpx.MockTransport(route)).generate(
            agent, inputs
        )
    )
    assert result == output
    assert paths == ["/api/status", "/api/tags", "/api/show", "/api/chat"]


@pytest.mark.parametrize(
    "path,bad",
    [
        ("/api/status", {}),
        ("/api/status", {"cloud": {"disabled": False}}),
        ("/api/status", {"cloud": {"disabled": 1}}),
        ("/api/tags", {"models": []}),
        ("/api/tags", {"models": [{"name": MODEL, "size": 0, "digest": "a" * 64}]}),
        ("/api/tags", {"models": [{"name": MODEL, "size": 1, "digest": "invalid"}]}),
        (
            "/api/show",
            {
                "remote_host": "https://cloud",
                "capabilities": ["completion"],
                "model_info": {"x": 1},
            },
        ),
        (
            "/api/show",
            {"remote_model": MODEL, "capabilities": ["completion"], "model_info": {"x": 1}},
        ),
        ("/api/show", {"capabilities": ["embedding"], "model_info": {"x": 1}}),
        ("/api/show", {"capabilities": "completion", "model_info": {"x": 1}}),
    ],
)
def test_availability_failure_has_no_download_cloud_or_script_fallback(registry, path, bad):
    calls = []

    def route(request):
        calls.append(request.url.path)
        return httpx.Response(200, json=bad) if request.url.path == path else handler(request)

    with pytest.raises(ProviderFailure):
        generate(registry, route)
    assert calls[-1] == path
    assert "/api/chat" not in calls
    assert not any("pull" in p or "signin" in p for p in calls)


@pytest.mark.parametrize(
    "case",
    [
        "missing_runner",
        "old_runner",
        "redirect",
        "timeout",
        "deadline",
        "invalid_json",
        "oversized",
    ],
)
def test_runner_errors_are_bounded_and_sanitized(registry, case):
    async def route(request):
        if case == "missing_runner":
            raise httpx.ConnectError("private data")
        if case == "timeout":
            raise httpx.ReadTimeout("private data")
        if case == "deadline":
            await asyncio.sleep(10)
        if case == "old_runner":
            return httpx.Response(404, text="private data")
        if case == "redirect":
            return httpx.Response(307, headers={"location": "https://cloud"})
        if case == "oversized":
            return httpx.Response(200, content=b"x" * 2_000_001)
        return httpx.Response(200, content=b"private data")

    with pytest.raises(ProviderFailure) as failure:
        generate(registry, route, timeout_seconds=0.03)
    assert "private data" not in str(failure.value)


@pytest.mark.parametrize(
    "response",
    [
        reply(done=False),
        reply(done_reason="length"),
        reply(model="other:4b"),
        reply(remote_host="https://cloud"),
        reply('{"wrong":true}'),
        reply('{"findings":NaN}'),
        reply('```json\n{"findings":"text"}\n```'),
        reply(message={"role": "assistant", "content": "{}", "tool_calls": [{"x": 1}]}),
    ],
)
def test_invalid_or_remote_results_never_become_success(registry, response):
    def route(request):
        return response if request.url.path == "/api/chat" else handler(request)

    with pytest.raises(ProviderFailure):
        generate(registry, route)


def test_production_branch_inherits_ledger_output_bytes_and_no_refunds(
    tmp_path, registry, monkeypatch
):
    policy = LiveRequestPolicy(
        session_id="local_test",
        endpoint=ENDPOINT,
        model=MODEL,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        max_requests=1,
        developer_requests=1,
        max_output_tokens=256,
        max_request_bytes=10_000,
        provider_spend_control_confirmed=True,
        spend_control_reference="test-only no billing",
    )
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(policy.model_dump_json(), encoding="utf-8")
    ledger_path = tmp_path / "ledger.db"
    LiveRequestLedger.initialize(ledger_path, policy)
    calls = []
    client = httpx.AsyncClient

    def route(request):
        calls.append(request.url.path)
        if request.url.path == "/api/chat":
            assert json.loads(request.content)["options"]["num_predict"] == 256
            return httpx.Response(500)
        return handler(request)

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: client(**(kwargs | {"transport": httpx.MockTransport(route)})),
    )
    model = create_model_executor(
        local_settings(
            allow_live_calls=True, live_policy_path=policy_path, live_ledger_path=ledger_path
        )
    )
    with pytest.raises(ProviderFailure, match="request limit"):
        asyncio.run(model.generate(registry.agent("investigation"), {"goal": "x" * 11_000}))
    assert not calls
    for _ in range(2):
        with pytest.raises(ProviderFailure):
            asyncio.run(model.generate(registry.agent("investigation"), {"goal": "fix"}))
    assert calls == ["/api/status", "/api/tags", "/api/show", "/api/chat"]
    assert not model.settings.live_limits_ready()


def test_disabled_local_api_cannot_silently_become_demo(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTOS_MODEL_PROVIDER", "ollama")
    monkeypatch.setenv("AGENTOS_MODEL", MODEL)
    monkeypatch.setenv("AGENTOS_MODEL_URL", ENDPOINT)
    monkeypatch.setenv("AGENTOS_ALLOW_LIVE_MODELS", "0")
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: pytest.fail("No provider calls"))
    with TestClient(create_app(db_path=tmp_path / "missions.db")) as client:
        status = client.get("/status").json()
        assert not status["provider_configured"]
        assert status["execution_mode"] != "demo"
        assert {w["role_id"] for w in status["workflows"]} == {"developer", "creator", "student"}
        assert not any(w["ready"] for w in status["workflows"])
