"""Sourced Student contracts; references establish provenance, not factual correctness."""

from copy import deepcopy
from functools import cache
from typing import Annotated, Any

from pydantic import Field, field_validator

from agentos.domain.base import Definition
from agentos.domain.planning import PlanBinding, PlanTask
from agentos.domain.sources import ResearchResult, SourceText
from agentos.domain.student import Question, StudyPlan, StudySettings
from agentos.domain.student_planning import StudentPlan

Ref = Annotated[int, Field(strict=True, ge=1, le=8)]
Refs = Annotated[tuple[Ref, ...], Field(min_length=1, max_length=8)]
KINDS = frozenset(
    {
        "student_research",
        "student_summary",
        "student_source_notes",
        "student_source_quiz",
        "student_source_focus",
    }
)


class StudentSourceTask(PlanTask):
    bindings: tuple[PlanBinding, ...] = Field(max_length=6)


class StudentSourcePlan(StudentPlan):
    tasks: tuple[StudentSourceTask, ...] = Field(min_length=4, max_length=8)


class SummaryTopic(Definition):
    text: str = Field(min_length=1, max_length=2000)
    evidence_refs: Refs

    @field_validator("text")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Summary text must not be blank")
        return value


class StudySummary(Definition):
    topics: tuple[SummaryTopic, ...] = Field(min_length=1, max_length=8)
    limitations: tuple[Annotated[str, Field(min_length=1, max_length=500)], ...] = Field(
        max_length=8
    )

    def verify(self, research: ResearchResult) -> None:
        for topic in self.topics:
            verify_refs(topic.evidence_refs, len(research.evidence))
        if any(not value.strip() for value in self.limitations):
            raise ValueError("Summary limitations must not be blank")


class SourcedNotes(Definition):
    notes: str = Field(min_length=1, max_length=24000)
    summary_refs: Refs


class SourcedQuiz(Definition):
    questions: tuple[Question, ...] = Field(min_length=3, max_length=8)
    question_refs: tuple[Refs, ...] = Field(min_length=3, max_length=8)


def verify_refs(refs: tuple[int, ...], count: int) -> None:
    if len(set(refs)) != len(refs) or any(ref > count for ref in refs):
        raise ValueError("Evidence reference is duplicated or outside its bound evidence")


@cache
def _inline_schema(model: type[Definition]) -> dict[str, Any]:
    """Embed bounded schemas without relocating $ref resolution into a parent schema."""
    schema = model.model_json_schema()
    definitions = schema.pop("$defs", {})

    def expand(value: Any) -> Any:
        if isinstance(value, dict):
            if "$ref" in value:
                return expand(deepcopy(definitions[value["$ref"].split("/")[-1]]))
            return {key: expand(item) for key, item in value.items()}
        if isinstance(value, list):
            return [expand(item) for item in value]
        return value

    return dict(expand(schema))


def inline_schema(model: type[Definition]) -> dict[str, Any]:
    return deepcopy(_inline_schema(model))


@cache
def _source_output_schema(kind: str) -> dict[str, Any]:
    if kind in {"student_research", "student_summary"}:
        key, model = (
            ("research", ResearchResult)
            if kind == "student_research"
            else ("study_summary", StudySummary)
        )
        return {
            "type": "object",
            "properties": {key: inline_schema(model)},
            "required": [key],
            "additionalProperties": False,
        }
    return inline_schema(
        SourcedNotes
        if kind == "student_source_notes"
        else SourcedQuiz
        if kind == "student_source_quiz"
        else StudyPlan
    )


def source_output_schema(kind: str) -> dict[str, Any]:
    return deepcopy(_source_output_schema(kind))


@cache
def _source_input_schema(kind: str) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "goal": {"type": "string", "minLength": 1, "maxLength": 8000},
        "objective": {"type": "string", "minLength": 1, "maxLength": 2000},
        "constraints": {
            "type": "array",
            "maxItems": 16,
            "items": {"type": "string", "minLength": 1, "maxLength": 1000},
        },
        "study_settings": {"anyOf": [inline_schema(StudySettings), {"type": "null"}]},
        "sources": {
            "type": "array",
            "minItems": 1,
            "maxItems": 8,
            "items": inline_schema(SourceText),
        },
    }
    if kind != "student_research":
        properties["research"] = source_output_schema("student_research")["properties"]["research"]
    if kind not in {"student_research", "student_summary"}:
        properties["study_summary"] = source_output_schema("student_summary")["properties"][
            "study_summary"
        ]
    if kind in {"student_source_quiz", "student_source_focus"}:
        properties.update(source_output_schema("student_source_notes")["properties"])
    if kind == "student_source_focus":
        properties.update(source_output_schema("student_source_quiz")["properties"])
    required = list(properties)
    if kind == "student_source_notes":
        properties["context"] = source_output_schema(kind)["properties"]["notes"]
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def source_input_schema(kind: str) -> dict[str, Any]:
    return deepcopy(_source_input_schema(kind))


@cache
def _source_planner_input_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "goal": {"type": "string", "minLength": 1, "maxLength": 8000},
            "agents": {"type": "array", "maxItems": 64, "items": {"type": "object"}},
            "study_settings": {"anyOf": [inline_schema(StudySettings), {"type": "null"}]},
            "sources": {
                "type": "array",
                "minItems": 1,
                "maxItems": 8,
                "items": {
                    "type": "object",
                    "properties": {
                        "id": SourceText.model_json_schema()["properties"]["id"],
                        "label": SourceText.model_json_schema()["properties"]["label"],
                    },
                    "required": ["id", "label"],
                    "additionalProperties": False,
                },
            },
            "boundaries": {"type": "string", "minLength": 1, "maxLength": 4000},
        },
        "required": ["goal", "agents", "study_settings", "sources", "boundaries"],
    }


def source_planner_input_schema() -> dict[str, Any]:
    return deepcopy(_source_planner_input_schema())
