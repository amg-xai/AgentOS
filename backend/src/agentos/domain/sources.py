"""Bounded supplied-source evidence; exact quotes establish provenance, not truth."""

from typing import Annotated

from pydantic import ConfigDict, Field, field_validator

from agentos.domain.base import Definition, Identifier


class SourceText(Definition):
    model_config = ConfigDict(str_strip_whitespace=False)
    id: Identifier
    label: str = Field(min_length=1, max_length=160)
    body: str = Field(min_length=1, max_length=12000)

    @field_validator("label", "body")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Source text must not be blank")
        return value


def validate_sources(sources: tuple[SourceText, ...]) -> tuple[SourceText, ...]:
    if len({source.id for source in sources}) != len(sources):
        raise ValueError("Source IDs must be unique")
    if sum(len(source.body) for source in sources) > 48000:
        raise ValueError("Source text exceeds 48000 characters")
    return sources


class EvidenceItem(Definition):
    model_config = ConfigDict(str_strip_whitespace=False)
    source_id: Identifier
    quote: str = Field(min_length=1, max_length=800)
    interpretation: str = Field(min_length=1, max_length=800)

    @field_validator("quote", "interpretation")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Evidence must not be blank")
        return value


class ResearchResult(Definition):
    model_config = ConfigDict(str_strip_whitespace=False)
    summary: str = Field(min_length=1, max_length=2000)
    evidence: tuple[EvidenceItem, ...] = Field(min_length=1, max_length=8)
    limitations: tuple[Annotated[str, Field(min_length=1, max_length=500)], ...] = Field(
        max_length=8
    )

    def verify(self, sources: tuple[SourceText, ...]) -> None:
        by_id = {source.id: source.body for source in validate_sources(sources)}
        if not self.summary.strip() or any(not item.strip() for item in self.limitations):
            raise ValueError("Research text must not be blank")
        for item in self.evidence:
            if item.source_id not in by_id or item.quote not in by_id[item.source_id]:
                raise ValueError("Research quote does not match supplied source text")
