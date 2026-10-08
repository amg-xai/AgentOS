"""Tool-free study generation and separate question/answer artifacts."""

from copy import deepcopy
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
from agentos.domain.missions import StateConflict

STUDENT_DEMO_GOAL = (
    "Prepare study notes and a three-question quiz using only these facts: "
    "A stack removes the most recently added item first (LIFO). "
    "A queue removes the earliest added item first (FIFO). "
    "Push adds to a stack; pop removes from a stack. "
    "Enqueue adds to a queue; dequeue removes from a queue."
)
STUDENT_DEMO_NOTES = (
    f"{DEMO_LABEL}\n\n# Stacks and queues\n\n"
    "- Stack: last in, first out (LIFO). Push adds; pop removes.\n"
    "- Queue: first in, first out (FIFO). Enqueue adds; dequeue removes.\n"
    "- Compare removal order: newest first for stacks, earliest first for queues.\n\n"
    "These notes summarize the supplied facts; no independent research was performed.\n"
)
STUDENT_DEMO_QUESTIONS: list[dict[str, Any]] = [
    {
        "prompt": "Which item does a stack remove first?",
        "choices": ["Most recently added", "Earliest added", "Smallest value", "Largest value"],
        "answer_index": 0,
        "explanation": "A stack follows LIFO: the most recently added item is removed first.",
    },
    {
        "prompt": "Which order describes a queue?",
        "choices": ["LIFO", "FIFO", "Sorted by value", "Random removal"],
        "answer_index": 1,
        "explanation": "A queue follows FIFO: the earliest added item is removed first.",
    },
    {
        "prompt": "Which operation removes an item from a queue?",
        "choices": ["Push", "Pop", "Enqueue", "Dequeue"],
        "answer_index": 3,
        "explanation": "Dequeue removes from a queue; enqueue adds to it.",
    },
]


class StudentDemoGenerator:
    async def generate(self, agent: AgentDefinition, inputs: dict[str, Any]) -> dict[str, Any]:
        if inputs["goal"] != STUDENT_DEMO_GOAL:
            raise StateConflict("Offline Student demo supports only its fixed study brief")
        if agent.id == "student_notes":
            return {"notes": STUDENT_DEMO_NOTES}
        if agent.id == "student_quiz" and inputs["notes"] == STUDENT_DEMO_NOTES:
            return {"questions": deepcopy(STUDENT_DEMO_QUESTIONS)}
        raise StateConflict("Offline Student inputs do not match the fixed scenario")


def render_quiz(questions: list[dict[str, Any]], *, demo: bool) -> tuple[str, str]:
    provenance = f"{DEMO_LABEL}\n\n" if demo else ""
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


class StudentExecutor:
    def __init__(self, generator: StructuredGenerator, *, demo: bool = False) -> None:
        self.generator = generator
        self.demo = demo

    async def execute(
        self, agent: AgentDefinition, inputs: dict[str, Any], context: ExecutionContext
    ) -> AgentResult:
        if agent.id not in {"student_notes", "student_quiz"} or agent.role != "student":
            raise StateConflict("Agent is outside the Student workflow")
        outputs = await self.generator.generate(agent, inputs)
        Draft202012Validator(agent.output_schema).validate(outputs)
        artifacts: tuple[ArtifactDraft, ...]
        if agent.id == "student_notes":
            artifacts = (
                ArtifactDraft(
                    name="notes.md", media_type="text/markdown", content=outputs["notes"]
                ),
            )
        else:
            quiz, key = render_quiz(outputs["questions"], demo=self.demo)
            artifacts = tuple(
                ArtifactDraft(name=name, media_type="text/markdown", content=content)
                for name, content in (
                    ("quiz.md", quiz),
                    ("answer-key.md", key),
                    ("reviewed-notes.md", inputs["notes"]),
                )
            )
        if self.demo:
            artifacts += (
                ArtifactDraft(
                    name="offline-demo.txt",
                    content=f"{DEMO_LABEL}\n"
                    "Student notes and questions are fixtures. No research, software tests, "
                    "scoring, or independent correctness verification occurred.\n",
                ),
            )
        return AgentResult(outputs=outputs, artifacts=artifacts)
