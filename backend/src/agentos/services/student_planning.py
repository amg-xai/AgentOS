"""Compile and validate Student plans on the shared mission engine."""

from typing import Any, Protocol, cast

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaValidationError

from agentos.domain.agents import AgentDefinition, Permission
from agentos.domain.missions import (
    InputBinding,
    Mission,
    MissionCreate,
    PlanningEvidence,
    StateConflict,
    TaskSpec,
)
from agentos.domain.student import Quiz, StudySettings
from agentos.domain.student_planning import StudentKind, StudentPlan, input_schema, output_schema
from agentos.domain.workspace import StudentMissionCreate
from agentos.services.execution import ExecutorRegistry
from agentos.services.registry import AgentRegistry


class StudentPlanner(Protocol):
    async def plan(self, request: StudentMissionCreate) -> tuple[StudentPlan, str]: ...


def student_kind(agent: AgentDefinition, *, legacy: bool = False) -> StudentKind:
    kind = agent.capability or (agent.id if legacy else None)
    if kind not in {"student_notes", "student_quiz", "student_focus"}:
        raise StateConflict("Unsupported Student capability")
    kind = cast(StudentKind, kind)
    if (
        agent.role != "student"
        or agent.tools
        or set(agent.permissions) != {Permission.READ}
        or agent.input_schema
        not in (
            [input_schema(kind), input_schema(kind, planned=False)]
            if legacy
            else [input_schema(kind)]
        )
        or agent.output_schema != output_schema(kind)
    ):
        raise StateConflict("Unsupported Student executor schema or permissions")
    return kind


def registered_student_planner(registry: AgentRegistry) -> AgentDefinition:
    planners = [a for a in registry.role_agents("student") if a.capability == "student_plan"]
    if (
        len(planners) != 1
        or planners[0].tools
        or planners[0].permissions
        or planners[0].output_schema != StudentPlan.model_json_schema()
    ):
        raise StateConflict("Student needs one supported tool-free mission planner")
    return planners[0]


def compile_student_plan(
    request: StudentMissionCreate,
    plan: StudentPlan,
    planner_id: str,
    registry: AgentRegistry,
    executors: ExecutorRegistry,
) -> MissionCreate:
    plan = StudentPlan.model_validate(plan.model_dump())
    settings = request.study_settings.model_dump(mode="json") if request.study_settings else None
    tasks = []
    for task in plan.tasks:
        bindings = {
            b.input_key: InputBinding(task_id=b.task_id, output_key=b.output_key)
            for b in task.bindings
        }
        if len(bindings) != len(task.bindings):
            raise StateConflict("Student plan bindings must be unique")
        tasks.append(
            TaskSpec(
                id=task.id,
                title=task.title,
                agent_id=task.agent_id,
                dependencies=task.dependencies,
                input_bindings=bindings,
                inputs={
                    "goal": request.goal,
                    "objective": task.objective,
                    "constraints": list(plan.constraints),
                    "study_settings": settings,
                },
                review_required=task.review_required,
            )
        )
    mission = MissionCreate(
        goal=request.goal,
        role_id="student",
        tasks=tuple(tasks),
        planning=PlanningEvidence(
            contract_version=1,
            planner_id=planner_id,
            rationale=plan.rationale,
            constraints=plan.constraints,
            objectives={t.id: t.objective for t in plan.tasks},
        ),
    )
    validate_student_plan(mission, registry, executors)
    return mission


def validate_student_plan(
    mission: Mission | MissionCreate,
    registry: AgentRegistry,
    executors: ExecutorRegistry,
) -> None:
    try:
        _validate_student_plan(mission, registry, executors)
    except StateConflict:
        raise
    except (ValueError, KeyError, SchemaValidationError):
        raise StateConflict("Student plan has invalid persisted evidence or IO contracts") from None


