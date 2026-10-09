"""Exact resource scopes for the private PostgreSQL integration, outside core."""

import hashlib
import json
from collections.abc import Iterator

from corpora_linking import Endpoint
from pydantic import BaseModel


def endpoint_scope(endpoint: Endpoint) -> tuple[str, dict]:
    """Locators share their pinned resource grant; work-only grants stay work-only."""
    scope = endpoint.model_dump(mode="json", exclude={"locators"})
    encoded = json.dumps(scope, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest(), scope


def evidence_endpoints(value: object) -> Iterator[Endpoint]:
    """Visit typed endpoints in history, resolver candidates and conversion evidence."""
    if isinstance(value, Endpoint):
        yield value
    elif isinstance(value, BaseModel):
        for name in type(value).model_fields:
            yield from evidence_endpoints(getattr(value, name))
    elif isinstance(value, (tuple, list)):
        for item in value:
            yield from evidence_endpoints(item)
