"""Study notes and quiz graph on the shared mission engine."""

from agentos.domain.missions import InputBinding, MissionCreate, TaskSpec


def student_mission(goal: str) -> MissionCreate:
    return MissionCreate(
        goal=goal,
        role_id="student",
        workspace_id="local",
        tasks=(
            TaskSpec(
                id="notes",
                title="Summarize the supplied material",
                agent_id="student_notes",
                inputs={"goal": goal},
            ),
            TaskSpec(
                id="quiz",
                title="Prepare a quiz and answer key for review",
                agent_id="student_quiz",
                inputs={"goal": goal},
                dependencies=("notes",),
                input_bindings={"notes": InputBinding(task_id="notes", output_key="notes")},
                review_required=True,
            ),
        ),
    )
