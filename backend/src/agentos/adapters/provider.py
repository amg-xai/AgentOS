"""Bounded Responses API adapter. Credentials and raw failures never enter results."""

import asyncio
import json
import os
from typing import Any
from urllib.parse import urlsplit

import httpx
from jsonschema import Draft202012Validator
from pydantic import Field, SecretStr, field_validator

from agentos.domain.agents import AgentDefinition, AgentResult, ExecutionContext
from agentos.domain.base import Definition, Text


class ProviderFailure(RuntimeError):
    """Safe failure category; never includes a response body or authorization header."""


class ProviderAuthenticationFailure(ProviderFailure):
    pass


class ProviderRateLimitFailure(ProviderFailure):
    pass


class ModelSettings(Definition):
    model: Text
    base_url: str = "https://api.openai.com/v1"
    api_key: SecretStr | None = Field(default=None, exclude=True, repr=False)
    timeout_seconds: float = Field(default=120, gt=0, le=300)
    max_output_tokens: int = Field(default=8192, ge=256, le=32768)

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
        endpoint = os.environ.get("AGENTOS_MODEL_URL", "https://api.openai.com/v1")
        key = os.environ.get("AGENTOS_MODEL_KEY") or os.environ.get("OPENAI_API_KEY")
        if urlsplit(endpoint).hostname == "api.openai.com" and not key:
            return None
        return cls(model=model, base_url=endpoint, api_key=SecretStr(key) if key else None)


class ResponsesExecutor:
    def __init__(
        self, settings: ModelSettings, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self.settings = settings
        self._transport = transport

    async def execute(
        self, agent: AgentDefinition, inputs: dict[str, Any], context: ExecutionContext
    ) -> AgentResult:
        return AgentResult(outputs=await self.generate(agent, inputs))

    async def generate(self, agent: AgentDefinition, inputs: dict[str, Any]) -> dict[str, Any]:
        try:
            return await asyncio.wait_for(
                self._generate(agent, inputs), timeout=self.settings.timeout_seconds
            )
        except TimeoutError:
            raise ProviderFailure("Provider request deadline exceeded") from None

    async def _generate(self, agent: AgentDefinition, inputs: dict[str, Any]) -> dict[str, Any]:
        body = {
            "model": self.settings.model,
            "store": False,
            "max_output_tokens": self.settings.max_output_tokens,
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
        encoded = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(encoded) > 1_000_000:
            raise ProviderFailure("Provider input exceeds the request limit")
        headers = {"Content-Type": "application/json"}
        if self.settings.api_key:
            headers["Authorization"] = f"Bearer {self.settings.api_key.get_secret_value()}"
        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=self.settings.timeout_seconds,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                async with client.stream(
                    "POST", f"{self.settings.base_url}/responses", content=encoded, headers=headers
                ) as response:
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
            result = json.loads(content)
            if result.get("status") != "completed":
                raise ProviderFailure("Provider response was incomplete")
            texts = [
                part["text"]
                for item in result["output"]
                if item.get("type") == "message"
                for part in item.get("content", [])
                if part.get("type") == "output_text"
            ]
            if len(texts) != 1:
                raise ProviderFailure("Provider returned no single structured result")
            outputs: Any = json.loads(texts[0], parse_constant=self._reject_constant)
            Draft202012Validator(agent.output_schema).validate(outputs)
            if not isinstance(outputs, dict):
                raise ProviderFailure("Provider returned a non-object result")
            return outputs
        except ProviderFailure:
            raise
        except Exception:
            raise ProviderFailure("Provider transport or structured output failed") from None

    @staticmethod
    def _reject_constant(value: str) -> None:
        raise ValueError("Non-finite JSON values are not supported")
