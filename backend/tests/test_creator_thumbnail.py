"""Injected model planning plus real PNGs, storage, review and restart; no live calls."""

import copy
import hashlib
import json
import sqlite3
from io import BytesIO

import httpx
import pytest
from creator_plan_fixture import creator_plan
from fastapi.testclient import TestClient
from PIL import Image
from test_creator import GOAL, OUTLINE, SCRIPT, decide
from test_creator_research import RESEARCH, SOURCE
from test_demo import demo_root as demo_fixture

from agentos.adapters.artifacts import ArtifactStore
from agentos.adapters.creator import CREATOR_DEMO_GOAL, CreatorExecutor
from agentos.adapters.provider import ModelSettings, ResponsesExecutor
from agentos.adapters.thumbnail import render_thumbnail
from agentos.api.app import create_app
from agentos.domain.agents import Permission
from agentos.domain.artifacts import ArtifactDraft
from agentos.domain.creator_planning import CreatorThumbnailPlan
from agentos.domain.governance import UserRole
from agentos.domain.thumbnail import ThumbnailLayout
from agentos.domain.workspace import CreatorMissionCreate
from agentos.services.creator_planning import compile_creator_plan
from agentos.services.execution import ExecutorRegistry
from agentos.services.registry import AgentRegistry

demo_root = demo_fixture
LAYOUT = dict(
    headline="Local missions, real evidence",
    subtitle="Inspect before accepting",
    background="#122033",
    foreground="#FFFFFF",
    accent="#50C8B0",
    composition="left",
    decoration="circle",
)


def thumbnail_plan(sources=False, refine=False, ids=None):
    plan = creator_plan(sources=sources, refine=refine, ids=ids)
    script = plan["tasks"][-1]
    script["review_required"] = False
    plan["tasks"].append(
        dict(
            id="image",
            title="Create a graphic thumbnail",
            agent_id=(ids or {}).get("creator_thumbnail", "creator_thumbnail"),
            objective="Reflect the original brief and reviewed script in a graphic",
            review_required=True,
            dependencies=["deliver", *script["dependencies"]],
            bindings=[
                {"input_key": "script", "task_id": "deliver", "output_key": "script"},
                *copy.deepcopy(script["bindings"]),
            ],
        )
    )
    return plan


def runtime(tmp_path, *, registry=None, mutate=None, bad_quote=False, corrupt=None):
    calls = []

    def transport(request):
        body = json.loads(request.content)
        name, inputs = body["text"]["format"]["name"], json.loads(body["input"])
        calls.append((name, inputs))
        if name.endswith("thumbnail_planner"):
            assert all("body" not in source for source in inputs["sources"])
            ids = (
                {a.capability: a.id for a in registry.role_agents("creator")} if registry else None
            )
            result = thumbnail_plan(bool(inputs["sources"]), True, ids)
            if mutate:
                mutate(result)
        elif name.endswith("research"):
            result = copy.deepcopy(RESEARCH)
            if bad_quote:
                result["evidence"][0]["quote"] = "Invented quote"
        elif name.endswith("outline"):
            result = {"outline": OUTLINE + (" Refined." if "context" in inputs else "")}
        elif name.endswith("script"):
            result = {"script": SCRIPT}
        else:
            result = LAYOUT
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": json.dumps(result)}],
                    }
                ],
            },
        )

    model = ResponsesExecutor(
        ModelSettings(model="injected-only"), transport=httpx.MockTransport(transport)
    )

    def app(role=UserRole.OPERATOR):
        executors = None
        if corrupt:

            class CorruptExecutor:
                async def execute(self, agent, inputs, context):
                    result = await CreatorExecutor(model).execute(agent, inputs, context)
                    if agent.capability == "creator_thumbnail":
                        return corrupt(result)
                    return result

            executors = ExecutorRegistry()
            for kind in (
                "creator_research",
                "creator_outline",
                "creator_script",
                "creator_thumbnail",
            ):
                executors.register_agent(kind, CorruptExecutor())
        return create_app(
            registry=registry,
            db_path=tmp_path / "missions.sqlite3",
            model=model,
            user_role=role,
            executors=executors,
        )

    return app, calls


def start(client, sources=False):
    response = client.post(
        "/workflows/creator",
        json={"goal": GOAL, "sources": [SOURCE] if sources else [], "include_thumbnail": True},
    )
    assert response.status_code == 201, response.text
    mission = response.json()
    base = f"/missions/{mission['id']}"
    response = client.post(base + "/run", json={"expected_version": 1})
    assert response.status_code == 200, response.text
    return base, response.json()


