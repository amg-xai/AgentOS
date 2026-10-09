"""Text and bounded PNG artifacts with immutable ids and content hashes."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, model_validator

from agentos.domain.base import Definition, Identifier, Text

ArtifactId = Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
ArtifactName = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,120}$")]
ArtifactMedia = Literal["text/plain", "text/markdown", "text/x-diff", "image/png"]


class ArtifactDraft(Definition):
    model_config = ConfigDict(str_strip_whitespace=False)
    name: ArtifactName
    media_type: ArtifactMedia = "text/plain"
    content: Annotated[str, Field(strict=True)] | Annotated[bytes, Field(strict=True)] = Field(
        max_length=2_000_000
    )

    @model_validator(mode="after")
    def content_type(self) -> "ArtifactDraft":
        if isinstance(self.content, bytes) != (self.media_type == "image/png"):
            raise ValueError("PNG requires bytes; text artifacts require text")
        return self


class Artifact(Definition):
    id: ArtifactId
    mission_id: Text
    task_id: Identifier
    name: ArtifactName
    media_type: ArtifactMedia
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size: int = Field(ge=0)
    created_at: datetime
