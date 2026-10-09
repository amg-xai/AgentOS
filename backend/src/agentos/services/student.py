"""Study notes and quiz graph on the shared mission engine."""

from typing import Any

from agentos.domain.agents import Permission
from agentos.domain.missions import InputBinding, Mission, MissionCreate, StateConflict, TaskSpec
from agentos.domain.student import (
    StudyPlan,
    StudyPlanningError,
    StudySettings,
    focus_input_schema,
    quiz_schema,
    study_evidence,
)
from agentos.services.execution import ExecutorRegistry
from agentos.services.registry import AgentRegistry


def student_mission(goal: str, study_settings: StudySettings | None = None) -> MissionCreate:
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
                review_required=study_settings is None,
            ),
            *(
                (
                    TaskSpec(
                        id="study_plan",
                        title="Prepare a bounded study plan for review",
                        agent_id="student_focus",
                        inputs={
                            "goal": goal,
                            "study_settings": study_settings.model_dump(mode="json"),
                        },
                        dependencies=("notes", "quiz"),
                        input_bindings={
                            "notes": InputBinding(task_id="notes", output_key="notes"),
                            "questions": InputBinding(task_id="quiz", output_key="questions"),
                        },
                        review_required=True,
                    ),
                )
                if study_settings is not None
                else ()
            ),
        ),
    )


def has_study_plan(mission: Mission | MissionCreate) -> bool:
    return mission.role_id == "student" and any(
        task.agent_id == "student_focus" or "study_settings" in task.inputs
        for task in mission.tasks
    )


def validate_study_mission(
    mission: Mission | MissionCreate, registry: AgentRegistry, executors: ExecutorRegistry
) -> None:
    try:
        focus = next(task for task in mission.tasks if task.id == "study_plan")
        settings = StudySettings.model_validate(focus.inputs["study_settings"])
        expected = student_mission(mission.goal, settings)
        actual = tuple(
            TaskSpec.model_validate(task.model_dump(include=set(TaskSpec.model_fields)))
            for task in mission.tasks
        )
        if mission.workspace_id != "local" or actual != expected.tasks:
            raise ValueError("Unsupported study graph")
        goal_schema = {"type": "string", "minLength": 1, "maxLength": 8000}
        notes_schema = {"type": "string", "minLength": 1, "maxLength": 24000}
        for task in expected.tasks:
            agent = registry.agent(task.agent_id)
            if (
                agent.role != "student"
                or agent.id not in registry.role("student").agents
                or agent.tools
                or set(agent.permissions) != {Permission.READ}
            ):
                raise ValueError("Unsupported study permissions")
            executors.resolve(agent)
            if task.id == "study_plan":
                inputs = focus_input_schema()
                outputs = StudyPlan.model_json_schema()
            else:
                properties = {"goal": goal_schema}
                if task.id == "quiz":
                    properties["notes"] = notes_schema
                inputs = {
                    "type": "object",
                    "properties": properties,
                    "required": list(properties),
                    "additionalProperties": False,
                }
                outputs = (
                    quiz_schema()
                    if task.id == "quiz"
                    else {
                        "type": "object",
                        "properties": {"notes": notes_schema},
                        "required": ["notes"],
                        "additionalProperties": False,
                    }
                )
            if agent.input_schema != inputs or agent.output_schema != outputs:
                raise ValueError("Unsupported study executor contract")
    except (KeyError, ValueError, StopIteration, StateConflict):
        raise StateConflict(
            "Student study planning capabilities or evidence graph are unavailable"
        ) from None


def study_review_evidence(mission: Mission, outputs: dict[str, Any]) -> dict[str, str]:
    try:
        by_id = {task.id: task for task in mission.tasks}
        return study_evidence(
            StudySettings.model_validate(by_id["study_plan"].inputs["study_settings"]),
            (by_id["notes"].outputs or {})["notes"],
            (by_id["quiz"].outputs or {})["questions"],
            outputs,
        )
    except StudyPlanningError:
        raise
    except (KeyError, ValueError):
        raise StateConflict("Student review is missing valid study evidence") from None
