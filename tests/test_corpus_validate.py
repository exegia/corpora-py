"""Tests for shared.corpus.validate and the validate_corpus MCP endpoint."""

import asyncio
from pathlib import Path

import pytest
from shared.corpus import (
    CorpusStats,
    CorpusValidationError,
    ValidationResult,
    validate_corpus,
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


# ── validate_corpus MCP endpoint ──────────────────────────────────────────────


def _call_validate_tool(arguments: dict) -> tuple[str, list[tuple[str, str]]]:
    """Call the validate_corpus tool through an in-memory MCP client.

    Returns the tool's text result and the notifications the client received.
    """
    from client.mcp.server import mcp
    from fastmcp import Client

    async def run() -> tuple[str, list[tuple[str, str]]]:
        notifications: list[tuple[str, str]] = []

        async def on_log(msg) -> None:
            notifications.append((msg.level, msg.data.get("msg", "")))

        async with Client(mcp, log_handler=on_log) as client:
            result = await client.call_tool("validate_corpus", arguments)
            return result.content[0].text, notifications

    return asyncio.run(run())


def test_endpoint_validates_corpus_by_path(mini_corpus: Path):
    text, notifications = _call_validate_tool({"path": str(mini_corpus)})
    assert "is a valid Context-Fabric" in text
    assert "slots:" in text
    # success notification was sent to the client
    assert any(level == "info" and "valid" in msg for level, msg in notifications)


def test_endpoint_reports_reasons_for_invalid_corpus(mini_corpus: Path):
    (mini_corpus / "otype.tf").write_text("@node\n@valueType=str\n\nthis is not valid\n")
    with pytest.raises(Exception, match="NOT a valid Context-Fabric corpus"):
        _call_validate_tool({"path": str(mini_corpus)})


def test_endpoint_validates_loaded_corpus_by_name(mini_corpus: Path):
    from client.mcp.corpus import corpus_manager

    name = corpus_manager.load(str(mini_corpus), name="mini-by-name")
    try:
        text, _ = _call_validate_tool({"corpus": name})
        assert f"Corpus '{name}' is a valid" in text
    finally:
        corpus_manager.unload(name)


def test_endpoint_rejects_unknown_corpus():
    with pytest.raises(Exception, match="not found|No corpus loaded"):
        _call_validate_tool({"corpus": "does-not-exist"})
