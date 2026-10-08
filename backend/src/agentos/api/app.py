"""Local discovery and mission API. Remote access is not supported."""

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from agentos.adapters.manifests import load_registry
from agentos.adapters.sqlite import SQLiteMissionRepository
from agentos.domain.agents import AgentDefinition
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
from agentos.services.missions import MissionService
from agentos.services.registry import AgentRegistry


def create_app(
    registry: AgentRegistry | None = None,
    *,
    package_root: Path | None = None,
    db_path: Path | None = None,
) -> FastAPI:
    if registry is None:
        root = package_root or Path(os.environ.get("AGENTOS_PACKAGES", "packages"))
        registry = load_registry(root)
    catalog = registry
    repository = SQLiteMissionRepository(
        db_path or Path(os.environ.get("AGENTOS_DATABASE", ".agentos/agentos.sqlite3"))
    )
    missions = MissionService(catalog, repository)
    app = FastAPI(title="AgentOS", version="0.1.0")

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
    def role(role_id: str) -> RolePackage:
        try:
            return catalog.role(role_id)
        except KeyError as exc:
            raise HTTPException(404, "Role not found") from exc

    @app.post("/missions", status_code=201)
    def create_mission(request: MissionCreate) -> Mission:
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
        return missions.act(mission_id, task_id, request)

    @app.post("/missions/{mission_id}/cancel")
    def cancel_mission(mission_id: str, request: VersionRequest) -> Mission:
        return missions.cancel(mission_id, request.expected_version)

    return app
