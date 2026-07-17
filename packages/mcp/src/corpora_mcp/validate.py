"""Validate that a Text-Fabric dataset is a valid Context-Fabric corpus.

Runs a downloaded/converted corpus through the full Context-Fabric cycle:

1. (optional) Text-Fabric loading from ``.tf`` files when text-fabric is installed
2. Context-Fabric loading from ``.tf`` files (which auto-compiles to ``.cfm``)
3. Context-Fabric loading from the ``.cfm`` mmap cache

Feature values are sampled from both the ``.tf`` and ``.cfm`` loading paths to
verify data integrity through the compile/load cycle. Caches are cleared first
so every validation starts from a clean state and error attribute correctly.

Two entry points:

* :func:`validate_corpus` validates a ``.tf`` dataset *directory* -- it clears
  any existing cache and recompiles, so it answers "do these ``.tf`` files
  compile and round-trip?".
* :func:`validate_corpus_archive` validates a packaged ``.corpus`` zip. It
  additionally loads the ``corpora/.cfm`` cache that *ships inside the archive*
  as-is (before any clearing) and compares it against a fresh recompile from
  the ``.tf`` sources -- catching a corrupt or stale delivered cache, which
  validating a bare directory cannot.

This module lives in ``corpora_mcp`` (not ``admin``): it is the consumer-side
concern of "is this corpus loadable/queryable?", it depends only on the
Context-Fabric runtime the MCP server already uses, and keeping it here lets
the umbrella app (which depends on both ``corpora-mcp`` and ``corpora-admin``)
expose it over HTTP without ``admin`` having to depend on ``corpora-mcp``.

``cfabric`` and ``text-fabric`` are imported lazily inside the load helpers, so
importing this module never requires them (the MCP package deliberately does
not hard-depend on the Context-Fabric runtime -- see ``packages/mcp/pyproject``).
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SAMPLE_SIZE = 100
_MAX_REPORTED_MISMATCHES = 5

_STAT_FIELDS = ("max_slot", "max_node", "node_types", "node_features", "edge_features")


@dataclass
class FeatureSamples:
    """Sampled feature values for validation."""

    node_samples: dict[str, list[tuple[int, Any]]] = field(default_factory=dict)
    edge_samples: dict[str, list[tuple[int, int, Any]]] = field(default_factory=dict)
    text_samples: list[tuple[int, str]] = field(default_factory=list)


@dataclass
class CorpusStats:
    """Statistics from loading a corpus."""

    max_slot: int = 0
    max_node: int = 0
    node_types: int = 0
    node_features: int = 0
    edge_features: int = 0
    samples: FeatureSamples | None = None
    error: str | None = None


@dataclass
class ValidationResult:
    """Result of validating a single corpus."""

    corpus: str
    tf_stats: CorpusStats | None  # None when text-fabric is not installed
    cf_stats: CorpusStats
    cf_mmap_stats: CorpusStats
    # Stats from the .cfm that shipped inside a .corpus archive, loaded as-is.
    # None unless this was an archive validation (validate_corpus_archive).
    shipped_cfm_stats: CorpusStats | None = None

    @property
    def tf_ok(self) -> bool:
        return self.tf_stats is None or self.tf_stats.error is None

    @property
    def cf_ok(self) -> bool:
        return self.cf_stats.error is None

    @property
    def cf_mmap_ok(self) -> bool:
        return self.cf_mmap_stats.error is None

    @property
    def shipped_cfm_ok(self) -> bool:
        return self.shipped_cfm_stats is None or self.shipped_cfm_stats.error is None

    @property
    def shipped_cfm_stats_match(self) -> bool:
        """Shipped .cfm stats vs stats recompiled from the .tf sources."""
        if self.shipped_cfm_stats is None or not (self.shipped_cfm_ok and self.cf_ok):
            return True
        return _stat_diffs(self.shipped_cfm_stats, self.cf_stats) == []

    @property
    def shipped_cfm_samples_match(self) -> bool:
        """Shipped .cfm feature samples vs samples from a .tf recompile."""
        return self.get_shipped_sample_mismatches() == []

    @property
    def stats_match(self) -> bool:
        if self.tf_stats is None or not (self.tf_ok and self.cf_ok):
            return True  # nothing to compare
        return _stat_diffs(self.tf_stats, self.cf_stats) == []

    @property
    def mmap_stats_match(self) -> bool:
        """Check that .cfm loading produces same stats as .tf loading."""
        if not (self.cf_ok and self.cf_mmap_ok):
            return True
        return _stat_diffs(self.cf_stats, self.cf_mmap_stats) == []

    @property
    def samples_match(self) -> bool:
        """Check that feature value samples match between .tf and .cfm loading."""
        return self.get_sample_mismatches() == []

    @property
    def is_valid(self) -> bool:
        return (
            self.tf_ok
            and self.cf_ok
            and self.cf_mmap_ok
            and self.shipped_cfm_ok
            and self.stats_match
            and self.mmap_stats_match
            and self.samples_match
            and self.shipped_cfm_stats_match
            and self.shipped_cfm_samples_match
        )

    def get_sample_mismatches(self) -> list[str]:
        """Features whose samples differ between the .tf and .cfm (mmap) loads."""
        return _sample_mismatches(self.cf_stats.samples, self.cf_mmap_stats.samples)

    def get_shipped_sample_mismatches(self) -> list[str]:
        """Features whose samples differ between the shipped .cfm and a .tf recompile."""
        if self.shipped_cfm_stats is None:
            return []
        return _sample_mismatches(self.shipped_cfm_stats.samples, self.cf_stats.samples)

    def failure_reasons(self) -> list[str]:
        """Human-readable reasons this corpus failed validation (empty if valid)."""
        reasons: list[str] = []
        if self.tf_stats is not None and self.tf_stats.error is not None:
            reasons.append(
                f"Text-Fabric failed to load .tf files: {self.tf_stats.error}"
            )
        if self.cf_stats.error is not None:
            reasons.append(
                f"Context-Fabric failed to load .tf files: {self.cf_stats.error}"
            )
        if self.cf_mmap_stats.error is not None:
            reasons.append(
                f"Context-Fabric failed to load the compiled .cfm cache: "
                f"{self.cf_mmap_stats.error}"
            )
        if not self.stats_match and self.tf_stats is not None:
            for diff in _stat_diffs(self.tf_stats, self.cf_stats):
                reasons.append(f"Text-Fabric vs Context-Fabric stats differ: {diff}")
        if not self.mmap_stats_match:
            for diff in _stat_diffs(self.cf_stats, self.cf_mmap_stats):
                reasons.append(f".tf vs .cfm stats differ: {diff}")
        mismatches = self.get_sample_mismatches()
        if mismatches:
            reasons.append(
                "Feature values differ between .tf and .cfm loading: "
                + _format_mismatches(mismatches)
            )
        if self.shipped_cfm_stats is not None and self.shipped_cfm_stats.error is not None:
            reasons.append(
                f"Context-Fabric failed to load the .cfm shipped in the archive: "
                f"{self.shipped_cfm_stats.error}"
            )
        if not self.shipped_cfm_stats_match and self.shipped_cfm_stats is not None:
            for diff in _stat_diffs(self.shipped_cfm_stats, self.cf_stats):
                reasons.append(f"shipped .cfm vs .tf-recompiled stats differ: {diff}")
        shipped_mismatches = self.get_shipped_sample_mismatches()
        if shipped_mismatches:
            reasons.append(
                "Feature values differ between the shipped .cfm and a .tf recompile: "
                + _format_mismatches(shipped_mismatches)
            )
        return reasons

    def summary(self) -> dict[str, Any]:
        """A JSON-serializable summary of the validation outcome.

        Used by the HTTP endpoint (which cannot return dataclasses holding
        numpy scalars / sampled values) and handy for structured logging.
        """
        return {
            "corpus": self.corpus,
            "valid": self.is_valid,
            "stats": _stats_dict(self.cf_stats) if self.cf_ok else None,
            "reasons": self.failure_reasons(),
            "checks": {
                "text_fabric_load": None if self.tf_stats is None else self.tf_ok,
                "context_fabric_load": self.cf_ok,
                "cfm_mmap_reload": self.cf_mmap_ok,
                "stats_match": self.mmap_stats_match,
                "samples_match": self.samples_match,
                # None unless this was a .corpus archive validation.
                "shipped_cfm_load": (
                    None if self.shipped_cfm_stats is None else self.shipped_cfm_ok
                ),
                "shipped_cfm_match": (
                    None
                    if self.shipped_cfm_stats is None
                    else (self.shipped_cfm_stats_match and self.shipped_cfm_samples_match)
                ),
            },
        }


class CorpusValidationError(RuntimeError):
    """Raised when a downloaded/converted corpus fails Context-Fabric validation."""

    def __init__(self, result: ValidationResult) -> None:
        self.result = result
        reasons = result.failure_reasons() or ["unknown validation failure"]
        super().__init__(
            f"Corpus '{result.corpus}' is not a valid Context-Fabric corpus: "
            + "; ".join(reasons)
        )


def _stats_dict(stats: CorpusStats) -> dict[str, int]:
    return {name: getattr(stats, name) for name in _STAT_FIELDS}


def _stat_diffs(a: CorpusStats, b: CorpusStats) -> list[str]:
    return [
        f"{name}: {getattr(a, name)} != {getattr(b, name)}"
        for name in _STAT_FIELDS
        if getattr(a, name) != getattr(b, name)
    ]


def _sample_mismatches(a: FeatureSamples | None, b: FeatureSamples | None) -> list[str]:
    """Names of features whose sampled values differ between two load paths."""
    if a is None or b is None:
        return []
    mismatches: list[str] = []
    for name in sorted(set(a.node_samples) | set(b.node_samples)):
        if a.node_samples.get(name) != b.node_samples.get(name):
            mismatches.append(name)
    for name in sorted(set(a.edge_samples) | set(b.edge_samples)):
        if a.edge_samples.get(name) != b.edge_samples.get(name):
            mismatches.append(f"{name} (edge)")
    if a.text_samples != b.text_samples:
        mismatches.append("(text)")
    return mismatches


def _format_mismatches(mismatches: list[str]) -> str:
    shown = ", ".join(mismatches[:_MAX_REPORTED_MISMATCHES])
    more = len(mismatches) - _MAX_REPORTED_MISMATCHES
    return f"{shown} (+{more} more)" if more > 0 else shown


def _plain(value: Any) -> Any:
    """Normalize numpy scalars/sequences so .tf and .cfm samples compare equal."""
    if isinstance(value, (list, tuple)):
        return tuple(_plain(v) for v in value)
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return item()
        except Exception:
            return value
    return value


def clear_caches(tf_path: Path) -> None:
    """Clear Text-Fabric and Context-Fabric cache directories."""
    for cache in (tf_path / ".cfm", tf_path / ".tf"):
        if cache.exists():
            shutil.rmtree(cache, ignore_errors=True)


def sample_feature_values(api: Any, sample_size: int = _SAMPLE_SIZE) -> FeatureSamples:
    """Sample feature values from a loaded API for validation.

    Samples nodes at regular intervals across the corpus to get
    representative coverage.
    """
    max_node = int(api.F.otype.maxNode)
    max_slot = int(api.F.otype.maxSlot)
    nodes = range(1, max_node + 1, max(1, max_node // sample_size))
    slots = range(1, max_slot + 1, max(1, max_slot // sample_size))

    samples = FeatureSamples()

    for name in sorted(api.Fall()):
        feat = api.Fs(name)
        samples.node_samples[name] = [(n, _plain(feat.v(n))) for n in nodes]

    for name in sorted(api.Eall()):
        feat = api.Es(name)
        collected: list[tuple[int, int, Any]] = []
        for n in nodes:
            try:
                links = feat.f(n)
            except Exception:
                try:
                    links = feat.s(n)
                except Exception:
                    links = None
            if not links:
                continue
            first = links[0]
            if isinstance(first, tuple):
                to, val = first[0], first[1] if len(first) > 1 else None
            else:
                to, val = first, None
            collected.append((n, int(to), _plain(val)))
        samples.edge_samples[name] = collected

    try:
        samples.text_samples = [(n, str(api.T.text(n))) for n in slots]
    except Exception:
        samples.text_samples = []

    return samples


def _stats_from_api(api: Any, collect_samples: bool) -> CorpusStats:
    otype = api.F.otype
    stats = CorpusStats(
        max_slot=int(otype.maxSlot),
        max_node=int(otype.maxNode),
        node_types=len(otype.all),
        node_features=len(list(api.Fall())),
        edge_features=len(list(api.Eall())),
    )
    if collect_samples:
        stats.samples = sample_feature_values(api)
    return stats


def load_with_text_fabric(tf_path: Path) -> CorpusStats | None:
    """Load corpus with Text-Fabric and return stats, or None if not installed."""
    try:
        from tf.fabric import Fabric  # type: ignore[import]
    except ImportError:
        logger.debug("text-fabric not installed; skipping TF validation step")
        return None

    try:
        tf = Fabric(locations=str(tf_path), silent="deep")
        api = tf.loadAll(silent="deep")
        if not api:
            return CorpusStats(error="Text-Fabric loadAll() returned no API")
        return CorpusStats(
            max_slot=int(api.F.otype.maxSlot),
            max_node=int(api.F.otype.maxNode),
            node_types=len(api.F.otype.all),
            node_features=len(list(api.Fall())),
            edge_features=len(list(api.Eall())),
        )
    except Exception as exc:
        return CorpusStats(error=str(exc))


def load_with_context_fabric(
    tf_path: Path,
    collect_samples: bool = False,
    expect_cfm: bool = False,
) -> CorpusStats:
    """Load corpus with Context-Fabric and return stats.

    With ``expect_cfm=True``, additionally requires that the load was served
    from the compiled ``.cfm`` mmap cache rather than the ``.tf`` source files.
    Context-Fabric records this on the ``Fabric`` instance as
    ``_loaded_from_cfm`` -- a private attribute, but the only signal that
    actually distinguishes "reloaded from mmap" from "recompiled from .tf".
    Merely checking that a ``.cfm`` directory exists would not: the first load
    also creates it. If a future Context-Fabric drops this attribute the load
    would (conservatively) be reported as not-from-cfm; ``expect_cfm`` loads
    are always the second load, when the attribute is present today.
    """
    try:
        from cfabric import Fabric  # type: ignore[import]
    except ImportError:
        return CorpusStats(error="context-fabric is not installed")

    try:
        tf = Fabric(locations=str(tf_path), silent="deep")
        api = tf.loadAll(silent="deep")
        if not api:
            return CorpusStats(error="Context-Fabric loadAll() returned no API")
        if expect_cfm and not getattr(tf, "_loaded_from_cfm", False):
            return CorpusStats(
                error="load was not served from the .cfm mmap cache "
                "(no usable .cfm present; recompiled from .tf instead)"
            )
        return _stats_from_api(api, collect_samples)
    except Exception as exc:
        return CorpusStats(error=str(exc))


def validate_corpus(
    corpus_name: str,
    corpus_dir: Path,
    validate_shipped_cfm: bool = False,
) -> ValidationResult:
    """Validate a single corpus through the full .tf -> .cfm -> mmap cycle.

    With ``validate_shipped_cfm=True`` the ``.cfm`` cache already present in
    ``corpus_dir`` is loaded *as-is first* (before caches are cleared) and its
    stats/samples recorded, so the delivered cache can be compared against the
    fresh recompile. Use this for a payload unpacked from a ``.corpus`` archive;
    leave it off (the default) to validate a raw ``.tf`` directory, where any
    existing cache is disposable and recompiled from scratch.

    Never raises for a corpus-level problem (a bad dataset, a failed load): the
    failure is captured in the returned :class:`ValidationResult` so callers
    can report every reason at once. Only genuinely unexpected errors (e.g. the
    directory disappearing mid-run) propagate.
    """
    corpus_dir = Path(corpus_dir)
    logger.info("Validating corpus '%s' at %s", corpus_name, corpus_dir)

    shipped_cfm_stats: CorpusStats | None = None
    if validate_shipped_cfm:
        # Load the shipped .cfm BEFORE clearing anything, requiring that the
        # load actually came from that mmap cache (not a silent recompile).
        shipped_cfm_stats = load_with_context_fabric(
            corpus_dir, collect_samples=True, expect_cfm=True
        )

    clear_caches(corpus_dir)

    tf_stats = load_with_text_fabric(corpus_dir)
    # First CF load reads .tf and auto-compiles the .cfm cache.
    cf_stats = load_with_context_fabric(corpus_dir, collect_samples=True)
    # Second CF load must be served from the .cfm mmap cache.
    cf_mmap_stats = load_with_context_fabric(
        corpus_dir, collect_samples=True, expect_cfm=True
    )

    result = ValidationResult(
        corpus=corpus_name,
        tf_stats=tf_stats,
        cf_stats=cf_stats,
        cf_mmap_stats=cf_mmap_stats,
        shipped_cfm_stats=shipped_cfm_stats,
    )
    if result.is_valid:
        logger.info("Corpus '%s' passed validation", corpus_name)
    else:
        logger.error(
            "Corpus '%s' failed validation: %s",
            corpus_name,
            "; ".join(result.failure_reasons()),
        )
    return result


def _manifest_name(root: Path) -> str | None:
    """Read the corpus ``name`` from an extracted archive's ``manifest.yml``."""
    manifest = root / "manifest.yml"
    if not manifest.exists():
        return None
    try:
        import yaml  # PyYAML: a transitive dep, not guaranteed for corpora-mcp alone

        data = yaml.safe_load(manifest.read_text())
    except Exception:
        return None
    name = data.get("name") if isinstance(data, dict) else None
    return name if isinstance(name, str) and name else None


