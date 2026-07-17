"""Runtime validation of emitted graphs against the shipped v1 JSON Schemas.

The Context Fabric schemas are packaged inside `corpora-common`
(`common/schemas/context_fabric/v1/`) precisely so converters can validate
their output offline at conversion time (phase 2 of
`docs/architecture/context-fabric/07-migration-mapping.md`). The schemas
cross-reference each other by absolute `$id` URI; a `referencing.Registry`
resolves them without any network fetch — same mechanism as
`tests/common/test_context_fabric_schemas.py`.
"""

from __future__ import annotations

import json
from functools import cache, lru_cache
from importlib import resources
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

_SCHEMA_ID_BASE = "https://schemas.exegia.co/context-fabric/v1/"


class GraphValidationError(ValueError):
    """An emitted graph violates the Context Fabric v1 schemas."""


@lru_cache(maxsize=1)
def _registry() -> Registry:
    schema_dir = resources.files("common") / "schemas" / "context_fabric" / "v1"
    resource_list = []
    for entry in schema_dir.iterdir():
        if entry.name.endswith(".schema.json"):
            schema = json.loads(entry.read_text(encoding="utf-8"))
            resource_list.append((schema["$id"], Resource.from_contents(schema)))
    return Registry().with_resources(resource_list)


@cache
def validator_for(schema_filename: str) -> Draft202012Validator:
    """A validator for one shipped schema file (e.g. ``"content-node.schema.json"``)."""
    return Draft202012Validator(
        {"$ref": _SCHEMA_ID_BASE + schema_filename}, registry=_registry()
    )


def _collect_errors(instance: dict[str, Any], schema_filename: str, at: str) -> list[str]:
    validator = validator_for(schema_filename)
    return [
        f"{at}/{'/'.join(str(p) for p in error.absolute_path)}: {error.message}"
        for error in sorted(validator.iter_errors(instance), key=lambda e: list(e.absolute_path))
    ]


def validate_graph(graph: dict[str, Any]) -> None:
    """Validate every entity of a graph dict (see `CanonicalGraph.to_dict()`).

    Raises `GraphValidationError` listing every violation across all
    entities, rather than stopping at the first, so one failed conversion
    surfaces everything wrong with it at once.
    """
    errors: list[str] = []
    for key, schema_filename in (
        ("corpus", "corpus.schema.json"),
        ("work", "work.schema.json"),
        ("edition", "edition.schema.json"),
        ("sourceAsset", "source-asset.schema.json"),
    ):
        if key in graph:
            errors.extend(_collect_errors(graph[key], schema_filename, at=key))
    for i, node in enumerate(graph.get("nodes", [])):
        errors.extend(_collect_errors(node, "content-node.schema.json", at=f"nodes[{i}]"))
    for i, fragment in enumerate(graph.get("fragments", [])):
        errors.extend(
            _collect_errors(fragment, "text-fragment.schema.json", at=f"fragments[{i}]")
        )
    if errors:
        raise GraphValidationError(
            "graph violates the Context Fabric v1 schemas:\n" + "\n".join(errors)
        )
