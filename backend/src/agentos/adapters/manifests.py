"""Load a complete registry from versioned, local JSON manifests."""

import json
from pathlib import Path

from pydantic import ValidationError

from agentos.domain.agents import AgentDefinition, AgentManifest
from agentos.domain.roles import RoleManifest, RolePackage
from agentos.services.registry import AgentRegistry, RegistryError

# Discovery metadata only; executable adapters and permission checks come later.
LOCAL_TOOL_IDS = frozenset({"filesystem", "terminal", "git"})


class ManifestError(ValueError):
    """A manifest cannot be loaded."""


def load_registry(root: Path, known_tools: frozenset[str] = LOCAL_TOOL_IDS) -> AgentRegistry:
    files = sorted(root.glob("**/*.json"))
    if not files:
        raise ManifestError(f"No JSON manifests found in {root}")
    agents: list[AgentDefinition] = []
    roles: list[RolePackage] = []
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("Manifest must be an object")
            if data.get("kind") == "agents":
                agents.extend(AgentManifest.model_validate(data).agents)
            elif data.get("kind") == "role":
                roles.append(RoleManifest.model_validate(data).role)
            else:
                raise ValueError(f"Unknown manifest kind: {data.get('kind')!r}")
        except (OSError, ValueError, ValidationError) as exc:
            raise ManifestError(f"{path}: {exc}") from exc
    try:
        return AgentRegistry(agents, roles, known_tools)
    except RegistryError as exc:
        raise ManifestError(f"{root}: {exc}") from exc
