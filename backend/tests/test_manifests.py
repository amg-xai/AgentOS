import json
from pathlib import Path

import pytest
from conftest import PACKAGES

from agentos.adapters.manifests import ManifestError, load_registry


@pytest.fixture
def manifests(tmp_path):
    for source in (PACKAGES / "developer").glob("*.json"):
        (tmp_path / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return tmp_path


def rewrite(root: Path, filename: str, mutate):
    path = root / filename
    data = json.loads(path.read_text(encoding="utf-8"))
    mutate(data)
    path.write_text(json.dumps(data), encoding="utf-8")


@pytest.mark.parametrize(
    "filename,mutate,match",
    [
        ("agents.json", lambda d: d.update(schema_version=2), "schema_version"),
        ("agents.json", lambda d: d["agents"][0].update(permissions=["SUPERUSER"]), "permissions"),
        (
            "agents.json",
            lambda d: d["agents"][0].update(input_schema={"type": "nonsense"}),
            "schema",
        ),
        (
            "agents.json",
            lambda d: d["agents"][0].update(input_schema={"$ref": "https://example.com/schema"}),
            "local fragments",
        ),
        (
            "agents.json",
            lambda d: d["agents"][0].update(
                input_schema={"$schema": "https://json-schema.org/draft-07/schema#"}
            ),
            "Draft 2020-12",
        ),
        ("agents.json", lambda d: d["agents"][0].update(role="other"), "role does not match"),
        ("agents.json", lambda d: d["agents"].append(d["agents"][0]), "Duplicate id"),
        ("agents.json", lambda d: d["agents"][0].update(instructions="  "), "instructions"),
        ("agents.json", lambda d: d["agents"][0].update(tools=["git", "git"]), "unique"),
        ("role.json", lambda d: d["role"].update(agents=["missing"]), "unknown agent"),
        ("role.json", lambda d: d["role"].update(tools=["external_service"]), "unknown tools"),
        ("role.json", lambda d: d.update(kind="unknown"), "Unknown manifest kind"),
    ],
)
def test_invalid_manifests_are_rejected(manifests, filename, mutate, match):
    rewrite(manifests, filename, mutate)
    with pytest.raises(ManifestError, match=match) as exc:
        load_registry(manifests)
    assert str(manifests) in str(exc.value)


def test_invalid_json(manifests):
    (manifests / "agents.json").write_text("{", encoding="utf-8")
    with pytest.raises(ManifestError, match="agents.json"):
        load_registry(manifests)


def test_empty_or_missing_root(tmp_path):
    for root in (tmp_path, tmp_path / "missing"):
        with pytest.raises(ManifestError, match="No JSON manifests"):
            load_registry(root)


@pytest.mark.parametrize("version", [True, 1.0, "1", None])
def test_manifest_version_is_an_exact_integer(manifests, version):
    rewrite(manifests, "role.json", lambda d: d.update(schema_version=version))
    with pytest.raises(ManifestError, match="schema_version"):
        load_registry(manifests)


def test_failed_load_does_not_change_existing_registry(manifests, registry):
    rewrite(manifests, "agents.json", lambda d: d["agents"].append(d["agents"][0]))
    with pytest.raises(ManifestError):
        load_registry(manifests)
    assert len(registry.agents()) == 9
