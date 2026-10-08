"""Shared validated value types."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

Identifier = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=80)]
Text = Annotated[str, Field(min_length=1)]


class Definition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
