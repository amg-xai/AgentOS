"""Production dispatch guards tested only with an in-memory HTTP transport."""

import asyncio
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from pydantic import ValidationError
from test_provider import response

from agentos.adapters.live_limits import LiveRequestLedger, LiveRequestPolicy
from agentos.adapters.provider import ModelSettings, ProviderFailure, ResponsesExecutor


def count(path):
    with sqlite3.connect(path) as conn:
        return conn.execute("SELECT COUNT(*) FROM reservations").fetchone()[0]


def settings(monkeypatch):
    monkeypatch.setenv("AGENTOS_MODEL", "configured-model")
    monkeypatch.setenv("AGENTOS_MODEL_KEY", "fake-key")
    monkeypatch.setenv("AGENTOS_ALLOW_LIVE_MODELS", "1")
    monkeypatch.setenv("AGENTOS_MODEL_URL", "https://api.openai.com/v1")
    return ModelSettings.from_environment()


def executor(monkeypatch, handler):
    # Exercise transport=None policy enforcement, but replace the client itself.
    client = httpx.AsyncClient

    def offline_client(**kwargs):
        assert kwargs.pop("transport") is None
        return client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", offline_client)
    return ResponsesExecutor(settings(monkeypatch))


def run(model, registry):
    return asyncio.run(model.generate(registry.agent("investigation"), {"goal": "fix"}))


def test_disabled_gate_precedes_policy_and_http(monkeypatch, registry):
    def forbidden(**kwargs):
        pytest.fail("Disabled generation constructed HTTP client")

    monkeypatch.setattr(httpx, "AsyncClient", forbidden)
    with pytest.raises(ProviderFailure, match="disabled"):
        run(ResponsesExecutor(ModelSettings(model="configured-model")), registry)


@pytest.mark.parametrize(
    "case",
    ["missing_policy", "missing_ledger", "corrupt", "changed", "expired", "model", "endpoint"],
)
def test_bad_limits_fail_before_http(case, live_policy_environment, monkeypatch, registry):
    config = settings(monkeypatch)
    policy, ledger = live_policy_environment
    if case == "missing_policy":
        config.live_policy_path.unlink()
    elif case == "missing_ledger":
        ledger.unlink()
    elif case == "corrupt":
        ledger.write_bytes(b"not a sqlite database")
    elif case in {"changed", "expired"}:
        changed = policy.model_copy(
            update={"max_requests": 25}
            if case == "changed"
            else {"expires_at": datetime.now(UTC) - timedelta(seconds=1)}
        )
        config.live_policy_path.write_text(changed.model_dump_json(), encoding="utf-8")
    elif case == "model":
        config = config.model_copy(update={"model": "another-model"})
    else:
        config = config.model_copy(update={"base_url": "https://another.example/v1"})
    assert not config.live_limits_ready()
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **_: pytest.fail("Invalid policy reached HTTP")
    )
    with pytest.raises(ProviderFailure, match="policy or ledger"):
        run(ResponsesExecutor(config), registry)
    if case == "missing_ledger":
        assert not ledger.exists()


@pytest.mark.parametrize("value", [False, 1, "true", None])
def test_spending_attestation_must_be_explicit_true(value, live_policy_environment):
    policy, _ = live_policy_environment
    with pytest.raises(ValidationError):
        LiveRequestPolicy.model_validate(
            policy.model_dump() | {"provider_spend_control_confirmed": value}
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_requests", 27),
        ("developer_requests", 10),
        ("creator_requests", 9),
        ("student_requests", 10),
        ("max_output_tokens", 8193),
        ("max_request_bytes", 1_000_001),
        ("max_requests", True),
        ("expires_at", datetime.now()),
        ("spend_control_reference", " "),
    ],
)
def test_policy_contract_rejects_invalid_bounds(field, value, live_policy_environment):
    policy, _ = live_policy_environment
    with pytest.raises(ValidationError):
        LiveRequestPolicy.model_validate(policy.model_dump() | {field: value})


def test_atomic_cap_survives_concurrent_reservations_and_restart(tmp_path, live_policy_environment):
    policy, _ = live_policy_environment
    policy = policy.model_copy(update={"max_requests": 3})
    path = tmp_path / "concurrent.db"
    LiveRequestLedger.initialize(path, policy)

    def reserve(_):
        try:
            LiveRequestLedger(path, policy).reserve("developer")
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(reserve, range(16))) == 3
    assert count(path) == 3
    with pytest.raises(ValueError, match="exhausted"):
        LiveRequestLedger(path, policy).reserve("creator")
    with pytest.raises(FileExistsError):
        LiveRequestLedger.initialize(path, policy)
    assert count(path) == 3


