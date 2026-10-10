"""Bounded Responses API adapter. Credentials and raw failures never enter results."""

import asyncio
import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Literal, Self
from urllib.parse import urlsplit

import httpx
from jsonschema import Draft202012Validator
from pydantic import Field, SecretStr, field_validator, model_validator

from agentos.adapters.live_limits import LiveRequestLedger, LiveRequestPolicy
from agentos.domain.agents import AgentDefinition, AgentResult, ExecutionContext
from agentos.domain.base import Definition, Text


class ProviderFailure(RuntimeError):
    """Safe failure category; never includes a response body or authorization header."""


class ProviderAuthenticationFailure(ProviderFailure):
    pass


class ProviderRateLimitFailure(ProviderFailure):
    pass


class ModelSettings(Definition):
    provider: Literal["responses", "ollama"] = "responses"
    model: Text
    base_url: str = "https://api.openai.com/v1"
    api_key: SecretStr | None = Field(default=None, exclude=True, repr=False)
    timeout_seconds: float = Field(default=120, gt=0, le=300)
    max_output_tokens: int = Field(default=8192, ge=256, le=32768)
    allow_live_calls: bool = Field(default=False, strict=True)
    live_policy_path: Path | None = None
    live_ledger_path: Path | None = None
    local_context_tokens: int = Field(default=8192, strict=True, ge=4096, le=32768)

    @model_validator(mode="after")
    def local_only(self) -> Self:
        if self.provider == "ollama":
            parsed = urlsplit(self.base_url)
            if (
                parsed.scheme != "http"
                or parsed.hostname not in {"127.0.0.1", "::1"}
                or parsed.path
                or self.api_key is not None
                or len(self.model) > 160
                or not re.fullmatch(r"[a-z0-9][a-z0-9._-]*:[a-z0-9][a-z0-9._-]*", self.model)
                or "cloud" in self.model
            ):
                raise ValueError(
                    "Ollama requires a literal loopback URL, explicit local tag and no key"
                )
        return self

    def live_limits(self) -> tuple[LiveRequestPolicy, LiveRequestLedger]:
        if self.live_policy_path is None or self.live_ledger_path is None:
            raise ValueError("Explicit acceptance policy and ledger are required")
        policy = LiveRequestPolicy.model_validate_json(self.live_policy_path.read_bytes())
        policy.check(self.base_url, self.model)
        ledger = LiveRequestLedger(self.live_ledger_path, policy)
        ledger.validate()
        return policy, ledger

    def live_limits_ready(self) -> bool:
        try:
            self.live_limits()
            return True
        except (ValueError, OSError, sqlite3.Error):
            return False

    @field_validator("base_url")
    @classmethod
    def safe_endpoint(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or not parsed.hostname
            or parsed.scheme not in {"http", "https"}
            or (
                parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            )
        ):
            raise ValueError(
                "Provider endpoint requires HTTPS or loopback HTTP without credentials"
            )
        return value.rstrip("/")

    @classmethod
    def from_environment(cls) -> "ModelSettings | None":
        model = os.environ.get("AGENTOS_MODEL", "").strip()
        if not model:
            return None
        provider = os.environ.get("AGENTOS_MODEL_PROVIDER", "responses")
        if provider not in {"responses", "ollama"}:
            raise ValueError("Unknown model provider")
        endpoint = os.environ.get(
            "AGENTOS_MODEL_URL",
            "http://127.0.0.1:11434" if provider == "ollama" else "https://api.openai.com/v1",
        )
        key = (
            None
            if provider == "ollama"
            else (os.environ.get("AGENTOS_MODEL_KEY") or os.environ.get("OPENAI_API_KEY"))
        )
        if urlsplit(endpoint).hostname == "api.openai.com" and not key:
            return None
        policy_path = os.environ.get("AGENTOS_LIVE_REQUEST_POLICY")
        ledger_path = os.environ.get("AGENTOS_LIVE_REQUEST_LEDGER")
        return cls(
            provider="ollama" if provider == "ollama" else "responses",
            model=model,
            base_url=endpoint,
            api_key=SecretStr(key) if key else None,
            allow_live_calls=os.environ.get("AGENTOS_ALLOW_LIVE_MODELS") == "1",
            live_policy_path=Path(policy_path) if policy_path else None,
            live_ledger_path=Path(ledger_path) if ledger_path else None,
        )