@pytest.mark.parametrize("sources", [False, True])
def test_full_thumbnail_review_retry_restart_no_regeneration(tmp_path, monkeypatch, sources):
    app, calls = runtime(tmp_path)
    with TestClient(app()) as client:
        assert next(
            w for w in client.get("/status").json()["workflows"] if w["role_id"] == "creator"
        )["thumbnail_ready"]
        base, mission = start(client, sources)
        assert mission["planning"]["contract_version"] == 2
        assert mission["status"] == "WAITING_APPROVAL", mission
        assert all("passed" not in (t["outputs"] or {}) for t in mission["tasks"])
        for _, inputs in calls[1:]:
            assert inputs["goal"] == GOAL
            assert inputs["constraints"] == ["Use only supplied facts"]
        assert calls[-1][1]["script"] == SCRIPT
        assert calls[-1][1]["outline"] == calls[-2][1]["outline"]
        if sources:
            assert calls[-1][1]["sources"] == [SOURCE]
        approval = client.get(base + "/approvals").json()[0]
        owned = {
            a["name"]: a
            for a in client.get(base + "/artifacts").json()
            if a["id"] in approval["payload"]["artifact_refs"]
        }
        assert len(owned) == (6 if sources else 4)
        png_response = client.get(f"/artifacts/{owned['thumbnail.png']['id']}/content")
        assert png_response.headers["content-type"] == "image/png"
        assert png_response.headers["content-disposition"].startswith("inline;")
        with Image.open(BytesIO(png_response.content)) as image:
            assert image.size == (1280, 720)
            assert len(image.getcolors(1_000_000)) > 3
        receipt = client.get(f"/artifacts/{owned['thumbnail-layout.json']['id']}/content").json()
        assert receipt["layout"] == LAYOUT
        assert receipt["receipt"]["png_sha256"] == hashlib.sha256(png_response.content).hexdigest()
        assert decide(client, base, mission, "deny").status_code == 200
        mission = client.get(base).json()
        mission = client.post(
            base + "/tasks/image/actions",
            json={"expected_version": mission["version"], "action": "retry"},
        ).json()
        before = len(calls)
        mission = client.post(base + "/run", json={"expected_version": mission["version"]}).json()
        assert len(calls) == before + 1
        assert mission["status"] == "WAITING_APPROVAL"
        assert (
            client.get(f"/artifacts/{owned['thumbnail.png']['id']}/content").content
            == png_response.content
        )

    def forbidden(_layout):
        raise AssertionError("Approval must not rerender")

    monkeypatch.setattr("agentos.adapters.thumbnail.render_thumbnail", forbidden)
    with TestClient(app()) as client:
        mission = client.get(base).json()
        assert decide(client, base, mission, "approve").status_code == 200
        assert client.get(base).json()["status"] == "COMPLETED"


@pytest.mark.parametrize(
    "damage",
    [
        "thumbnail.png",
        "thumbnail-layout.json",
        "reviewed-script.md",
        "reviewed-outline.md",
        "reviewed-research.json",
        "reviewed-sources.json",
    ],
)
def test_each_frozen_artifact_tamper_rejects_acceptance(tmp_path, damage):
    app, _ = runtime(tmp_path)
    with TestClient(app()) as client:
        base, mission = start(client, True)
        artifact = next(
            a
            for a in client.get(base + "/artifacts").json()
            if a["task_id"] == "image" and a["name"] == damage
        )
        (tmp_path / "artifacts" / f"{artifact['id']}.txt").write_bytes(b"damaged")
        assert decide(client, base, mission, "approve").status_code == 409


