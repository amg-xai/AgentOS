"""Validate agent IO around an injected executor; no tools are dispatched here."""

from typing import Any

from jsonschema import Draft202012Validator

from agentos.domain.agents import AgentDefinition, AgentExecutor, AgentResult, ExecutionContext
from agentos.domain.missions import StateConflict
from agentos.services.registry import AgentRegistry


class ExecutorRegistry:
    """Explicit bindings only; no built-in fixture or implicit provider execution."""

    def __init__(self) -> None:
        self._agents: dict[str, AgentExecutor] = {}
        self._providers: dict[str, AgentExecutor] = {}

    def register_agent(self, agent_id: str, executor: AgentExecutor) -> None:
        if agent_id in self._agents:
            raise ValueError(f"Duplicate executor: {agent_id}")
        self._agents[agent_id] = executor

    def register_provider(self, provider_id: str, executor: AgentExecutor) -> None:
        if provider_id in self._providers:
            raise ValueError(f"Duplicate provider: {provider_id}")
        self._providers[provider_id] = executor

    def resolve(self, agent: AgentDefinition) -> AgentExecutor:
        if agent.id in self._agents:
            return self._agents[agent.id]
        if agent.provider and agent.provider.provider in self._providers:
            return self._providers[agent.provider.provider]
        raise StateConflict(f"No executor configured for agent {agent.id}")


async def execute_agent(
    registry: AgentRegistry,
    agent_id: str,
    executor: AgentExecutor,
    inputs: dict[str, Any],
    context: ExecutionContext,
) -> AgentResult:
    agent = registry.agent(agent_id)
    Draft202012Validator(agent.input_schema).validate(inputs)
    result = await executor.execute(agent, inputs, context)
    result = AgentResult.model_validate(result)
    Draft202012Validator(agent.output_schema).validate(result.outputs)
    return result
