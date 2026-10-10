"""Tool-free sourced Student execution through the existing structured generator."""

from typing import Any

from jsonschema import Draft202012Validator

from agentos.domain.agents import (
    AgentDefinition,
    AgentResult,
    ExecutionContext,
    StructuredGenerator,
)
from agentos.domain.artifacts import ArtifactDraft
from agentos.domain.missions import StateConflict
from agentos.services.student_sources import source_artifacts, source_kind


class StudentSourceExecutor:
    def __init__(self, generator: StructuredGenerator) -> None:
        self.generator = generator

    async def execute(
        self, agent: AgentDefinition, inputs: dict[str, Any], context: ExecutionContext
    ) -> AgentResult:
        if context.planning_version != 2 or context.workspace_id != "local":
            raise StateConflict("Sourced Student execution requires its validated v2 context")
        kind = source_kind(agent)
        outputs = await self.generator.generate(agent, inputs)
        Draft202012Validator(agent.output_schema).validate(outputs)
        evidence = source_artifacts(kind, inputs, outputs)
        return AgentResult(
            outputs=outputs,
            artifacts=tuple(
                ArtifactDraft(
                    name=name,
                    content=content,
                    media_type="text/markdown" if name.endswith(".md") else "text/plain",
                )
                for name, content in evidence.items()
            ),
        )
