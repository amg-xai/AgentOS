"""Versioned baseline evidence, frozen recipes, and exact final review boundaries."""

import asyncio
import copy
import json
import sqlite3
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_developer import PATCH, configured_app, model_transport, plan_data
from test_developer import workspace as workspace_fixture
from test_orchestration import FixtureExecutor, bindings
from test_planning import compiled

from agentos.adapters.artifacts import ArtifactStore
from agentos.adapters.local_tools import LocalWorkspaceTools
from agentos.adapters.sqlite import SQLiteMissionRepository
from agentos.adapters.workspace import WorkspaceStore
from agentos.domain.agents import AgentResult, ExecutionContext, Permission
from agentos.domain.artifacts import ArtifactDraft
from agentos.domain.governance import UserRole
from agentos.domain.missions import (
    MissionCreate,
    MissionValidationError,
    PlanningEvidence,
    StateConflict,
)
from agentos.domain.workspace import MemoryCreate, WorkspaceSettings
from agentos.services.missions import MissionService
from agentos.services.orchestration import Orchestrator
from agentos.services.planning import developer_kind, validate_planned_mission

workspace = workspace_fixture


def context(version=2):
    return ExecutionContext(
        workspace_id="local", mission_id="frozen", task_id="baseline", planning_version=version
    )


def tools(tmp_path, workspace):
    return LocalWorkspaceTools(
        workspace, WorkspaceStore(tmp_path / "workspace.sqlite3"), tmp_path / "scratch"
    )


def protected_settings(workspace):
    return WorkspaceSettings(
        **(workspace.model_dump() | {"protected_files": ("test_calculator.py",)})
    )


@pytest.mark.parametrize("version", [2, 3])
def test_protected_verification_freezes_across_restart_retry_and_configuration(
    tmp_path, workspace, version
):
    protected = protected_settings(workspace)
    baseline = asyncio.run(
        tools(tmp_path, protected).test({"operation": "baseline"}, context(version))
    )
    assert baseline["baseline_passed"] is False
    assert "Verification: protected" in baseline["baseline_report"]
    changed = WorkspaceSettings(
        **(
            workspace.model_dump()
            | {"files": ("calculator.py",), "test_commands": (("python", "missing.py"),)}
        )
    )
    (workspace.repository / "test_calculator.py").unlink()
    for _ in range(2):
        result = asyncio.run(tools(tmp_path, changed).test({"diff": PATCH}, context(version)))
        assert result["passed"] is True
        assert "Verification: protected" in result["report"]
        assert "Protected file SHA-256: test_calculator.py:" in result["report"]
        assert "missing.py" not in result["report"]


@pytest.mark.parametrize("version", [2, 3])
def test_patch_cannot_touch_frozen_protected_test(tmp_path, workspace, version):
    instance = tools(tmp_path, protected_settings(workspace))
    instance._read(context(version))
    bad = (
        "diff --git a/test_calculator.py b/test_calculator.py\n"
        "--- a/test_calculator.py\n+++ b/test_calculator.py\n"
        "@@ -1 +1 @@\n-import unittest\n+raise SystemExit(0)\n"
    )
    with patch(
        "agentos.adapters.local_tools.subprocess.run", side_effect=AssertionError("No Git dispatch")
    ):
        with pytest.raises(StateConflict, match="protected verification"):
            instance._prepare(bad, context(version))


@pytest.mark.parametrize("damage", ["missing", "changed", "symlink"])
def test_missing_or_modified_verification_prevents_test_execution(tmp_path, workspace, damage):
    instance = tools(tmp_path, protected_settings(workspace))
    scratch = instance._scratch

    def damaged(files):
        directory = scratch(files)
        target = directory / "test_calculator.py"
        if damage == "changed":
            target.write_text("raise SystemExit(0)\n")
        else:
            target.unlink()
            if damage == "symlink":
                try:
                    target.symlink_to(workspace.repository / "test_calculator.py")
                except OSError:
                    pytest.skip("Symlink creation unavailable")
        return directory

    instance._scratch = damaged
    with patch(
        "agentos.adapters.local_tools.subprocess.Popen", side_effect=AssertionError("No tests")
    ):
        result = asyncio.run(instance.test({"operation": "baseline"}, context(3)))
    assert result["baseline_passed"] is False
    assert "integrity failed before execution" in result["baseline_report"]