@pytest.mark.parametrize(
    "change",
    [
        "missing_review",
        "early_review",
        "wrong_outline",
        "wrong_script",
        "missing_binding",
        "cycle",
        "foreign",
        "orphan",
        "duplicates",
    ],
)
def test_invalid_thumbnail_plan_never_persists(tmp_path, change):
    def mutate(plan):
        image = plan["tasks"][-1]
        if change == "missing_review":
            image["review_required"] = False
        elif change == "early_review":
            plan["tasks"][-2]["review_required"] = True
        elif change == "wrong_outline":
            image["bindings"][-1]["task_id"] = "draft"
            image["dependencies"][-1] = "draft"
        elif change == "wrong_script":
            image["bindings"][0]["task_id"] = "draft"
            image["dependencies"][0] = "draft"
        elif change == "missing_binding":
            image["bindings"].pop()
        elif change == "cycle":
            plan["tasks"][0]["dependencies"] = ["image"]
        elif change == "foreign":
            image["agent_id"] = "testing"
        elif change == "orphan":
            extra = copy.deepcopy(plan["tasks"][0])
            extra["id"] = "unused"
            plan["tasks"].insert(0, extra)
        else:
            image["id"] = "deliver"

    app, calls = runtime(tmp_path, mutate=mutate)
    with TestClient(app()) as client:
        response = client.post("/workflows/creator", json={"goal": GOAL, "include_thumbnail": True})
        assert response.status_code == 422, response.text
        assert client.get("/missions").json() == []
        assert len(calls) == 1


@pytest.mark.parametrize("change", ["permissions", "schema", "executor", "planner"])
def test_unsafe_thumbnail_registration_rejected(registry, change):
    agents = [
        a.model_copy(
            update=(
                {"permissions": (Permission.WRITE,)}
                if change == "permissions"
                else {"output_schema": {"type": "string"}}
                if change == "schema"
                else {}
            )
        )
        if a.id == "creator_thumbnail"
        else a
        for a in registry.agents()
    ]
    if change == "planner":
        agents = [
            a.model_copy(update={"permissions": (Permission.READ,)})
            if a.id == "creator_thumbnail_planner"
            else a
            for a in agents
        ]
    registry = AgentRegistry(
        agents, registry.roles(), {t for r in registry.roles() for t in r.tools}
    )
    executors = ExecutorRegistry()
    for agent in agents:
        if not (change == "executor" and agent.id == "creator_thumbnail"):
            executors.register_agent(agent.id, CreatorExecutor(None))
    with pytest.raises(ValueError):
        compile_creator_plan(
            CreatorMissionCreate(goal=GOAL, include_thumbnail=True),
            CreatorThumbnailPlan.model_validate(thumbnail_plan()),
            "creator_thumbnail_planner",
            registry,
            executors,
        )


@pytest.mark.parametrize("composition", ["left", "center"])
@pytest.mark.parametrize("decoration", ["circle", "bars", "none"])
def test_real_render_variants_and_wrapping(composition, decoration):
    png, receipt = render_thumbnail(
        ThumbnailLayout.model_validate(
            {
                **LAYOUT,
                "headline": "A headline long enough to wrap onto another line safely",
                "composition": composition,
                "decoration": decoration,
            }
        )
    )
    assert len(png) < 2_000_000
    assert receipt.receipt.png_sha256 == hashlib.sha256(png).hexdigest()


@pytest.mark.parametrize(
    "change",
    [
        dict(headline="Unsupported 🚀"),
        dict(background="red"),
        dict(decoration="https://example.com/image"),
        dict(font="C:/secret"),
        dict(headline="W" * 100),
        dict(foreground="#122033"),
    ],
)
def test_invalid_layout_and_unusable_text_rejected(change):
    with pytest.raises(ValueError):
        render_thumbnail(ThumbnailLayout.model_validate({**LAYOUT, **change}))


def test_png_artifact_contract_and_storage_integrity(tmp_path):
    png, _ = render_thumbnail(ThumbnailLayout.model_validate(LAYOUT))
    store = ArtifactStore(tmp_path)
    artifact = store.write(
        "mission", "image", ArtifactDraft(name="thumbnail.png", media_type="image/png", content=png)
    )
    assert store.read(artifact) == png
    with pytest.raises(ValueError):
        store.write(
            "mission",
            "image",
            ArtifactDraft(name="bad.png", media_type="image/png", content=b"bad"),
        )
    for media, content in [("image/png", "text"), ("text/plain", png)]:
        with pytest.raises(ValueError):
            ArtifactDraft(name="bad", media_type=media, content=content)
    for dimensions, image_format in [((32, 32), "PNG"), ((1280, 720), "JPEG")]:
        buffer = BytesIO()
        Image.new("RGB", dimensions).save(buffer, format=image_format)
        with pytest.raises(ValueError):
            store.write(
                "mission",
                "image",
                ArtifactDraft(name="bad.png", media_type="image/png", content=buffer.getvalue()),
            )
    with pytest.raises(ValueError):
        ArtifactDraft(name="too-large.png", media_type="image/png", content=b"x" * 2_000_001)
    assert len(list(tmp_path.iterdir())) == 1


