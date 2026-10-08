"""Read-only discovery API. Bind to loopback; remote access is not supported."""

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException

from agentos.adapters.manifests import load_registry
from agentos.domain.agents import AgentDefinition
from agentos.domain.roles import RolePackage
from agentos.services.registry import AgentRegistry


def create_app(
    registry: AgentRegistry | None = None, *, package_root: Path | None = None
) -> FastAPI:
    if registry is None:
        root = package_root or Path(os.environ.get("AGENTOS_PACKAGES", "packages"))
        registry = load_registry(root)
    catalog = registry
    app = FastAPI(title="AgentOS", version="0.1.0")

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

    return app
