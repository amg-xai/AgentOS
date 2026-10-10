"""Student v2 compiles into, and is checked at boundaries of, the shared engine."""

import json
from typing import Any

from jsonschema import Draft202012Validator

from agentos.domain.agents import AgentDefinition, Permission
from agentos.domain.missions import Mission, MissionCreate, StateConflict, TaskSpec, TaskStatus
from agentos.domain.sources import ResearchResult
from agentos.domain.student import StudySettings, render_quiz, study_evidence
from agentos.domain.student_sources import (
    KINDS,
    SourcedNotes,
    SourcedQuiz,
    StudentSourcePlan,
    StudySummary,
    source_input_schema,
    source_output_schema,
    source_planner_input_schema,
    verify_refs,
)
from agentos.domain.workspace import StudentMissionCreate
from agentos.services.execution import ExecutorRegistry
from agentos.services.registry import AgentRegistry
from agentos.services.runtime import ArtifactStorage, RuntimeRepository


def is_sourced(mission: Mission | MissionCreate) -> bool:
    return bool(
        mission.role_id == "student" and mission.planning and mission.planning.contract_version == 2
    )


def source_kind(agent: AgentDefinition) -> str:
    kind = agent.capability
    if (
        kind not in KINDS
        or agent.role != "student"
        or agent.tools
        or set(agent.permissions) != {Permission.READ}
        or agent.input_schema != source_input_schema(kind)
        or agent.output_schema != source_output_schema(kind)
    ):
        raise StateConflict("Unsupported sourced Student executor schema or permissions")
    return kind


def require_source_plan(mission: Mission | MissionCreate, registry: AgentRegistry) -> None:
    sourced_agents = {a.id for a in registry.agents() if a.capability in KINDS}
    if any(t.agent_id in sourced_agents for t in mission.tasks) and not is_sourced(mission):
        raise StateConflict("Sourced Student agents require a validated version-2 Student plan")


def source_planner(registry: AgentRegistry) -> AgentDefinition:
    candidates = [
        a for a in registry.role_agents("student") if a.capability == "student_source_plan"
    ]
    if (
        len(candidates) != 1
        or candidates[0].tools
        or candidates[0].permissions
        or candidates[0].input_schema != source_planner_input_schema()
        or candidates[0].output_schema != StudentSourcePlan.model_json_schema()
    ):
        raise StateConflict("Student needs one supported sourced mission planner")
    return candidates[0]


def validate_source_plan(
    mission: Mission | MissionCreate, registry: AgentRegistry, executors: ExecutorRegistry
) -> None:
    try:
        _validate_source_plan(mission, registry, executors)
    except StateConflict:
        raise
    except (ValueError, KeyError, TypeError):
        raise StateConflict("Sourced Student plan has invalid evidence or bindings") from None


