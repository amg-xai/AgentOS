"""Read-only local prerequisites. Never invokes a provider or configured test commands."""

import os
import shutil
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import computed_field

from agentos.adapters.demo import demo_directory, demo_workspace
from agentos.adapters.manifests import load_registry
from agentos.adapters.provider import ModelSettings
from agentos.adapters.workspace import read_workspace_source
from agentos.domain.base import Definition
from agentos.domain.governance import UserRole
from agentos.domain.workspace import WorkspaceSettings
from agentos.services.planning import developer_kind, registered_planner


class SetupCheck(Definition):
    id: str
    passed: bool
    detail: str


class SetupReport(Definition):
    checks: tuple[SetupCheck, ...]
    live_provider_verified: bool = False
    execution_mode: str = "live"
    workflow: str = "developer"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def configured_ready(self) -> bool:
        return all(check.passed for check in self.checks)


class ClientAssets(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.scripts: list[str] = []
        self.styles: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "script" and attributes.get("src"):
            self.scripts.append(str(attributes["src"]))
        if tag == "link" and attributes.get("rel") == "stylesheet" and attributes.get("href"):
            self.styles.append(str(attributes["href"]))


def client_assets_valid(directory: Path) -> bool:
    try:
        parser = ClientAssets()
        parser.feed((directory / "index.html").read_text(encoding="utf-8"))
        if not parser.scripts or not parser.styles:
            return False
        root = directory.resolve(strict=True)
        for asset in (*parser.scripts, *parser.styles):
            url = urlsplit(asset)
            if url.scheme or url.netloc or not url.path.startswith("/app/assets/"):
                return False
            path = (root / url.path.removeprefix("/app/")).resolve(strict=True)
            if not path.is_relative_to(root) or not path.is_file():
                return False
        return True
    except (OSError, ValueError):
        return False


def diagnose(root: Path, *, demo: bool = False, workflow: str = "developer") -> SetupReport:
    if workflow not in {"developer", "creator", "student"}:
        raise ValueError("Unknown workflow")
    checks: list[SetupCheck] = []

    def record(id: str, passed: bool, detail: str) -> None:
        checks.append(SetupCheck(id=id, passed=passed, detail=detail))

    if demo:
        try:
            demo_directory(root)
            record("demo_storage", True, "Separate demo storage paths do not redirect elsewhere.")
        except Exception:
            record("demo_storage", False, "Demo storage paths must not be symlinks or junctions.")
    try:
        packages = Path("packages" if demo else os.environ.get("AGENTOS_PACKAGES", "packages"))
        registry = load_registry(packages if packages.is_absolute() else root / packages)
        required = (
            {"student_notes", "student_quiz"}
            if workflow == "student"
            else {"creator_outline", "creator_script"}
            if workflow == "creator"
            else {"investigation", "code_helper", "testing"}
        )
        if workflow == "developer" and not demo:
            agents = registry.role_agents(workflow)
            registered_planner(registry)
            kinds = set()
            for agent in agents:
                try:
                    kinds.add(developer_kind(agent))
                except ValueError:
                    continue
            if kinds != {
                "developer_investigate",
                "developer_patch",
                "developer_test",
                "developer_baseline",
            }:
                raise ValueError("Package is missing supported planning capabilities")
        elif not required <= set(registry.role(workflow).agents):
            raise ValueError("Package is missing required workflow agents")
        record(
            "packages",
            True,
            f"Registered agents: {len(registry.agents())}; role packages: {len(registry.roles())}.",
        )
    except Exception:
        record("packages", False, "Check role and agent manifests; package loading failed.")
    try:
        provider = None if demo else ModelSettings.from_environment()
        record(
            "provider",
            demo or (provider is not None and provider.allow_live_calls),
            "Offline demo uses scripted responses; provider configuration is ignored."
            if demo
            else "Provider configuration and live-call authorization are present; "
            "connectivity is unverified."
            if provider and provider.allow_live_calls
            else "Live calls are disabled; explicit authorization is required."
            if provider
            else "Set AGENTOS_MODEL and the provider key when required in .env.",
        )
    except ValueError:
        record(
            "provider", False, "Model configuration is invalid; check the endpoint and settings."
        )
    try:
        role = UserRole(os.environ.get("AGENTOS_USER_ROLE", "operator"))
        record(
            "permissions",
            role != UserRole.VIEWER,
            "Operator/Admin can run and review missions."
            if role != UserRole.VIEWER
            else "Viewer is read-only and cannot run missions.",
        )
    except ValueError:
        record("permissions", False, "AGENTOS_USER_ROLE must be viewer, operator, or admin.")
    if workflow in {"creator", "student"}:
        if demo:
            try:
                demo_workspace(root)
                record(
                    "demo_sample", True, "Bundled Calculator fixture is unchanged for demo startup."
                )
            except Exception:
                record(
                    "demo_sample", False, "Demo startup requires the unchanged Calculator sample."
                )
        assets = client_assets_valid(root / "frontend" / "dist")
        record("client", assets, "Client assets exist." if assets else "Build the client first.")
        return SetupReport(
            checks=tuple(checks), execution_mode="demo" if demo else "live", workflow=workflow
        )
    record("git", shutil.which("git") is not None, "Git is required for scratch patch checking.")
    config = Path(os.environ.get("AGENTOS_WORKSPACE_CONFIG", ".agentos/workspace.json"))
    try:
        path = config if config.is_absolute() else root / config
        settings = (
            demo_workspace(root)
            if demo
            else WorkspaceSettings.model_validate_json(path.read_text(encoding="utf-8"))
        )
        if not settings.repository.is_absolute():
            settings = settings.model_copy(update={"repository": root / settings.repository})
        files = read_workspace_source(settings)
        record(
            "workspace",
            True,
            f"Validated {len(files)} selected UTF-8 source files; source was not changed.",
        )
        missing = any(
            not shutil.which(sys.executable if command[0] in {"python", "python3"} else command[0])
            for command in settings.test_commands
        )
        record(
            "test_runners",
            not missing,
            "A configured test runner is missing from disk or PATH."
            if missing
            else "Configured test runners exist; commands were not executed.",
        )
    except Exception:
        record(
            "workspace",
            False,
            "Offline demo requires the unchanged bundled Calculator sample."
            if demo
            else "Check workspace.json, paths, UTF-8 encoding, and size limits. "
            "Use setup-sample for the bundled project.",
        )
        record(
            "test_runners", False, "Validate workspace configuration before checking test runners."
        )
    assets = client_assets_valid(root / "frontend" / "dist")
    record(
        "client",
        assets,
        "Client entry point and referenced assets exist."
        if assets
        else "Build the client: npm --prefix frontend ci, then npm --prefix frontend run build.",
    )
    return SetupReport(
        checks=tuple(checks), execution_mode="demo" if demo else "live", workflow=workflow
    )
