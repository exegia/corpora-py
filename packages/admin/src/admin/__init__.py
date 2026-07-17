"""admin — admin-only / full-featured tooling.

Houses conversion pipelines (EPUB/HTML → Text-Fabric, TF → .exg packaging)
and other heavy or privileged operations. These typically require the
[full] extra (text-fabric) and are not needed in the slim client runtime.
"""

from . import converters, parsers, services

__all__ = ["converters", "parsers", "services"]

try:
    # admin.ingest imports docling-core (pandas, pillow) at module import
    # time. Slim serverless bundles (Vercel — see vercel.json) exclude that
    # chain to stay under the function size limit, so its absence must not
    # break `import admin`; /ingest degrades to 503 there (see
    # services/ingest_api.py).
    from . import ingest  # noqa: F401

    __all__.append("ingest")
except ModuleNotFoundError:  # pragma: no cover - exercised only in slim deploys
    pass
