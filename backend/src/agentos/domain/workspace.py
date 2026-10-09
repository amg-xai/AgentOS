"""Explicit local workspace configuration and durable context contracts."""

from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Annotated

from pydantic import Field, field_validator

from agentos.domain.base import Definition, Text
from agentos.domain.creator import SourceText, validate_sources
from agentos.domain.student import StudySettings


def scoped_path(value: str) -> str:
    path = PurePosixPath(value.replace("\\", "/"))
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {".", ".."} or ":" in part for part in path.parts)
        or any(part.lower() in {".git", ".agentos", "node_modules", ".venv"} for part in path.parts)
        or any(part.lower().startswith(".env") for part in path.parts)
        or path.suffix.lower() in {".key", ".pem", ".pfx", ".p12"}
    ):
        raise ValueError("File must be a scoped relative source path without secret/config paths")
    return path.as_posix()


class WorkspaceSettings(Definition):
    name: Text
    repository: Path
    files: Annotated[tuple[str, ...], Field(min_length=1, max_length=64)]
    test_commands: Annotated[tuple[tuple[str, ...], ...], Field(min_length=1, max_length=8)]
    test_timeout_seconds: int = Field(default=30, ge=1, le=120)

    @field_validator("files")
    @classmethod
    def safe_files(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        paths = tuple(scoped_path(value) for value in values)
        if len(set(path.casefold() for path in paths)) != len(paths):
            raise ValueError("Workspace file paths must be unique")
        return paths

    @field_validator("test_commands")
    @classmethod
    def safe_commands(cls, values: tuple[tuple[str, ...], ...]) -> tuple[tuple[str, ...], ...]:
        for command in values:
            if (
                not command
                or len(command) > 64
                or any(
                    not part or len(part) > 1000 or any(c in part for c in "\n\r\x00")
                    for part in command
                )
            ):
                raise ValueError("Test commands must be bounded argv arrays")
            executable = Path(command[0]).stem.lower()
            if executable not in {"python", "python3", "pytest", "node", "npm", "npx"}:
                raise ValueError("Only Python/pytest or Node/npm test runners are supported")
            if any(arg in {"-c", "-e", "--eval", "--exec"} for arg in command[1:]):
                raise ValueError("Inline execution is not a test command")
        return values


class MemoryCreate(Definition):
    title: Annotated[str, Field(min_length=1, max_length=160)]
    content: Annotated[str, Field(min_length=1, max_length=8000)]
    artifact_refs: Annotated[tuple[str, ...], Field(max_length=20)] = ()


class MemoryNote(MemoryCreate):
    id: str
    workspace_id: str = "local"
    created_at: datetime


class DeveloperMissionCreate(Definition):
    goal: Annotated[str, Field(min_length=1, max_length=8000)]


class CreatorMissionCreate(Definition):
    goal: Annotated[str, Field(min_length=1, max_length=8000)]
    sources: tuple[SourceText, ...] = Field(default=(), max_length=8)

    _sources = field_validator("sources")(validate_sources)


class StudentMissionCreate(Definition):
    goal: Annotated[str, Field(min_length=1, max_length=8000)]
    study_settings: StudySettings | None = None
