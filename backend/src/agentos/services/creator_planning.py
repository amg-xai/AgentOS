"""Creator compilation/preflight on the shared mission engine."""

from typing import Any, Protocol, cast

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaValidationError

from agentos.domain.agents import AgentDefinition, Permission
from agentos.domain.creator_planning import (
    CreatorKind,
    CreatorPlan,
    CreatorThumbnailPlan,
    input_schema,
    output_schema,
)
from agentos.domain.missions import (
    InputBinding,
    Mission,
    MissionCreate,
    PlanningEvidence,
    StateConflict,
    TaskSpec,
)
from agentos.domain.workspace import CreatorMissionCreate
from agentos.services.execution import ExecutorRegistry
from agentos.services.registry import AgentRegistry


class CreatorPlanner(Protocol):
    async def plan(
        self, request: CreatorMissionCreate
    ) -> tuple[CreatorPlan | CreatorThumbnailPlan, str]: ...


def creator_kind(agent: AgentDefinition, *, legacy: bool = False) -> CreatorKind:
    kind = agent.capability or (agent.id if legacy else None)
    if kind not in {"creator_research", "creator_outline", "creator_script", "creator_thumbnail"}:
        raise StateConflict("Unsupported Creator capability")
    kind = cast(CreatorKind, kind)
    if (
        agent.role != "creator"
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
        raise StateConflict("Unsupported Creator executor schema or permissions")
    return kind


def registered_creator_planner(
    registry: AgentRegistry, *, thumbnail: bool = False
) -> AgentDefinition:
    capability = "creator_thumbnail_plan" if thumbnail else "creator_plan"
    model = CreatorThumbnailPlan if thumbnail else CreatorPlan
    planners = [a for a in registry.role_agents("creator") if a.capability == capability]
    if (
        len(planners) != 1
        or planners[0].tools
        or planners[0].permissions
        or planners[0].output_schema != model.model_json_schema()
    ):
        raise StateConflict("Creator needs one supported tool-free planner")
    return planners[0]


def compile_creator_plan(
    request: CreatorMissionCreate,
    plan: CreatorPlan | CreatorThumbnailPlan,
    planner_id: str,
    registry: AgentRegistry,
    executors: ExecutorRegistry,
) -> MissionCreate:
    model = CreatorThumbnailPlan if request.include_thumbnail else CreatorPlan
    plan = model.model_validate(plan.model_dump())
    context = (
        {"sources": [s.model_dump(mode="json") for s in request.sources]} if request.sources else {}
    )
    tasks = []
    for task in plan.tasks:
        bindings = {
            b.input_key: InputBinding(task_id=b.task_id, output_key=b.output_key)
            for b in task.bindings
        }
        if len(bindings) != len(task.bindings):
            raise StateConflict("Creator plan bindings must be unique")
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
                    **context,
                    **(
                        {"include_thumbnail": True}
                        if registry.agent(task.agent_id).capability == "creator_thumbnail"
                        else {}
                    ),
                },
                review_required=task.review_required,
            )
        )
    mission = MissionCreate(
        goal=request.goal,
        role_id="creator",
        tasks=tuple(tasks),
        planning=PlanningEvidence(
            contract_version=2 if request.include_thumbnail else 1,
            planner_id=planner_id,
            rationale=plan.rationale,
            constraints=plan.constraints,
            objectives={t.id: t.objective for t in plan.tasks},
        ),
    )
    validate_creator_plan(mission, registry, executors)
    return mission


def validate_creator_plan(
    mission: Mission | MissionCreate, registry: AgentRegistry, executors: ExecutorRegistry
) -> None:
    try:
        _validate_creator_plan(mission, registry, executors)
    except StateConflict:
        raise
    except (ValueError, KeyError, SchemaValidationError):
        raise StateConflict("Creator plan has invalid persisted evidence or IO contracts") from None


