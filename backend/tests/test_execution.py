import asyncio

import pytest
from jsonschema.exceptions import ValidationError

from agentos.domain.agents import AgentResult, ExecutionContext
from agentos.services.execution import execute_agent


class RecordingExecutor:
    """Test fixture only; not an AI provider."""

    def __init__(self, outputs=None):
        self.outputs = outputs if outputs is not None else {"findings": "Evidence from fixture"}
        self.calls = []

    async def execute(self, agent, inputs, context):
        self.calls.append((agent.id, inputs, context.task_id))
        return AgentResult(outputs=self.outputs, artifact_refs=("artifact:test-report",))


def run(registry, executor, inputs):
    return asyncio.run(
        execute_agent(
            registry,
            "investigation",
            executor,
            inputs,
            ExecutionContext(workspace_id="w", mission_id="m", task_id="t"),
        )
    )


def test_execution_contract(registry):
    executor = RecordingExecutor()
    result = run(registry, executor, {"goal": "Investigate bug"})
    assert result.outputs["findings"] == "Evidence from fixture"
    assert result.artifact_refs == ("artifact:test-report",)
    assert executor.calls == [("investigation", {"goal": "Investigate bug"}, "t")]


@pytest.mark.parametrize("inputs", [{}, {"goal": 123}, {"goal": ""}, {"goal": "bug", "extra": 1}])
def test_invalid_input_does_not_call_executor(registry, inputs):
    executor = RecordingExecutor()
    with pytest.raises(ValidationError):
        run(registry, executor, inputs)
    assert executor.calls == []


def test_invalid_output_rejected(registry):
    with pytest.raises(ValidationError):
        run(registry, RecordingExecutor(outputs={"findings": 12}), {"goal": "bug"})


def test_provider_failure_propagates(registry):
    class FailingExecutor:
        async def execute(self, agent, inputs, context):
            raise RuntimeError("Provider unavailable")

    with pytest.raises(RuntimeError, match="Provider unavailable"):
        run(registry, FailingExecutor(), {"goal": "bug"})