def _find_payload_dir(root: Path) -> Path | None:
    """Locate the Text-Fabric payload inside an extracted ``.corpus`` archive.

    The canonical layout puts it under ``corpora/``; fall back to searching for
    the directory that holds ``otype.tf`` (the one file every TF dataset has).
    """
    canonical = root / "corpora"
    if (canonical / "otype.tf").exists():
        return canonical
    for otype in root.rglob("otype.tf"):
        return otype.parent
    return None


def validate_corpus_archive(
    archive_path: Path,
    corpus_name: str | None = None,
) -> ValidationResult:
    """Validate a packaged ``.corpus`` archive, *including its shipped ``.cfm``*.

    Extracts the zip to a temporary directory, locates the ``corpora/`` payload
    (``*.tf`` + the compiled ``.cfm/`` cache), and validates it with
    ``validate_shipped_cfm=True`` -- so the delivered ``.cfm`` is loaded as-is
    and compared against a fresh recompile from the ``.tf`` sources. This
    catches a corrupt or stale shipped cache, which validating a bare ``.tf``
    directory cannot.

    Corpus-level problems (unreadable zip, missing payload, bad dataset) are
    captured in the returned :class:`ValidationResult`, never raised.
    """
    archive_path = Path(archive_path)
    with tempfile.TemporaryDirectory(prefix="corpus-validate-") as tmp:
        extract_dir = Path(tmp)
        try:
            shutil.unpack_archive(str(archive_path), str(extract_dir), format="zip")
        except Exception as exc:
            name = corpus_name or archive_path.stem
            return ValidationResult(
                corpus=name,
                tf_stats=None,
                cf_stats=CorpusStats(error=f"could not read .corpus archive: {exc}"),
                cf_mmap_stats=CorpusStats(error="archive not readable"),
            )

        name = corpus_name or _manifest_name(extract_dir) or archive_path.stem
        payload = _find_payload_dir(extract_dir)
        if payload is None:
            return ValidationResult(
                corpus=name,
                tf_stats=None,
                cf_stats=CorpusStats(
                    error="no Text-Fabric payload (corpora/otype.tf) found in archive"
                ),
                cf_mmap_stats=CorpusStats(error="no payload in archive"),
            )

        # validate_corpus fully consumes the payload and returns a result of
        # plain values (no open file/mmap handles), so it is safe to run inside
        # the TemporaryDirectory and let the extraction be cleaned up on exit.
        return validate_corpus(name, payload, validate_shipped_cfm=True)


__all__ = [
    "CorpusStats",
    "CorpusValidationError",
    "FeatureSamples",
    "ValidationResult",
    "validate_corpus",
    "validate_corpus_archive",
]
