import asyncio
import json
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from agentos.adapters.manifests import load_registry
from agentos.adapters.provider import (
    ModelSettings,
    ProviderAuthenticationFailure,
    ProviderFailure,
    ProviderRateLimitFailure,
    ResponsesExecutor,
)


def generate(handler):
    executor = ResponsesExecutor(
        ModelSettings(model="configured-model", api_key=SecretStr("private-key")),
        transport=httpx.MockTransport(handler),
    )
    return asyncio.run(
        executor.generate(load_registry(Path("packages")).agent("investigation"), {"goal": "fix"})
    )


def response(text='{"findings":"Evidence"}', status="completed"):
    return httpx.Response(
        200,
        json={
            "status": status,
            "output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}],
        },
    )


def test_responses_contract_and_secret_exclusion():
    def handler(request):
        assert request.url == "https://api.openai.com/v1/responses"
        assert request.headers["authorization"] == "Bearer private-key"
        body = json.loads(request.content)
        assert body["store"] is False
        assert body["text"]["format"]["strict"] is True
        assert body["text"]["format"]["schema"]["additionalProperties"] is False
        return response()

    assert generate(handler) == {"findings": "Evidence"}
    settings = ModelSettings(model="model", api_key=SecretStr("private-key"))
    assert "private-key" not in repr(settings) + settings.model_dump_json()


@pytest.mark.parametrize(
    "reply,category",
    [
        (httpx.Response(401, text="private-key"), ProviderAuthenticationFailure),
        (httpx.Response(429, text="private-key"), ProviderRateLimitFailure),
        (httpx.Response(307, headers={"location": "https://evil.example"}), ProviderFailure),
        (response(status="incomplete"), ProviderFailure),
        (response('{"wrong":true}'), ProviderFailure),
        (response('{"findings":NaN}'), ProviderFailure),
        (httpx.Response(200, content=b"x" * 2_000_001), ProviderFailure),
    ],
)
def test_rejects_failures_without_exposing_raw_data(reply, category):
    with pytest.raises(category) as failure:
        generate(lambda _: reply)
    assert "private-key" not in str(failure.value)


@pytest.mark.parametrize("url", ["http://remote.example/v1", "https://key@host/v1", "file:///x"])
def test_rejects_unsafe_endpoints(url):
    with pytest.raises(ValidationError):
        ModelSettings(model="model", base_url=url)


def test_configuration_is_explicit(monkeypatch):
    for key in ("AGENTOS_MODEL", "AGENTOS_MODEL_KEY", "OPENAI_API_KEY", "AGENTOS_MODEL_URL"):
        monkeypatch.delenv(key, raising=False)
    assert ModelSettings.from_environment() is None
    monkeypatch.setenv("AGENTOS_MODEL", "configured-model")
    assert ModelSettings.from_environment() is None
    monkeypatch.setenv("AGENTOS_MODEL_URL", "http://127.0.0.1:11434/v1")
    assert ModelSettings.from_environment().model == "configured-model"
