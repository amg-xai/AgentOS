"""Developer workflow graph built only from core mission contracts."""

from agentos.domain.missions import InputBinding, MissionCreate, TaskSpec


def developer_mission(goal: str) -> MissionCreate:
    return MissionCreate(
        goal=goal,
        role_id="developer",
        workspace_id="local",
        tasks=(
            TaskSpec(
                id="investigate",
                title="Investigate source evidence",
                agent_id="investigation",
                inputs={"goal": goal},
            ),
            TaskSpec(
                id="fix",
                title="Generate and check a patch",
                agent_id="code_helper",
                dependencies=("investigate",),
                input_bindings={
                    "findings": InputBinding(task_id="investigate", output_key="findings")
                },
            ),
            TaskSpec(
                id="verify",
                title="Run tests and review the result",
                agent_id="testing",
                dependencies=("fix",),
                review_required=True,
                requires_passed_tests=True,
                input_bindings={"diff": InputBinding(task_id="fix", output_key="diff")},
            ),
        ),
    )
