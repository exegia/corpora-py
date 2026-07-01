"""admin.services — HTTP surface for the conversion pipeline.

`api` exposes `POST/GET /convert...` (upload + poll + download) and
`websocket` exposes `/convert/{id}/ws` (status push). Both are plain
`APIRouter`s meant to be included into the combined app built by
`corpora_py.app` -- this package intentionally does not build its own
`FastAPI` instance. `jobs` is the `JobManager` both routers share.
"""

from . import api, jobs, websocket

__all__ = ["api", "jobs", "websocket"]
