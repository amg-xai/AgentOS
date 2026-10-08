import sqlite3

import pytest
from fastapi.testclient import TestClient
from test_overview import snapshot

from agentos.adapters.sqlite import SQLiteMissionRepository
from agentos.api.app import create_app
from agentos.domain.governance import UserRole
from agentos.domain.missions import MissionStatus, TaskStatus


@pytest.fixture
def history(tmp_path):
    return SQLiteMissionRepository(tmp_path / "history.sqlite3")


def put(repository, goal, index=0, status=TaskStatus.PENDING, role="developer", id=None):
    mission = snapshot(status, index=index, role=role).model_copy(update={"goal": goal})
    if id is not None:
        mission = mission.model_copy(update={"id": id})
    return repository.create(mission, [])


def test_full_history_filters_before_paging_and_preserves_defaults(history):
    oldest = put(history, "Repair a calculator", status=TaskStatus.FAILED)
    for index in range(1, 126):
        put(history, f"Other project {index}", index=index, role="creator")
    assert oldest.id not in {m.id for m in history.list_missions(100)}
    assert history.list_missions(
        100, query=" CALCULATOR ", role_id="developer", status=MissionStatus.FAILED
    ) == [oldest]
    assert len(history.list_missions(100, role_id="creator")) == 100
    second = history.list_missions(100, 100, role_id="creator")
    assert len(second) == 25
    assert not history.list_missions(100, 125, role_id="creator")
    assert history.list_missions(20, 5) == history.list_missions(20, 5, query=" \t ")
    assert history.list_missions(20, 5, query="Other") == history.list_missions(
        20, 5, role_id="creator"
    )


@pytest.mark.parametrize("status", list(TaskStatus))
def test_status_filter_reuses_derived_state(history, status):
    mission = put(history, "State example", status=status)
    for state in MissionStatus:
        assert history.list_missions(status=state) == ([mission] if state == mission.status else [])


@pytest.mark.parametrize(
    "goal,query,matched",
    [
        ("Straße repair", "STRASSE", True),
        ("ΣΧΕΔΙΟ", "σχεδιο", True),
        ("Keep 100%_ coverage", "%_", True),
        ("Ordinary title", "%", False),
        ("Literal [a-z].* text", "[a-z].*", True),
        ("Ordinary title", "[a-z].*", False),
        ("Existing mission", "", True),
        ("Existing mission", " \n ", True),
        ("Unrelated goal", "not-in-overview", False),
    ],
)
def test_literal_unicode_goal_search_excludes_task_inputs_outputs(history, goal, query, matched):
    mission = put(history, goal)
    assert history.list_missions(query=query) == ([mission] if matched else [])


def test_roles_are_exact_historic_and_filters_combine_with_and(history):
    old = put(history, "Archived issue", role="archived_role", status=TaskStatus.FAILED)
    put(history, "Archived issue", index=1, role="developer")
    assert history.list_missions(
        role_id="archived_role", query="issue", status=MissionStatus.FAILED
    ) == [old]
    assert not history.list_missions(role_id="archived")
    assert not history.list_missions(role_id="missing_role")
    assert not history.list_missions(role_id="archived_role", status=MissionStatus.COMPLETED)
    assert not history.list_missions(query="missing", role_id="archived_role")


def test_tie_order_and_page_boundaries_are_stable(history):
    older = put(history, "Matching oldest", index=0, id="older")
    put(history, "Matching tie", index=1, id="b")
    put(history, "Matching tie", index=1, id="a")
    put(history, "Unrelated newest", index=2)
    assert [m.id for m in history.list_missions(2, query="Matching")] == ["a", "b"]
    assert history.list_missions(2, 2, query="Matching") == [older]
    assert not history.list_missions(2, 3, query="Matching")


def test_viewer_api_search_preserves_claims_and_events(history, registry, monkeypatch):
    monkeypatch.delenv("AGENTOS_MODEL", raising=False)
    monkeypatch.setenv("AGENTOS_WORKSPACE_CONFIG", str(history.path.parent / "missing.json"))
    mission = put(history, "Retained claim target", status=TaskStatus.RUNNING, role="historic")
    claim = history.acquire_claim(mission.id, 1, "local")
    events = history.events(mission.id)
    with TestClient(
        create_app(registry, db_path=history.path, user_role=UserRole.VIEWER)
    ) as client:
        response = client.get(
            "/missions",
            params={"query": "TARGET", "role_id": "historic", "status": "RUNNING", "limit": 1},
        )
        assert response.status_code == 200
        assert response.json() == [mission.model_dump(mode="json")]
        assert client.get("/missions", params={"role_id": "missing_role"}).json() == []
        assert (
            client.post(f"/missions/{mission.id}/run", json={"expected_version": 1}).status_code
            == 403
        )
    assert history.claim(mission.id) == claim and history.events(mission.id) == events
    with sqlite3.connect(history.path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2


@pytest.mark.parametrize(
    "params",
    [
        {"query": "x" * 201},
        {"role_id": "Bad Role"},
        {"role_id": "a" * 81},
        {"role_id": ""},
        {"status": "READY"},
        {"status": "unknown"},
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
    ],
)
def test_api_rejects_invalid_filter_and_pagination_parameters(
    history, registry, monkeypatch, params
):
    monkeypatch.delenv("AGENTOS_MODEL", raising=False)
    monkeypatch.setenv("AGENTOS_WORKSPACE_CONFIG", str(history.path.parent / "missing.json"))
    with TestClient(create_app(registry, db_path=history.path)) as client:
        assert client.get("/missions", params=params).status_code == 422
