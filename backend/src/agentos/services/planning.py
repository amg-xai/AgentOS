"""Bounded Developer plan compilation and validation; no execution engine here."""

from typing import Annotated, Any, Literal, Protocol

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import Field

from agentos.domain.agents import AgentDefinition, Permission
from agentos.domain.base import Definition, Identifier
from agentos.domain.missions import (
    InputBinding,
    Mission,
    MissionCreate,
    MissionValidationError,
    PlanningEvidence,
    TaskSpec,
)
from agentos.services.execution import ExecutorRegistry
from agentos.services.registry import AgentRegistry


class PlanBinding(Definition):
    input_key: Identifier
    task_id: Identifier
    output_key: Identifier


class PlanTask(Definition):
    id: Identifier
    title: str = Field(min_length=1, max_length=160)
    agent_id: Identifier
    objective: str = Field(min_length=1, max_length=2000)
    dependencies: tuple[Identifier, ...] = Field(max_length=8)
    bindings: tuple[PlanBinding, ...] = Field(max_length=3)
    review_required: bool = Field(strict=True)


class DeveloperPlan(Definition):
    rationale: str = Field(min_length=1, max_length=4000)
    constraints: tuple[Annotated[str, Field(min_length=1, max_length=1000)], ...] = Field(
        max_length=16
    )
    tasks: tuple[PlanTask, ...] = Field(min_length=4, max_length=8)


class DeveloperPlanner(Protocol):
    async def plan(self, goal: str) -> tuple[DeveloperPlan, str]: ...


Kind = Literal["developer_investigate", "developer_patch", "developer_test", "developer_baseline"]


def registered_planner(registry: AgentRegistry) -> AgentDefinition:
    planners = [
        agent for agent in registry.role_agents("developer") if agent.capability == "developer_plan"
    ]
    if (
        len(planners) != 1
        or planners[0].tools
        or planners[0].permissions
        or planners[0].output_schema != DeveloperPlan.model_json_schema()
    ):
        raise MissionValidationError("Developer needs one supported tool-free planner")
    return planners[0]


def developer_kind(agent: AgentDefinition) -> Kind:
    contracts = {
        "developer_baseline": (
            {"goal"},
            {
                "baseline_passed": "boolean",
                "baseline_report": "string",
                "baseline_summary": "string",
            },
            {"filesystem", "terminal"},
            {Permission.READ, Permission.EXECUTE},
        ),
        "developer_investigate": (
            {"goal"},
            {"findings": "string"},
            {"filesystem", "git"},
            {Permission.READ},
        ),
        "developer_patch": (
            {"findings"},
            {"diff": "string", "summary": "string"},
            {"filesystem", "git"},
            {Permission.READ, Permission.WRITE},
        ),
        "developer_test": (
            {"diff"},
            {"passed": "boolean", "report": "string"},
            {"filesystem", "terminal"},
            {Permission.READ, Permission.EXECUTE},
        ),
    }
    kind = agent.capability
    if agent.role != "developer" or kind not in contracts:
        raise MissionValidationError("Unsupported Developer capability")
    required, outputs, tools, permissions = contracts[kind]
    schema = agent.input_schema
    output = agent.output_schema
    # No arbitrary IO extensions or elevated permissions accepted by this adapter.
    allowed = required | (
        {"goal", "objective", "constraints", "context"} if kind != "developer_test" else set()
    )
    if kind == "developer_patch":
        allowed.add("baseline_summary")
    if kind == "developer_test":
        allowed.add("baseline_report")
    if kind == "developer_baseline":
        allowed.discard("context")
    properties = schema.get("properties", {})
    if (
        schema.get("type") != "object"
        or schema.get("additionalProperties") is not False
        or set(schema.get("required", [])) != required
        or not required <= properties.keys()
        or (
            kind != "developer_test"
            and not {"goal", "objective", "constraints"} <= properties.keys()
        )
        or not set(properties) <= allowed
        or any(
            not isinstance(properties[key], dict)
            or properties[key].get("type") != ("array" if key == "constraints" else "string")
            for key in properties
        )
        or output.get("type") != "object"
        or output.get("additionalProperties") is not False
        or set(output.get("required", [])) != set(outputs)
        or set(output.get("properties", {})) != set(outputs)
        or any(
            not isinstance(output["properties"][key], dict)
            or output["properties"][key].get("type") != value
            for key, value in outputs.items()
        )
        or set(agent.tools) != tools
        or not permissions <= set(agent.permissions)
        or Permission.DESTRUCTIVE in agent.permissions
        or not set(agent.permissions) <= permissions
    ):
        raise MissionValidationError("Unsupported Developer executor schema or capabilities")
    return kind  # type: ignore[return-value]