class ResponsesExecutor:
    provider_name = "responses"
    request_path = "/responses"

    def __init__(
        self, settings: ModelSettings, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        if settings.provider != self.provider_name:
            raise ValueError("Executor does not match the selected provider")
        self.settings = settings
        self._transport = transport

    async def execute(
        self, agent: AgentDefinition, inputs: dict[str, Any], context: ExecutionContext
    ) -> AgentResult:
        return AgentResult(outputs=await self.generate(agent, inputs))

    async def generate(self, agent: AgentDefinition, inputs: dict[str, Any]) -> dict[str, Any]:
        if self._transport is None and not self.settings.allow_live_calls:
            raise ProviderFailure("Live model calls are disabled pending explicit authorization")
        try:
            return await asyncio.wait_for(
                self._generate(agent, inputs), timeout=self.settings.timeout_seconds
            )
        except TimeoutError:
            raise ProviderFailure("Provider request deadline exceeded") from None

    async def _generate(self, agent: AgentDefinition, inputs: dict[str, Any]) -> dict[str, Any]:
        policy = None
        ledger = None
        if self._transport is None:
            try:
                policy, ledger = self.settings.live_limits()
            except Exception:
                raise ProviderFailure("Live acceptance policy or ledger is unavailable") from None
        max_tokens = (
            min(self.settings.max_output_tokens, policy.max_output_tokens)
            if policy
            else self.settings.max_output_tokens
        )
        body = self.request_body(agent, inputs, max_tokens)
        encoded = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(encoded) > (policy.max_request_bytes if policy else 1_000_000):
            raise ProviderFailure("Provider input exceeds the request limit")
        headers = {"Content-Type": "application/json"}
        if self.settings.api_key:
            headers["Authorization"] = f"Bearer {self.settings.api_key.get_secret_value()}"
        try:
            if ledger is not None:
                try:
                    ledger.reserve(agent.role)
                except Exception:
                    raise ProviderFailure(
                        "Live acceptance request allowance is unavailable"
                    ) from None
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=self.settings.timeout_seconds,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                await self.preflight(client)
                result = await self.request_json(
                    client, "POST", self.request_path, content=encoded, headers=headers
                )
            outputs: Any = json.loads(
                self.result_text(result), parse_constant=self._reject_constant
            )
            Draft202012Validator(agent.output_schema).validate(outputs)
            if not isinstance(outputs, dict):
                raise ProviderFailure("Provider returned a non-object result")
            return outputs
        except ProviderFailure:
            raise
        except Exception:
            raise ProviderFailure("Provider transport or structured output failed") from None

    def request_body(
        self, agent: AgentDefinition, inputs: dict[str, Any], max_tokens: int
    ) -> dict[str, Any]:
        return {
            "model": self.settings.model,
            "store": False,
            "max_output_tokens": max_tokens,
            "instructions": agent.instructions,
            "input": json.dumps(inputs, ensure_ascii=False, allow_nan=False),
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": agent.id,
                    "strict": True,
                    "schema": agent.output_schema,
                }
            },
        }

    async def preflight(self, client: httpx.AsyncClient) -> None:
        pass

    async def request_json(
        self, client: httpx.AsyncClient, method: str, path: str, **kwargs: Any
    ) -> dict[str, Any]:
        async with client.stream(method, self.settings.base_url + path, **kwargs) as response:
            if response.status_code in {401, 403}:
                raise ProviderAuthenticationFailure("Provider authentication failed")
            if response.status_code == 429:
                raise ProviderRateLimitFailure("Provider rate limit reached")
            if response.status_code != 200:
                raise ProviderFailure("Provider request failed")
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > 2_000_000:
                    raise ProviderFailure("Provider response exceeds the response limit")
        result = json.loads(content, parse_constant=self._reject_constant)
        if not isinstance(result, dict):
            raise ProviderFailure("Provider returned a non-object envelope")
        return result

    def result_text(self, result: dict[str, Any]) -> str:
        if result.get("status") != "completed":
            raise ProviderFailure("Provider response was incomplete")
        texts = [
            part["text"]
            for item in result["output"]
            if item.get("type") == "message"
            for part in item.get("content", [])
            if part.get("type") == "output_text"
        ]
        if len(texts) != 1 or not isinstance(texts[0], str):
            raise ProviderFailure("Provider returned no single structured result")
        return texts[0]

    @staticmethod
    def _reject_constant(value: str) -> None:
        raise ValueError("Non-finite JSON values are not supported")
