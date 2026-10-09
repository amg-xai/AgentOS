"""Creator graph reuses the existing mission and dependency contracts."""

import hashlib
import json
from typing import Any

from jsonschema.exceptions import ValidationError as SchemaValidationError

from agentos.domain.agents import Permission
from agentos.domain.creator import ResearchResult, SourceText
from agentos.domain.missions import InputBinding, Mission, MissionCreate, StateConflict, TaskSpec
from agentos.domain.workspace import CreatorMissionCreate
from agentos.services.execution import ExecutorRegistry
from agentos.services.registry import AgentRegistry


def creator_mission(goal: str, sources: tuple[SourceText, ...] = ()) -> MissionCreate:
    context = {"sources": [source.model_dump(mode="json") for source in sources]} if sources else {}
    research_bindings = (
        {
            key: InputBinding(task_id="research", output_key=key)
            for key in ("summary", "evidence", "limitations")
        }
        if sources
        else {}
    )
    research_tasks = (
        (
            TaskSpec(
                id="research",
                title="Research the supplied sources",
                agent_id="creator_research",
                inputs={"goal": goal, **context},
            ),
        )
        if sources
        else ()
    )
    return MissionCreate(
        goal=goal,
        role_id="creator",
        workspace_id="local",
        tasks=(
            *research_tasks,
            TaskSpec(
                id="outline",
                title="Outline the supplied brief",
                agent_id="creator_outline",
                inputs={"goal": goal, **context},
                dependencies=("research",) if sources else (),
                input_bindings=research_bindings,
            ),
            TaskSpec(
                id="script",
                title="Draft the script for review",
                agent_id="creator_script",
                inputs={"goal": goal, **context},
                dependencies=("outline", "research") if sources else ("outline",),
                input_bindings={
                    "outline": InputBinding(task_id="outline", output_key="outline"),
                    **research_bindings,
                },
                review_required=True,
            ),
        ),
    )


def has_sources(mission: Mission | MissionCreate) -> bool:
    return mission.role_id == "creator" and any(
        task.agent_id == "creator_research" or task.inputs.get("sources") for task in mission.tasks
    )


def validate_source_mission(
    mission: Mission | MissionCreate, registry: AgentRegistry, executors: ExecutorRegistry
) -> None:
    """Preflight the supported graph without changing legacy brief-only workflows."""
    try:
        research = next(task for task in mission.tasks if task.id == "research")
        request = CreatorMissionCreate(goal=mission.goal, sources=research.inputs["sources"])
        expected = creator_mission(request.goal, request.sources)
        if not request.sources or mission.workspace_id != "local":
            raise ValueError("Missing source context")
        actual = tuple(
            TaskSpec.model_validate(task.model_dump(include=set(TaskSpec.model_fields)))
            for task in mission.tasks
        )
        if actual != expected.tasks:
            raise ValueError("Source workflow does not match its evidence graph")
        for task in expected.tasks:
            agent = registry.agent(task.agent_id)
            if (
                agent.role != "creator"
                or agent.id not in registry.role("creator").agents
                or agent.tools
                or set(agent.permissions) != {Permission.READ}
            ):
                raise ValueError("Unsupported source workflow permissions")
            executors.resolve(agent)
            from agentos.services.creator_planning import creator_kind

            if creator_kind(agent, legacy=True) != agent.id:
                raise ValueError("Legacy Creator capability changed")
    except (KeyError, ValueError, StopIteration, StateConflict, SchemaValidationError):
        raise StateConflict(
            "Creator source research capabilities or evidence graph are unavailable"
        ) from None


def source_review_evidence(mission: Mission, outputs: dict[str, Any]) -> dict[str, str | bytes]:
    if mission.planning is not None:
        task = next(t for t in mission.tasks if t.review_required)
        return creator_review_evidence(mission, task, outputs)
    by_id = {task.id: task for task in mission.tasks}
    source_inputs = by_id["research"].inputs
    sources = CreatorMissionCreate(goal=mission.goal, sources=source_inputs["sources"]).sources
    research = ResearchResult.model_validate(by_id["research"].outputs)
    research.verify(sources)
    outline = (by_id["outline"].outputs or {}).get("outline")
    script = outputs.get("script")
    if not isinstance(outline, str) or not isinstance(script, str):
        raise StateConflict("Creator review is missing its content evidence")
    return {
        "script.md": script,
        "reviewed-outline.md": outline,
        "reviewed-research.json": research.model_dump_json(indent=2),
        "reviewed-sources.json": json.dumps(
            [source.model_dump(mode="json") for source in sources], ensure_ascii=False, indent=2
        ),
    }


def creator_review_evidence(
    mission: Mission, task: TaskSpec, outputs: dict[str, Any]
) -> dict[str, str | bytes]:
    try:
        if mission.planning and mission.planning.contract_version == 2:
            return thumbnail_review_evidence(mission, task, outputs)
        return {**_creator_review_evidence(mission, task, outputs)}
    except (KeyError, ValueError, StopIteration):
        raise StateConflict("Creator review evidence is incomplete or changed") from None


