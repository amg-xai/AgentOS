"""Creator graph reuses the existing mission and dependency contracts."""

import json
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaValidationError

from agentos.domain.agents import Permission
from agentos.domain.creator import ResearchResult, SourceText
from agentos.domain.missions import InputBinding, Mission, MissionCreate, StateConflict, TaskSpec
from agentos.domain.workspace import CreatorMissionCreate
from agentos.services.execution import ExecutorRegistry
from agentos.services.registry import AgentRegistry


def creator_mission(goal: str, sources: tuple[SourceText, ...] = ()) -> MissionCreate:
    context = {"sources": [source.model_dump(mode="json") for source in sources]} if sources else {}
    research_bindings = (
        {
            key: InputBinding(task_id="research", output_key=key)
            for key in ("summary", "evidence", "limitations")
        }
        if sources
        else {}
    )
    research_tasks = (
        (
            TaskSpec(
                id="research",
                title="Research the supplied sources",
                agent_id="creator_research",
                inputs={"goal": goal, **context},
            ),
        )
        if sources
        else ()
    )
    return MissionCreate(
        goal=goal,
        role_id="creator",
        workspace_id="local",
        tasks=(
            *research_tasks,
            TaskSpec(
                id="outline",
                title="Outline the supplied brief",
                agent_id="creator_outline",
                inputs={"goal": goal, **context},
                dependencies=("research",) if sources else (),
                input_bindings=research_bindings,
            ),
            TaskSpec(
                id="script",
                title="Draft the script for review",
                agent_id="creator_script",
                inputs={"goal": goal, **context},
                dependencies=("outline", "research") if sources else ("outline",),
                input_bindings={
                    "outline": InputBinding(task_id="outline", output_key="outline"),
                    **research_bindings,
                },
                review_required=True,
            ),
        ),
    )


def has_sources(mission: Mission | MissionCreate) -> bool:
    return mission.role_id == "creator" and any(
        task.agent_id == "creator_research" or task.inputs.get("sources") for task in mission.tasks
    )


def validate_source_mission(
    mission: Mission | MissionCreate, registry: AgentRegistry, executors: ExecutorRegistry
) -> None:
    """Preflight the supported graph without changing legacy brief-only workflows."""
    try:
        research = next(task for task in mission.tasks if task.id == "research")
        request = CreatorMissionCreate(goal=mission.goal, sources=research.inputs["sources"])
        expected = creator_mission(request.goal, request.sources)
        if not request.sources or mission.workspace_id != "local":
            raise ValueError("Missing source context")
        actual = tuple(
            TaskSpec.model_validate(task.model_dump(include=set(TaskSpec.model_fields)))
            for task in mission.tasks
        )
        if actual != expected.tasks:
            raise ValueError("Source workflow does not match its evidence graph")
        for task in expected.tasks:
            agent = registry.agent(task.agent_id)
            if (
                agent.role != "creator"
                or agent.id not in registry.role("creator").agents
                or agent.tools
                or set(agent.permissions) != {Permission.READ}
            ):
                raise ValueError("Unsupported source workflow permissions")
            executors.resolve(agent)
            schema = agent.input_schema
            research_schema = ResearchResult.model_json_schema()
            properties = schema.get("properties", {})
            fields = {"goal", "sources"}
            if task.id != "research":
                fields.update(("summary", "evidence", "limitations"))
            if task.id == "script":
                fields.add("outline")
            required = (
                ["goal", "sources"]
                if task.id == "research"
                else (["goal", "outline"] if task.id == "script" else ["goal"])
            )
            if (
                schema.get("type") != "object"
                or schema.get("additionalProperties") is not False
                or set(properties) != fields
                or schema.get("required") != required
                or properties["sources"]
                != {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 8,
                    "items": {"$ref": "#/$defs/SourceText"},
                }
                or schema.get("$defs", {}).get("SourceText") != SourceText.model_json_schema()
            ):
                raise ValueError("Unsupported source input contract")
            if task.id != "research" and (
                any(
                    properties[key] != research_schema["properties"][key]
                    for key in ("summary", "evidence", "limitations")
                )
                or schema.get("$defs", {}).get("EvidenceItem")
                != research_schema["$defs"]["EvidenceItem"]
            ):
                raise ValueError("Unsupported research binding contract")
            inputs = dict(task.inputs)
            if task.id != "research":
                inputs.update(
                    summary="Evidence",
                    evidence=[
                        {
                            "source_id": request.sources[0].id,
                            "quote": request.sources[0].body[:800],
                            "interpretation": "Evidence",
                        }
                    ],
                    limitations=[],
                )
            if task.id == "script":
                inputs["outline"] = "Outline"
            Draft202012Validator(agent.input_schema).validate(inputs)
            if task.id == "research":
                if agent.output_schema != ResearchResult.model_json_schema():
                    raise ValueError("Unsupported research output contract")
            else:
                key = "outline" if task.id == "outline" else "script"
                if (
                    agent.output_schema.get("additionalProperties") is not False
                    or agent.output_schema.get("required") != [key]
                    or set(agent.output_schema.get("properties", {})) != {key}
                    or agent.output_schema["properties"][key].get("type") != "string"
                    or agent.output_schema["properties"][key].get("minLength") != 1
                    or agent.output_schema["properties"][key].get("maxLength") != 24000
                ):
                    raise ValueError("Unsupported content output contract")
    except (KeyError, ValueError, StopIteration, StateConflict, SchemaValidationError):
        raise StateConflict(
            "Creator source research capabilities or evidence graph are unavailable"
        ) from None


def source_review_evidence(mission: Mission, outputs: dict[str, Any]) -> dict[str, str]:
    by_id = {task.id: task for task in mission.tasks}
    source_inputs = by_id["research"].inputs
    sources = CreatorMissionCreate(goal=mission.goal, sources=source_inputs["sources"]).sources
    research = ResearchResult.model_validate(by_id["research"].outputs)
    research.verify(sources)
    outline = (by_id["outline"].outputs or {}).get("outline")
    script = outputs.get("script")
    if not isinstance(outline, str) or not isinstance(script, str):
        raise StateConflict("Creator review is missing its content evidence")
    return {
        "script.md": script,
        "reviewed-outline.md": outline,
        "reviewed-research.json": research.model_dump_json(indent=2),
        "reviewed-sources.json": json.dumps(
            [source.model_dump(mode="json") for source in sources], ensure_ascii=False, indent=2
        ),
    }