def test_verification_modified_during_zero_exit_command_cannot_pass(tmp_path, workspace):
    runner = workspace.repository / "runner.py"
    runner.write_text(
        "from pathlib import Path\nPath('test_calculator.py').write_text('weakened')\n"
    )
    config = WorkspaceSettings(
        **(
            workspace.model_dump()
            | {
                "files": workspace.files + ("runner.py",),
                "protected_files": ("test_calculator.py",),
                "test_commands": (("python", "runner.py"),),
            }
        )
    )
    result = asyncio.run(tools(tmp_path, config).test({"diff": PATCH}, context(3)))
    assert result["passed"] is False
    assert "Exit code: 0" in result["report"]
    assert "integrity failed after execution" in result["report"]


def test_old_recipe_never_acquires_protection_from_new_settings(tmp_path, workspace):
    instance = tools(tmp_path, workspace)
    instance._read(context(3))
    result = asyncio.run(
        tools(tmp_path, protected_settings(workspace)).test({"diff": PATCH}, context(3))
    )
    assert result["passed"] is True
    assert "Verification: legacy/unprotected" in result["report"]


def test_integrity_failure_cannot_be_human_accepted(tmp_path, workspace):
    (workspace.repository / "runner.py").write_text(
        "from pathlib import Path\nPath('test_calculator.py').unlink()\n"
    )
    config = WorkspaceSettings(
        **(
            workspace.model_dump()
            | {
                "files": workspace.files + ("runner.py",),
                "protected_files": ("test_calculator.py",),
                "test_commands": (("python", "runner.py"),),
            }
        )
    )
    with TestClient(configured_app(tmp_path, config)) as client:
        mission = client.post("/workflows/developer", json={"goal": "Fix addition"}).json()
        base = f"/missions/{mission['id']}"
        result = client.post(base + "/run", json={"expected_version": mission["version"]}).json()
        assert result["status"] == "WAITING_APPROVAL"
        assert result["tasks"][-1]["outputs"]["passed"] is False
        approval = client.get(base + "/approvals").json()[0]
        response = client.post(
            f"/approvals/{approval['id']}/decision",
            json={
                "expected_version": result["version"],
                "payload_digest": approval["payload_digest"],
                "decision": "approve",
            },
        )
        assert response.status_code == 409
        assert "Tests must explicitly pass" in response.json()["detail"]


@pytest.mark.parametrize("evidence", [None, {}, {"test_calculator.py": "bad"}])
def test_malformed_frozen_verification_is_rejected(tmp_path, workspace, evidence):
    import hashlib

    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    store.execution_snapshot("frozen", protected_settings(workspace))
    with sqlite3.connect(store.path) as conn:
        payload, source_digest = conn.execute(
            "SELECT payload, source_digest FROM recipes"
        ).fetchone()
        recipe = json.loads(payload)
        recipe["verification"] = evidence
        payload = json.dumps(recipe)
        digest = hashlib.sha256((source_digest + payload).encode()).hexdigest()
        conn.execute("UPDATE recipes SET payload=?, digest=?", (payload, digest))
    with pytest.raises(StateConflict, match="verification evidence"):
        store.execution_snapshot("frozen", workspace)


@pytest.mark.parametrize(
    "paths",
    [
        ("../tests.py",),
        ("missing.py",),
        ("test_calculator.py", "TEST_calculator.py"),
        ("calculator.py", "test_calculator.py"),
    ],
)
def test_protected_verification_scope_is_explicit_and_valid(workspace, paths):
    with pytest.raises(ValidationError):
        WorkspaceSettings(**(workspace.model_dump() | {"protected_files": paths}))


@pytest.mark.parametrize(
    "case",
    [
        "missing",
        "duplicate",
        "patch_missing",
        "review_missing",
        "wrong_source",
        "wrong_output",
        "baseline_binding",
        "downgrade",
    ],
)
def test_invalid_baseline_plans_are_rejected_before_calls(registry, case):
    data = copy.deepcopy(plan_data())
    investigation, patch_task, baseline, review = data["tasks"]
    if case == "missing":
        data["tasks"].remove(baseline)
    elif case == "duplicate":
        data["tasks"].append(baseline | {"id": "duplicate_baseline"})
    elif case == "patch_missing":
        patch_task["bindings"].pop()
        patch_task["dependencies"].remove("baseline")
    elif case == "review_missing":
        review["bindings"].pop()
        review["dependencies"].remove("baseline")
    elif case == "wrong_source":
        patch_task["bindings"][-1]["task_id"] = investigation["id"]
    elif case == "wrong_output":
        review["bindings"][-1]["output_key"] = "baseline_summary"
    elif case == "baseline_binding":
        baseline["dependencies"] = [investigation["id"]]
        baseline["bindings"] = [
            {"input_key": "context", "task_id": investigation["id"], "output_key": "findings"}
        ]
    else:
        data["contract_version"] = 1
    executor = FixtureExecutor()
    with pytest.raises((MissionValidationError, ValidationError)):
        compiled(registry, data, bindings(executor))
    assert executor.calls == []