def _creator_review_evidence(
    mission: Mission, task: TaskSpec, outputs: dict[str, Any]
) -> dict[str, str]:
    """Resolve exact current review evidence by bindings, never canonical task IDs."""
    if mission.planning:
        if mission.planning.contract_version not in {1, 2}:
            raise StateConflict("Unsupported Creator review plan version")
        for item in mission.tasks:
            if (
                item.inputs.get("goal") != mission.goal
                or item.inputs.get("constraints") != list(mission.planning.constraints)
                or item.inputs.get("objective") != mission.planning.objectives.get(item.id)
            ):
                raise StateConflict("Creator review plan inputs changed")
    by_id = {t.id: t for t in mission.tasks}
    outline_binding = task.input_bindings["outline"]
    outline = (by_id[outline_binding.task_id].outputs or {}).get(outline_binding.output_key)
    script = outputs.get("script")
    if not isinstance(outline, str) or not isinstance(script, str):
        raise StateConflict("Creator review is missing its bound outline/script")
    expected = {"script.md": script, "reviewed-outline.md": outline}
    sources = CreatorMissionCreate(
        goal=mission.goal, sources=task.inputs.get("sources", ())
    ).sources
    if sources:
        binding = task.input_bindings["summary"]
        source = by_id[binding.task_id]
        if source.inputs.get("sources") != task.inputs["sources"]:
            raise StateConflict("Creator source evidence changed")
        research = ResearchResult.model_validate(source.outputs)
        research.verify(sources)
        expected.update(
            {
                "reviewed-research.json": research.model_dump_json(indent=2),
                "reviewed-sources.json": json.dumps(
                    [s.model_dump(mode="json") for s in sources], ensure_ascii=False, indent=2
                ),
            }
        )
    return expected


def thumbnail_review_evidence(
    mission: Mission,
    task: TaskSpec,
    outputs: dict[str, Any],
    *,
    frozen: tuple[bytes, str] | None = None,
) -> dict[str, str | bytes]:
    """Stage by independently rendering; accept a validated frozen receipt without rendering."""
    from agentos.adapters.thumbnail import render_thumbnail, validate_png
    from agentos.domain.missions import TaskStatus
    from agentos.domain.thumbnail import ThumbnailEvidence, ThumbnailLayout

    try:
        if not mission.planning or mission.planning.contract_version != 2:
            raise ValueError("Missing thumbnail plan")
        if task.inputs.get("include_thumbnail") is not True or not task.review_required:
            raise ValueError("Missing thumbnail intent or review")
        by_id = {t.id: t for t in mission.tasks}
        script_binding = task.input_bindings["script"]
        script = by_id[script_binding.task_id]
        research_keys = (
            {"summary", "evidence", "limitations"} if task.inputs.get("sources") else set()
        )
        if (
            set(task.input_bindings) != {"script", "outline"} | research_keys
            or set(task.dependencies) != {b.task_id for b in task.input_bindings.values()}
            or any(
                task.input_bindings[key] != script.input_bindings.get(key) for key in research_keys
            )
        ):
            raise ValueError("Thumbnail evidence bindings changed")
        if (
            script_binding.output_key != "script"
            or script.review_required
            or script.input_bindings.get("outline") != task.input_bindings.get("outline")
            or any(
                by_id[b.task_id].status != TaskStatus.COMPLETED
                for b in task.input_bindings.values()
            )
        ):
            raise ValueError("Thumbnail upstream evidence is incomplete or changed")
        # Reuse exact script/outline/source validation; don't trust executor-provided review text.
        text = _creator_review_evidence(mission, script, script.outputs or {})
        if task.inputs.get("sources") != script.inputs.get("sources"):
            raise ValueError("Thumbnail sources changed")
        if (
            task.inputs.get("goal") != mission.goal
            or task.inputs.get("constraints") != list(mission.planning.constraints)
            or task.inputs.get("objective") != mission.planning.objectives.get(task.id)
        ):
            raise ValueError("Thumbnail plan inputs changed")
        text["reviewed-script.md"] = text.pop("script.md")
        layout = ThumbnailLayout.model_validate(outputs)
        if frozen is None:
            png, receipt = render_thumbnail(layout)
            receipt_text = receipt.model_dump_json(indent=2)
        else:
            png, receipt_text = frozen
            receipt = ThumbnailEvidence.model_validate_json(receipt_text)
            validate_png(png)
            if (
                receipt.layout != layout
                or receipt.receipt.png_sha256 != hashlib.sha256(png).hexdigest()
            ):
                raise ValueError("Frozen thumbnail receipt does not match")
        return {**text, "thumbnail.png": png, "thumbnail-layout.json": receipt_text}
    except (KeyError, ValueError, StopIteration):
        raise StateConflict("Thumbnail review evidence is incomplete or changed") from None
