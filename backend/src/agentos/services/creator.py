"""Creator graph reuses the existing mission and dependency contracts."""

from agentos.domain.missions import InputBinding, MissionCreate, TaskSpec


def creator_mission(goal: str) -> MissionCreate:
    return MissionCreate(
        goal=goal,
        role_id="creator",
        workspace_id="local",
        tasks=(
            TaskSpec(
                id="outline",
                title="Outline the supplied brief",
                agent_id="creator_outline",
                inputs={"goal": goal},
            ),
            TaskSpec(
                id="script",
                title="Draft the script for review",
                agent_id="creator_script",
                inputs={"goal": goal},
                dependencies=("outline",),
                input_bindings={"outline": InputBinding(task_id="outline", output_key="outline")},
                review_required=True,
            ),
        ),
    )