def compile_plan(
    goal: str,
    plan: DeveloperPlan,
    planner_id: str,
    registry: AgentRegistry,
    executors: ExecutorRegistry,
) -> MissionCreate:
    tasks = []
    for proposed in plan.tasks:
        try:
            agent = registry.agent(proposed.agent_id)
        except KeyError as exc:
            raise MissionValidationError("Plan assigns an unknown agent") from exc
        kind = developer_kind(agent)
        bindings = {
            binding.input_key: InputBinding(task_id=binding.task_id, output_key=binding.output_key)
            for binding in proposed.bindings
        }
        if len(bindings) != len(proposed.bindings):
            raise MissionValidationError("Plan input bindings must be unique")
        inputs = (
            {}
            if kind == "developer_test"
            else {
                "goal": goal,
                "objective": proposed.objective,
                "constraints": list(plan.constraints),
            }
        )
        tasks.append(
            TaskSpec(
                id=proposed.id,
                title=proposed.title,
                agent_id=agent.id,
                dependencies=proposed.dependencies,
                inputs=inputs,
                input_bindings=bindings,
                review_required=proposed.review_required,
                requires_passed_tests=kind == "developer_test",
            )
        )
    mission = MissionCreate(
        goal=goal,
        tasks=tuple(tasks),
        planning=PlanningEvidence(
            contract_version=2,
            planner_id=planner_id,
            rationale=plan.rationale,
            constraints=plan.constraints,
            objectives={task.id: task.objective for task in plan.tasks},
        ),
    )
    validate_planned_mission(mission, registry, executors)
    return mission


