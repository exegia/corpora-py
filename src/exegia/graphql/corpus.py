"""Corpus registry — loads and holds Context-Fabric `Fabric` instances.

Wrapping the `cfabric` API in a handle keeps the rest of the GraphQL layer
ignorant of loader details and lets resolvers stay synchronous and stateless.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from typing import Any

import cfabric


@dataclass
class CorpusHandle:
    """Loaded corpus exposing the Text-Fabric-compatible API surface.

    Attribute names mirror the TF/CF conventions so resolver code reads the
    same as the upstream docs: `F` features, `E` edges, `L` locality,
    `T` text, `S` search, `N` nodes.
    """

    name: str
    path: str
    api: Any = field(repr=False)

    @property
    def F(self) -> Any:  # noqa: N802 — mirror upstream naming
        return self.api.F

    @property
    def E(self) -> Any:  # noqa: N802
        return self.api.E

    @property
    def L(self) -> Any:  # noqa: N802
        return self.api.L

    @property
    def T(self) -> Any:  # noqa: N802
        return self.api.T

    @property
    def S(self) -> Any:  # noqa: N802
        return self.api.S

    @property
    def N(self) -> Any:  # noqa: N802
        return self.api.N

    def feature(self, name: str, node: int) -> str | None:
        """Return `F.<name>.v(node)` as a string, or None if the feature is absent."""
        feat = getattr(self.F, name, None)
        if feat is None:
            return None
        value = feat.v(node)
        return None if value is None else str(value)

    def object_types(self) -> list[str]:
        return list(self.F.otype.all)

    def feature_names(self) -> list[str]:
        return sorted(self.api.Fall())


class CorpusRegistry:
    """Process-wide map of named corpora. Thread-safe for lazy loads."""

    def __init__(self) -> None:
        self._corpora: dict[str, CorpusHandle] = {}
        self._lock = RLock()

    def load(self, name: str, path: str | Path) -> CorpusHandle:
        """Load a corpus from disk and register it under `name`.

        Re-loading a name replaces the existing handle.
        """
        resolved = str(Path(path).expanduser().resolve())
        fabric = cfabric.Fabric(resolved)
        api = fabric.loadAll()
        handle = CorpusHandle(name=name, path=resolved, api=api)
        with self._lock:
            self._corpora[name] = handle
        return handle

    def register(self, handle: CorpusHandle) -> None:
        with self._lock:
            self._corpora[handle.name] = handle

    def get(self, name: str) -> CorpusHandle | None:
        with self._lock:
            return self._corpora.get(name)

    def require(self, name: str) -> CorpusHandle:
        handle = self.get(name)
        if handle is None:
            raise KeyError(f"corpus {name!r} is not loaded")
        return handle

    def names(self) -> list[str]:
        with self._lock:
            return sorted(self._corpora)

    def all(self) -> list[CorpusHandle]:
        with self._lock:
            return list(self._corpora.values())


registry = CorpusRegistry()
