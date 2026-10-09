"""Bounded study effort and review evidence; content suitability needs human review."""

from typing import Annotated, Any, Literal, cast

from pydantic import ConfigDict, Field, field_validator

from agentos.domain.base import Definition


class StudyPlanningError(ValueError):
    """Fixed messages suitable for audit history; never include model text."""

    def __init__(self, code: Literal["blank", "session", "budget", "coverage"]) -> None:
        self.code = code
        super().__init__(self.safe_message)

    @property
    def safe_message(self) -> str:
        return {
            "blank": "Study plan text must not be blank",
            "session": "Study block exceeds the maximum session length",
            "budget": "Study plan exceeds the available time budget",
            "coverage": "Study plan must reference all and only the supplied questions",
        }.get(self.code, "Study plan violates its bounded output contract")


class StudySettings(Definition):
    total_minutes: int = Field(strict=True, ge=10, le=240)
    max_session_minutes: int = Field(strict=True, ge=10, le=60)


class Question(Definition):
    model_config = ConfigDict(str_strip_whitespace=False)
    prompt: str = Field(min_length=1, max_length=600)
    choices: tuple[Annotated[str, Field(min_length=1, max_length=240)], ...] = Field(
        min_length=4, max_length=4
    )
    answer_index: int = Field(strict=True, ge=0, le=3)
    explanation: str = Field(min_length=1, max_length=1000)

    @field_validator("prompt", "explanation")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Question text must not be blank")
        return value

    @field_validator("choices")
    @classmethod
    def nonblank_choices(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value.strip() for value in values):
            raise ValueError("Choices must not be blank")
        return values


class Quiz(Definition):
    questions: tuple[Question, ...] = Field(min_length=3, max_length=8)


class StudyBlock(Definition):
    model_config = ConfigDict(str_strip_whitespace=False)
    activity: Literal["review_notes", "practice_quiz", "recall"]
    objective: str = Field(min_length=1, max_length=500)
    minutes: int = Field(strict=True, ge=5, le=60)
    question_refs: tuple[Annotated[int, Field(strict=True, ge=1, le=8)], ...] = Field(
        min_length=1, max_length=8
    )

    @field_validator("objective")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Study objective must not be blank")
        return value

    @field_validator("question_refs")
    @classmethod
    def unique_refs(cls, values: tuple[int, ...]) -> tuple[int, ...]:
        if len(set(values)) != len(values):
            raise ValueError("Question references must be unique within a block")
        return values


class StudyPlan(Definition):
    model_config = ConfigDict(str_strip_whitespace=False)
    summary: str = Field(min_length=1, max_length=1000)
    blocks: tuple[StudyBlock, ...] = Field(min_length=1, max_length=12)
    limitations: tuple[Annotated[str, Field(min_length=1, max_length=500)], ...] = Field(
        max_length=8
    )

    def verify(self, settings: StudySettings, quiz: Quiz) -> None:
        if not self.summary.strip() or any(not text.strip() for text in self.limitations):
            raise StudyPlanningError("blank")
        if any(block.minutes > settings.max_session_minutes for block in self.blocks):
            raise StudyPlanningError("session")
        if sum(block.minutes for block in self.blocks) > settings.total_minutes:
            raise StudyPlanningError("budget")
        covered = {number for block in self.blocks for number in block.question_refs}
        if covered != set(range(1, len(quiz.questions) + 1)):
            raise StudyPlanningError("coverage")


def render_quiz(questions: list[dict[str, Any]], *, provenance: str = "") -> tuple[str, str]:
    quiz = [
        provenance + "# Study quiz\n\nQuestions only. See answer-key.md after attempting them.\n"
    ]
    key = [provenance + "# Answer key\n\nReview these answers against your supplied material.\n"]
    for number, question in enumerate(questions, start=1):
        quiz.append(f"\n## {number}. {question['prompt']}\n")
        for index, choice in enumerate(question["choices"]):
            quiz.append(f"{chr(65 + index)}. {choice}\n")
        answer = question["answer_index"]
        key.append(
            f"\n## {number}. {chr(65 + answer)} — {question['choices'][answer]}\n\n"
            f"{question['explanation']}\n"
        )
    return "".join(quiz), "".join(key)


def study_evidence(
    settings: StudySettings, notes: str, questions: Any, outputs: dict[str, Any]
) -> dict[str, str]:
    if not isinstance(notes, str) or not notes.strip() or len(notes) > 24000:
        raise ValueError("Study review requires bounded nonblank notes")
    quiz = Quiz(questions=questions)
    plan = StudyPlan.model_validate(outputs)
    plan.verify(settings, quiz)
    quiz_text, key = render_quiz([question.model_dump(mode="json") for question in quiz.questions])
    allocated = sum(block.minutes for block in plan.blocks)
    readable = [
        "# Study plan\n\n",
        plan.summary,
        f"\n\nAvailable: {settings.total_minutes} minutes. "
        f"Maximum session: {settings.max_session_minutes} minutes. "
        f"Proposed allocation: {allocated} minutes.\n\n",
        "Suggested effort only; no timer, scheduling, scoring, or exam-readiness verification.\n",
    ]
    for number, block in enumerate(plan.blocks, 1):
        readable.append(
            f"\n## {number}. {block.activity.replace('_', ' ')} — {block.minutes} minutes\n\n"
            f"{block.objective}\n\nQuiz references: {', '.join(map(str, block.question_refs))}.\n"
        )
    readable.append("\n## Limitations\n\n")
    readable.extend(f"- {text}\n" for text in plan.limitations)
    if not plan.limitations:
        readable.append(
            "No additional limitations supplied; review content suitability yourself.\n"
        )
    return {
        "study-plan.md": "".join(readable),
        "study-plan.json": plan.model_dump_json(indent=2),
        "reviewed-study-settings.json": settings.model_dump_json(indent=2),
        "reviewed-notes.md": notes,
        "quiz.md": quiz_text,
        "answer-key.md": key,
    }


def quiz_schema() -> dict[str, Any]:
    """Keep the existing inline quiz contract stable while validating with value types."""
    schema = Quiz.model_json_schema()
    schema["properties"]["questions"]["items"] = schema.pop("$defs")["Question"]

    def without_titles(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: without_titles(item) for key, item in value.items() if key != "title"}
        if isinstance(value, list):
            return [without_titles(item) for item in value]
        return value

    return cast(dict[str, Any], without_titles(schema))


def focus_input_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "goal": {"type": "string", "minLength": 1, "maxLength": 8000},
            "notes": {"type": "string", "minLength": 1, "maxLength": 24000},
            "questions": quiz_schema()["properties"]["questions"],
            "study_settings": StudySettings.model_json_schema(),
        },
        "required": ["goal", "study_settings", "notes", "questions"],
    }
