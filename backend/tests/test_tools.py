import asyncio

import pytest
from jsonschema.exceptions import ValidationError

from agentos.domain.agents import ExecutionContext, Permission
from agentos.domain.governance import PermissionDenied, UserRole
from agentos.domain.tools import ToolDefinition
from agentos.services.tools import ToolRegistry


class ToyTool:
    def __init__(self):
        self.calls = 0

    async def execute(self, inputs, context):
        self.calls += 1
        return {"result": inputs["value"]}


def tool(permissions=(Permission.READ,), high_impact=False):
    return ToolDefinition(
        id="filesystem",
        description="Test fixture; no actual filesystem access",
        permissions=permissions,
        high_impact=high_impact,
        input_schema={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        },
        output_schema={
            "type": "object",
            "properties": {"result": {"type": "string"}},
            "required": ["result"],
        },
    )


def invoke(catalog, agent, role, inputs=None):
    return asyncio.run(
        catalog.execute(
            "filesystem",
            agent,
            role,
            {"value": "fixture"} if inputs is None else inputs,
            ExecutionContext(workspace_id="local", mission_id="m", task_id="t"),
        )
    )


def test_permitted_tool_is_validated_and_audited(registry):
    events, executor = [], ToyTool()
    catalog = ToolRegistry(events.append)
    catalog.register(tool(), executor)
    assert invoke(catalog, registry.agent("investigation"), UserRole.VIEWER) == {
        "result": "fixture"
    }
    assert executor.calls == 1
    assert [event.outcome for event in events] == ["started", "completed"]
    assert events[0].context.mission_id == "m"
    assert "fixture" not in events[0].model_dump_json()


@pytest.mark.parametrize(
    "role,agent_id", [(UserRole.VIEWER, "code_helper"), (UserRole.ADMIN, "investigation")]
)
def test_user_and_agent_capabilities_are_both_required(registry, role, agent_id):
    events, executor = [], ToyTool()
    catalog = ToolRegistry(events.append)
    catalog.register(tool((Permission.WRITE,)), executor)
    with pytest.raises(PermissionDenied):
        invoke(catalog, registry.agent(agent_id), role)
    assert executor.calls == 0
    assert events[-1].outcome == "denied"


def test_admin_cannot_bypass_high_impact_approval(registry):
    events, executor = [], ToyTool()
    catalog = ToolRegistry(events.append)
    catalog.register(tool(high_impact=True), executor)
    with pytest.raises(PermissionDenied, match="dedicated action approval"):
        invoke(catalog, registry.agent("investigation"), UserRole.ADMIN)
    assert executor.calls == 0
    assert events[-1].outcome == "denied"


def test_bad_input_and_missing_audit_prevent_execution(registry):
    events, executor = [], ToyTool()
    catalog = ToolRegistry(events.append)
    catalog.register(tool(), executor)
    with pytest.raises(ValidationError):
        invoke(catalog, registry.agent("investigation"), UserRole.OPERATOR, {})
    assert executor.calls == 0
    assert events[-1].outcome == "failed"

    def broken_audit(event):
        raise RuntimeError("Audit unavailable")

    catalog = ToolRegistry(broken_audit)
    catalog.register(tool(), executor)
    with pytest.raises(RuntimeError, match="Audit unavailable"):
        invoke(catalog, registry.agent("investigation"), UserRole.OPERATOR)
    assert executor.calls == 0


def test_duplicate_tools_and_invalid_output(registry):
    class InvalidTool(ToyTool):
        async def execute(self, inputs, context):
            return {"result": 42}

    events = []
    catalog = ToolRegistry(events.append)
    catalog.register(tool(), InvalidTool())
    with pytest.raises(ValueError, match="Duplicate tool"):
        catalog.register(tool(), ToyTool())
    with pytest.raises(ValidationError):
        invoke(catalog, registry.agent("investigation"), UserRole.OPERATOR)
    assert events[-1].outcome == "failed"
