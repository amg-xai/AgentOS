"""Product role packages, distinct from authorization roles."""

from typing import Literal

from pydantic import Field, field_validator

from agentos.domain.agents import Definition, Identifier, Text, VersionedManifest


class RolePackage(Definition):
    id: Identifier
    name: Text
    description: Text
    agents: tuple[Identifier, ...] = Field(min_length=1)
    tools: tuple[Identifier, ...] = ()

    @field_validator("agents", "tools")
    @classmethod
    def unique_entries(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("Entries must be unique")
        return values


class RoleManifest(VersionedManifest):
    kind: Literal["role"]
    role: RolePackage
