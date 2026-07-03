"""Validate that a Text-Fabric dataset is a valid Context-Fabric corpus.

Runs a downloaded/converted corpus through the full Context-Fabric cycle:

1. (optional) Text-Fabric loading from ``.tf`` files, when text-fabric is installed
2. Context-Fabric loading from ``.tf`` files (which auto-compiles to ``.cfm``)
3. Context-Fabric loading from the ``.cfm`` mmap cache

Feature values are sampled from both the ``.tf`` and ``.cfm`` loading paths to
verify data integrity through the compile/load cycle. Caches are cleared first
so every validation starts from a clean state and errors attribute correctly.
"""

import logging
import shutil
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
            and self.stats_match
            and self.mmap_stats_match
            and self.samples_match
        )

    def get_sample_mismatches(self) -> list[str]:
        """Get list of features with mismatched samples."""
        a = self.cf_stats.samples
        b = self.cf_mmap_stats.samples
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

    def failure_reasons(self) -> list[str]:
        """Human-readable reasons this corpus failed validation (empty if valid)."""
        reasons: list[str] = []
        if self.tf_stats is not None and self.tf_stats.error is not None:
            reasons.append(f"Text-Fabric failed to load .tf files: {self.tf_stats.error}")
        if self.cf_stats.error is not None:
            reasons.append(f"Context-Fabric failed to load .tf files: {self.cf_stats.error}")
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
            shown = ", ".join(mismatches[:_MAX_REPORTED_MISMATCHES])
            more = len(mismatches) - _MAX_REPORTED_MISMATCHES
            suffix = f" (+{more} more)" if more > 0 else ""
            reasons.append(
                f"Feature values differ between .tf and .cfm loading: {shown}{suffix}"
            )
        return reasons


class CorpusValidationError(RuntimeError):
    """Raised when a downloaded/converted corpus fails Context-Fabric validation."""

    def __init__(self, result: ValidationResult) -> None:
        self.result = result
        reasons = result.failure_reasons() or ["unknown validation failure"]
        super().__init__(
            f"Corpus '{result.corpus}' is not a valid Context-Fabric corpus: "
            + "; ".join(reasons)
        )


def _stat_diffs(a: CorpusStats, b: CorpusStats) -> list[str]:
    return [
        f"{name}: {getattr(a, name)} != {getattr(b, name)}"
        for name in _STAT_FIELDS
        if getattr(a, name) != getattr(b, name)
    ]


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

    With expect_cfm=True, additionally requires that the load was served from
    the compiled .cfm mmap cache rather than the .tf source files.
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
                error="corpus did not compile to .cfm (mmap cache missing after first load)"
            )
        return _stats_from_api(api, collect_samples)
    except Exception as exc:
        return CorpusStats(error=str(exc))


def validate_corpus(corpus_name: str, corpus_dir: Path) -> ValidationResult:
    """Validate a single corpus through the full .tf -> .cfm -> mmap cycle."""
    corpus_dir = Path(corpus_dir)
    logger.info("Validating corpus '%s' at %s", corpus_name, corpus_dir)

    clear_caches(corpus_dir)

    tf_stats = load_with_text_fabric(corpus_dir)
    # First CF load reads .tf and auto-compiles the .cfm cache.
    cf_stats = load_with_context_fabric(corpus_dir, collect_samples=True)
    # Second CF load must be served from the .cfm mmap cache.
    cf_mmap_stats = load_with_context_fabric(corpus_dir, collect_samples=True, expect_cfm=True)

    result = ValidationResult(
        corpus=corpus_name,
        tf_stats=tf_stats,
        cf_stats=cf_stats,
        cf_mmap_stats=cf_mmap_stats,
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
