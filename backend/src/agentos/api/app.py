"""Local discovery and mission API. Remote access is not supported."""

import os
from collections.abc import Awaitable, Callable
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from jsonschema.exceptions import ValidationError as SchemaValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from agentos.adapters.artifacts import ArtifactStore
from agentos.adapters.creator import CREATOR_DEMO_GOAL, CreatorDemoGenerator, CreatorExecutor
from agentos.adapters.demo import (
    DEMO_GOAL,
    DEMO_LABEL,
    DemoDeveloperExecutor,
    DemoGenerator,
    demo_directory,
    demo_workspace,
)
from agentos.adapters.developer import DeveloperExecutor, register_local_tools
from agentos.adapters.local_tools import LocalWorkspaceTools
from agentos.adapters.manifests import load_registry
from agentos.adapters.planning import StructuredDeveloperPlanner
from agentos.adapters.provider import ModelSettings, ProviderFailure, ResponsesExecutor
from agentos.adapters.sqlite import SQLiteMissionRepository
from agentos.adapters.student import STUDENT_DEMO_GOAL, StudentDemoGenerator, StudentExecutor
from agentos.adapters.workspace import WorkspaceStore
from agentos.domain.agents import AgentDefinition, AgentExecutor, StructuredGenerator
from agentos.domain.artifacts import Artifact
from agentos.domain.base import Identifier
from agentos.domain.governance import (
    Approval,
    ApprovalDecision,
    PermissionDenied,
    RecoveryRequest,
    RunClaim,
    UserRole,
    require_operator,
)
from agentos.domain.missions import (
    Mission,
    MissionCreate,
    MissionEvent,
    MissionNotFound,
    MissionStatus,
    MissionValidationError,
    PatchRevisionRequest,
    StateConflict,
    TaskAction,
    TaskActionRequest,
    VersionRequest,
)
from agentos.domain.overview import WorkspaceOverview
from agentos.domain.revisions import PatchRevisionStatus
from agentos.domain.roles import RolePackage
from agentos.domain.workspace import (
    CreatorMissionCreate,
    DeveloperMissionCreate,
    MemoryCreate,
    MemoryNote,
    StudentMissionCreate,
    WorkspaceSettings,
)
from agentos.services.approvals import ApprovalService
from agentos.services.creator import creator_mission, has_sources, validate_source_mission
from agentos.services.developer import developer_mission
from agentos.services.execution import ExecutorRegistry
from agentos.services.missions import MissionService
from agentos.services.orchestration import Orchestrator
from agentos.services.overview import workspace_overview
from agentos.services.planning import (
    DeveloperPlanner,
    compile_plan,
    developer_kind,
    registered_planner,
)
from agentos.services.registry import AgentRegistry
from agentos.services.revisions import PatchRevisionService
from agentos.services.student import has_study_plan, student_mission, validate_study_mission
from agentos.services.tools import ToolRegistry


