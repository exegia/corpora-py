"""Path management for Context-Fabric corpus cache.

This module provides utilities for managing the local cache directory
where downloaded corpora are stored.
"""

from __future__ import annotations

import os
from pathlib import Path


def get_cache_dir() -> Path:
    """Get the cfabric cache directory.

    Resolution order:
        1. CFABRIC_CACHE environment variable
        2. Platform-specific cache directory via platformdirs

    Note:
        By default, huggingface_hub caches to ~/.cache/huggingface/
        This function returns the cfabric-specific cache for any
        additional local data.

    Returns:
        Path to the cache directory.

    Example:
        >>> from cfabric.downloader import get_cache_dir
        >>> cache = get_cache_dir()
        >>> print(cache)
        /Users/username/.cache/cfabric
    """
    env_dir = os.environ.get("CFABRIC_CACHE")
    if env_dir:
        return Path(env_dir)

    try:
        from platformdirs import user_cache_dir

        return Path(user_cache_dir("cfabric", "cfabric"))
    except ImportError:
        # Fallback if platformdirs not installed
        return Path.home() / ".cache" / "cfabric"


def clear_cache(corpus_id: str | None = None) -> None:
    """Clear downloaded corpus cache.

    Args:
        corpus_id: Specific corpus to clear, or None for all.
            Note: This only clears the cfabric-specific cache.
            To clear huggingface_hub cache, use their cache management.

    Note:
        This is a stub - full implementation requires huggingface_hub
        cache management integration.
    """
    # TODO: Implement cache clearing via huggingface_hub
    raise NotImplementedError(
        "Cache clearing not yet implemented. "
        "Use huggingface_hub's cache management for now."
    )