@pytest.mark.parametrize("version", [0, 4, True, "2"])
def test_unknown_or_noninteger_contract_versions_rejected(version):
    with pytest.raises(ValidationError):
        PlanningEvidence(planner_id="developer_planner", rationale="test", contract_version=version)


@pytest.mark.parametrize("change", ["permissions", "tools", "output_type"])
def test_baseline_capabilities_cannot_be_elevated_or_change_outcome_types(registry, change):
    agent = registry.agent("baseline_testing")
    if change == "permissions":
        agent = agent.model_copy(update={"permissions": (*agent.permissions, Permission.WRITE)})
    elif change == "tools":
        agent = agent.model_copy(update={"tools": (*agent.tools, "git")})
    else:
        schema = copy.deepcopy(agent.output_schema)
        schema["properties"]["baseline_passed"]["type"] = "string"
        agent = agent.model_copy(update={"output_schema": schema})
    with pytest.raises(MissionValidationError):
        developer_kind(agent)


def test_saved_version_two_cannot_downgrade_before_claim(registry, tmp_path):
    request = compiled(registry)
    evidence = request.planning.model_copy(update={"contract_version": 1})
    repository = SQLiteMissionRepository(tmp_path / "missions.sqlite3")
    mission = MissionService(registry, repository).create(
        request.model_copy(update={"planning": evidence})
    )
    executor = FixtureExecutor()
    runner = Orchestrator(
        registry, repository, bindings(executor), ArtifactStore(tmp_path / "artifacts")
    )
    with pytest.raises(MissionValidationError):
        asyncio.run(runner.run(mission.id, 1, UserRole.OPERATOR))
    assert repository.claim(mission.id) is None and executor.calls == []


@pytest.mark.parametrize(
    "script,passed,flag",
    [
        ("print('private-log'); raise SystemExit(7)\n", False, "Exit code: 7"),
        ("print('private-log')\n", True, "Exit code: 0"),
        ("import time; time.sleep(30)\n", False, "Timed out: True"),
        ("print('x' * 2000000)\n", False, "Output limit exceeded: True"),
    ],
)
@pytest.mark.parametrize("version", [2, 3])
def test_baseline_actual_outcomes_and_sanitized_summary(
    tmp_path, workspace, script, passed, flag, version
):
    (workspace.repository / "runner.py").write_text(script)
    settings = WorkspaceSettings(
        **(
            workspace.model_dump()
            | {
                "files": workspace.files + ("runner.py",),
                "test_commands": (("python", "runner.py"),),
                "test_timeout_seconds": 1,
            }
        )
    )
    result = asyncio.run(
        tools(tmp_path, settings).test({"operation": "baseline"}, context(version))
    )
    assert result["baseline_passed"] is passed
    assert flag in result["baseline_report"]
    summary = json.loads(result["baseline_summary"])
    assert summary["passed"] is passed and len(summary["outcomes"]) == 1
    assert "private-log" not in result["baseline_summary"]
    assert "runner.py" not in result["baseline_summary"]
    assert len(result["baseline_summary"]) < 2000


@pytest.mark.parametrize("version", [2, 3])
def test_restart_uses_identical_source_and_recipe_despite_settings_changes(
    tmp_path, workspace, version
):
    baseline = asyncio.run(
        tools(tmp_path, workspace).test({"operation": "baseline"}, context(version))
    )
    changed = WorkspaceSettings(
        **(
            workspace.model_dump()
            | {
                "files": ("calculator.py",),
                "test_commands": (("python", "missing.py"),),
                "test_timeout_seconds": 1,
            }
        )
    )
    (workspace.repository / "calculator.py").write_text("changed original source\n")
    result = asyncio.run(tools(tmp_path, changed).test({"diff": PATCH}, context(version)))
    assert baseline["baseline_passed"] is False and result["passed"] is True
    for prefix in ("Source SHA-256:", "Recipe SHA-256:"):
        assert (
            next(
                line for line in baseline["baseline_report"].splitlines() if line.startswith(prefix)
            )
            in result["report"]
        )
    assert "missing.py" not in result["report"]
    assert (workspace.repository / "calculator.py").read_text() == "changed original source\n"


