"""Permission checks around registered tools. High-impact dispatch stays disabled."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from jsonschema import Draft202012Validator

from agentos.domain.agents import AgentDefinition, ExecutionContext, Permission
from agentos.domain.governance import PermissionDenied, UserRole
from agentos.domain.tools import ToolCallEvent, ToolDefinition, ToolExecutor


class ToolRegistry:
    def __init__(self, audit: Callable[[ToolCallEvent], None]) -> None:
        self._tools: dict[str, tuple[ToolDefinition, ToolExecutor]] = {}
        self._audit = audit

    def register(self, definition: ToolDefinition, executor: ToolExecutor) -> None:
        if definition.id in self._tools:
            raise ValueError(f"Duplicate tool: {definition.id}")
        self._tools[definition.id] = (definition.model_copy(deep=True), executor)

    async def execute(
        self,
        tool_id: str,
        agent: AgentDefinition,
        role: UserRole,
        inputs: dict[str, Any],
        context: ExecutionContext,
    ) -> dict[str, Any]:
        try:
            return await self._execute(tool_id, agent, role, inputs, context)
        except Exception as exc:
            self._audit(
                ToolCallEvent(
                    timestamp=datetime.now(UTC),
                    context=context,
                    tool_id=tool_id,
                    role=role,
                    outcome="denied" if isinstance(exc, PermissionDenied) else "failed",
                )
            )
            raise

    async def _execute(
        self,
        tool_id: str,
        agent: AgentDefinition,
        role: UserRole,
        inputs: dict[str, Any],
        context: ExecutionContext,
    ) -> dict[str, Any]:
        if tool_id not in self._tools:
            raise ValueError(f"Unknown tool: {tool_id}")
        definition, executor = self._tools[tool_id]
        allowed = {
            UserRole.VIEWER: {Permission.READ},
            UserRole.OPERATOR: {Permission.READ, Permission.WRITE, Permission.EXECUTE},
            UserRole.ADMIN: set(Permission),
        }[role]
        needed = set(definition.permissions)
        if (
            tool_id not in agent.tools
            or not needed <= set(agent.permissions)
            or not needed <= allowed
        ):
            raise PermissionDenied("Tool is outside the user or agent's permitted capabilities")
        if definition.high_impact or Permission.DESTRUCTIVE in needed:
            raise PermissionDenied(
                "High-impact tool dispatch requires a dedicated action approval; it is not enabled"
            )
        Draft202012Validator(definition.input_schema).validate(inputs)
        self._audit(
            ToolCallEvent(
                timestamp=datetime.now(UTC),
                context=context,
                tool_id=tool_id,
                role=role,
                outcome="started",
            )
        )
        output = await executor.execute(inputs, context)
        Draft202012Validator(definition.output_schema).validate(output)
        self._audit(
            ToolCallEvent(
                timestamp=datetime.now(UTC),
                context=context,
                tool_id=tool_id,
                role=role,
                outcome="completed",
            )
        )
        return output
