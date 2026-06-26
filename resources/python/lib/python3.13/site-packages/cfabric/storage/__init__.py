"""Low-level storage backends for Context-Fabric.

This module provides memory-mapped storage implementations for
efficient feature data access.
"""

from cfabric.storage.mmap_manager import MmapManager
from cfabric.storage.csr import CSRArray, CSRArrayWithValues
from cfabric.storage.string_pool import StringPool, IntFeatureArray

__all__ = [
    "MmapManager",
    "CSRArray",
    "CSRArrayWithValues",
    "StringPool",
    "IntFeatureArray",
]