@pytest.mark.parametrize("damage", ["recipe", "snapshot", "missing_recipe", "missing_snapshot"])
@pytest.mark.parametrize("version", [2, 3])
def test_damaged_frozen_evidence_prevents_subprocess_execution(
    tmp_path, workspace, damage, version
):
    runner = tools(tmp_path, workspace)
    asyncio.run(runner.read({}, context(version)))
    with sqlite3.connect(runner.store.path) as conn:
        if damage.startswith("missing"):
            conn.execute(
                "DELETE FROM " + ("recipes" if damage == "missing_recipe" else "snapshots")
            )
        else:
            conn.execute(
                "UPDATE "
                + ("recipes" if damage == "recipe" else "snapshots")
                + " SET payload = '{}'"
            )
    with patch("agentos.adapters.local_tools.subprocess.Popen") as spawn:
        with pytest.raises(StateConflict, match="integrity|incomplete"):
            asyncio.run(runner.test({"operation": "baseline"}, context(version)))
        spawn.assert_not_called()


@pytest.mark.parametrize("failure", ["missing", "spawn"])
def test_runner_failure_blocks_patch_without_approval(tmp_path, workspace, failure):
    settings = (
        WorkspaceSettings(**(workspace.model_dump() | {"test_commands": (("pytest",),)}))
        if failure == "missing"
        else workspace
    )
    with TestClient(configured_app(tmp_path, settings)) as client:
        mission = client.post("/workflows/developer", json={"goal": "Fix addition"}).json()
        target = (
            "agentos.adapters.workspace.shutil.which"
            if failure == "missing"
            else "agentos.adapters.local_tools.subprocess.Popen"
        )
        with patch(
            target,
            **(
                {"return_value": None}
                if failure == "missing"
                else {"side_effect": OSError("private spawn error")}
            ),
        ):
            result = client.post(
                f"/missions/{mission['id']}/run", json={"expected_version": 1}
            ).json()
        by_id = {task["id"]: task for task in result["tasks"]}
        failed_id = "investigate" if failure == "missing" else "baseline"
        assert by_id[failed_id]["status"] == "FAILED"
        assert by_id["fix"]["status"] == "BLOCKED" and by_id["verify"]["status"] == "BLOCKED"
        assert client.get(f"/missions/{mission['id']}/approvals").json() == []
        assert "private spawn error" not in json.dumps(result)


@pytest.mark.parametrize("damaged_name", ["reviewed-baseline-report.txt", "test-report.txt"])
def test_review_copy_exactness_restart_damage_and_denial_retry(tmp_path, workspace, damaged_name):
    seen = []

    def transport(request):
        body = json.loads(request.content)
        if body["text"]["format"]["name"] == "code_helper":
            inputs = json.loads(body["input"])
            seen.append(inputs)
            assert "baseline_report" not in inputs
            assert json.loads(inputs["baseline_summary"])["passed"] is False
        return model_transport(request)

    with TestClient(configured_app(tmp_path, workspace, transport)) as client:
        mission = client.post("/workflows/developer", json={"goal": "Fix addition"}).json()
        base = f"/missions/{mission['id']}"
        result = client.post(base + "/run", json={"expected_version": 1}).json()
        by_id = {task["id"]: task for task in result["tasks"]}
        assert by_id["baseline"]["status"] == "COMPLETED"
        assert by_id["baseline"]["outputs"]["baseline_passed"] is False
        assert by_id["verify"]["outputs"]["passed"] is True
        artifacts = client.get(base + "/artifacts").json()
        baseline = next(a for a in artifacts if a["name"] == "baseline-report.txt")
        reviewed = next(a for a in artifacts if a["name"] == "reviewed-baseline-report.txt")
        assert (
            client.get(f"/artifacts/{baseline['id']}/content").content
            == client.get(f"/artifacts/{reviewed['id']}/content").content
        )
        damaged = next(a for a in artifacts if a["name"] == damaged_name)
        (tmp_path / "artifacts" / f"{damaged['id']}.txt").write_text("damaged")
    with TestClient(configured_app(tmp_path, workspace, transport)) as client:
        approval = client.get(base + "/approvals").json()[0]
        payload = {
            "expected_version": result["version"],
            "payload_digest": approval["payload_digest"],
            "decision": "approve",
        }
        assert client.post(f"/approvals/{approval['id']}/decision", json=payload).status_code == 409
        denied = client.post(
            f"/approvals/{approval['id']}/decision", json=payload | {"decision": "deny"}
        ).json()
        retried = client.post(
            base + "/tasks/verify/actions",
            json={"expected_version": denied["version"], "action": "retry"},
        ).json()
        rerun = client.post(base + "/run", json={"expected_version": retried["version"]}).json()
        assert [task["attempts"] for task in rerun["tasks"]] == [1, 1, 1, 1, 2]
        assert len(client.get(base + "/artifacts").json()) == 16
        assert len(client.get(base + "/approvals?pending_only=false").json()) == 2
        assert (
            client.post(
                f"/approvals/{approval['id']}/decision",
                json=payload | {"expected_version": rerun["version"]},
            ).status_code
            == 409
        )
    assert len(seen) == 1


