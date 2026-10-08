"""Local discovery and mission API. Remote access is not supported."""

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response

from agentos.adapters.artifacts import ArtifactStore
from agentos.adapters.manifests import load_registry
from agentos.adapters.sqlite import SQLiteMissionRepository
from agentos.domain.agents import AgentDefinition
from agentos.domain.artifacts import Artifact
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
    MissionValidationError,
    StateConflict,
    TaskActionRequest,
    VersionRequest,
)
from agentos.domain.roles import RolePackage
from agentos.services.approvals import ApprovalService
from agentos.services.execution import ExecutorRegistry
from agentos.services.missions import MissionService
from agentos.services.orchestration import Orchestrator
from agentos.services.registry import AgentRegistry


def create_app(
    registry: AgentRegistry | None = None,
    *,
    package_root: Path | None = None,
    db_path: Path | None = None,
    artifact_root: Path | None = None,
    executors: ExecutorRegistry | None = None,
    user_role: UserRole | None = None,
) -> FastAPI:
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
    orchestrator = Orchestrator(catalog, repository, executors or ExecutorRegistry(), storage)
    approvals = ApprovalService(repository, storage)
    app = FastAPI(title="AgentOS", version="0.1.0")

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

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "capability": "discovery"}

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
        return missions.create(request)

    @app.get("/missions")
    def list_missions(
        limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0)
    ) -> list[Mission]:
        return repository.list_missions(limit, offset)

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
        return missions.act(mission_id, task_id, request)

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

    return app