def create_app(
    registry: AgentRegistry | None = None,
    *,
    package_root: Path | None = None,
    db_path: Path | None = None,
    artifact_root: Path | None = None,
    executors: ExecutorRegistry | None = None,
    user_role: UserRole | None = None,
    workspace: WorkspaceSettings | None = None,
    model: ResponsesExecutor | None = None,
    frontend_root: Path | None = None,
    demo_root: Path | None = None,
    desktop_session: str | None = None,
    planner: DeveloperPlanner | None = None,
) -> FastAPI:
    if demo_root is not None:
        if any(
            item is not None
            for item in (
                registry,
                workspace,
                model,
                executors,
                db_path,
                artifact_root,
                package_root,
                frontend_root,
                planner,
            )
        ):
            raise ValueError("Demo mode uses its own isolated startup configuration")
        demo_root = demo_root.resolve(strict=True)
        workspace = demo_workspace(demo_root)
        directory = demo_directory(demo_root)
        db_path = directory / "agentos.sqlite3"
        artifact_root = directory / "artifacts"
        package_root = demo_root / "packages"
        frontend_root = demo_root / "frontend" / "dist"
    if registry is None:
        root = package_root or Path(os.environ.get("AGENTOS_PACKAGES", "packages"))
        registry = load_registry(root)
    catalog = registry
    repository = SQLiteMissionRepository(
        db_path or Path(os.environ.get("AGENTOS_DATABASE", ".agentos/agentos.sqlite3"))
    )
    missions = MissionService(catalog, repository)
    role = user_role or UserRole(os.environ.get("AGENTOS_USER_ROLE", "operator"))
    storage = ArtifactStore(
        artifact_root
        or Path(os.environ.get("AGENTOS_ARTIFACTS", str(repository.path.parent / "artifacts")))
    )
    memory = WorkspaceStore(repository.path.parent / "workspace.sqlite3")
    configuration = Path(os.environ.get("AGENTOS_WORKSPACE_CONFIG", ".agentos/workspace.json"))
    workspace_error: str | None = None
    if demo_root is None and workspace is None and configuration.exists():
        try:
            workspace = WorkspaceSettings.model_validate_json(
                configuration.read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            workspace_error = "Developer workspace configuration is invalid; check workspace.json."
    settings = ModelSettings.from_environment() if demo_root is None and model is None else None
    if settings is not None:
        if settings.allow_live_calls:
            model = ResponsesExecutor(settings)
    bindings = executors or ExecutorRegistry()
    generator: StructuredGenerator | None = DemoGenerator() if demo_root is not None else model
    if executors is None and workspace is not None and generator is not None:
        tools = ToolRegistry(repository.record_tool_event)
        register_local_tools(
            tools, LocalWorkspaceTools(workspace, memory, repository.path.parent / "scratch")
        )
        scoped = DeveloperExecutor(generator, tools, memory, role)
        developer: AgentExecutor = (
            DemoDeveloperExecutor(scoped) if demo_root is not None else scoped
        )
        for candidate in catalog.role_agents("developer"):
            try:
                developer_kind(candidate)
            except MissionValidationError:
                continue
            bindings.register_agent(candidate.id, developer)
    if planner is None and demo_root is None and generator is not None and workspace is not None:
        planner = StructuredDeveloperPlanner(generator, catalog, workspace)
    if executors is None and generator is not None:
        creator = CreatorExecutor(
            CreatorDemoGenerator() if demo_root is not None else generator,
            demo=demo_root is not None,
        )
        for agent_id in ("creator_outline", "creator_script", "creator_research"):
            bindings.register_agent(agent_id, creator)
        student = StudentExecutor(
            StudentDemoGenerator() if demo_root is not None else generator,
            demo=demo_root is not None,
        )
        for agent_id in ("student_notes", "student_quiz", "student_focus"):
            bindings.register_agent(agent_id, student)

    def workflow_status() -> list[dict[str, object]]:
        result: list[dict[str, object]] = []
        for role_id, agents, steps, notice, goal in (
            (
                "developer",
                ("investigation", "code_helper", "testing"),
                (
                    "Investigate → propose a patch → run tests → human review"
                    if demo_root is not None
                    else "Baseline + investigation → patch → patched tests → human review"
                ),
                "Selected source files and relevant notes are sent to the configured model.",
                DEMO_GOAL,
            ),
            (
                "creator",
                ("creator_outline", "creator_script"),
                "Brief → outline → script → human review",
                "Only the supplied brief and outline are sent to the configured model.",
                CREATOR_DEMO_GOAL,
            ),
            (
                "student",
                ("student_notes", "student_quiz"),
                "Study brief → notes → quiz and answer key → human review",
                "Only the supplied study brief and notes are sent to the configured model.",
                STUDENT_DEMO_GOAL,
            ),
        ):
            try:
                package = catalog.role(role_id)
            except KeyError:
                continue
            reason = ""
            if generator is None:
                reason = "Configure a model provider and explicitly authorize live model calls."
            elif role_id == "developer" and workspace is None:
                reason = workspace_error or "Configure selected source files and test commands."
            else:
                try:
                    if role_id == "developer" and demo_root is None:
                        registered_planner(catalog)
                        kinds = set()
                        for candidate in catalog.role_agents("developer"):
                            if candidate.capability == "developer_plan":
                                continue
                            try:
                                kind = developer_kind(candidate)
                            except MissionValidationError:
                                continue
                            bindings.resolve(candidate)
                            kinds.add(kind)
                        if (
                            kinds
                            != {
                                "developer_investigate",
                                "developer_patch",
                                "developer_test",
                                "developer_baseline",
                            }
                            or planner is None
                        ):
                            raise StateConflict("Developer planning capabilities are unavailable")
                    else:
                        if not set(agents) <= set(package.agents):
                            raise StateConflict("Package is missing required workflow agents")
                        for agent_id in agents:
                            bindings.resolve(catalog.agent(agent_id))
                except (KeyError, StateConflict, MissionValidationError):
                    reason = "Required workflow agents or executors are unavailable."
            source_research_ready = False
            study_planning_ready = False
            if role_id == "student" and not reason and demo_root is None:
                from agentos.domain.student import StudySettings

                try:
                    validate_study_mission(
                        student_mission(
                            "Check study planning support",
                            StudySettings(total_minutes=60, max_session_minutes=25),
                        ),
                        catalog,
                        bindings,
                    )
                    study_planning_ready = True
                    steps = "Notes → quiz → optional study plan → human review"
                    notice = (
                        "Your brief, notes, quiz and optional time settings are sent to the model."
                    )
                except StateConflict:
                    pass
            if role_id == "creator" and not reason and demo_root is None:
                try:
                    from agentos.domain.creator import SourceText

                    validate_source_mission(
                        creator_mission(
                            "Check source support",
                            (SourceText(id="sample", label="Sample", body="Evidence"),),
                        ),
                        catalog,
                        bindings,
                    )
                    source_research_ready = True
                except StateConflict:
                    pass
            if source_research_ready:
                steps = "Optional source research → outline → script → human review"
                notice = (
                    "Only your brief and optional pasted source text are sent to the model. "
                    "Quotes are checked for provenance; source truth and interpretations "
                    "require review."
                )
            result.append(
                {
                    "role_id": role_id,
                    "name": package.name,
                    "ready": not reason,
                    "reason": reason,
                    "steps": steps,
                    "context_notice": "Fixed scripted scenario. No model calls or source sharing."
                    if demo_root is not None
                    else notice,
                    "demo_goal": goal if demo_root is not None else None,
                    **(
                        {"source_research_ready": source_research_ready}
                        if role_id == "creator"
                        else {}
                    ),
                    **(
                        {"study_planning_ready": study_planning_ready}
                        if role_id == "student"
                        else {}
                    ),
                }
            )
        return result

    def require_workflow(role_id: str) -> None:
        item = next((w for w in workflow_status() if w["role_id"] == role_id), None)
        if item is None or not item["ready"]:
            raise StateConflict(
                str(item["reason"]) if item else "Workflow package is not installed"
            )

    orchestrator = Orchestrator(catalog, repository, bindings, storage)
    approvals = ApprovalService(repository, storage)
    revisions = PatchRevisionService(
        catalog, repository, bindings, storage, demo=demo_root is not None
    )
    app = FastAPI(title="AgentOS", version="0.1.0")
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"]
    )

    @app.middleware("http")
    async def local_browser_access(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        origin = request.headers.get("origin")
        expected = f"{request.url.scheme}://{request.headers.get('host', '')}"
        if origin is not None and origin != expected:
            return JSONResponse(
                status_code=403, content={"detail": "Cross-origin access is disabled"}
            )
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and (
            request.headers.get("content-type", "").split(";", 1)[0] != "application/json"
        ):
            return JSONResponse(status_code=415, content={"detail": "JSON requests are required"})
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/app"):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
                "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
            )
        return response

    @app.exception_handler(PermissionDenied)
    async def forbidden(request: Request, exc: PermissionDenied) -> JSONResponse:
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    @app.exception_handler(MissionNotFound)
    async def not_found(request: Request, exc: MissionNotFound) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(StateConflict)
    async def conflict(request: Request, exc: StateConflict) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(MissionValidationError)
    async def invalid_mission(request: Request, exc: MissionValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(ProviderFailure)
    async def provider_failed(request: Request, exc: ProviderFailure) -> JSONResponse:
        return JSONResponse(
            status_code=502, content={"detail": "Provider planning failed; no mission was created"}
        )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "capability": "discovery"}

    @app.get("/status")
    def status() -> dict[str, object]:
        return {
            "provider_configured": model is not None,
            "desktop_session": desktop_session,
            "active_runs": orchestrator.active_run_count,
            "model": model.settings.model if model else None,
            "workspace_configured": workspace is not None,
            "workspace_error": workspace_error,
            "workspace_name": workspace.name if workspace else None,
            "workspace_files": list(workspace.files) if workspace else [],
            "test_commands": workspace.test_commands if workspace else [],
            "user_role": role.value,
            "memory_retrieval": "lexical",
            "workflow_ready": any(
                w["role_id"] == "developer" and w["ready"] for w in workflow_status()
            ),
            "workflows": workflow_status(),
            "execution_mode": "demo" if demo_root is not None else "live",
            "execution_label": DEMO_LABEL
            if demo_root is not None
            else "Configured model execution",
            "demo_goal": DEMO_GOAL if demo_root is not None else None,
        }

    @app.get("/overview")
    def overview() -> WorkspaceOverview:
        return workspace_overview(
            repository,
            catalog,
            "demo" if demo_root is not None else "live",
            orchestrator.active_run_count,
        )

    @app.get("/memory")
    def list_memory(
        query: str = Query(default="", max_length=8000),
        limit: int = Query(default=20, ge=1, le=100),
    ) -> list[MemoryNote]:
        return memory.notes(query, limit)

    @app.post("/memory", status_code=201)
    def add_memory(request: MemoryCreate) -> MemoryNote:
        require_operator(role)
        for artifact_id in request.artifact_refs:
            repository.artifact(artifact_id)
        return memory.add_note(request)

    @app.post("/workflows/developer", status_code=201)
    async def create_developer_mission(request: DeveloperMissionCreate) -> Mission:
        require_operator(role)
        require_workflow("developer")
        if demo_root is not None:
            if request.goal != DEMO_GOAL:
                raise StateConflict("Offline demo supports only its fixed Calculator mission")
            demo_workspace(demo_root)
            return missions.create(developer_mission(request.goal))
        if planner is None:
            raise StateConflict("Developer planner is unavailable")
        try:
            plan, planner_id = await planner.plan(request.goal)
            compiled = compile_plan(request.goal, plan, planner_id, catalog, bindings)
        except (ValueError, SchemaValidationError, KeyError):
            raise MissionValidationError(
                "Developer plan rejected: invalid graph, capability or IO contract"
            ) from None
        return missions.create(compiled)

    @app.post("/workflows/creator", status_code=201)
    def create_creator_mission(request: CreatorMissionCreate) -> Mission:
        require_operator(role)
        require_workflow("creator")
        if demo_root is not None and (request.goal != CREATOR_DEMO_GOAL or request.sources):
            raise StateConflict("Offline Creator demo supports only its fixed brief")
        mission = creator_mission(request.goal, request.sources)
        if request.sources:
            validate_source_mission(mission, catalog, bindings)
        return missions.create(mission)

    @app.post("/workflows/student", status_code=201)
    def create_student_mission(request: StudentMissionCreate) -> Mission:
        require_operator(role)
        require_workflow("student")
        if demo_root is not None and (
            request.goal != STUDENT_DEMO_GOAL or request.study_settings is not None
        ):
            raise StateConflict("Offline Student demo supports only its fixed study brief")
        mission = student_mission(request.goal, request.study_settings)
        if request.study_settings is not None:
            validate_study_mission(mission, catalog, bindings)
        return missions.create(mission)

    @app.get("/agents")
    def agents() -> list[AgentDefinition]:
        return catalog.agents()

    @app.get("/agents/{agent_id}")
    def agent(agent_id: str) -> AgentDefinition:
        try:
            return catalog.agent(agent_id)
        except KeyError as exc:
            raise HTTPException(404, "Agent not found") from exc

    @app.get("/roles")
    def roles() -> list[RolePackage]:
        return catalog.roles()

    @app.get("/roles/{role_id}")
    def get_role(role_id: str) -> RolePackage:
        try:
            return catalog.role(role_id)
        except KeyError as exc:
            raise HTTPException(404, "Role not found") from exc

    @app.post("/missions", status_code=201)
    def create_mission(request: MissionCreate) -> Mission:
        require_operator(role)
        if demo_root is not None:
            raise StateConflict("Use a fixed workflow scenario in offline demo mode")
        return missions.create(request)

    @app.get("/missions")
    def list_missions(
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
        query: str = Query(default="", max_length=200),
        role_id: Identifier | None = None,
        status: MissionStatus | None = None,
    ) -> list[Mission]:
        return repository.list_missions(limit, offset, query=query, role_id=role_id, status=status)

    @app.get("/missions/{mission_id}")
    def get_mission(mission_id: str) -> Mission:
        return repository.get(mission_id)

    @app.get("/missions/{mission_id}/events")
    def mission_events(
        mission_id: str,
        after: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=1000),
    ) -> list[MissionEvent]:
        return repository.events(mission_id, after, limit)

    @app.post("/missions/{mission_id}/tasks/{task_id}/actions")
    def task_action(mission_id: str, task_id: str, request: TaskActionRequest) -> Mission:
        require_operator(role)
        managed = repository.get(mission_id)
        if (
            managed.planning is not None or has_sources(managed) or has_study_plan(managed)
        ) and request.action != TaskAction.RETRY:
            raise StateConflict(
                "Planned missions use executor results; only explicit retry is allowed"
            )
        if demo_root is not None and request.action != TaskAction.RETRY:
            raise StateConflict(
                "Offline demo uses executor results; only explicit retry is allowed"
            )
        return missions.act(mission_id, task_id, request)

    @app.get("/missions/{mission_id}/patch-revision")
    def patch_revision_status(mission_id: str) -> PatchRevisionStatus:
        return revisions.status(repository.get(mission_id))

    @app.post("/missions/{mission_id}/patch-revision")
    def request_patch_revision(mission_id: str, request: PatchRevisionRequest) -> Mission:
        return revisions.request(mission_id, request, role)

    @app.post("/missions/{mission_id}/cancel")
    def cancel_mission(mission_id: str, request: VersionRequest) -> Mission:
        require_operator(role)
        return missions.cancel(mission_id, request.expected_version)

    @app.post("/missions/{mission_id}/run")
    async def run_mission(mission_id: str, request: VersionRequest) -> Mission:
        return await orchestrator.run(mission_id, request.expected_version, role)

    @app.get("/missions/{mission_id}/run")
    def run_claim(mission_id: str) -> RunClaim | None:
        return repository.claim(mission_id)

    @app.post("/missions/{mission_id}/recover")
    def recover_mission(mission_id: str, request: RecoveryRequest) -> Mission:
        return orchestrator.recover(mission_id, request, role)

    @app.get("/missions/{mission_id}/approvals")
    def mission_approvals(mission_id: str, pending_only: bool = True) -> list[Approval]:
        return repository.approvals(mission_id, pending_only)

    @app.get("/approvals/{approval_id}")
    def get_approval(approval_id: str) -> Approval:
        return repository.approval(approval_id)

    @app.post("/approvals/{approval_id}/decision")
    def decide_approval(approval_id: str, request: ApprovalDecision) -> Mission:
        return approvals.decide(approval_id, request, role)

    @app.get("/missions/{mission_id}/artifacts")
    def mission_artifacts(
        mission_id: str,
        limit: int = Query(default=100, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
    ) -> list[Artifact]:
        return repository.artifacts(mission_id, limit, offset)

    @app.get("/artifacts/{artifact_id}")
    def get_artifact(artifact_id: str) -> Artifact:
        return repository.artifact(artifact_id)

    @app.get("/artifacts/{artifact_id}/content")
    def artifact_content(artifact_id: str) -> Response:
        artifact = repository.artifact(artifact_id)
        return Response(
            content=storage.read(artifact),
            media_type=artifact.media_type,
            headers={"Content-Disposition": f'attachment; filename="{artifact.name}"'},
        )

    assets = frontend_root or Path("frontend/dist")
    if assets.is_dir():
        app.mount("/app", StaticFiles(directory=assets, html=True), name="mission-control")

    return app


def create_demo_app() -> FastAPI:
    """Opt-in CLI factory; never selected because a provider is missing."""
    return create_app(demo_root=Path.cwd())
