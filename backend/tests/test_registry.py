import pytest

from agentos.domain.agents import ProviderConfig
from agentos.domain.roles import RolePackage
from agentos.services.registry import AgentRegistry, RegistryError


def test_developer_membership(registry):
    assert [a.id for a in registry.role_agents("developer")] == [
        "investigation",
        "code_helper",
        "testing",
        "developer_planner",
        "baseline_testing",
        "issue_specification",
    ]
    assert all(a.provider is None for a in registry.agents())


def test_duplicate_registration_rejected(registry):
    agents = registry.agents()
    with pytest.raises(RegistryError, match="Duplicate id"):
        AgentRegistry([*agents, agents[0]], registry.roles(), {"filesystem", "terminal", "git"})
    with pytest.raises(RegistryError, match="Duplicate id"):
        AgentRegistry(agents, registry.roles() * 2, {"filesystem", "terminal", "git"})


def test_unknown_agent_rejected(registry):
    role = registry.role("developer").model_dump()
    role["agents"] += ("missing",)
    with pytest.raises(RegistryError, match="unknown agent missing"):
        AgentRegistry(registry.agents(), [RolePackage(**role)], {"filesystem", "terminal", "git"})


def test_unknown_tools_rejected(registry):
    with pytest.raises(RegistryError, match="unknown tools"):
        AgentRegistry(registry.agents(), registry.roles(), {"filesystem"})


def test_role_cannot_hide_agent_tools(registry):
    role = registry.role("developer").model_dump()
    role["tools"] = ("filesystem", "git")
    with pytest.raises(RegistryError, match="tools exceed role"):
        AgentRegistry(registry.agents(), [RolePackage(**role)], {"filesystem", "terminal", "git"})


def test_orphan_agent_rejected(registry):
    with pytest.raises(RegistryError, match="missing role membership"):
        AgentRegistry(registry.agents(), [], {"filesystem", "terminal", "git"})


def test_lookup_is_defensive(registry):
    agent = registry.agent("investigation")
    agent.input_schema["required"].clear()
    assert registry.agent("investigation").input_schema["required"] == ["goal"]
    with pytest.raises(KeyError):
        registry.agent("missing")


def test_credential_reference_not_inline_secret():
    config = ProviderConfig(
        provider="example", model="example-model", credential_env="MODEL_API_KEY"
    )
    assert config.credential_env == "MODEL_API_KEY"
    with pytest.raises(ValueError):
        ProviderConfig(provider="example", model="example-model", api_key="secret")
