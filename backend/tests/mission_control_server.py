"""Test-only real HTTP server; never a production startup or demo option."""

import difflib
import json
import os
import shutil
import socket
import sys
import threading
from pathlib import Path

import httpx
import uvicorn
from student_source_fixture import output_for
from test_developer import ISSUE, issue_plan

from agentos.adapters.provider import ModelSettings, ResponsesExecutor
from agentos.api.app import create_app
from agentos.domain.workspace import WorkspaceSettings


def main():
    root = Path(sys.argv[1]).resolve(strict=True)
    project = Path(__file__).resolve().parents[2]
    source = root / "source"
    if not source.exists():
        shutil.copytree(project / "samples" / "calculator", source)
    # Persist test observations across server restarts, outside product APIs.
    observations = root / "model-inputs.jsonl"

    def transport(request):
        body = json.loads(request.content)
        inputs = json.loads(body["input"])
        agent = body["text"]["format"]["name"]
        with observations.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"agent": agent, "inputs": inputs}) + "\n")
        if agent.startswith("student_"):
            outputs = output_for(agent, inputs)
            if "invalid evidence" in inputs["goal"] and agent == "student_research":
                outputs["research"]["evidence"][0]["quote"] = "Invented quotation"
        elif agent == "developer_planner":
            outputs = issue_plan()
        elif agent == "issue_specification":
            outputs = {"issue": ISSUE}
        elif agent == "investigation":
            outputs = {"findings": "Addition subtracts; preserve all existing assertions"}
        elif agent == "code_helper":
            revision = inputs.get("patch_revision", {}).get("number", 0)
            goal = inputs["goal"]
            passes = "revision" not in goal or ("exhaust" not in goal and revision == 2)
            before = inputs["source_files"]["calculator.py"]
            after = before.replace(
                "return left - right", "return left + right" if passes else "return left * right"
            )
            diff = "diff --git a/calculator.py b/calculator.py\n" + "".join(
                difflib.unified_diff(
                    before.splitlines(True),
                    after.splitlines(True),
                    fromfile="a/calculator.py",
                    tofile="b/calculator.py",
                )
            )
            outputs = {"diff": diff, "summary": "Injected patch; actual tests decide its outcome"}
        else:
            raise AssertionError(f"Unexpected model capability: {agent}")
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": json.dumps(outputs)}],
                    }
                ],
            },
        )

    assert os.environ.get("AGENTOS_ALLOW_LIVE_MODELS") == "0"
    model = ResponsesExecutor(
        ModelSettings(model="INJECTED ACCEPTANCE TRANSPORT", allow_live_calls=False),
        transport=httpx.MockTransport(transport),
    )
    workspace = WorkspaceSettings(
        name="Isolated Calculator acceptance",
        repository=source,
        files=("calculator.py", "test_calculator.py", "README.md"),
        test_commands=(("python", "-m", "unittest", "discover", "-v"),),
        test_timeout_seconds=30,
    )
    app = create_app(
        package_root=project / "packages",
        db_path=root / "missions.sqlite3",
        artifact_root=root / "artifacts",
        workspace=workspace,
        model=model,
    )
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))

        def shutdown():
            sys.stdin.read()
            server.should_exit = True

        threading.Thread(target=shutdown, daemon=True).start()
        print(json.dumps({"origin": f"http://127.0.0.1:{listener.getsockname()[1]}"}), flush=True)
        server.run(sockets=[listener])


if __name__ == "__main__":
    main()
