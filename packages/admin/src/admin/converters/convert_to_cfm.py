"""
    This is the "main" library to convert any Text-Fabric to Context-Fabric.
    ## See the links below for more information:
        - Automatically convert to .cfm: https://context-fabric.ai/docs/concepts/text-fabric-compat
        - Context-Fabric format: https://context-fabric.ai/docs/file-formats/cfm-format
        - Corpus discovery (features): https://context-fabric.ai/docs/core/tutorials/corpus-discovery

    Context-Fabric reads the same `.tf` files Text-Fabric does. Compilation
    to the memory-mapped `.cfm` cache happens automatically the first time a
    dataset is loaded (`Fabric(...).loadAll()`) — there is no separate
    compiler API. This module's job is just to trigger that load so the
    `.cfm` cache exists on disk, ready to be packaged by `convert_to_corpus`.
"""

from pathlib import Path

from cfabric import Fabric


def convert_to_cfm(tf_dir: str | Path) -> Path:
    """
    Compile the Text-Fabric dataset at `tf_dir` into Context-Fabric's `.cfm`
    cache and return that cache's directory.

    `tf_dir` must already contain the `.tf` files produced by one of the
    `_{format}_to_tf.py` converters.
    """
    tf_dir = Path(tf_dir)
    api = Fabric(locations=str(tf_dir)).loadAll()
    if api is False:
        raise RuntimeError(f"Context-Fabric failed to load/compile {tf_dir!r}")

    cfm_dir = tf_dir / ".cfm"
    if not cfm_dir.exists():
        raise RuntimeError(f"Expected Context-Fabric cache at {cfm_dir!r} after compilation")
    return cfm_dir
