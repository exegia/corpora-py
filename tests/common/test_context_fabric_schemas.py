"""Validate the Context Fabric v1 JSON Schemas and their example payloads.

Two guarantees:

1. Every ``*.schema.json`` under ``common/schemas/context_fabric/v1/`` is a valid
   JSON Schema Draft 2020-12 document with a unique ``$id``.
2. Every example payload listed in ``examples/index.json`` validates against the
   schema ``$ref`` the index assigns to it, and no fixture file is left out of
   the index (an unlisted fixture would silently skip validation).

The schemas cross-reference each other by absolute ``$id`` URI; nothing is
fetched over the network — a ``referencing.Registry`` resolves them offline.
"""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

SCHEMA_DIR = (
    Path(__file__).resolve().parents[2]
    / "packages"
    / "common"
    / "src"
    / "common"
    / "schemas"
    / "context_fabric"
    / "v1"
)
EXAMPLES_DIR = SCHEMA_DIR / "examples"

SCHEMA_PATHS = sorted(SCHEMA_DIR.glob("*.schema.json"))
DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def registry() -> Registry:
    resources = [
        (schema["$id"], Resource.from_contents(schema))
        for schema in (_load(p) for p in SCHEMA_PATHS)
    ]
    return Registry().with_resources(resources)


def test_schema_dir_is_populated():
    assert len(SCHEMA_PATHS) >= 12, f"expected the v1 schema set, found {len(SCHEMA_PATHS)}"


@pytest.mark.parametrize("path", SCHEMA_PATHS, ids=lambda p: p.name)
def test_schema_is_valid_draft_2020_12(path: Path):
    schema = _load(path)
    assert schema.get("$schema") == DRAFT_2020_12, f"{path.name} must declare draft 2020-12"
    assert schema.get("$id", "").endswith(path.name), (
        f"{path.name}: $id must end with the filename for offline resolution"
    )
    Draft202012Validator.check_schema(schema)


def test_schema_ids_are_unique():
    ids = [_load(p)["$id"] for p in SCHEMA_PATHS]
    assert len(ids) == len(set(ids))


def _example_index() -> dict[str, str]:
    return _load(EXAMPLES_DIR / "index.json")["examples"]


@pytest.mark.parametrize(("example_name", "schema_ref"), sorted(_example_index().items()))
def test_example_validates_against_schema(example_name: str, schema_ref: str, registry: Registry):
    instance = _load(EXAMPLES_DIR / example_name)
    validator = Draft202012Validator({"$ref": schema_ref}, registry=registry)
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.absolute_path))
    assert not errors, "\n".join(
        f"at /{'/'.join(str(p) for p in e.absolute_path)}: {e.message}" for e in errors
    )


def test_every_fixture_is_listed_in_index():
    listed = set(_example_index())
    on_disk = {p.name for p in EXAMPLES_DIR.glob("*.json")} - {"index.json"}
    assert on_disk == listed, (
        f"unlisted fixtures: {on_disk - listed}; missing files: {listed - on_disk}"
    )
