"""Generic tool contracts; integrations live outside the domain."""

from datetime import datetime
from typing import Any, Literal, Protocol

from pydantic import Field, field_validator

from agentos.domain.agents import ExecutionContext, Permission, validate_schema
from agentos.domain.base import Definition, Identifier, Text
from agentos.domain.governance import UserRole


class ToolDefinition(Definition):
    id: Identifier
    description: Text
    permissions: tuple[Permission, ...] = Field(min_length=1)
    high_impact: bool = False
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]

    _schemas = field_validator("input_schema", "output_schema")(validate_schema)


class ToolExecutor(Protocol):
    async def execute(
        self, inputs: dict[str, Any], context: ExecutionContext
    ) -> dict[str, Any]: ...


class ToolCallEvent(Definition):
    timestamp: datetime
    context: ExecutionContext
    tool_id: Identifier
    role: UserRole
    outcome: Literal["started", "completed", "denied", "failed"]