def _validate_creator_plan(
    mission: Mission | MissionCreate, registry: AgentRegistry, executors: ExecutorRegistry
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
        request.role_id != "creator"
        or request.workspace_id != "local"
        or not request.planning
        or request.planning.contract_version not in {1, 2}
        or not (3 if request.planning.contract_version == 2 else 2)
        <= len(request.tasks)
        <= (7 if request.planning.contract_version == 2 else 6)
    ):
        raise StateConflict("Invalid planned Creator mission")
    evidence = PlanningEvidence.model_validate(request.planning.model_dump())
    thumbnail = evidence.contract_version == 2
    model = CreatorThumbnailPlan if thumbnail else CreatorPlan
    model.model_validate(
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
                        {"input_key": key, **binding.model_dump()}
                        for key, binding in t.input_bindings.items()
                    ],
                }
                for t in request.tasks
            ],
        }
    )
    if evidence.planner_id != registered_creator_planner(registry, thumbnail=thumbnail).id or set(
        evidence.objectives
    ) != {t.id for t in request.tasks}:
        raise StateConflict("Creator planning evidence does not match its tasks or planner")
    by_id = {t.id: t for t in request.tasks}
    kinds = {}
    for task in request.tasks:
        if task.agent_id not in registry.role("creator").agents:
            raise StateConflict("Creator plan assigns an agent outside its role")
        agent = registry.agent(task.agent_id)
        kinds[task.id] = creator_kind(agent)
        executors.resolve(agent)
    sources = CreatorMissionCreate(
        goal=request.goal, sources=request.tasks[0].inputs.get("sources", ())
    ).sources
    source_data = [s.model_dump(mode="json") for s in sources]
    counts = list(kinds.values())
    if (
        counts.count("creator_script") != 1
        or not 1 <= counts.count("creator_outline") <= 4
        or counts.count("creator_research") != int(bool(sources))
        or counts.count("creator_thumbnail") != int(thumbnail)
    ):
        raise StateConflict(
            "Creator plan needs outlines, one final script and supplied-source research"
        )
    consumed = set()
    research_ids = {key for key, kind in kinds.items() if kind == "creator_research"}
    for task in request.tasks:
        kind = kinds[task.id]
        expected: dict[str, Any] = {
            "goal": request.goal,
            "objective": evidence.objectives[task.id],
            "constraints": list(evidence.constraints),
        }
        if sources:
            expected["sources"] = source_data
        if kind == "creator_thumbnail":
            expected["include_thumbnail"] = True
        if (
            task.inputs != expected
            or task.requires_passed_tests
            or task.review_required
            != (kind == ("creator_thumbnail" if thumbnail else "creator_script"))
        ):
            raise StateConflict(
                "Creator plan must preserve goal, constraints, sources and final review"
            )
        keys = set(task.input_bindings)
        required = (
            {"summary", "evidence", "limitations"}
            if sources and kind != "creator_research"
            else set()
        )
        if kind in {"creator_script", "creator_thumbnail"}:
            required.add("outline")
        if kind == "creator_thumbnail":
            required.add("script")
            script_task = next(t for t in request.tasks if kinds[t.id] == "creator_script")
            if task.input_bindings.get("outline") != script_task.input_bindings.get("outline"):
                raise StateConflict("Thumbnail and script must use the same final outline")
        allowed = required | ({"context"} if kind == "creator_outline" else set())
        if not required <= keys <= allowed or (kind == "creator_research" and keys):
            raise StateConflict("Unsupported Creator input bindings")
        if set(task.dependencies) != {b.task_id for b in task.input_bindings.values()}:
            raise StateConflict("Every Creator dependency must supply bound evidence")
        resolved = dict(task.inputs)
        for key, binding in task.input_bindings.items():
            source = by_id[binding.task_id]
            research_key = key in {"summary", "evidence", "limitations"}
            if (
                binding.output_key != (key if research_key or key == "script" else "outline")
                or kinds[source.id]
                != (
                    "creator_research"
                    if research_key
                    else "creator_script"
                    if key == "script"
                    else "creator_outline"
                )
                or (research_key and source.id not in research_ids)
            ):
                raise StateConflict("Creator binding source/output does not match its capability")
            schema = registry.agent(source.agent_id).output_schema["properties"][binding.output_key]
            if schema != registry.agent(task.agent_id).input_schema["properties"][key]:
                raise StateConflict("Creator binding schemas do not match")
            resolved[key] = (
                []
                if key == "limitations"
                else (
                    [
                        {
                            "source_id": sources[0].id,
                            "quote": sources[0].body[:800],
                            "interpretation": "Evidence",
                        }
                    ]
                    if key == "evidence"
                    else "Bounded evidence"
                )
            )
            consumed.add(source.id)
        Draft202012Validator(registry.agent(task.agent_id).input_schema).validate(resolved)
    terminal = set(by_id) - consumed
    if len(terminal) != 1 or kinds[next(iter(terminal))] != (
        "creator_thumbnail" if thumbnail else "creator_script"
    ):
        raise StateConflict("Every Creator task must lead to the final script review")
