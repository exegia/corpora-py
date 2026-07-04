"""
Shared Text-Fabric walking logic used by every `_{format}_to_tf.py` converter.

Every format parser (see `parsers/schema.py`) already reduces its source to
the same `Document`/`Unit` tree, so the walk from that tree into Text-Fabric
nodes/slots is identical across formats. Each `_{format}_to_tf.py` module
only supplies:

- a `Parser` to turn its source into a `Document`
- a name for the root node that wraps the whole document (e.g. "book")
- `otype_for(unit)`, mapping the parser's free-form `Unit.type` down to the
  handful of Text-Fabric node types that format wants to expose

and calls `convert_document()` here to do the actual walk.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from tf.convert.walker import CV
from tf.fabric import Fabric

from ..parsers.schema import Document, DocumentMetadata, Parser, Token, Unit

TypeMapper = Callable[[Unit], str]


def metadata_features(metadata: DocumentMetadata) -> dict[str, str]:
    """Flatten `DocumentMetadata` into scalar Text-Fabric feature values."""
    features: dict[str, str] = {
        "title": metadata.title or "Untitled",
        "source_format": metadata.source_format.value,
    }
    if metadata.creators:
        features["creators"] = "; ".join(metadata.creators)
    if metadata.language:
        features["language"] = metadata.language
    if metadata.publisher:
        features["publisher"] = metadata.publisher
    if metadata.date:
        features["date"] = metadata.date
    if metadata.description:
        features["description"] = metadata.description
    if metadata.identifier:
        features["identifier"] = metadata.identifier
    if metadata.rights:
        features["rights"] = metadata.rights
    if metadata.subjects:
        features["subjects"] = "; ".join(metadata.subjects)
    features.update(metadata.extra)
    return features


def set_features(cv: CV, node: tuple[str, int], **features: Any) -> None:
    """
    `cv.feature()` the given values, first registering metadata for any
    feature name not already known.

    Feature names here vary per source document (HTML/TEI attributes,
    document metadata, ...), so they can't all be declared upfront in
    `cv.walk(featureMeta=...)`. Text-Fabric's walker supports registering
    them as they're encountered instead, via `cv.meta()`.
    """
    for name in features:
        cv.meta(name, description=f"'{name}' feature", valueType="str")
    cv.feature(node, **features)


def _unit_features(unit: Unit) -> dict[str, Any]:
    features: dict[str, Any] = {"tag": unit.type}
    if unit.label is not None:
        features["label"] = unit.label
    if unit.id is not None:
        features["uid"] = unit.id
    # Source attributes win on name collisions (e.g. an HTML id="..." vs
    # our own "uid" is already a different name, but this keeps the source
    # data authoritative for anything we didn't rename).
    features.update(unit.attrs)
    return features


def _walk_unit(cv: CV, unit: Unit, otype_for: TypeMapper) -> None:
    node = cv.node(otype_for(unit))
    set_features(cv, node, **_unit_features(unit))

    for child in unit.children:
        _walk_unit(cv, child, otype_for)

    tokens = unit.tokens
    if not tokens and not unit.children:
        # A node covering zero slots gets silently dropped by Text-Fabric's
        # "remove unlinked nodes" pass. A genuinely empty leaf (an <img>, an
        # <hr>, a blank page) still deserves a node — e.g. to keep its
        # attributes queryable — so give it one placeholder empty slot.
        tokens = [Token(text="", after="")]

    for token in tokens:
        slot = cv.slot()
        set_features(cv, slot, text=token.text, after=token.after)

    cv.terminate(node)


def convert_document(
    parser: Parser,
    source: str,
    output_dir: str | Path,
    *,
    root_type: str,
    otype_for: TypeMapper,
) -> Path:
    """
    Convert `source` (read via `parser`) into a Text-Fabric dataset at
    `output_dir`.

    Every top-level `Unit` of the parsed `Document` is wrapped in one
    `root_type` node (e.g. "book", "text") that carries the document's
    metadata as features; `otype_for` decides the Text-Fabric node type for
    everything nested inside it.
    """
    document: Document = parser.parse(source)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    def director(cv: CV) -> None:
        root = cv.node(root_type)
        set_features(cv, root, **metadata_features(document.metadata))
        for unit in document.units:
            _walk_unit(cv, unit, otype_for)
        cv.terminate(root)

    tf = Fabric(locations=str(output_path))
    cv = CV(tf)
    good = cv.walk(
        director,
        "word",
        otext={
            # A single section level — the whole document — is enough
            # structure to satisfy Text-Fabric's validation; formats that
            # want finer-grained sections still expose them as ordinary
            # node types (e.g. "chapter", "page") via `otype_for`.
            "sectionTypes": root_type,
            "sectionFeatures": "title",
            "fmt:text-orig-full": "{text}{after}",
        },
        generic={"converter": "corpora-admin", "format": parser.format.value},
    )
    if not good:
        raise RuntimeError(f"Text-Fabric conversion failed for {source!r}")
    return output_path
