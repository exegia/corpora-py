"""Tests for corpus validation logic and the `validate_corpus` MCP tool.

Three layers:

* Pure dataclass logic (`ValidationResult` / `CorpusStats` / `failure_reasons`)
  with no corpus loading at all.
* One real end-to-end run of the `.tf -> .cfm -> mmap` cycle over a tiny
  hand-written Text-Fabric corpus -- `context-fabric` is a declared dependency,
  so this exercises the actual compile/reload path rather than a hand-built fake.
* The `validate_corpus` MCP tool, driven through an in-memory FastMCP client
  with the underlying `validate_corpus` function monkeypatched to a canned
  result -- fast, deterministic, and independent of cfabric.
"""

import asyncio
import shutil
from pathlib import Path

import pytest
from corpora_mcp import validate as validate_module
from corpora_mcp.validate import (
    CorpusStats,
    CorpusValidationError,
    ValidationResult,
    validate_corpus,
    validate_corpus_archive,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────

_MINI_CORPUS = {
    "otype.tf": "@node\n@valueType=str\n\n1-6\tword\n7-8\tsentence\n",
    "oslots.tf": "@edge\n@valueType=str\n\n7\t1-3\n8\t4-6\n",
    "otext.tf": (
        "@config\n"
        "@fmt:text-orig-full={word} \n"
        "@sectionTypes=sentence\n"
        "@sectionFeatures=n\n"
    ),
    "word.tf": "@node\n@valueType=str\n\n1\tin\n2\tthe\n3\tbeginning\n4\twas\n5\tthe\n6\tword\n",
    "n.tf": "@node\n@valueType=int\n\n7\t1\n8\t2\n",
}


@pytest.fixture
def mini_corpus(tmp_path: Path) -> Path:
    corpus_dir = tmp_path / "minicorpus"
    corpus_dir.mkdir()
    for filename, content in _MINI_CORPUS.items():
        (corpus_dir / filename).write_text(content)
    return corpus_dir


def _build_archive(tmp_path: Path, *, tamper: bool = False) -> Path:
    """Build a real `.corpus` zip: `corpora/` payload (*.tf + a compiled `.cfm/`)
    plus a `manifest.yml`, mirroring `admin.converters.convert_to_corpus`'s
    layout without pulling in that package (or its git snapshot step)."""
    from cfabric import Fabric  # type: ignore[import]

    root = tmp_path / "pkg"
    corpora = root / "corpora"
    corpora.mkdir(parents=True)
    for filename, content in _MINI_CORPUS.items():
        (corpora / filename).write_text(content)

    # Compile the shipped .cfm the way packaging does (first load auto-compiles).
    Fabric(locations=str(corpora), silent="deep").loadAll(silent="deep")
    assert (corpora / ".cfm").exists()

    if tamper:
        cfm_files = [p for p in (corpora / ".cfm").rglob("*") if p.is_file()]
        largest = max(cfm_files, key=lambda p: p.stat().st_size)
        largest.write_bytes(b"\x00\x01\x02 not a valid cfm payload")

    (root / "manifest.yml").write_text("name: Archived Mini\n")

    archive = tmp_path / "mini.corpus"
    made = shutil.make_archive(str(archive.with_suffix("")), "zip", root_dir=root)
    Path(made).rename(archive)
    return archive


@pytest.fixture
def corpus_archive(tmp_path: Path) -> Path:
    return _build_archive(tmp_path)


def _stats(**overrides: object) -> CorpusStats:
    base: dict = dict(max_slot=6, max_node=8, node_types=2, node_features=3, edge_features=1)
    base.update(overrides)
    return CorpusStats(**base)


# ── ValidationResult logic (no corpus loading required) ───────────────────────


def test_result_valid_when_all_stats_match():
    result = ValidationResult(
        corpus="x", tf_stats=None, cf_stats=_stats(), cf_mmap_stats=_stats()
    )
    assert result.is_valid
    assert result.failure_reasons() == []


def test_result_invalid_on_load_error():
    result = ValidationResult(
        corpus="x",
        tf_stats=None,
        cf_stats=CorpusStats(error="boom"),
        cf_mmap_stats=_stats(),
    )
    assert not result.is_valid
    assert any("boom" in r for r in result.failure_reasons())


def test_result_invalid_on_mmap_stat_mismatch():
    result = ValidationResult(
        corpus="x",
        tf_stats=None,
        cf_stats=_stats(),
        cf_mmap_stats=_stats(max_node=999),
    )
    assert not result.is_valid
    assert any("max_node: 8 != 999" in r for r in result.failure_reasons())


def test_result_invalid_on_tf_cf_stat_mismatch():
    result = ValidationResult(
        corpus="x",
        tf_stats=_stats(max_slot=5),
        cf_stats=_stats(),
        cf_mmap_stats=_stats(),
    )
    assert not result.is_valid
    assert any("max_slot: 5 != 6" in r for r in result.failure_reasons())


def test_shipped_cfm_absent_does_not_affect_validity():
    # A plain .tf-directory validation never sets shipped_cfm_stats.
    result = ValidationResult(
        corpus="x", tf_stats=None, cf_stats=_stats(), cf_mmap_stats=_stats()
    )
    assert result.shipped_cfm_stats is None
    assert result.is_valid
    assert result.summary()["checks"]["shipped_cfm_load"] is None
    assert result.summary()["checks"]["shipped_cfm_match"] is None


def test_shipped_cfm_load_error_makes_invalid():
    result = ValidationResult(
        corpus="x",
        tf_stats=None,
        cf_stats=_stats(),
        cf_mmap_stats=_stats(),
        shipped_cfm_stats=CorpusStats(error="cfm cache failed to load"),
    )
    assert not result.is_valid
    assert any("shipped in the archive" in r for r in result.failure_reasons())
    assert result.summary()["checks"]["shipped_cfm_load"] is False


def test_shipped_cfm_stat_mismatch_makes_invalid():
    result = ValidationResult(
        corpus="x",
        tf_stats=None,
        cf_stats=_stats(),
        cf_mmap_stats=_stats(),
        shipped_cfm_stats=_stats(max_slot=999),
    )
    assert not result.is_valid
    assert any("shipped .cfm vs .tf-recompiled stats differ" in r for r in result.failure_reasons())
    assert result.summary()["checks"]["shipped_cfm_match"] is False


def test_summary_shape_for_valid_result():
    result = ValidationResult(
        corpus="x", tf_stats=None, cf_stats=_stats(), cf_mmap_stats=_stats()
    )
    summary = result.summary()
    assert summary["valid"] is True
    assert summary["stats"] == {
        "max_slot": 6,
        "max_node": 8,
        "node_types": 2,
        "node_features": 3,
        "edge_features": 1,
    }
    assert summary["reasons"] == []
    # text-fabric step absent -> reported as None, not True/False
    assert summary["checks"]["text_fabric_load"] is None


def test_summary_stats_none_when_cf_load_failed():
    result = ValidationResult(
        corpus="x",
        tf_stats=None,
        cf_stats=CorpusStats(error="cannot parse otype.tf"),
        cf_mmap_stats=CorpusStats(error="no cache"),
    )
    summary = result.summary()
    assert summary["valid"] is False
    assert summary["stats"] is None
    assert summary["checks"]["context_fabric_load"] is False


def test_validation_error_message_contains_reasons():
    result = ValidationResult(
        corpus="broken",
        tf_stats=None,
        cf_stats=CorpusStats(error="cannot parse otype.tf"),
        cf_mmap_stats=CorpusStats(error="no cache"),
    )
    err = CorpusValidationError(result)
    assert "broken" in str(err)
    assert "cannot parse otype.tf" in str(err)


# ── End-to-end validation with a real mini corpus ─────────────────────────────


def test_validate_corpus_valid(mini_corpus: Path):
    result = validate_corpus("minicorpus", mini_corpus)
    assert result.cf_ok
    assert result.cf_mmap_ok, result.cf_mmap_stats.error
    assert result.is_valid, result.failure_reasons()
    assert result.cf_stats.max_slot == 6
    assert result.cf_stats.max_node == 8
    # .cfm cache was compiled as part of validation
    assert (mini_corpus / ".cfm").exists()
    # samples were collected on both loading paths and match
    assert result.cf_stats.samples is not None
    assert result.cf_mmap_stats.samples is not None
    assert result.cf_stats.samples.node_samples["word"] == (
        result.cf_mmap_stats.samples.node_samples["word"]
    )


def test_validate_corpus_invalid(mini_corpus: Path):
    (mini_corpus / "otype.tf").write_text("@node\n@valueType=str\n\nthis is not valid\n")
    result = validate_corpus("minicorpus", mini_corpus)
    assert not result.is_valid
    assert result.failure_reasons()


# ── End-to-end validation of a real .corpus archive ───────────────────────────


def test_validate_archive_valid_checks_shipped_cfm(corpus_archive: Path):
    result = validate_corpus_archive(corpus_archive)
    # Name comes from the archive's manifest.yml, not the file name.
    assert result.corpus == "Archived Mini"
    assert result.is_valid, result.failure_reasons()
    # The .cfm shipped inside the archive was loaded as-is and matched.
    assert result.shipped_cfm_stats is not None
    assert result.shipped_cfm_ok, result.shipped_cfm_stats.error
    assert result.shipped_cfm_stats_match
    assert result.shipped_cfm_samples_match
    checks = result.summary()["checks"]
    assert checks["shipped_cfm_load"] is True
    assert checks["shipped_cfm_match"] is True


def test_validate_archive_detects_corrupt_shipped_cfm(tmp_path: Path):
    archive = _build_archive(tmp_path, tamper=True)
    result = validate_corpus_archive(archive)
    assert not result.is_valid
    assert not result.shipped_cfm_ok
    assert any("shipped in the archive" in r for r in result.failure_reasons())


def test_validate_archive_rejects_non_zip(tmp_path: Path):
    bogus = tmp_path / "not.corpus"
    bogus.write_text("this is not a zip archive")
    result = validate_corpus_archive(bogus)
    assert not result.is_valid
    assert any("could not read .corpus archive" in r for r in result.failure_reasons())


def test_validate_archive_rejects_missing_payload(tmp_path: Path):
    root = tmp_path / "pkg"
    root.mkdir()
    (root / "manifest.yml").write_text("name: Empty\n")
    archive = tmp_path / "empty.corpus"
    made = shutil.make_archive(str(archive.with_suffix("")), "zip", root_dir=root)
    Path(made).rename(archive)

    result = validate_corpus_archive(archive)
    assert not result.is_valid
    assert any("no Text-Fabric payload" in r for r in result.failure_reasons())


# ── validate_corpus MCP tool (validation logic mocked) ────────────────────────


def _call_validate_tool(arguments: dict) -> tuple[str, list[tuple[str, str]]]:
    """Call the validate_corpus tool through an in-memory MCP client.

    Returns the tool's text result and the notifications the client received.
    """
    from corpora_mcp.server import mcp
    from fastmcp import Client

    async def run() -> tuple[str, list[tuple[str, str]]]:
        notifications: list[tuple[str, str]] = []

        async def on_log(msg) -> None:
            notifications.append((msg.level, msg.data.get("msg", "")))

        async with Client(mcp, log_handler=on_log) as client:
            result = await client.call_tool("validate_corpus", arguments)
            return result.content[0].text, notifications

    return asyncio.run(run())


def test_tool_reports_stats_for_valid_corpus(mini_corpus: Path, monkeypatch):
    canned = ValidationResult(
        corpus="minicorpus", tf_stats=None, cf_stats=_stats(), cf_mmap_stats=_stats()
    )
    monkeypatch.setattr(validate_module, "validate_corpus", lambda name, path: canned)

    text, notifications = _call_validate_tool({"path": str(mini_corpus)})

    assert "is a valid Context-Fabric" in text
    assert "slots:" in text
    assert "6" in text  # max_slot rendered
    assert any(level == "info" and "valid" in msg for level, msg in notifications)


def test_tool_dispatches_file_path_to_archive_validation(tmp_path: Path, monkeypatch):
    archive_file = tmp_path / "mini.corpus"
    archive_file.write_bytes(b"PK\x03\x04 placeholder")  # exists + is a file
    canned = ValidationResult(
        corpus="Archived Mini",
        tf_stats=None,
        cf_stats=_stats(),
        cf_mmap_stats=_stats(),
        shipped_cfm_stats=_stats(),
    )
    seen: dict = {}

    def fake_archive(path, name=None):
        seen["path"] = path
        return canned

    # The .tf-directory validator must NOT be used for a file path.
    monkeypatch.setattr(
        validate_module,
        "validate_corpus",
        lambda *a, **k: pytest.fail("directory validator used for a file path"),
    )
    monkeypatch.setattr(validate_module, "validate_corpus_archive", fake_archive)

    text, _ = _call_validate_tool({"path": str(archive_file)})

    assert seen["path"] == archive_file
    assert "Archived Mini" in text
    assert "shipped .cfm" in text  # shipped-cache line rendered


def test_tool_raises_with_reasons_for_invalid_corpus(mini_corpus: Path, monkeypatch):
    canned = ValidationResult(
        corpus="minicorpus",
        tf_stats=None,
        cf_stats=CorpusStats(error="cannot parse otype.tf"),
        cf_mmap_stats=CorpusStats(error="no cache"),
    )
    monkeypatch.setattr(validate_module, "validate_corpus", lambda name, path: canned)

    with pytest.raises(Exception, match="NOT a valid Context-Fabric corpus"):
        _call_validate_tool({"path": str(mini_corpus)})


def test_tool_rejects_missing_path(tmp_path: Path):
    with pytest.raises(Exception, match="Corpus path not found"):
        _call_validate_tool({"path": str(tmp_path / "nope")})


def test_tool_rejects_unknown_corpus():
    with pytest.raises(Exception, match="not found|No corpus loaded"):
        _call_validate_tool({"corpus": "does-not-exist"})
