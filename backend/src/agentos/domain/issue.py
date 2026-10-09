"""Bounded local issue proposals; neither reproduction nor test-pass evidence."""

import json
from typing import Annotated, Any

from pydantic import Field

from agentos.domain.base import Definition

ShortText = Annotated[str, Field(strict=True, min_length=1, max_length=1000)]


class IssueSpec(Definition):
    title: str = Field(strict=True, min_length=1, max_length=160)
    problem: str = Field(strict=True, min_length=1, max_length=4000)
    observed_behavior: str = Field(strict=True, min_length=1, max_length=4000)
    expected_behavior: str = Field(strict=True, min_length=1, max_length=4000)
    suggested_reproduction_steps: tuple[ShortText, ...] = Field(min_length=1, max_length=8)
    proposed_acceptance_criteria: tuple[ShortText, ...] = Field(min_length=1, max_length=8)
    limitations: tuple[ShortText, ...] = Field(max_length=8)


def issue_schema() -> dict[str, Any]:
    return IssueSpec.model_json_schema()


def issue_evidence(value: object, *, reviewed: bool = False) -> dict[str, str]:
    issue = IssueSpec.model_validate(value)
    # Fence each value so model prose is displayed as evidence, not active markup.
    sections = [
        "# Local issue proposal",
        "Suggested reproduction and acceptance criteria are proposals, not proof of "
        "reproduction, coverage, correctness or passing tests.",
    ]
    for key, content in issue.model_dump(mode="json").items():
        sections.append("## " + key.replace("_", " ").capitalize())
        values = content if isinstance(content, list) else [content]
        sections.extend("    " + line for item in values for line in item.splitlines())
    prefix = "reviewed-" if reviewed else ""
    return {
        prefix + "issue.json": json.dumps(issue.model_dump(mode="json"), indent=2) + "\n",
        prefix + "issue.md": "\n\n".join(sections) + "\n",
    }