def test_role_limit_cannot_borrow_other_roles(tmp_path, live_policy_environment):
    policy, _ = live_policy_environment
    policy = policy.model_copy(update={"developer_requests": 1, "student_requests": 0})
    path = tmp_path / "roles.db"
    LiveRequestLedger.initialize(path, policy)
    ledger = LiveRequestLedger(path, policy)
    ledger.reserve("developer")
    for role in ("developer", "student", "unknown"):
        with pytest.raises(ValueError, match="exhausted|unauthorized"):
            ledger.reserve(role)
    ledger.reserve("creator")
    assert count(path) == 2


@pytest.mark.parametrize(
    "case", ["success", "authentication", "timeout", "invalid_output", "cancel"]
)
def test_attempt_consumed_before_dispatch_never_refunded(
    case, live_policy_environment, monkeypatch, registry
):
    _, path = live_policy_environment

    def handler(request):
        assert count(path) == 1
        if case == "timeout":
            raise httpx.ReadTimeout("private data")
        if case == "cancel":
            raise asyncio.CancelledError()
        if case == "authentication":
            return httpx.Response(401)
        return response() if case == "success" else response('{"wrong":true}')

    model = executor(monkeypatch, handler)
    if case == "success":
        assert run(model, registry) == {"findings": "Evidence"}
    else:
        with pytest.raises(asyncio.CancelledError if case == "cancel" else ProviderFailure):
            run(model, registry)
    assert count(path) == 1


def test_token_and_byte_caps_apply_to_actual_request(
    live_policy_environment, monkeypatch, registry, tmp_path
):
    policy, _ = live_policy_environment
    policy = policy.model_copy(update={"max_output_tokens": 256, "max_request_bytes": 10_000})
    config = settings(monkeypatch)
    config.live_policy_path.write_text(policy.model_dump_json(), encoding="utf-8")
    path = tmp_path / "bounded.db"
    LiveRequestLedger.initialize(path, policy)
    monkeypatch.setenv("AGENTOS_LIVE_REQUEST_LEDGER", str(path))

    def handler(request):
        assert json.loads(request.content)["max_output_tokens"] == 256
        return response()

    model = executor(monkeypatch, handler)
    run(model, registry)
    with pytest.raises(ProviderFailure, match="request limit"):
        asyncio.run(model.generate(registry.agent("investigation"), {"goal": "x" * 11_000}))
    assert count(path) == 1


def test_exhausted_allowance_blocks_http_and_readiness(
    live_policy_environment, monkeypatch, registry
):
    policy, path = live_policy_environment
    for _ in range(9):
        LiveRequestLedger(path, policy).reserve("developer")
    model = executor(monkeypatch, lambda _: pytest.fail("Exhausted role contacted provider"))
    with pytest.raises(ProviderFailure, match="allowance"):
        run(model, registry)
    for role, amount in (("creator", 8), ("student", 9)):
        for _ in range(amount):
            LiveRequestLedger(path, policy).reserve(role)
    assert not settings(monkeypatch).live_limits_ready()
    assert count(path) == 26


def test_outer_deadline_consumes_attempt(live_policy_environment, monkeypatch, registry):
    _, path = live_policy_environment

    async def slow_response(request):
        assert count(path) == 1
        await asyncio.sleep(10)
        return response()

    model = executor(monkeypatch, slow_response)
    model.settings = model.settings.model_copy(update={"timeout_seconds": 0.02})
    with pytest.raises(ProviderFailure, match="deadline"):
        run(model, registry)
    assert count(path) == 1


def test_no_authorized_roles_is_not_ready(tmp_path, live_policy_environment):
    policy, _ = live_policy_environment
    policy = policy.model_copy(
        update={"developer_requests": 0, "creator_requests": 0, "student_requests": 0}
    )
    path = tmp_path / "empty.db"
    LiveRequestLedger.initialize(path, policy)
    with pytest.raises(ValueError, match="role allowances"):
        LiveRequestLedger(path, policy).validate()


def test_expiry_rechecked_during_reservation(tmp_path, live_policy_environment):
    policy, _ = live_policy_environment
    policy = policy.model_copy(update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)})
    path = tmp_path / "expired.db"
    LiveRequestLedger.initialize(path, policy)
    with pytest.raises(ValueError, match="expired"):
        LiveRequestLedger(path, policy).reserve("developer")
    assert count(path) == 0


def test_invalid_ledger_reservation_blocks_dispatch(live_policy_environment):
    policy, path = live_policy_environment
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO reservations VALUES ('unsupported')")
    with pytest.raises(ValueError, match="invalid reservations"):
        LiveRequestLedger(path, policy).reserve("developer")
    assert count(path) == 1
