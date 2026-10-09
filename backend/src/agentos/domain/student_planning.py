"""Bounded mission decomposition, distinct from the Focus study schedule artifact."""

from typing import Annotated, Any, Literal

from pydantic import Field

from agentos.domain.base import Definition
from agentos.domain.planning import PlanTask
from agentos.domain.student import StudyPlan, StudySettings, focus_input_schema, quiz_schema

StudentKind = Literal["student_notes", "student_quiz", "student_focus"]


class StudentPlan(Definition):
    rationale: str = Field(min_length=1, max_length=4000)
    constraints: tuple[Annotated[str, Field(min_length=1, max_length=1000)], ...] = Field(
        max_length=16
    )
    tasks: tuple[PlanTask, ...] = Field(min_length=2, max_length=6)


def input_schema(kind: StudentKind, *, planned: bool = True) -> dict[str, Any]:
    if kind == "student_focus":
        schema = focus_input_schema()
    else:
        properties: dict[str, Any] = {"goal": {"type": "string", "minLength": 1, "maxLength": 8000}}
        if kind == "student_quiz":
            properties["notes"] = {"type": "string", "minLength": 1, "maxLength": 24000}
        schema = {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        }
    if planned:
        properties = schema["properties"]
        properties["objective"] = {"type": "string", "minLength": 1, "maxLength": 2000}
        properties["constraints"] = {
            "type": "array",
            "maxItems": 16,
            "items": {"type": "string", "minLength": 1, "maxLength": 1000},
        }
        if kind != "student_focus":
            properties["study_settings"] = {
                "anyOf": [StudySettings.model_json_schema(), {"type": "null"}]
            }
        if kind == "student_notes":
            properties["context"] = {"type": "string", "minLength": 1, "maxLength": 24000}
    return schema


def output_schema(kind: StudentKind) -> dict[str, Any]:
    if kind == "student_focus":
        return StudyPlan.model_json_schema()
    if kind == "student_quiz":
        return quiz_schema()
    return {
        "type": "object",
        "properties": {"notes": {"type": "string", "minLength": 1, "maxLength": 24000}},
        "required": ["notes"],
        "additionalProperties": False,
    }
