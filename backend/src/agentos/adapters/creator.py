"""Content-only Creator adapter; no project-file, memory, shell or publishing access."""

import json
from typing import Any

from jsonschema import Draft202012Validator

from agentos.adapters.demo import DEMO_LABEL
from agentos.domain.agents import (
    AgentDefinition,
    AgentResult,
    ExecutionContext,
    StructuredGenerator,
)
from agentos.domain.artifacts import ArtifactDraft
from agentos.domain.creator import ResearchResult
from agentos.domain.missions import StateConflict
from agentos.domain.workspace import CreatorMissionCreate

CREATOR_DEMO_GOAL = (
    "Create a short introductory video script explaining AgentOS's bundled Calculator "
    "investigation, scratch fix, actual tests, and human review. Do not claim live AI verification."
)
CREATOR_DEMO_OUTLINE = (
    f"{DEMO_LABEL}\n\n# Video outline\n"
    "1. Introduce AgentOS as a local workspace for dependency-linked missions.\n"
    "2. Explain the Calculator bug: addition subtracts instead.\n"
    "3. Show a proposed patch and actual tests in a scratch copy.\n"
    "4. Inspect evidence, then accept or deny the result.\n"
    "5. Distinguish scripted demo behavior from unverified live model behavior.\n"
)


class CreatorDemoGenerator:
    async def generate(self, agent: AgentDefinition, inputs: dict[str, Any]) -> dict[str, Any]:
        if inputs["goal"] != CREATOR_DEMO_GOAL:
            raise StateConflict("Offline Creator demo supports only its fixed brief")
        if agent.id == "creator_outline":
            return {"outline": CREATOR_DEMO_OUTLINE}
        if agent.id == "creator_script" and inputs["outline"] == CREATOR_DEMO_OUTLINE:
            return {
                "script": f"{DEMO_LABEL}\n\n# AgentOS walkthrough script\n\n"
                "[Opening] A goal becomes a mission, with tasks and evidence you can inspect.\n\n"
                "[Calculator] The bundled sample subtracts where it should add. The Developer "
                "demo uses scripted findings and a scripted patch. Git checks and the three "
                "Calculator tests actually run in scratch; the source sample stays unchanged.\n\n"
                "[Review] Read the tested patch and report. Accept or deny the staged result. "
                "Acceptance records the result; it does not apply or publish the patch.\n\n"
                "[Closing] History, artifacts, and notes persist locally. This Creator script "
                "is also a fixture. No model calls, research, images, or video production "
                "occur here, and live AI verification remains outstanding.\n"
            }
        raise StateConflict("Offline Creator inputs do not match the fixed scenario")


class CreatorExecutor:
    def __init__(self, generator: StructuredGenerator, *, demo: bool = False) -> None:
        self.generator = generator
        self.demo = demo

    async def execute(
        self, agent: AgentDefinition, inputs: dict[str, Any], context: ExecutionContext
    ) -> AgentResult:
        from agentos.services.creator_planning import creator_kind

        kind = creator_kind(agent, legacy=True)
        sources = CreatorMissionCreate(
            goal=inputs["goal"], sources=inputs.get("sources", ())
        ).sources
        research = None
        if sources and kind != "creator_research":
            research = ResearchResult.model_validate(
                {key: inputs[key] for key in ("summary", "evidence", "limitations")}
            )
            research.verify(sources)
        # Do not enrich with source files or unrelated workspace notes.
        outputs = await self.generator.generate(agent, inputs)
        Draft202012Validator(agent.output_schema).validate(outputs)
        if kind == "creator_research":
            result = ResearchResult.model_validate(outputs)
            result.verify(sources)
            return AgentResult(
                outputs=outputs,
                artifacts=(
                    ArtifactDraft(
                        name="research.json",
                        content=result.model_dump_json(indent=2),
                    ),
                ),
            )
        artifacts: tuple[ArtifactDraft, ...] = (
            (
                ArtifactDraft(
                    name="outline.md", media_type="text/markdown", content=outputs["outline"]
                ),
            )
            if kind == "creator_outline"
            else (
                ArtifactDraft(
                    name="script.md", media_type="text/markdown", content=outputs["script"]
                ),
                ArtifactDraft(
                    name="reviewed-outline.md",
                    media_type="text/markdown",
                    content=inputs["outline"],
                ),
            )
        )
        if sources and kind == "creator_script":
            assert research is not None
            artifacts += (
                ArtifactDraft(
                    name="reviewed-research.json", content=research.model_dump_json(indent=2)
                ),
                ArtifactDraft(
                    name="reviewed-sources.json",
                    content=json.dumps(
                        [source.model_dump(mode="json") for source in sources],
                        ensure_ascii=False,
                        indent=2,
                    ),
                ),
            )
        if self.demo:
            artifacts += (
                ArtifactDraft(
                    name="offline-demo.txt",
                    content=f"{DEMO_LABEL}\n"
                    "Creator outline and script are fixtures. No research, tests, media "
                    "production, or publication was performed for this content mission.\n",
                ),
            )
        return AgentResult(outputs=outputs, artifacts=artifacts)
