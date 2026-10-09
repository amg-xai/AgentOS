"""Bounded Creator planning and supported content schemas."""

from typing import Annotated, Any, Literal

from pydantic import Field

from agentos.domain.base import Definition
from agentos.domain.creator import ResearchResult, SourceText
from agentos.domain.planning import PlanBinding, PlanTask

CreatorKind = Literal["creator_research", "creator_outline", "creator_script"]


class CreatorPlanTask(PlanTask):
    bindings: tuple[PlanBinding, ...] = Field(max_length=4)


class CreatorPlan(Definition):
    rationale: str = Field(min_length=1, max_length=4000)
    constraints: tuple[Annotated[str, Field(min_length=1, max_length=1000)], ...] = Field(
        max_length=16
    )
    tasks: tuple[CreatorPlanTask, ...] = Field(min_length=2, max_length=6)


def input_schema(kind: CreatorKind, *, planned: bool = True) -> dict[str, Any]:
    research = ResearchResult.model_json_schema()
    properties: dict[str, Any] = {
        "goal": {"type": "string", "minLength": 1, "maxLength": 8000},
        "sources": {
            "type": "array",
            "minItems": 1,
            "maxItems": 8,
            "items": {"$ref": "#/$defs/SourceText"},
        },
    }
    definitions = {"SourceText": SourceText.model_json_schema()}
    required = ["goal"]
    if kind == "creator_research":
        required.append("sources")
    else:
        properties.update(
            {key: research["properties"][key] for key in ("summary", "evidence", "limitations")}
        )
        definitions.update(research["$defs"])
    if kind == "creator_script":
        properties["outline"] = {"type": "string", "minLength": 1, "maxLength": 24000}
        required.append("outline")
    if planned:
        properties["objective"] = {"type": "string", "minLength": 1, "maxLength": 2000}
        properties["constraints"] = {
            "type": "array",
            "maxItems": 16,
            "items": {"type": "string", "minLength": 1, "maxLength": 1000},
        }
        if kind == "creator_outline":
            properties["context"] = {"type": "string", "minLength": 1, "maxLength": 24000}
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": required,
        "$defs": definitions,
    }


def output_schema(kind: CreatorKind) -> dict[str, Any]:
    if kind == "creator_research":
        return ResearchResult.model_json_schema()
    key = "outline" if kind == "creator_outline" else "script"
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {key: {"type": "string", "minLength": 1, "maxLength": 24000}},
        "required": [key],
    }
