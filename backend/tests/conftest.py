from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agentos.adapters.live_limits import LiveRequestLedger, LiveRequestPolicy
from agentos.adapters.manifests import load_registry
from agentos.services.registry import AgentRegistry

PACKAGES = Path(__file__).resolve().parents[2] / "packages"


@pytest.fixture
def registry() -> AgentRegistry:
    return load_registry(PACKAGES)


@pytest.fixture
def live_policy_environment(tmp_path, monkeypatch):
    """Temporary fake-provider controls; does not enable generation or contact a provider."""
    policy = LiveRequestPolicy(
        session_id="acceptance_test",
        endpoint="https://api.openai.com/v1",
        model="configured-model",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        max_requests=26,
        developer_requests=9,
        creator_requests=8,
        student_requests=9,
        max_output_tokens=8192,
        max_request_bytes=1_000_000,
        provider_spend_control_confirmed=True,
        spend_control_reference="test-only attestation",
    )
    path = tmp_path / "policy.json"
    path.write_text(policy.model_dump_json(), encoding="utf-8")
    ledger_path = tmp_path / "allowance.db"
    LiveRequestLedger.initialize(ledger_path, policy)
    monkeypatch.setenv("AGENTOS_LIVE_REQUEST_POLICY", str(path))
    monkeypatch.setenv("AGENTOS_LIVE_REQUEST_LEDGER", str(ledger_path))
    return policy, ledger_path
