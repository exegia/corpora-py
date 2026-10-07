"""AI curation surface (`/ai`) — contract-first router.

See `router.py` for the endpoint contract and `schemas.py` for the shared
shapes. Frozen ahead of implementation so exegia/corpora-web#108 can mock
against a stable OpenAPI document; tracked by exegia/corpora-py#214.
"""

from .draft_router import router as draft_router
from .router import router

router.include_router(draft_router)

__all__ = ["router"]
