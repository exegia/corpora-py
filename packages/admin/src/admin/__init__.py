"""admin — admin-only / full-featured tooling.

Houses conversion pipelines (EPUB/HTML → Text-Fabric, TF → .exg packaging)
and other heavy or privileged operations. These typically require the
[full] extra (text-fabric) and are not needed in the slim client runtime.
"""

from . import converters, parsers, services

__all__ = ["converters", "parsers", "services"]
