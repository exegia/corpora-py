"""The `reference_*` tools of the standalone MCP server (`corpora_mcp.reference`).

A fresh `CorpusManager` loads the skill's `spanning-mini` fixture (unpacked
into an archive-like layout with a `manifest.yml` beside `corpora/`), and the
tools are driven through an in-memory FastMCP client.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import pytest
from corpora_mcp import reference as reference_module
from corpora_mcp.corpus import CorpusManager

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "skills" / "tf-reference-id" / "assets" / "fixtures" / "spanning-mini"
BOOK_ENC = "Moby-Dick%3A Or, The Whale"


@pytest.fixture(scope="module")
def manager(tmp_path_factory) -> CorpusManager:
    pytest.importorskip("cfabric")
    root = tmp_path_factory.mktemp("runtime")
    shutil.copytree(FIXTURE, root / "corpora")
    (root / "manifest.yml").write_text(
        "uid: u-1\nname: Moby Dick\nversion: '0.1'\nwritten_date: '1851-10-18'\nlanguage: English\n"
    )
    (root / "toc.yml").write_text("corpusId: u-1\nauthorId: melville\npublisherId: harper\n")
    m = CorpusManager()
    m.load(str(root / "corpora"), name="mobydick")
    return m


@pytest.fixture(autouse=True)
def _use_manager(monkeypatch, manager):
    monkeypatch.setattr(reference_module, "corpus_manager", manager)
    monkeypatch.setattr(reference_module, "_adapters", {})


def _call(tool: str, arguments: dict) -> dict:
    from corpora_mcp.server import mcp
    from fastmcp import Client

    async def run() -> str:
        async with Client(mcp) as client:
            result = await client.call_tool(tool, arguments)
            return result.content[0].text

    return json.loads(asyncio.run(run()))


def test_reference_create_anchors_spanning_clause_to_first_slot():
    body = _call("reference_create", {"node": 16})
    assert body["ref"] == f"mobydick@0.1/{BOOK_ENC}:1:2!clause1"
    assert body["sections"] == {"book": "Moby-Dick: Or, The Whale", "chapter": 1, "para": 2}
    assert body["first_slot"] == 5 and body["last_slot"] == 10
    assert body["corpus"]["title"] == "Moby Dick" and body["corpus"]["year"] == "1851"
    assert body["corpus"]["authors"] == ["melville"] and body["corpus"]["corpusId"] == "mobydick"


def test_reference_resolve_returns_node_and_canonical_form():
    body = _call("reference_resolve", {"ref": f"mobydick/{BOOK_ENC}:2:1!clause1"})
    assert body["node"] == 17 and body["ref"] == f"mobydick@0.1/{BOOK_ENC}:2:1!clause1"
    assert body["text"].startswith("forth")
    rng = _call("reference_resolve", {"ref": f"{BOOK_ENC}:1:1!word1-4"})  # no corpus -> current
    assert rng["nodes"] == [1, 2, 3, 4] and rng["is_range"]


def test_reference_resolve_errors_are_tool_errors():
    from fastmcp.exceptions import ToolError

    with pytest.raises(ToolError, match="out of range"):
        _call("reference_resolve", {"ref": f"mobydick/{BOOK_ENC}:2:1!clause2"})
    with pytest.raises(ToolError, match="not loaded"):
        _call("reference_resolve", {"ref": f"{BOOK_ENC}:1", "corpus": "nope"})


def test_reference_shortcode_from_node_and_from_foreign_ref():
    body = _call("reference_shortcode", {"node": 16, "url_template": "https://app/r/{ref}"})
    assert body["label"] == "Moby-Dick: Or, The Whale 1:2 · clause 1"
    assert body["compact"] == "Moby-Dick: Or, The Whale 1:2 cl1"
    assert body["url"].startswith("https://app/r/mobydick%400.1%2F")
    foreign = _call("reference_shortcode", {"ref": "bhsa@2021/Deut:4:2!clause1"})
    assert (
        foreign["label"] == "Deut 4:2 · clause 1" and foreign["ref"] == "bhsa@2021/Deut:4:2!clause1"
    )
