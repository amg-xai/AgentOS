"""Compose persisted activity with installed agents and current server context."""

from typing import Literal, Protocol

from agentos.domain.overview import PersistedOverview, WorkspaceOverview
from agentos.services.registry import AgentRegistry


class OverviewRepository(Protocol):
    def overview(self, agent_ids: tuple[str, ...]) -> PersistedOverview: ...


def workspace_overview(
    repository: OverviewRepository,
    registry: AgentRegistry,
    execution_mode: Literal["live", "demo"],
    local_active_runs: int,
) -> WorkspaceOverview:
    persisted = repository.overview(tuple(agent.id for agent in registry.agents()))
    return WorkspaceOverview(
        **persisted.model_dump(),
        execution_mode=execution_mode,
        local_active_runs=local_active_runs,
    )
