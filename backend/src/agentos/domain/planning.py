"""Shared bounded planning primitives; workflows define their own limits."""

from pydantic import Field

from agentos.domain.base import Definition, Identifier


class PlanBinding(Definition):
    input_key: Identifier
    task_id: Identifier
    output_key: Identifier


class PlanTask(Definition):
    id: Identifier
    title: str = Field(min_length=1, max_length=160)
    agent_id: Identifier
    objective: str = Field(min_length=1, max_length=2000)
    dependencies: tuple[Identifier, ...] = Field(max_length=8)
    bindings: tuple[PlanBinding, ...] = Field(max_length=3)
    review_required: bool = Field(strict=True)
