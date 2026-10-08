"""Explicit legacy TF seam; no implicit conversion into CUSX identity."""

from common.utils.tfref import parse
from corpora_linking import CitationLocator


def tf_citation(value: str, *, scheme_id: str, scheme_version: str) -> CitationLocator:
    """Validate a pinned legacy request while retaining its original spelling."""
    parsed = parse(value)
    if not parsed.corpus or not parsed.version:
        raise ValueError("durable TF citations require corpus and explicit version")
    return CitationLocator(
        value=value, profile="legacy-tf", scheme_id=scheme_id, scheme_version=scheme_version
    )
