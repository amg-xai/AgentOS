"""Local setup and loopback launcher. Never overwrites existing configuration."""

import argparse
import os
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

from agentos.adapters.diagnostics import diagnose
from agentos.domain.workspace import WorkspaceSettings


def setup_sample(root: Path) -> Path:
    directory = root / ".agentos"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "workspace.json"
    settings = WorkspaceSettings(
        name="Calculator acceptance project",
        repository=(root / "samples" / "calculator").resolve(strict=True),
        files=("calculator.py", "test_calculator.py", "README.md"),
        test_commands=(("python", "-m", "unittest", "discover", "-v"),),
    )
    with target.open("x", encoding="utf-8") as output:
        output.write(settings.model_dump_json(indent=2) + "\n")
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description="AgentOS local Mission Control")
    parser.add_argument("command", choices=("serve", "setup-sample", "doctor"))
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--json", action="store_true", help="Print doctor results as JSON")
    parser.add_argument(
        "--demo", action="store_true", help="Use the isolated scripted Calculator demo"
    )
    args = parser.parse_args()
    if args.demo and args.command == "setup-sample":
        parser.error("Demo mode selects its sample without changing workspace configuration")
    root = args.root.resolve(strict=True)
    if not (root / "packages").is_dir():
        parser.error("Run from the AgentOS checkout, or select it with --root")
    if args.command == "setup-sample":
        try:
            print(f"Sample workspace configured: {setup_sample(root)}")
        except FileExistsError:
            parser.error("Workspace configuration already exists; it was preserved")
        return
    if not 1 <= args.port <= 65535:
        parser.error("Port must be between 1 and 65535")
    os.chdir(root)
    load_dotenv(root / ".env", override=False)
    if args.command == "doctor":
        report = diagnose(root, demo=args.demo)
        if args.json:
            print(report.model_dump_json(indent=2))
        else:
            for check in report.checks:
                print(f"{'PASS' if check.passed else 'BLOCKED'} [{check.id}] {check.detail}")
            print("Read-only checks only. Live model and browser acceptance remain separate.")
        raise SystemExit(0 if report.configured_ready else 1)
    print(f"Mission Control: http://127.0.0.1:{args.port}/app/")
    if not (root / "frontend" / "dist" / "index.html").exists():
        parser.error(
            "Build the client first: npm --prefix frontend ci; npm --prefix frontend run build"
        )
    factory = "create_demo_app" if args.demo else "create_app"
    if args.demo:
        print("Offline demo: scripted responses, no model calls; separate .agentos/demo history.")
    uvicorn.run(f"agentos.api.app:{factory}", factory=True, host="127.0.0.1", port=args.port)
