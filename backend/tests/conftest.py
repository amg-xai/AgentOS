from pathlib import Path

import pytest

from agentos.adapters.manifests import load_registry
from agentos.services.registry import AgentRegistry

PACKAGES = Path(__file__).resolve().parents[2] / "packages"


@pytest.fixture
def registry() -> AgentRegistry:
    return load_registry(PACKAGES)
