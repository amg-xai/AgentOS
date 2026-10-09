"""Strict local graphic layout; no paths, URLs or drawing instructions."""

from typing import Annotated, Literal

from pydantic import ConfigDict, Field, field_validator

from agentos.domain.base import Definition
from agentos.domain.missions import StateConflict

Color = Annotated[str, Field(pattern=r"^#[0-9A-Fa-f]{6}$")]


class ThumbnailLayout(Definition):
    model_config = ConfigDict(str_strip_whitespace=False)
    headline: str = Field(min_length=1, max_length=100)
    subtitle: str = Field(max_length=160)
    background: Color
    foreground: Color
    accent: Color
    composition: Literal["left", "center"]
    decoration: Literal["circle", "bars", "none"]

    @field_validator("headline", "subtitle")
    @classmethod
    def supported_text(cls, value: str) -> str:
        if any(not 32 <= ord(char) <= 126 for char in value):
            raise ValueError("Graphic thumbnail text supports printable ASCII only")
        return value

    @field_validator("headline")
    @classmethod
    def visible_headline(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Thumbnail headline must contain visible text")
        return value


class ThumbnailRenderingError(StateConflict):
    def __init__(self, safe_message: str) -> None:
        super().__init__(safe_message)
        self.safe_message = safe_message


class ThumbnailReceipt(Definition):
    renderer: Literal["agentos-graphic-v1"]
    pillow: str = Field(min_length=1, max_length=40)
    font_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    png_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    width: Literal[1280]
    height: Literal[720]


class ThumbnailEvidence(Definition):
    layout: ThumbnailLayout
    receipt: ThumbnailReceipt
