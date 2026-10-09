"""Injected structured plans for deterministic tests, never product fallbacks."""


def student_plan(*, focus=False, refine=False, ids=None):
    agents = ids or {key: key for key in ("student_notes", "student_quiz", "student_focus")}
    tasks = [
        {
            "id": "draft",
            "title": "Study the supplied goal",
            "agent_id": agents["student_notes"],
            "objective": "Explain the original supplied material",
            "dependencies": [],
            "bindings": [],
            "review_required": False,
        }
    ]
    if refine:
        tasks.append(
            {
                "id": "refine",
                "title": "Refine learning notes",
                "agent_id": agents["student_notes"],
                "objective": "Clarify the goal-specific notes",
                "dependencies": ["draft"],
                "bindings": [{"input_key": "context", "task_id": "draft", "output_key": "notes"}],
                "review_required": False,
            }
        )
    notes = {
        "input_key": "notes",
        "task_id": "refine" if refine else "draft",
        "output_key": "notes",
    }
    tasks.append(
        {
            "id": "questions",
            "title": "Prepare the study quiz",
            "agent_id": agents["student_quiz"],
            "objective": "Practice supplied concepts",
            "dependencies": [notes["task_id"]],
            "bindings": [notes],
            "review_required": not focus,
        }
    )
    if focus:
        tasks.append(
            {
                "id": "schedule",
                "title": "Plan bounded study effort",
                "agent_id": agents["student_focus"],
                "objective": "Allocate explicit study time",
                "dependencies": [notes["task_id"], "questions"],
                "bindings": [
                    notes,
                    {"input_key": "questions", "task_id": "questions", "output_key": "questions"},
                ],
                "review_required": True,
            }
        )
    return {
        "rationale": "Plan the supplied goal with registered Student agents",
        "constraints": ["Use supplied material only"],
        "tasks": tasks,
    }
