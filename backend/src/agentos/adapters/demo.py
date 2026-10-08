"""Explicit Calculator fixture adapter. No provider construction or network calls."""

import difflib
import hashlib
from pathlib import Path
from typing import Any

from agentos.adapters.developer import DeveloperExecutor
from agentos.adapters.workspace import read_workspace_source
from agentos.domain.agents import AgentDefinition, AgentResult, ExecutionContext
from agentos.domain.artifacts import ArtifactDraft
from agentos.domain.missions import StateConflict
from agentos.domain.workspace import WorkspaceSettings

DEMO_LABEL = "Offline demo — scripted responses, no model calls"
DEMO_GOAL = "Fix incorrect addition in the bundled Calculator sample. Preserve all test assertions."
SAMPLE_DIGESTS = {
    "calculator.py": "e30939bb54ee813598d4bc015899458158455afe3dfb50d59c2aced4a6a8f6ab",
    "test_calculator.py": "52df56562692aaec1b66b41241e1f95b6fe780e2b5f29da842474a27528c104a",
    "README.md": "b74fe5f1d56ff3cdaa0853e44046d7deb272b6c2915dea21c97ab099c8a9a3f4",
}


def validate_demo_source(files: dict[str, str]) -> None:
    if {name: hashlib.sha256(text.encode()).hexdigest() for name, text in files.items()} != (
        SAMPLE_DIGESTS
    ):
        raise StateConflict("Offline demo requires the unchanged bundled Calculator sample")


def demo_workspace(root: Path) -> WorkspaceSettings:
    settings = WorkspaceSettings(
        name="Offline demo · Calculator",
        repository=root / "samples" / "calculator",
        files=tuple(SAMPLE_DIGESTS),
        test_commands=(("python", "-m", "unittest", "discover", "-v"),),
    )
    validate_demo_source(read_workspace_source(settings))
    return settings


def demo_directory(root: Path) -> Path:
    directory = root / ".agentos" / "demo"
    for path in (
        directory.parent,
        directory,
        directory / "agentos.sqlite3",
        directory / "workspace.sqlite3",
        directory / "artifacts",
        directory / "scratch",
    ):
        if path.resolve() != path:
            raise StateConflict("Demo storage must not redirect outside its local directory")
    return directory


class DemoGenerator:
    async def generate(self, agent: AgentDefinition, inputs: dict[str, Any]) -> dict[str, Any]:
        source: dict[str, str] = inputs["source_files"]
        validate_demo_source(source)
        if agent.id == "investigation" and inputs["goal"] == DEMO_GOAL:
            return {
                "findings": f"{DEMO_LABEL}\n\n"
                "Scripted finding: calculator.py returns left - right in add; "
                "the existing positive and negative addition assertions expose the bug."
            }
        if agent.id == "code_helper":
            original = source["calculator.py"]
            patched = original.replace("return left - right", "return left + right")
            patch = "diff --git a/calculator.py b/calculator.py\n" + "".join(
                difflib.unified_diff(
                    original.splitlines(keepends=True),
                    patched.splitlines(keepends=True),
                    fromfile="a/calculator.py",
                    tofile="b/calculator.py",
                )
            )
            return {
                "diff": patch,
                "summary": f"{DEMO_LABEL}\n\n"
                "Scripted patch: change subtraction to addition; preserve the test file. "
                "Inspect the separate actual subprocess test report before acceptance.",
            }
        raise StateConflict("Offline demo supports only its fixed Calculator scenario")


class DemoDeveloperExecutor:
    """Reuse the real scoped workflow; persist provenance alongside every result."""

    def __init__(self, developer: DeveloperExecutor) -> None:
        self.developer = developer

    async def execute(
        self, agent: AgentDefinition, inputs: dict[str, Any], context: ExecutionContext
    ) -> AgentResult:
        result = await self.developer.execute(agent, inputs, context)
        if agent.id == "testing":
            report = f"{DEMO_LABEL}\nActual configured subprocess test execution follows.\n\n"
            report += result.outputs["report"]
            result = result.model_copy(
                update={
                    "outputs": result.outputs | {"report": report},
                    "artifacts": tuple(
                        item.model_copy(update={"content": report})
                        if item.name == "test-report.txt"
                        else item
                        for item in result.artifacts
                    ),
                }
            )
        return result.model_copy(
            update={
                "artifacts": result.artifacts
                + (
                    ArtifactDraft(
                        name="offline-demo.txt",
                        media_type="text/plain",
                        content=f"{DEMO_LABEL}\n"
                        f"Agent: {agent.id}\n"
                        "Investigation findings and proposed/tested patches are fixtures. "
                        "Test reports record actual local test execution. "
                        "This mode does not verify live AI behavior.\n",
                    ),
                )
            }
        )
