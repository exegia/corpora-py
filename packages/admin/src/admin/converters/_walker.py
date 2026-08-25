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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tf.convert.walker import CV
from tf.fabric import Fabric

from ..parsers.schema import CorpusCategory, Document, DocumentMetadata, Parser, Token, Unit

TypeMapper = Callable[[Unit], str]


@dataclass(frozen=True)
class SectionSpec:
    """Ordered Text-Fabric section levels for one dataset (issue #174).

    ``types[i]`` is the node type of section level ``i+1`` (coarsest first)
    and ``features[i]`` is the feature that carries that level's human
    label in ``T.sectionFromNode`` refs. The walker guarantees every node
    of a section type actually carries its label feature (see
    `_section_label`), because a section node without one breaks
    `T.sectionFromNode` and every ref-based read built on it.
    """

    types: tuple[str, ...]
    features: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.types or len(self.types) != len(self.features):
            raise ValueError("SectionSpec needs one feature per section type")

    @property
    def feature_for(self) -> dict[str, str]:
        return dict(zip(self.types, self.features, strict=True))


class ConvertedDataset(Path):
    """The TF dataset path, annotated with what the conversion resolved.

    A plain `Path` to every existing caller; `category` (what should land in
    ``manifest.category``) and `warnings` (human-readable notes to surface on
    the job log, e.g. a downgraded category override or skipped OCR pages)
    ride along for callers that know to look (issues #175/#176).
    """

    category: CorpusCategory | None
    warnings: list[str]

    @classmethod
    def wrap(
        cls,
        path: str | Path,
        *,
        category: CorpusCategory | None = None,
        warnings: list[str] | None = None,
    ) -> "ConvertedDataset":
        result = cls(path)
        result.category = category
        result.warnings = list(warnings or [])
        return result


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


def _section_label(
    unit: Unit, otype: str, counters: dict[str, int]
) -> str:
    """A guaranteed-nonempty label for a section node (issue #174).

    Prefers the unit's own `label` (a TEI `<head>`, a markdown heading),
    then its source `id`, then a per-parent 1-based ordinal of that type
    ("Chapter 3" territory, rendered as just "3") -- so `T.sectionFromNode`
    always has something human-usable at every declared level.
    """
    if unit.label and unit.label.strip():
        return unit.label.strip()
    if unit.id and unit.id.strip():
        return unit.id.strip()
    return str(counters[otype])


def _walk_unit(
    cv: CV,
    unit: Unit,
    otype_for: TypeMapper,
    section_features: dict[str, str] | None = None,
    counters: dict[str, int] | None = None,
) -> None:
    section_features = section_features or {}
    counters = {} if counters is None else counters
    otype = otype_for(unit)
    counters[otype] = counters.get(otype, 0) + 1
    node = cv.node(otype)
    features = _unit_features(unit)
    section_feature = section_features.get(otype)
    if section_feature is not None and not features.get(section_feature):
        features[section_feature] = _section_label(unit, otype, counters)
    set_features(cv, node, **features)

    child_counters: dict[str, int] = {}
    for child in unit.children:
        _walk_unit(cv, child, otype_for, section_features, child_counters)

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
    section_spec: SectionSpec | None = None,
    category: CorpusCategory | None = None,
) -> ConvertedDataset:
    """
    Convert `source` (read via `parser`) into a Text-Fabric dataset at
    `output_dir`.

    Every top-level `Unit` of the parsed `Document` is wrapped in one
    `root_type` node (e.g. "book", "text") that carries the document's
    metadata as features; `otype_for` decides the Text-Fabric node type for
    everything nested inside it.
    """
    return convert_documents(
        [parser.parse(source)],
        output_dir,
        root_type=root_type,
        otype_for=otype_for,
        format_value=parser.format.value,
        source_label=source,
        section_spec=section_spec,
        category=category,
    )


def convert_documents(
    documents: list[Document],
    output_dir: str | Path,
    *,
    root_type: str,
    otype_for: TypeMapper,
    format_value: str,
    source_label: str,
    section_spec: SectionSpec | None = None,
    category: CorpusCategory | None = None,
) -> ConvertedDataset:
    """
    Convert one or more already-parsed `Document`s into a single Text-Fabric
    dataset at `output_dir`.

    Each document becomes its own `root_type` node carrying that document's
    metadata as features, so a multi-document source (e.g. a ZIP of TEI
    files, one per book) lands as sibling sections of one dataset rather
    than one dataset per file. With a single document this is exactly the
    classic `convert_document` walk.
    """
    if not documents:
        raise ValueError("No documents to convert")
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Default: a single section level — the document root, labeled by its
    # `title`. A caller wanting finer TF sections (chapters, verses — issue
    # #174) passes a `SectionSpec` whose levels its `otype_for` actually
    # emits; anything not declared as a section stays an ordinary node type.
    spec = section_spec or SectionSpec(types=(root_type,), features=("title",))
    section_features = spec.feature_for

    def director(cv: CV) -> None:
        for document in documents:
            root = cv.node(root_type)
            features = metadata_features(document.metadata)
            root_feature = section_features.get(root_type)
            if root_feature is not None and not features.get(root_feature):
                features[root_feature] = features["title"]
            set_features(cv, root, **features)
            counters: dict[str, int] = {}
            for unit in document.units:
                _walk_unit(cv, unit, otype_for, section_features, counters)
            cv.terminate(root)

    tf = Fabric(locations=str(output_path))
    cv = CV(tf)
    good = cv.walk(
        director,
        "word",
        otext={
            "sectionTypes": ",".join(spec.types),
            "sectionFeatures": ",".join(spec.features),
            "fmt:text-orig-full": "{text}{after}",
        },
        generic={"converter": "corpora-admin", "format": format_value},
    )
    if not good:
        raise RuntimeError(f"Text-Fabric conversion failed for {source_label!r}")
    return ConvertedDataset.wrap(output_path, category=category)
