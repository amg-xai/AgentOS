"""Agent discovery and execution contracts."""

from enum import StrEnum
from typing import Annotated, Any, Literal, Protocol

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import BaseModel, ConfigDict, Field, field_validator

Identifier = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=80)]
Text = Annotated[str, Field(min_length=1)]


class Definition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class VersionedManifest(Definition):
    schema_version: Literal[1]

    @field_validator("schema_version", mode="before")
    @classmethod
    def exact_version(cls, value: Any) -> Any:
        if type(value) is not int or value != 1:
            raise ValueError("schema_version must be integer 1")
        return value


class Permission(StrEnum):
    READ = "READ"
    WRITE = "WRITE"
    EXECUTE = "EXECUTE"
    DESTRUCTIVE = "DESTRUCTIVE"


class ProviderConfig(Definition):
    provider: Identifier
    model: Text
    credential_env: Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]*$")] | None = None


def validate_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Accept self-contained Draft 2020-12 schemas; never fetch remote references."""
    if schema.get("$schema", "https://json-schema.org/draft/2020-12/schema") != (
        "https://json-schema.org/draft/2020-12/schema"
    ):
        raise ValueError("Only JSON Schema Draft 2020-12 is supported")

    def check_refs(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in {"$ref", "$dynamicRef"} and (
                    not isinstance(value, str) or not value.startswith("#")
                ):
                    raise ValueError("Schema references must be local fragments")
                check_refs(value)
        elif isinstance(node, list):
            for item in node:
                check_refs(item)

    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise ValueError(f"Invalid JSON schema: {exc.message}") from exc
    check_refs(schema)
    return schema


class AgentDefinition(Definition):
    id: Identifier
    name: Text
    description: Text
    role: Identifier
    instructions: Text
    tools: tuple[Identifier, ...] = ()
    permissions: tuple[Permission, ...] = ()
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    provider: ProviderConfig | None = None

    _schemas = field_validator("input_schema", "output_schema")(validate_schema)

    @field_validator("tools", "permissions")
    @classmethod
    def unique_entries(cls, values: tuple[Any, ...]) -> tuple[Any, ...]:
        if len(set(values)) != len(values):
            raise ValueError("Entries must be unique")
        return values


class ExecutionContext(Definition):
    workspace_id: Text
    mission_id: Text
    task_id: Text


class AgentResult(Definition):
    outputs: dict[str, Any]
    artifact_refs: tuple[Text, ...] = ()


class AgentExecutor(Protocol):
    async def execute(
        self, agent: AgentDefinition, inputs: dict[str, Any], context: ExecutionContext
    ) -> AgentResult: ...


class AgentManifest(VersionedManifest):
    kind: Literal["agents"]
    agents: tuple[AgentDefinition, ...] = Field(min_length=1)
