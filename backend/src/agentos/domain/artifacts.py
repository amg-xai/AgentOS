"""Text artifacts with immutable ids and content hashes."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import ConfigDict, Field

from agentos.domain.base import Definition, Identifier, Text

ArtifactId = Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
ArtifactName = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,120}$")]


class ArtifactDraft(Definition):
    model_config = ConfigDict(str_strip_whitespace=False)
    name: ArtifactName
    media_type: Literal["text/plain", "text/markdown", "text/x-diff"] = "text/plain"
    content: str = Field(max_length=2_000_000)


class Artifact(Definition):
    id: ArtifactId
    mission_id: Text
    task_id: Identifier
    name: ArtifactName
    media_type: Literal["text/plain", "text/markdown", "text/x-diff"]
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size: int = Field(ge=0)
    created_at: datetime
