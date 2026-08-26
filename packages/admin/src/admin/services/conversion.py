"""Transport-free conversion pipeline: source document → ``.corpus`` archive.

This is the one place the end-to-end orchestration lives — parse →
Text-Fabric → ``.cfm`` → ``.corpus`` plus the pre-derived display name and
the post-conversion validation gate (issue #177). It knows nothing about
HTTP, jobs, or threads: `admin.services.api._run_conversion` wraps it with
`JobManager` bookkeeping for the `/convert` surface, and the `corpora` CLI
(`corpora_py.cli`, issue #188) calls it directly for terminal conversions.
The Tauri sidecar (issue #187) gets the same seam for free via the API.

Progress is reported through the optional callbacks (`on_log`,
`on_display_name`, `on_validation`) — coarse, fixed checkpoints, not real
percentages (the converters have no mid-call progress hook, see
`packages/admin/CLAUDE.md`).

Error contract:

- `ConversionError` — the message is user-facing by design (the sanctioned
  passthrough for converter ``ValueError`` messages, issue #184).
- `CorpusValidationError` (a `ConversionError`) — the built archive failed
  `validate_corpus_archive`; carries the full validation ``summary``.
- A converter ``ValueError`` whose message names a private server path is
  re-raised as-is (never wrapped), so callers keep it behind a sanitized
  generic message.
- Anything else propagates untouched.
"""

from __future__ import annotations

import logging
import re
import shutil
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from ..converters import CONVERTERS
from ..converters.convert_to_corpus import convert_to_corpus
from ..parsers import PARSERS
from ..parsers.schema import CorpusCategory, SourceFormat

logger = logging.getLogger("corpora.admin.conversion")

__all__ = [
    "ConversionError",
    "CorpusValidationError",
    "clean_filename_stem",
    "derive_display_name",
    "extract_source_title",
    "mentions_any_path",
    "run_conversion",
    "validate_archive",
]


class ConversionError(Exception):
    """Conversion failed with a deliberately user-facing message."""


class CorpusValidationError(ConversionError):
    """The converted archive failed post-conversion validation (issue #177)."""

    def __init__(self, message: str, summary: dict[str, Any] | None = None):
        super().__init__(message)
        self.summary = summary


def clean_filename_stem(filename: str) -> str:
    """Turn an upload filename into a human-readable fallback title.

    Strips the extension, replaces ``-`` and ``_`` with spaces, collapses
    repeated whitespace, and strips. ``"summa-theologia-1200-ENG.xml"`` ->
    ``"summa theologia 1200 ENG"``. This is the last-resort fallback (see
    `derive_display_name`) for when the source has no extractable title and
    the caller supplied no ``name`` -- not a title-caser, so the original
    letter casing survives untouched.
    """
    stem = Path(filename).stem
    return re.sub(r"\s+", " ", stem.replace("-", " ").replace("_", " ")).strip()


def extract_source_title(
    source_format: SourceFormat, source_path: Path
) -> str | None:
    """Read the source document's own title, if a parser knows how.

    Uses the format parser's lightweight ``parse_metadata`` (headers only --
    TEI ``teiHeader``, PDF ``info``, HTML ``<title>``, EPUB ``dc:title``),
    not the full parse, so this is cheap to run before the expensive TF
    walk. Returns ``None`` for formats without a parser (``tf_zip`` --
    already a dataset, no source metadata; ``tei_zip`` -- multiple
    documents, no single title), so the caller falls back to the request
    ``name`` / filename stem (see issue #109).
    """
    parser = PARSERS.get(source_format)
    if parser is None:
        return None
    try:
        return parser.parse_metadata(str(source_path)).title
    except Exception:
        logger.warning(
            "Metadata extraction failed for %s (%s) -- falling back to "
            "request name",
            source_path.name,
            source_format.value,
            exc_info=True,
        )
        return None


def derive_display_name(
    *,
    source_format: SourceFormat,
    source_path: Path,
    name: str,
) -> str:
    """Pick the human-readable title that becomes ``manifest.name``.

    Priority (see issue #109):
    1. The source document's own title (TEI ``titleStmt``, PDF
       ``info.title``, HTML ``<title>``, EPUB ``dc:title``) -- a person would
       read this.
    2. The request ``name`` (whatever the client sent -- may already be
       human-readable).
    3. A cleaned upload filename stem (spaces, not kebab).

    Never returns an empty string: the filename stem is the final stop and
    always has at least the stem of the uploaded file.
    """
    source_title = extract_source_title(source_format, source_path)
    if source_title and source_title.strip():
        return source_title.strip()
    if name and name.strip():
        return name.strip()
    return clean_filename_stem(source_path.name) or name