def validate_planned_mission(
    mission: Mission | MissionCreate, registry: AgentRegistry, executors: ExecutorRegistry
) -> None:
    # Revalidate frozen model copies and persisted snapshots before acquiring a run claim.
    request = MissionCreate(
        goal=mission.goal,
        role_id=mission.role_id,
        workspace_id=mission.workspace_id,
        tasks=tuple(
            TaskSpec.model_validate(task.model_dump(include=set(TaskSpec.model_fields)))
            for task in mission.tasks
        ),
        planning=mission.planning,
    )
    if (
        request.role_id != "developer"
        or request.workspace_id != "local"
        or not 3 <= len(request.tasks) <= 8
        or request.planning is None
    ):
        raise MissionValidationError("Invalid planned Developer mission")
    role = registry.role("developer")
    evidence = PlanningEvidence.model_validate(request.planning.model_dump())
    version = evidence.contract_version
    if version == 2 and len(request.tasks) < 4:
        raise MissionValidationError("Version 2 requires at least four tasks")
    planner = registered_planner(registry)
    if planner.id != request.planning.planner_id:
        raise MissionValidationError("Planning evidence does not match the registered planner")
    if set(request.planning.objectives) != {task.id for task in request.tasks}:
        raise MissionValidationError("Planning evidence must cover exactly the planned tasks")
    by_id = {task.id: task for task in request.tasks}
    kinds = {}
    for task in request.tasks:
        if task.agent_id not in role.agents:
            raise MissionValidationError("Plan assigns an agent outside the Developer role")
        agent = registry.agent(task.agent_id)
        kinds[task.id] = developer_kind(agent)
        executors.resolve(agent)
    if (
        list(kinds.values()).count("developer_patch") != 1
        or list(kinds.values()).count("developer_test") != 1
        or list(kinds.values()).count("developer_baseline") != (1 if version == 2 else 0)
        or "developer_investigate" not in kinds.values()
    ):
        raise MissionValidationError("Plan requires exactly one patch and one test/review task")
    consumed = set()
    for task in request.tasks:
        kind = kinds[task.id]
        if kind != "developer_test":
            if (
                task.inputs.get("goal") != request.goal
                or task.inputs.get("constraints") != list(request.planning.constraints)
                or task.inputs.get("objective") != request.planning.objectives.get(task.id)
            ):
                raise MissionValidationError(
                    "Plan must preserve original goal, constraints and objectives"
                )
            if task.review_required or task.requires_passed_tests:
                raise MissionValidationError("Only the test/result task may request review")
        elif task.inputs or not task.review_required or not task.requires_passed_tests:
            raise MissionValidationError(
                "Test/result task requires explicit outcome and human review"
            )
        keys = set(task.input_bindings)
        patch_required = {"findings", "baseline_summary"} if version == 2 else {"findings"}
        test_required = {"diff", "baseline_report"} if version == 2 else {"diff"}
        if (
            (
                kind == "developer_patch"
                and (not patch_required <= keys or not keys <= patch_required | {"context"})
            )
            or (kind == "developer_test" and keys != test_required)
            or (kind == "developer_investigate" and not keys <= {"context"})
            or (kind == "developer_baseline" and keys)
        ):
            raise MissionValidationError("Plan uses unsupported input bindings")
        if set(task.dependencies) != {binding.task_id for binding in task.input_bindings.values()}:
            raise MissionValidationError("Every dependency must supply supported evidence")
        resolved = dict(task.inputs)
        for key, binding in task.input_bindings.items():
            if key in {"baseline_summary", "baseline_report"}:
                expected_kind, expected_output = "developer_baseline", key
            elif kind == "developer_test":
                expected_kind, expected_output = "developer_patch", "diff"
            else:
                expected_kind, expected_output = "developer_investigate", "findings"
            if kinds[binding.task_id] != expected_kind or binding.output_key != expected_output:
                raise MissionValidationError(
                    "Binding source/output does not match executor contract"
                )
            source_schema = registry.agent(by_id[binding.task_id].agent_id).output_schema
            if source_schema["properties"][binding.output_key].get("type") != "string":
                raise MissionValidationError("Binding requires string evidence")
            consumed.add(binding.task_id)
            resolved[key] = "validated upstream evidence"
        try:
            Draft202012Validator(registry.agent(task.agent_id).input_schema).validate(resolved)
        except SchemaValidationError:
            raise MissionValidationError(
                "Planned task inputs do not match the executor schema"
            ) from None
    terminal = {key for key in by_id if key not in consumed}
    if len(terminal) != 1 or kinds[next(iter(terminal))] != "developer_test":
        raise MissionValidationError("Every planned task must lead to the final tested review")


def review_evidence(mission: Mission, task: TaskSpec, outputs: dict[str, Any]) -> dict[str, str]:
    """Version-2 review owns exact upstream evidence, independent of executor implementation."""
    by_id = {item.id: item for item in mission.tasks}
    bound = {}
    for key in ("diff", "baseline_report"):
        binding = task.input_bindings[key]
        source = by_id[binding.task_id]
        if source.outputs is None or not isinstance(source.outputs.get(binding.output_key), str):
            raise MissionValidationError("Tested review is missing upstream evidence")
        bound[key] = source.outputs[binding.output_key]
    report = outputs.get("report")
    if not isinstance(report, str) or not report:
        raise MissionValidationError("Tested review is missing its test report")
    return {
        "tested.diff": bound["diff"],
        "test-report.txt": report,
        "reviewed-baseline-report.txt": bound["baseline_report"],
    }
