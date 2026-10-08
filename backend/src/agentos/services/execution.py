"""Validate agent IO around an injected executor; no tools are dispatched here."""

from typing import Any

from jsonschema import Draft202012Validator

from agentos.domain.agents import AgentExecutor, AgentResult, ExecutionContext
from agentos.services.registry import AgentRegistry


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
