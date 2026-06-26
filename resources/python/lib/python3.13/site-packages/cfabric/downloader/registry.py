"""Corpus registry for Context-Fabric.

This module maintains a registry of known corpora that can be
downloaded using short names.
"""

from __future__ import annotations

# Registry of known corpora
# Users can add their own corpora by submitting PRs or using full repo IDs
CORPUS_REGISTRY: dict[str, dict[str, str]] = {
    # Example entries - to be populated with real corpora
    # "bhsa": {
    #     "repo_id": "etcbc/cfabric-bhsa",
    #     "description": "BHSA Hebrew Bible",
    #     "language": "hbo",
    #     "version": "2023.1",
    # },
}


def list_corpora() -> dict[str, dict[str, str]]:
    """List registered corpora with metadata.

    Returns:
        Dictionary mapping corpus short names to their metadata.

    Example:
        >>> from cfabric.downloader import list_corpora
        >>> for name, info in list_corpora().items():
        ...     print(f"{name}: {info['description']}")
    """
    return CORPUS_REGISTRY.copy()


def _resolve_corpus_id(corpus_id: str) -> str:
    """Resolve short name to full HF repo ID.

    Args:
        corpus_id: Either a short name from CORPUS_REGISTRY or a full
            Hugging Face repo ID (format: username/repo-name).

    Returns:
        Full Hugging Face repo ID.

    Raises:
        ValueError: If corpus_id is not found in registry and doesn't
            look like a full repo ID.
    """
    if "/" in corpus_id:
        return corpus_id  # Already a full repo ID

    if corpus_id in CORPUS_REGISTRY:
        return CORPUS_REGISTRY[corpus_id]["repo_id"]

    raise ValueError(
        f"Unknown corpus: {corpus_id}. "
        f"Use list_corpora() to see available corpora, "
        f"or provide a full HF repo ID (e.g., 'username/cfabric-corpus')."
    )
