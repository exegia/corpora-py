"""admin.ingest — Docling-based ingestion into the Context Fabric v1 graph.

Unlike `admin.parsers` (which reduces sources to the `Document`/`Unit` tree
consumed by the Text-Fabric walker), this package extracts uploaded documents
directly into the canonical content graph specified by
`docs/architecture/context-fabric/` and the JSON Schemas shipped in
`corpora-common` — ContentNode trees, TextFragments, and PhysicalLocators
that keep Docling's page/bbox provenance.

`extract_graph` (pure mapping over `docling-core` models) is always
available; `parse_file` additionally needs the heavy `docling` converter,
installed via the `corpora-admin[docling]` extra.
"""

from .docling_graph import (
    SCHEMA_VERSION,
    CanonicalGraph,
    DoclingNotInstalledError,
    extract_graph,
    parse_file,
)
from .validation import GraphValidationError, validate_graph

__all__ = [
    "SCHEMA_VERSION",
    "CanonicalGraph",
    "DoclingNotInstalledError",
    "GraphValidationError",
    "extract_graph",
    "parse_file",
    "validate_graph",
]
