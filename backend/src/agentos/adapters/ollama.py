"""Local-only Ollama wire adapter; inherits the disabled gate and durable limits."""

import json
import re
from typing import Any

import httpx

from agentos.adapters.provider import ModelSettings, ProviderFailure, ResponsesExecutor
from agentos.domain.agents import AgentDefinition


class OllamaExecutor(ResponsesExecutor):
    provider_name = "ollama"
    request_path = "/api/chat"

    async def preflight(self, client: httpx.AsyncClient) -> None:
        status = await self.request_json(client, "GET", "/api/status")
        if not isinstance(status.get("cloud"), dict) or status["cloud"].get("disabled") is not True:
            raise ProviderFailure(
                "Ollama cloud must be disabled and verifiable before local inference"
            )
        tags = await self.request_json(client, "GET", "/api/tags")
        matches = [m for m in tags.get("models", []) if m.get("name") == self.settings.model]
        if len(matches) != 1:
            raise ProviderFailure(
                "Selected local model is not uniquely installed; no automatic download"
            )
        model = matches[0]
        if (
            type(model.get("size")) is not int
            or model["size"] <= 0
            or not isinstance(model.get("digest"), str)
            or not re.fullmatch(r"[a-f0-9]{64}", model["digest"])
        ):
            raise ProviderFailure("Local model metadata is invalid")
        details = await self.request_json(
            client, "POST", "/api/show", json={"model": self.settings.model}
        )
        capabilities = details.get("capabilities")
        if (
            any(details.get(k) not in (None, "") for k in ("remote_host", "remote_model"))
            or not isinstance(capabilities, list)
            or "completion" not in capabilities
            or not isinstance(details.get("model_info"), dict)
            or not details["model_info"]
        ):
            raise ProviderFailure(
                "Local completion model required; remote or unsupported model rejected"
            )

    def request_body(
        self, agent: AgentDefinition, inputs: dict[str, Any], max_tokens: int
    ) -> dict[str, Any]:
        return {
            "model": self.settings.model,
            "messages": [
                {"role": "system", "content": agent.instructions},
                {
                    "role": "user",
                    "content": json.dumps(inputs, ensure_ascii=False, allow_nan=False),
                },
            ],
            "format": agent.output_schema,
            "stream": False,
            "think": False,
            "truncate": False,
            "shift": False,
            "keep_alive": 0,
            "options": {
                "temperature": 0,
                "num_predict": max_tokens,
                "num_ctx": self.settings.local_context_tokens,
            },
        }

    def result_text(self, result: dict[str, Any]) -> str:
        message = result.get("message", {})
        if (
            result.get("done") is not True
            or result.get("done_reason") != "stop"
            or result.get("model") != self.settings.model
            or result.get("error")
            or any(result.get(k) not in (None, "") for k in ("remote_host", "remote_model"))
            or not isinstance(message, dict)
            or message.get("role") != "assistant"
            or message.get("tool_calls")
            or not isinstance(message.get("content"), str)
        ):
            raise ProviderFailure("Ollama returned no completed local structured result")
        return str(message["content"])


def create_model_executor(
    settings: ModelSettings, *, transport: httpx.AsyncBaseTransport | None = None
) -> ResponsesExecutor:
    """Explicit selection; availability failure never changes the provider or execution mode."""
    executor = OllamaExecutor if settings.provider == "ollama" else ResponsesExecutor
    return executor(settings, transport=transport)
