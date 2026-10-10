"""Study notes and quiz graph on the shared mission engine."""

from typing import Any

from agentos.domain.agents import Permission
from agentos.domain.missions import InputBinding, Mission, MissionCreate, StateConflict, TaskSpec
from agentos.domain.student import (
    Quiz,
    StudyPlanningError,
    StudySettings,
    render_quiz,
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
    if mission.role_id == "student" and mission.planning is not None:
        return any(task.inputs.get("study_settings") is not None for task in mission.tasks)
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
            from agentos.services.student_planning import student_kind

            if student_kind(agent, legacy=True) != agent.id:
                raise ValueError("Legacy Student capability changed")
    except (KeyError, ValueError, StopIteration, StateConflict):
        raise StateConflict(
            "Student study planning capabilities or evidence graph are unavailable"
        ) from None


def study_review_evidence(mission: Mission, outputs: dict[str, Any]) -> dict[str, str]:
    if mission.planning is not None:
        task = next(t for t in mission.tasks if t.review_required)
        return student_review_evidence(mission, task, outputs)
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


def student_review_evidence(
    mission: Mission, task: TaskSpec, outputs: dict[str, Any]
) -> dict[str, str]:
    """Resolve the exact planned result bundle through current dependency bindings."""
    from agentos.services.student_sources import is_sourced, source_review_evidence

    if is_sourced(mission):
        return source_review_evidence(mission, task, outputs)
    try:
        evidence = mission.planning
        if mission.role_id != "student" or not evidence or evidence.contract_version != 1:
            raise StateConflict("Unsupported Student review plan")
        settings = task.inputs["study_settings"]
        for item in mission.tasks:
            if (
                item.inputs.get("goal") != mission.goal
                or item.inputs.get("constraints") != list(evidence.constraints)
                or item.inputs.get("objective") != evidence.objectives.get(item.id)
                or item.inputs.get("study_settings") != settings
            ):
                raise StateConflict("Student review plan inputs changed")
        by_id = {t.id: t for t in mission.tasks}
        binding = task.input_bindings["notes"]
        notes = (by_id[binding.task_id].outputs or {})[binding.output_key]
        if not isinstance(notes, str) or not notes.strip() or len(notes) > 24000:
            raise StateConflict("Student review is missing bounded notes")
        if settings is not None:
            quiz_binding = task.input_bindings["questions"]
            quiz = by_id[quiz_binding.task_id]
            if binding != quiz.input_bindings["notes"]:
                raise StateConflict("Student review notes do not match the quiz")
            return study_evidence(
                StudySettings.model_validate(settings),
                notes,
                (quiz.outputs or {})[quiz_binding.output_key],
                outputs,
            )
        content = Quiz.model_validate(outputs)
        questions, key = render_quiz([q.model_dump(mode="json") for q in content.questions])
        return {"quiz.md": questions, "answer-key.md": key, "reviewed-notes.md": notes}
    except StudyPlanningError:
        raise
    except (KeyError, ValueError):
        raise StateConflict("Student review evidence is incomplete or changed") from None
