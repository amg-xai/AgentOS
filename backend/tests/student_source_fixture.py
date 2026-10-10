"""Injected sourced Student data; never used as a product fallback."""

from copy import deepcopy

from agentos.adapters.student import STUDENT_DEMO_QUESTIONS

SOURCE = {
    "id": "course",
    "label": "Course excerpt",
    "body": (
        "  Stacks use LIFO. Queues use FIFO.\n"
        "Push and pop act on stacks; enqueue and dequeue act on queues. Café 日本語\n"
    ),
}
RESEARCH = {
    "summary": "Removal order and operations",
    "evidence": [
        {"source_id": "course", "quote": "Stacks use LIFO.", "interpretation": "Newest first"},
        {"source_id": "course", "quote": "Queues use FIFO.", "interpretation": "Earliest first"},
        {
            "source_id": "course",
            "quote": "Push and pop act on stacks; enqueue and dequeue act on queues.",
            "interpretation": "Operations",
        },
    ],
    "limitations": ["Supplied excerpt only; no independent verification"],
}
SUMMARY = {
    "topics": [{"text": "Compare removal order and operations.", "evidence_refs": [1, 2, 3]}],
    "limitations": ["No complexity material supplied"],
}
NOTES = {
    "notes": "# Study notes\n\nStacks: LIFO, push/pop. Queues: FIFO, enqueue/dequeue.",
    "summary_refs": [1],
}
QUIZ = {"questions": deepcopy(STUDENT_DEMO_QUESTIONS), "question_refs": [[1], [1], [1]]}
FOCUS = {
    "summary": "Practice the supplied quiz",
    "limitations": ["Suggested effort only"],
    "blocks": [
        {
            "activity": "practice_quiz",
            "objective": "Practice supplied operations",
            "minutes": 20,
            "question_refs": [1, 2, 3],
        }
    ],
}


def sourced_plan(*, focus=False, refine=False, ids=None):
    ids = ids or {
        key: key
        for key in (
            "student_research",
            "student_summary",
            "student_source_notes",
            "student_source_quiz",
            "student_source_focus",
        )
    }
    tasks = []

    def add(task_id, kind, bindings, review=False):
        tasks.append(
            {
                "id": task_id,
                "title": kind.replace("_", " "),
                "agent_id": ids[kind],
                "objective": "Address the study goal with supplied evidence",
                "dependencies": list(dict.fromkeys(b["task_id"] for b in bindings)),
                "bindings": bindings,
                "review_required": review,
            }
        )

    def bind(key, task, output=None):
        return {"input_key": key, "task_id": task, "output_key": output or key}

    add("evidence", "student_research", [])
    research = bind("research", "evidence")
    add("summary", "student_summary", [research])
    context = [research, bind("study_summary", "summary")]
    add("notes", "student_source_notes", context)
    if refine:
        add("refinement", "student_source_notes", context + [bind("context", "notes", "notes")])
    final_notes = "refinement" if refine else "notes"
    quiz_context = context + [bind("notes", final_notes), bind("summary_refs", final_notes)]
    add("quiz", "student_source_quiz", quiz_context, not focus)
    if focus:
        add(
            "focus",
            "student_source_focus",
            quiz_context + [bind("questions", "quiz"), bind("question_refs", "quiz")],
            True,
        )
    return {
        "rationale": "Source-grounded study with registered capabilities",
        "constraints": ["Use supplied material only"],
        "tasks": tasks,
    }


def output_for(agent, inputs):
    if agent == "student_source_planner":
        return sourced_plan(focus=inputs["study_settings"] is not None)
    result = deepcopy(
        {
            "student_research": {"research": RESEARCH},
            "student_summary": {"study_summary": SUMMARY},
            "student_source_notes": NOTES,
            "student_source_quiz": QUIZ,
            "student_source_focus": FOCUS,
        }[agent]
    )
    if agent == "student_research":
        for item in result["research"]["evidence"]:
            item["source_id"] = inputs["sources"][0]["id"]
    return result
