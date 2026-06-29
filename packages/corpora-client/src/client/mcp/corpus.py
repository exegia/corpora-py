import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class CorpusManager:
    def __init__(self) -> None:
        self._corpora: dict[str, tuple[Any, Any]] = {}  # name -> (Fabric, api)
        self._current: str | None = None

    @property
    def current(self) -> str | None:
        return self._current

    def load(self, path: str, name: str | None = None, features: list[str] | None = None) -> str:
        try:
            from cfabric import Fabric  # type: ignore[import]
        except ImportError as exc:
            raise ImportError("context-fabric is required: pip install context-fabric") from exc

        p = Path(path).expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(f"Corpus path not found: {p}")

        corpus_name = name or p.name
        tf = Fabric(locations=str(p), silent=True)
        api = tf.load(" ".join(features), silent=True) if features else tf.loadAll(silent=True)

        if api is False:
            raise RuntimeError(f"Failed to load corpus from {p}")

        self._corpora[corpus_name] = (tf, api)
        if self._current is None:
            self._current = corpus_name

        logger.info("Loaded corpus '%s' from %s", corpus_name, p)
        return corpus_name

    def get_api(self, name: str | None = None) -> Any:
        target = name or self._current
        if target is None:
            raise RuntimeError("No corpus loaded. Pass --corpus when starting the server.")
        if target not in self._corpora:
            loaded = self.list_corpora()
            raise KeyError(f"Corpus '{target}' not found. Loaded: {loaded}")
        return self._corpora[target][1]

    def list_corpora(self) -> list[str]:
        return list(self._corpora.keys())

    def select(self, name: str) -> None:
        if name not in self._corpora:
            raise KeyError(f"Corpus '{name}' not loaded")
        self._current = name

    def unload(self, name: str) -> None:
        if name not in self._corpora:
            raise KeyError(f"Corpus '{name}' not loaded")
        del self._corpora[name]
        if self._current == name:
            self._current = next(iter(self._corpora), None)


corpus_manager = CorpusManager()