@pytest.mark.parametrize("mode", ["missing", "stale"])
def test_executor_cannot_stage_missing_or_substituted_baseline_review(registry, tmp_path, mode):
    class DamagedReview(FixtureExecutor):
        async def execute(self, agent, inputs, context):
            result = await super().execute(agent, inputs, context)
            if agent.capability == "developer_test":
                drafts = (
                    result.artifacts[:-1]
                    if mode == "missing"
                    else (
                        *result.artifacts[:-1],
                        ArtifactDraft(
                            name="reviewed-baseline-report.txt", content="Other baseline"
                        ),
                    )
                )
                return AgentResult(outputs=result.outputs, artifacts=drafts)
            return result

    executor = DamagedReview()
    repository = SQLiteMissionRepository(tmp_path / "missions.sqlite3")
    mission = MissionService(registry, repository).create(compiled(registry))
    runner = Orchestrator(
        registry, repository, bindings(executor), ArtifactStore(tmp_path / "artifacts")
    )
    result = asyncio.run(runner.run(mission.id, 1, UserRole.OPERATOR))
    assert result.tasks[-1].status == "FAILED" and repository.approvals(mission.id) == []


def test_version_one_workspace_migration_and_saved_mission_restart(registry, tmp_path, workspace):
    path = tmp_path / "workspace.sqlite3"
    store = WorkspaceStore(path)
    snapshot = store.snapshot("legacy", workspace)
    note = store.add_note(MemoryCreate(title="Legacy note", content="Preserve migration evidence"))
    with sqlite3.connect(path) as conn:
        conn.execute("DROP TABLE recipes")
        conn.execute("DROP TABLE memory_index")
        conn.execute("PRAGMA user_version = 1")
    migrated = WorkspaceStore(path)
    assert migrated.snapshot("legacy", workspace) == snapshot and migrated.notes()[0] == note
    request = compiled(registry).model_dump()
    request["tasks"] = [task for task in request["tasks"] if task["id"] != "baseline"]
    request["planning"].pop("contract_version")
    request["planning"]["objectives"].pop("baseline")
    for task in request["tasks"]:
        task["dependencies"] = tuple(dep for dep in task["dependencies"] if dep != "baseline")
        task["input_bindings"] = {
            key: value
            for key, value in task["input_bindings"].items()
            if value["task_id"] != "baseline"
        }
    legacy = MissionCreate.model_validate(request)
    validate_planned_mission(legacy, registry, bindings(FixtureExecutor()))
    repository = SQLiteMissionRepository(tmp_path / "missions.sqlite3")
    mission = MissionService(registry, repository).create(legacy)
    with TestClient(configured_app(tmp_path, workspace)) as client:
        result = client.post(f"/missions/{mission.id}/run", json={"expected_version": 1}).json()
        assert (
            result["status"] == "WAITING_APPROVAL" and result["planning"]["contract_version"] == 1
        )
        assert len(client.get(f"/missions/{mission.id}/artifacts").json()) == 5
        assert client.get("/memory").json()[0]["id"] == note.id
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
        assert conn.execute("SELECT count(*) FROM recipes").fetchone()[0] == 0