def _validate_source_plan(
    mission: Mission | MissionCreate, registry: AgentRegistry, executors: ExecutorRegistry
) -> None:
    # Reconstructing invokes shared task ID, dependency and cycle validation too.
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
        not is_sourced(request)
        or request.workspace_id != "local"
        or not 4 <= len(request.tasks) <= 8
    ):
        raise StateConflict("Invalid sourced Student mission")
    evidence = request.planning
    assert evidence is not None
    if evidence.planner_id != source_planner(registry).id or set(evidence.objectives) != {
        t.id for t in request.tasks
    }:
        raise StateConflict("Sourced Student planner evidence does not match")
    StudentSourcePlan.model_validate(
        {
            "rationale": evidence.rationale,
            "constraints": evidence.constraints,
            "tasks": [
                {
                    "id": t.id,
                    "title": t.title,
                    "agent_id": t.agent_id,
                    "objective": evidence.objectives[t.id],
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
    kinds = {}
    for task in request.tasks:
        if task.agent_id not in registry.role("student").agents:
            raise StateConflict("Sourced Student assignment is outside its role")
        kinds[task.id] = source_kind(registry.agent(task.agent_id))
        executors.resolve(registry.agent(task.agent_id))
    first = request.tasks[0].inputs
    brief = StudentMissionCreate(
        goal=request.goal, sources=first["sources"], study_settings=first["study_settings"]
    )
    if not brief.sources:
        raise StateConflict("Sourced Student needs supplied text")
    counts = list(kinds.values())
    if (
        counts.count("student_research") != 1
        or counts.count("student_summary") != 1
        or counts.count("student_source_quiz") != 1
        or not 1 <= counts.count("student_source_notes") <= 4
        or counts.count("student_source_focus") != int(brief.study_settings is not None)
    ):
        raise StateConflict(
            "Sourced Student requires research, summary, notes, quiz and explicit Focus"
        )
    by_id = {t.id: t for t in request.tasks}
    research = next(t for t in request.tasks if kinds[t.id] == "student_research")
    summary = next(t for t in request.tasks if kinds[t.id] == "student_summary")
    quiz = next(t for t in request.tasks if kinds[t.id] == "student_source_quiz")
    final_kind = "student_source_focus" if brief.study_settings else "student_source_quiz"
    consumed = set()
    for task in request.tasks:
        kind = kinds[task.id]
        literal = {
            "goal": request.goal,
            "objective": evidence.objectives[task.id],
            "constraints": list(evidence.constraints),
            "sources": [s.model_dump(mode="json") for s in brief.sources],
            "study_settings": brief.study_settings.model_dump(mode="json")
            if brief.study_settings
            else None,
        }
        if (
            task.inputs != literal
            or task.requires_passed_tests
            or task.review_required != (kind == final_kind)
        ):
            raise StateConflict("Sourced Student goal, sources, settings or review changed")
        required = set(source_input_schema(kind)["required"]) - set(literal)
        keys = set(task.input_bindings)
        if (
            not required
            <= keys
            <= required | ({"context"} if kind == "student_source_notes" else set())
        ):
            raise StateConflict("Sourced Student has unsupported input bindings")
        if set(task.dependencies) != {b.task_id for b in task.input_bindings.values()}:
            raise StateConflict("Every sourced Student dependency must supply evidence")
        for key, binding in task.input_bindings.items():
            source = by_id[binding.task_id]
            expected_kind = {
                "research": "student_research",
                "study_summary": "student_summary",
                "notes": "student_source_notes",
                "summary_refs": "student_source_notes",
                "context": "student_source_notes",
                "questions": "student_source_quiz",
                "question_refs": "student_source_quiz",
            }[key]
            output_key = "notes" if key == "context" else key
            if kinds[source.id] != expected_kind or binding.output_key != output_key:
                raise StateConflict("Sourced Student binding capability or output is invalid")
            if (
                source_output_schema(expected_kind)["properties"][output_key]
                != source_input_schema(kind)["properties"][key]
            ):
                raise StateConflict("Sourced Student binding schemas differ")
            if (
                key == "research"
                and source.id != research.id
                or key == "study_summary"
                and source.id != summary.id
            ):
                raise StateConflict("Sourced Student evidence chain changed")
            consumed.add(source.id)
        if (
            kind in {"student_source_quiz", "student_source_focus"}
            and task.input_bindings["notes"].task_id != task.input_bindings["summary_refs"].task_id
        ):
            raise StateConflict("Notes and provenance must share an owning task")
        if kind == "student_source_focus" and (
            task.input_bindings["notes"] != quiz.input_bindings["notes"]
            or task.input_bindings["questions"].task_id
            != task.input_bindings["question_refs"].task_id
        ):
            raise StateConflict("Focus must use the quiz's exact notes and provenance")
        schema = source_input_schema(kind)
        schema["required"] = list(literal)
        Draft202012Validator(schema).validate(literal)
    terminal = set(by_id) - consumed
    if len(terminal) != 1 or kinds[next(iter(terminal))] != final_kind:
        raise StateConflict("Every sourced Student task must lead to human review")


def validate_source_output(kind: str, inputs: dict[str, Any], outputs: dict[str, Any]) -> None:
    brief = StudentMissionCreate(
        goal=inputs["goal"], sources=inputs["sources"], study_settings=inputs["study_settings"]
    )
    research = ResearchResult.model_validate(
        outputs["research"] if kind == "student_research" else inputs["research"]
    )
    research.verify(brief.sources)
    if kind == "student_research":
        return
    summary = StudySummary.model_validate(
        outputs["study_summary"] if kind == "student_summary" else inputs["study_summary"]
    )
    summary.verify(research)
    if kind == "student_summary":
        return
    notes = SourcedNotes.model_validate(
        outputs
        if kind == "student_source_notes"
        else {key: inputs[key] for key in ("notes", "summary_refs")}
    )
    if not notes.notes.strip():
        raise StateConflict("Sourced notes must not be blank")
    verify_refs(notes.summary_refs, len(summary.topics))
    if kind == "student_source_notes":
        return
    quiz = SourcedQuiz.model_validate(
        outputs
        if kind == "student_source_quiz"
        else {key: inputs[key] for key in ("questions", "question_refs")}
    )
    if len(quiz.questions) != len(quiz.question_refs):
        raise StateConflict("Every quiz question needs summary evidence")
    for refs in quiz.question_refs:
        verify_refs(refs, len(summary.topics))
        if not set(refs) <= set(notes.summary_refs):
            raise StateConflict("Quiz evidence must be covered by its bound notes")
    if kind == "student_source_focus":
        study_evidence(
            StudySettings.model_validate(inputs["study_settings"]),
            inputs["notes"],
            inputs["questions"],
            outputs,
        )


def source_artifacts(kind: str, inputs: dict[str, Any], outputs: dict[str, Any]) -> dict[str, str]:
    validate_source_output(kind, inputs, outputs)

    def dump(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, indent=2)

    if kind == "student_research":
        return {"sources.json": dump(inputs["sources"]), "research.json": dump(outputs["research"])}
    if kind == "student_summary":
        return {"study-summary.json": dump(outputs["study_summary"])}
    if kind == "student_source_notes":
        return {
            "notes.md": outputs["notes"],
            "notes-provenance.json": dump(outputs["summary_refs"]),
        }
    quiz = outputs if kind == "student_source_quiz" else inputs
    if kind == "student_source_focus":
        result = study_evidence(
            StudySettings.model_validate(inputs["study_settings"]),
            inputs["notes"],
            inputs["questions"],
            outputs,
        )
    else:
        questions, key = render_quiz(outputs["questions"])
        result = {"quiz.md": questions, "answer-key.md": key, "reviewed-notes.md": inputs["notes"]}
    return {
        **result,
        "reviewed-sources.json": dump(inputs["sources"]),
        "reviewed-research.json": dump(inputs["research"]),
        "reviewed-study-summary.json": dump(inputs["study_summary"]),
        "reviewed-notes-provenance.json": dump(inputs["summary_refs"]),
        "reviewed-quiz-provenance.json": dump(quiz["question_refs"]),
    }


def resolved_inputs(mission: Mission, task: TaskSpec) -> dict[str, Any]:
    result = dict(task.inputs)
    for key, binding in task.input_bindings.items():
        source = next(t for t in mission.tasks if t.id == binding.task_id)
        if source.status != TaskStatus.COMPLETED or source.outputs is None:
            raise StateConflict("Sourced Student upstream evidence is incomplete")
        result[key] = source.outputs[binding.output_key]
    return result


def source_review_evidence(
    mission: Mission, task: TaskSpec, outputs: dict[str, Any]
) -> dict[str, str]:
    try:
        evidence = mission.planning
        if not is_sourced(mission) or evidence is None:
            raise StateConflict("Unsupported sourced Student review")
        for item in mission.tasks:
            if (
                item.inputs["goal"] != mission.goal
                or item.inputs["constraints"] != list(evidence.constraints)
                or item.inputs["objective"] != evidence.objectives[item.id]
            ):
                raise StateConflict("Sourced Student review plan changed")
        kind = (
            "student_source_focus"
            if task.inputs["study_settings"] is not None
            else "student_source_quiz"
        )
        return source_artifacts(kind, resolved_inputs(mission, task), outputs)
    except (ValueError, KeyError, StopIteration):
        raise StateConflict("Sourced Student review evidence is invalid") from None


def validate_source_artifacts(
    mission: Mission, repository: RuntimeRepository, storage: ArtifactStorage
) -> None:
    try:
        _validate_source_artifacts(mission, repository, storage)
    except (ValueError, KeyError, StopIteration, UnicodeDecodeError):
        raise StateConflict("Sourced Student retained evidence is invalid or changed") from None


def _validate_source_artifacts(
    mission: Mission, repository: RuntimeRepository, storage: ArtifactStorage
) -> None:
    if not is_sourced(mission):
        return
    # Bindings identify capabilities without trusting canonical agent or task IDs.
    final = next(t for t in mission.tasks if t.review_required)
    research_id = final.input_bindings["research"].task_id
    summary_id = final.input_bindings["study_summary"].task_id
    quiz_id = (
        final.input_bindings["questions"].task_id if final.inputs["study_settings"] else final.id
    )
    for task in mission.tasks:
        if task.status != TaskStatus.COMPLETED:
            continue
        kind = (
            "student_source_focus"
            if task.id == final.id and final.inputs["study_settings"]
            else "student_research"
            if task.id == research_id
            else "student_summary"
            if task.id == summary_id
            else "student_source_quiz"
            if task.id == quiz_id
            else "student_source_notes"
        )
        expected = source_artifacts(kind, resolved_inputs(mission, task), task.outputs or {})
        actual = {}
        for ref in task.artifact_refs:
            artifact = repository.artifact(ref)
            if artifact.mission_id != mission.id or artifact.task_id != task.id:
                raise StateConflict("Sourced Student artifact scope changed")
            actual[artifact.name] = storage.read(artifact).decode("utf-8")
        if len(task.artifact_refs) != len(expected) or actual != expected:
            raise StateConflict("Sourced Student retained output differs from its frozen artifacts")