def mentions_any_path(message: str, paths: Sequence[str]) -> bool:
    """True when an exception message leaks one of the given filesystem paths.

    Guards `run_conversion`'s ``ValueError`` passthrough: the message may
    round-trip to end users, so one naming a private server-side location
    must stay behind the caller's generic sanitized form.
    """
    return any(path and path in message for path in paths)


def validate_archive(archive: Path) -> dict[str, Any]:
    """Run `validate_corpus_archive` over a ``.corpus`` and return its summary.

    Imported lazily: `corpora_mcp` is a sibling workspace package that admin
    doesn't import at module load (and the lazy call-time attribute is the
    test seam the services conftest stubs).
    """
    from corpora_mcp.validate import validate_corpus_archive

    return validate_corpus_archive(archive).summary()


def _noop(*_args: Any) -> None:
    return None


def run_conversion(
    *,
    source_path: Path,
    work_dir: Path,
    source_format: SourceFormat,
    output_path_for: Callable[[str], Path],
    name: str = "",
    description: str = "",
    category: CorpusCategory | None = None,
    author_sub: str | None = None,
    converters: Mapping[SourceFormat, Callable[..., Any]] | None = None,
    convert_fn: Callable[..., Path] | None = None,
    private_paths: Sequence[str] = (),
    on_log: Callable[[str], None] = _noop,
    on_display_name: Callable[[str], None] = _noop,
    on_validation: Callable[[dict[str, Any]], None] = _noop,
) -> Path:
    """Blocking pipeline: parse -> Text-Fabric -> .cfm -> .corpus -> validate.

    Long-running, CPU-bound -- never call it from an async endpoint without
    a worker thread. Always cleans up ``work_dir`` (which must hold only
    intermediates -- the ``tf/`` tree is built inside it) on the way out,
    success or failure; only the final ``.corpus``, written to the path
    `output_path_for` returns for the derived display name, survives. The
    caller owns ``source_path`` -- it is only deleted when it lives inside
    ``work_dir`` (the upload case; a CLI source file elsewhere is untouched).

    ``converters`` / ``convert_fn`` default to the real `CONVERTERS` /
    `convert_to_corpus` and exist so a transport wrapper can inject its own
    (module-global, monkeypatchable) references.

    The display name (issue #109) is derived before the expensive TF walk
    and reported through ``on_display_name`` so a status surface can show it
    while the job runs; `on_log` receives the coarse stage checkpoints.
    """
    active_converters = converters if converters is not None else CONVERTERS
    active_convert = convert_fn if convert_fn is not None else convert_to_corpus

    display_name = derive_display_name(
        source_format=source_format, source_path=source_path, name=name
    )
    on_display_name(display_name)
    try:
        if source_format == SourceFormat.TF_ZIP:
            on_log("Inspecting ZIP and importing Text-Fabric dataset...")
        elif source_format == SourceFormat.TEI_ZIP:
            on_log(
                "Extracting TEI documents from ZIP and building Text-Fabric dataset..."
            )
        else:
            on_log(
                f"Parsing {source_format.value} source and building Text-Fabric dataset..."
            )
        converter = active_converters[source_format]
        tf_dir = work_dir / "tf"
        try:
            dataset = converter(str(source_path), tf_dir, category=category)
        except ValueError as exc:
            # Parsers/converters raise `ValueError` with deliberately
            # user-facing messages ("ZIP contains multiple Text-Fabric
            # datasets: ...", "not a valid ZIP archive") -- the sanctioned
            # passthrough (issue #184). Messages that mention private
            # server-side paths keep the caller's sanitized form.
            message = str(exc).strip()
            if message and not mentions_any_path(message, private_paths):
                raise ConversionError(message) from exc
            raise
        # Converters return a `ConvertedDataset` carrying the resolved
        # category (auto-detected, possibly downgrading the request -- issue
        # #176) and human-readable warnings (skipped OCR pages, downgraded
        # overrides) that belong on the caller's log.
        resolved = getattr(dataset, "category", None) or category
        for warning in getattr(dataset, "warnings", []):
            on_log(warning)

        on_log(
            "Text-Fabric dataset ready. Compiling cache and packaging .corpus archive..."
        )
        result = active_convert(
            tf_dir,
            output_path_for(display_name),
            name=display_name,
            description=description,
            author_sub=author_sub,
            category=resolved.value if resolved else "",
        )

        on_log("Validating converted corpus...")
        summary = validate_archive(result)
        on_validation(summary)
        if not summary.get("valid"):
            reasons = [str(r) for r in summary.get("reasons") or []]
            detail = "; ".join(reasons[:3]) or "corpus integrity checks failed"
            raise CorpusValidationError(
                f"Converted corpus failed validation: {detail}", summary
            )
        on_log("Conversion complete.")
        return result
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
