"""admin.services — HTTP surface for the conversion and validation pipelines.

`api` exposes `POST/GET /convert...` (upload + poll + download) and
`websocket` exposes `/convert/{id}/ws` (status push). `validation_api` exposes
`POST /validate` (corpus integrity checks). `storage` wraps Hugging Face Hub
storage of finished `.corpus` archives; `storage_api` (REST `/storage...`) and
`storage_mcp` (MCP `storage_*` tools) expose it. All routers are plain
`APIRouter`s meant to be included into the combined app built by
`corpora_py.app` -- this package intentionally does not build its own
`FastAPI` instance. `jobs` is the `JobManager` the conversion routers share.

`corpus_detail` (read/patch manifest, section index, paginated content of a
stored `.corpus` archive) adds a detail surface over `storage`; `corpus_detail_api`
exposes it as REST under `/storage/{filename}/...`.

`storage_mcp` and `corpus_detail_mcp` are deliberately NOT imported here: they
import `fastmcp`, which is a dependency of `corpora-mcp`/the umbrella app, not of
`corpora-admin` itself -- eagerly importing them would make bare `import admin`
fail in a slim admin-only install. The umbrella app imports them explicitly.
"""

from . import (
    api,
    corpus_detail,
    corpus_detail_api,
    jobs,
    storage,
    storage_api,
    validation_api,
    websocket,
)

__all__ = [
    "api",
    "corpus_detail",
    "corpus_detail_api",
    "jobs",
    "storage",
    "storage_api",
    "validation_api",
    "websocket",
]
