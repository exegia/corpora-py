"""admin — admin-only / full-featured tooling.

Houses conversion pipelines (EPUB/HTML → Text-Fabric, TF → .exg packaging)
and other heavy or privileged operations. These typically require the
[full] extra (text-fabric) and are not needed in the slim client runtime.
"""

from shared import __version__  # re-export for convenience

from . import utils

__all__ = ["utils", "__version__"]
