"""Scoped source snapshots, patch checking, and explicitly configured test execution.

Scratch directories protect source files, not the host OS. Run only trusted code.
"""

import asyncio
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from agentos.adapters.workspace import WorkspaceStore
from agentos.domain.agents import ExecutionContext
from agentos.domain.missions import StateConflict
from agentos.domain.workspace import WorkspaceSettings, scoped_path


def minimal_environment() -> dict[str, str]:
    names = {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "HOME", "LANG"}
    return {key: value for key, value in os.environ.items() if key.upper() in names} | {
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
    }


class LocalWorkspaceTools:
    def __init__(self, settings: WorkspaceSettings, store: WorkspaceStore, scratch: Path) -> None:
        self.settings = settings
        self.store = store
        self.scratch = scratch.resolve()
        self.scratch.mkdir(parents=True, exist_ok=True)

    async def read(self, inputs: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
        return await asyncio.to_thread(self._read, context)

    def _read(self, context: ExecutionContext) -> dict[str, Any]:
        if context.workspace_id != "local":
            raise StateConflict("Unknown workspace")
        files = (
            self.store.execution_snapshot(context.mission_id, self.settings)[0]
            if context.planning_version in (2, 3)
            else self.store.snapshot(context.mission_id, self.settings)
        )
        return {"files": files}

    def _scratch(self, files: dict[str, str]) -> Path:
        directory = Path(tempfile.mkdtemp(prefix="run-", dir=self.scratch))
        for relative, content in files.items():
            target = directory / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content.encode("utf-8"))
        return directory

    def _prepare(self, diff: str, context: ExecutionContext) -> Path:
        if len(diff.encode()) > 200_000 or not diff.strip():
            raise StateConflict("Patch must be nonempty and at most 200 KB")
        files = self._read(context)["files"]
        # Restrict patches to existing, explicitly selected text files. No renames,
        # mode changes, binary patches, new paths, symlinks, or submodules.
        paths = []
        for line in diff.splitlines():
            if line.startswith("diff --git ") and line not in {
                f"diff --git a/{path} b/{path}" for path in files
            }:
                raise StateConflict("Patch git header is outside the selected scope")
            if line.startswith(("--- ", "+++ ")):
                label = line[4:].split("\t", 1)[0]
                if not label.startswith(("a/", "b/")):
                    raise StateConflict("Patch must modify existing selected files")
                path = scoped_path(label[2:])
                if path not in files:
                    raise StateConflict("Patch targets a file outside the selected scope")
                paths.append(path)
            if re.match(
                r"(?:old mode|new mode|new file mode|deleted file mode|rename |copy |GIT binary)",
                line,
            ):
                raise StateConflict("Patch operation is outside the supported text edit scope")
        if not paths:
            raise StateConflict("Patch has no supported file headers")
        directory = self._scratch(files)
        patch = directory / "agentos-proposed.patch"
        patch.write_bytes(diff.encode("utf-8"))
        git = shutil.which("git")
        if not git:
            raise StateConflict("Git is required to check patches")
        for args in (["init", "--quiet"], ["apply", "--check", str(patch)], ["apply", str(patch)]):
            result = subprocess.run(
                [git, *args],
                cwd=directory,
                env=minimal_environment(),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=15,
                check=False,
            )
            if result.returncode:
                raise StateConflict("Patch did not apply cleanly to the immutable source snapshot")
        return directory

    async def patch(self, inputs: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
        directory = await asyncio.to_thread(self._prepare, inputs["diff"], context)
        return {"checked": True, "scratch_id": directory.name}

    async def test(self, inputs: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
        if inputs.get("operation") == "baseline":
            if context.planning_version not in (2, 3):
                raise StateConflict("Baseline requires Developer planning version 2 or 3")
            return await asyncio.to_thread(self._test, None, context)
        return await asyncio.to_thread(self._test, inputs["diff"], context)

    def _test(self, diff: str | None, context: ExecutionContext) -> dict[str, Any]:
        files = self._read(context)["files"]
        commands = self.settings.test_commands
        timeout = self.settings.test_timeout_seconds
        digests = []
        if context.planning_version in (2, 3):
            files, recipe, source_digest, recipe_digest = self.store.execution_snapshot(
                context.mission_id, self.settings
            )
            commands, timeout = recipe["commands"], recipe["timeout_seconds"]
            digests = [f"Source SHA-256: {source_digest}", f"Recipe SHA-256: {recipe_digest}"]
        directory = self._prepare(diff, context) if diff is not None else self._scratch(files)
        reports = [
            f"Patch SHA-256: {hashlib.sha256(diff.encode()).hexdigest()}"
            if diff is not None
            else "Baseline: immutable source without a patch",
            f"Scratch directory: {directory.name}",
            *digests,
        ]
        passed = True
        outcomes = []
        for configured in commands:
            command = list(configured)
            if command[0] in {"python", "python3"}:
                command[0] = sys.executable
            # A file-backed log bounds memory even when a child emits large output.
            with tempfile.TemporaryFile() as output:
                process = subprocess.Popen(
                    command,
                    cwd=directory,
                    env=minimal_environment(),
                    stdin=subprocess.DEVNULL,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    shell=False,
                    start_new_session=os.name != "nt",
                    creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
                )
                timed_out = False
                output_limited = False
                deadline = time.monotonic() + timeout
                try:
                    while process.poll() is None:
                        output_limited = os.fstat(output.fileno()).st_size > 1_000_000
                        if time.monotonic() >= deadline or output_limited:
                            raise subprocess.TimeoutExpired(command, timeout)
                        time.sleep(0.05)
                    code = process.wait()
                except subprocess.TimeoutExpired:
                    timed_out = not output_limited
                    if os.name == "nt":
                        subprocess.run(
                            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            timeout=10,
                            check=False,
                        )
                    else:
                        kill_group = getattr(os, "killpg", None)
                        if kill_group is not None:
                            kill_group(process.pid, 9)
                    process.kill()
                    code = process.wait(timeout=5)
                output_limited = output_limited or os.fstat(output.fileno()).st_size > 1_000_000
                output.seek(0)
                text = output.read(32_001).decode("utf-8", errors="replace")
            passed = passed and code == 0 and not timed_out and not output_limited
            outcomes.append(
                {"exit_code": code, "timed_out": timed_out, "output_limited": output_limited}
            )
            reports.append(
                f"Command argv: {list(configured)!r}\nExit code: {code}\n"
                f"Timed out: {timed_out}\nOutput limit exceeded: {output_limited}\n{text[:32000]}\n"
                + ("[Output truncated]" if len(text) > 32000 else "")
            )
        if diff is None:
            return {
                "baseline_passed": passed,
                "baseline_report": "\n\n".join(reports),
                "baseline_summary": json.dumps({"passed": passed, "outcomes": outcomes}),
            }
        return {"passed": passed, "report": "\n\n".join(reports)}


class MethodTool:
    def __init__(self, workspace: LocalWorkspaceTools, method: str) -> None:
        self.workspace = workspace
        self.method = method

    async def execute(self, inputs: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
        if self.method == "read":
            return await self.workspace.read(inputs, context)
        if self.method == "patch":
            return await self.workspace.patch(inputs, context)
        if self.method == "test":
            return await self.workspace.test(inputs, context)
        raise StateConflict("Unknown local tool method")