def test_dependency_failure_viewer_and_manual_completion(tmp_path):
    app, calls = runtime(tmp_path, bad_quote=True)
    with TestClient(app(UserRole.VIEWER)) as client:
        assert (
            client.post(
                "/workflows/creator", json={"goal": GOAL, "include_thumbnail": True}
            ).status_code
            == 403
        )
        assert calls == []
    with TestClient(app()) as client:
        base, mission = start(client, True)
        assert mission["status"] == "FAILED"
        assert len(calls) == 2
        assert client.get(base + "/approvals").json() == []
        assert (
            client.post(
                base + "/tasks/image/actions",
                json={
                    "expected_version": mission["version"],
                    "action": "complete",
                    "outputs": LAYOUT,
                },
            ).status_code
            == 409
        )


@pytest.mark.parametrize("change", ["png", "receipt", "missing", "duplicate", "script", "media"])
def test_injected_executor_cannot_stage_false_bundle(tmp_path, change):
    def corrupt(result):
        artifacts = list(result.artifacts)
        if change == "png":
            png, _ = render_thumbnail(
                ThumbnailLayout.model_validate({**LAYOUT, "decoration": "none"})
            )
            artifacts[0] = artifacts[0].model_copy(update={"content": png})
        elif change == "receipt":
            artifacts[1] = artifacts[1].model_copy(update={"content": "{}"})
        elif change == "missing":
            artifacts.pop()
        elif change == "duplicate":
            artifacts.append(artifacts[0])
        elif change == "script":
            artifacts[2] = artifacts[2].model_copy(update={"content": "Changed script"})
        else:
            artifacts[2] = artifacts[2].model_copy(update={"media_type": "text/plain"})
        return result.model_copy(update={"artifacts": tuple(artifacts)})

    app, _ = runtime(tmp_path, corrupt=corrupt)
    with TestClient(app()) as client:
        base, mission = start(client)
        assert mission["status"] == "FAILED", mission
        assert client.get(base + "/approvals").json() == []
        assert not any(a["task_id"] == "image" for a in client.get(base + "/artifacts").json())


@pytest.mark.parametrize("change", ["goal", "constraints", "binding", "attempt"])
def test_changed_scope_bindings_attempt_reject_approval(tmp_path, change):
    app, _ = runtime(tmp_path)
    with TestClient(app()) as client:
        base, mission = start(client)
        with sqlite3.connect(tmp_path / "missions.sqlite3") as conn:
            payload = json.loads(conn.execute("SELECT payload FROM missions").fetchone()[0])
            if change == "goal":
                payload["goal"] = "Changed scope"
            elif change == "constraints":
                payload["planning"]["constraints"] = ["Changed"]
            elif change == "binding":
                payload["tasks"][-1]["input_bindings"]["outline"]["task_id"] = "draft"
                payload["tasks"][-1]["dependencies"] = ["deliver", "draft"]
            else:
                payload["tasks"][-1]["attempts"] += 1
            conn.execute("UPDATE missions SET payload = ?", (json.dumps(payload),))
        assert decide(client, base, mission, "approve").status_code == 409


def test_demo_rejects_thumbnail_and_normal_has_no_fallback(
    demo_root, tmp_path, registry, monkeypatch
):
    with TestClient(create_app(demo_root=demo_root)) as client:
        assert not next(
            w for w in client.get("/status").json()["workflows"] if w["role_id"] == "creator"
        )["thumbnail_ready"]
        assert (
            client.post(
                "/workflows/creator", json={"goal": CREATOR_DEMO_GOAL, "include_thumbnail": True}
            ).status_code
            == 409
        )
    monkeypatch.delenv("AGENTOS_MODEL", raising=False)
    with TestClient(create_app(registry=registry, db_path=tmp_path / "offline.sqlite3")) as client:
        assert (
            client.post(
                "/workflows/creator", json={"goal": GOAL, "include_thumbnail": True}
            ).status_code
            == 409
        )


