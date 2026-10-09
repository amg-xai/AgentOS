"""Structured plans supplied by injected transports, never normal-mode fallbacks."""


def creator_plan(*, sources=False, refine=False, ids=None):
    agents = ids or {key: key for key in ("creator_research", "creator_outline", "creator_script")}
    research = (
        [
            {"input_key": key, "task_id": "evidence", "output_key": key}
            for key in ("summary", "evidence", "limitations")
        ]
        if sources
        else []
    )
    tasks = []
    if sources:
        tasks.append(
            {
                "id": "evidence",
                "title": "Research supplied evidence",
                "agent_id": agents["creator_research"],
                "objective": "Verify supplied quotes",
                "dependencies": [],
                "bindings": [],
                "review_required": False,
            }
        )
    tasks.append(
        {
            "id": "draft",
            "title": "Outline the goal",
            "agent_id": agents["creator_outline"],
            "objective": "Structure the original goal",
            "dependencies": ["evidence"] if sources else [],
            "bindings": research,
            "review_required": False,
        }
    )
    if refine:
        tasks.append(
            {
                "id": "polish",
                "title": "Refine the audience structure",
                "agent_id": agents["creator_outline"],
                "objective": "Refine the goal-specific outline",
                "dependencies": ["draft", *(["evidence"] if sources else [])],
                "bindings": [
                    *research,
                    {"input_key": "context", "task_id": "draft", "output_key": "outline"},
                ],
                "review_required": False,
            }
        )
    tasks.append(
        {
            "id": "deliver",
            "title": "Write the reviewed script",
            "agent_id": agents["creator_script"],
            "objective": "Write from verified supplied evidence",
            "dependencies": ["polish" if refine else "draft", *(["evidence"] if sources else [])],
            "bindings": [
                *research,
                {
                    "input_key": "outline",
                    "task_id": "polish" if refine else "draft",
                    "output_key": "outline",
                },
            ],
            "review_required": True,
        }
    )
    return {
        "rationale": "Plan the original goal using supported content agents",
        "constraints": ["Use only supplied facts"],
        "tasks": tasks,
    }
