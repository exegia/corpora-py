"""UUIDv7 minting for canonical Context Fabric entities.

The v1 schemas recommend UUIDv7 (`common.defs.schema.json#/$defs/Id`) so ids
sort roughly by creation time. Python's stdlib `uuid` doesn't grow `uuid7()`
until 3.14 and this workspace supports 3.13, so this is a small local
implementation of RFC 9562 §5.7: 48-bit unix-epoch milliseconds, then random
bits, with the version/variant fields stamped in.
"""

from __future__ import annotations

import os
import time
import uuid


def uuid7() -> str:
    """Return a new UUIDv7 as a canonical lowercase string."""
    timestamp_ms = time.time_ns() // 1_000_000
    value = timestamp_ms << 80 | int.from_bytes(os.urandom(10))
    value &= ~(0xF << 76)
    value |= 0x7 << 76  # version 7
    value &= ~(0x3 << 62)
    value |= 0x2 << 62  # RFC 4122/9562 variant
    return str(uuid.UUID(int=value))