def test_equivalent_registered_ids_and_optional_readiness(tmp_path, registry):
    mapping = {a.id: "alternate_" + a.id for a in registry.role_agents("creator")}
    agents = [a.model_copy(update={"id": mapping.get(a.id, a.id)}) for a in registry.agents()]
    roles = [
        r.model_copy(update={"agents": tuple(mapping.get(i, i) for i in r.agents)})
        for r in registry.roles()
    ]
    alternate = AgentRegistry(agents, roles, {t for r in roles for t in r.tools})
    app, _ = runtime(tmp_path, registry=alternate)
    with TestClient(app()) as client:
        base, mission = start(client, True)
        assert mission["status"] == "WAITING_APPROVAL", mission
        assert all(t["agent_id"].startswith("alternate_") for t in mission["tasks"])
        assert decide(client, base, mission, "approve").status_code == 200
    # An unavailable optional executor must not disable existing script-only planning.
    agents = [
        a.model_copy(update={"input_schema": {"type": "string"}})
        if a.id == "creator_thumbnail"
        else a
        for a in registry.agents()
    ]
    limited = AgentRegistry(
        agents, registry.roles(), {t for r in registry.roles() for t in r.tools}
    )
    app, calls = runtime(tmp_path / "limited", registry=limited)
    with TestClient(app()) as client:
        workflow = next(
            w for w in client.get("/status").json()["workflows"] if w["role_id"] == "creator"
        )
        assert workflow["ready"] and not workflow["thumbnail_ready"]
        assert (
            client.post(
                "/workflows/creator", json={"goal": GOAL, "include_thumbnail": True}
            ).status_code
            == 409
        )
        assert calls == []


def test_preflight_manual_graph_and_cancel_rejected_before_execution(tmp_path):
    app, calls = runtime(tmp_path)
    with TestClient(app()) as client:
        mission = client.post(
            "/workflows/creator", json={"goal": GOAL, "include_thumbnail": True}
        ).json()
        unmanaged = {
            "goal": GOAL,
            "role_id": "creator",
            "tasks": [
                {
                    "id": "image",
                    "title": "Unsafe graph",
                    "agent_id": "creator_thumbnail",
                    "inputs": {"goal": GOAL},
                }
            ],
        }
        assert client.post("/missions", json=unmanaged).status_code == 409
        base = f"/missions/{mission['id']}"
        with sqlite3.connect(tmp_path / "missions.sqlite3") as conn:
            payload = json.loads(conn.execute("SELECT payload FROM missions").fetchone()[0])
            payload["tasks"][-1]["review_required"] = False
            conn.execute("UPDATE missions SET payload = ?", (json.dumps(payload),))
        assert client.post(base + "/run", json={"expected_version": 1}).status_code == 409
        assert client.get(base + "/run").json() is None
        assert len(calls) == 1
        cancellable = client.post(
            "/workflows/creator", json={"goal": GOAL, "include_thumbnail": True}
        ).json()
        cancel_base = f"/missions/{cancellable['id']}"
        cancelled = client.post(cancel_base + "/cancel", json={"expected_version": 1})
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["status"] == "CANCELLED"
        assert (
            client.post(
                cancel_base + "/run", json={"expected_version": cancelled.json()["version"]}
            ).status_code
            == 409
        )
        assert len(calls) == 2  # Planning only; cancelled content/layout agents never execute.


def test_plan_bounds_allow_four_refinements_and_explicit_request_only(registry):
    plan = thumbnail_plan(True)
    outline = copy.deepcopy(plan["tasks"][1])
    for index in range(3):
        step = copy.deepcopy(outline)
        step["id"] = f"refine{index}"
        previous = "draft" if index == 0 else f"refine{index - 1}"
        step["dependencies"] += [previous]
        step["bindings"] += [{"input_key": "context", "task_id": previous, "output_key": "outline"}]
        plan["tasks"].insert(index + 2, step)
    for task in plan["tasks"][-2:]:
        task["dependencies"] = ["refine2" if d == "draft" else d for d in task["dependencies"]]
        for binding in task["bindings"]:
            if binding["input_key"] == "outline":
                binding["task_id"] = "refine2"
    executors = ExecutorRegistry()
    for agent in registry.role_agents("creator"):
        executors.register_agent(agent.id, CreatorExecutor(None))
    compiled = compile_creator_plan(
        CreatorMissionCreate(goal=GOAL, sources=[SOURCE], include_thumbnail=True),
        CreatorThumbnailPlan.model_validate(plan),
        "creator_thumbnail_planner",
        registry,
        executors,
    )
    assert len(compiled.tasks) == 7
    with pytest.raises(ValueError):
        compile_creator_plan(
            CreatorMissionCreate(goal=GOAL, sources=[SOURCE]),
            CreatorThumbnailPlan.model_validate(plan),
            "creator_thumbnail_planner",
            registry,
            executors,
        )
