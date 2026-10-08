"""Validated discovery registry. Registration grants no execution authority."""

from collections.abc import Iterable
from typing import TypeVar

from agentos.domain.agents import AgentDefinition
from agentos.domain.roles import RolePackage

T = TypeVar("T", AgentDefinition, RolePackage)


class RegistryError(ValueError):
    """Invalid or inconsistent registration."""


def index_unique(items: Iterable[T]) -> dict[str, T]:
    result: dict[str, T] = {}
    for item in items:
        if item.id in result:
            raise RegistryError(f"Duplicate id: {item.id}")
        result[item.id] = item.model_copy(deep=True)
    return result


class AgentRegistry:
    """Construct atomically; return copies so callers cannot mutate stored schemas."""

    def __init__(
        self,
        agents: Iterable[AgentDefinition],
        roles: Iterable[RolePackage],
        known_tools: Iterable[str],
    ) -> None:
        agent_map = index_unique(agents)
        role_map = index_unique(roles)
        tools = frozenset(known_tools)
        for role in role_map.values():
            unknown_tools = set(role.tools) - tools
            if unknown_tools:
                raise RegistryError(f"Role {role.id}: unknown tools {sorted(unknown_tools)}")
            for agent_id in role.agents:
                if agent_id not in agent_map:
                    raise RegistryError(f"Role {role.id}: unknown agent {agent_id}")
                agent = agent_map[agent_id]
                if agent.role != role.id:
                    raise RegistryError(f"Agent {agent.id}: role does not match {role.id}")
                if not set(agent.tools) <= set(role.tools):
                    raise RegistryError(f"Agent {agent.id}: tools exceed role {role.id}")
        for agent in agent_map.values():
            if agent.role not in role_map or agent.id not in role_map[agent.role].agents:
                raise RegistryError(f"Agent {agent.id}: missing role membership {agent.role}")
            if not set(agent.tools) <= tools:
                raise RegistryError(f"Agent {agent.id}: unknown tools")
        self._agents = agent_map
        self._roles = role_map

    def agents(self) -> list[AgentDefinition]:
        return [self.agent(key) for key in sorted(self._agents)]

    def roles(self) -> list[RolePackage]:
        return [self.role(key) for key in sorted(self._roles)]

    def agent(self, agent_id: str) -> AgentDefinition:
        return self._agents[agent_id].model_copy(deep=True)

    def role(self, role_id: str) -> RolePackage:
        return self._roles[role_id].model_copy(deep=True)

    def role_agents(self, role_id: str) -> list[AgentDefinition]:
        return [self.agent(agent_id) for agent_id in self.role(role_id).agents]