def _validate_student_plan(
    mission: Mission | MissionCreate,
    registry: AgentRegistry,
    executors: ExecutorRegistry,
) -> None:
    request = MissionCreate(
        goal=mission.goal,
        role_id=mission.role_id,
        workspace_id=mission.workspace_id,
        tasks=tuple(
            TaskSpec.model_validate(t.model_dump(include=set(TaskSpec.model_fields)))
            for t in mission.tasks
        ),
        planning=mission.planning,
    )
    if (
        request.role_id != "student"
        or request.workspace_id != "local"
        or not request.planning
        or request.planning.contract_version != 1
        or not 2 <= len(request.tasks) <= 6
    ):
        raise StateConflict("Invalid planned Student mission")
    evidence = PlanningEvidence.model_validate(request.planning.model_dump())
    StudentPlan.model_validate(
        {
            "rationale": evidence.rationale,
            "constraints": evidence.constraints,
            "tasks": [
                {
                    "id": t.id,
                    "title": t.title,
                    "agent_id": t.agent_id,
                    "objective": evidence.objectives.get(t.id, ""),
                    "dependencies": t.dependencies,
                    "review_required": t.review_required,
                    "bindings": [
                        {"input_key": key, **b.model_dump()} for key, b in t.input_bindings.items()
                    ],
                }
                for t in request.tasks
            ],
        }
    )
    if evidence.planner_id != registered_student_planner(registry).id or set(
        evidence.objectives
    ) != {t.id for t in request.tasks}:
        raise StateConflict("Student planning evidence does not match its tasks or planner")
    by_id = {t.id: t for t in request.tasks}
    kinds = {}
    for task in request.tasks:
        if task.agent_id not in registry.role("student").agents:
            raise StateConflict("Student plan assigns an agent outside its role")
        agent = registry.agent(task.agent_id)
        kinds[task.id] = student_kind(agent)
        executors.resolve(agent)
    settings_value = request.tasks[0].inputs["study_settings"]
    settings = StudySettings.model_validate(settings_value) if settings_value is not None else None
    settings_data = settings.model_dump(mode="json") if settings else None
    counts = list(kinds.values())
    if (
        not 1 <= counts.count("student_notes") <= 4
        or counts.count("student_quiz") != 1
        or counts.count("student_focus") != int(settings is not None)
    ):
        raise StateConflict("Student plan needs notes, one quiz and explicitly requested Focus")
    final_kind = "student_focus" if settings else "student_quiz"
    consumed = set()
    for task in request.tasks:
        kind = kinds[task.id]
        if (
            task.inputs
            != {
                "goal": request.goal,
                "objective": evidence.objectives[task.id],
                "constraints": list(evidence.constraints),
                "study_settings": settings_data,
            }
            or task.requires_passed_tests
            or task.review_required != (kind == final_kind)
        ):
            raise StateConflict("Student plan must preserve goal, constraints, settings and review")
        required = (
            {"notes", "questions"}
            if kind == "student_focus"
            else {"notes"}
            if kind == "student_quiz"
            else set()
        )
        keys = set(task.input_bindings)
        allowed = required | ({"context"} if kind == "student_notes" else set())
        if not required <= keys <= allowed:
            raise StateConflict("Unsupported Student input bindings")
        if set(task.dependencies) != {b.task_id for b in task.input_bindings.values()}:
            raise StateConflict("Every Student dependency must supply bound evidence")
        resolved = dict(task.inputs)
        for key, binding in task.input_bindings.items():
            source = by_id[binding.task_id]
            if binding.output_key != ("questions" if key == "questions" else "notes") or kinds[
                source.id
            ] != ("student_quiz" if key == "questions" else "student_notes"):
                raise StateConflict("Student binding source/output does not match its capability")
            schema = registry.agent(source.agent_id).output_schema["properties"][binding.output_key]
            if schema != registry.agent(task.agent_id).input_schema["properties"][key]:
                raise StateConflict("Student binding schemas do not match")
            resolved[key] = (
                [
                    {
                        "prompt": "Question",
                        "choices": ["A", "B", "C", "D"],
                        "answer_index": 0,
                        "explanation": "Evidence",
                    }
                ]
                * 3
                if key == "questions"
                else "Bounded notes"
            )
            consumed.add(source.id)
        if kind == "student_focus":
            quiz = by_id[task.input_bindings["questions"].task_id]
            if task.input_bindings["notes"] != quiz.input_bindings["notes"]:
                raise StateConflict("Student Focus and quiz must bind the same final notes")
        Draft202012Validator(registry.agent(task.agent_id).input_schema).validate(resolved)
    terminal = set(by_id) - consumed
    if len(terminal) != 1 or kinds[next(iter(terminal))] != final_kind:
        raise StateConflict("Every Student task must lead to the final review")


def validate_student_output(kind: StudentKind, outputs: dict[str, Any]) -> None:
    if kind == "student_notes":
        notes = outputs.get("notes")
        if not isinstance(notes, str) or not notes.strip() or len(notes) > 24000:
            raise StateConflict("Student execution requires bounded nonblank notes")
    elif kind == "student_quiz":
        Quiz.model_validate(outputs)
