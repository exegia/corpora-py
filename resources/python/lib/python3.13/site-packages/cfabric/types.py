"""Type definitions for Context-Fabric.

This module defines type aliases used throughout the codebase for
improved type safety and documentation.
"""

from typing import TypeAlias
import numpy as np
from numpy.typing import NDArray

# Node identifiers are 1-indexed positive integers
Node: TypeAlias = int

# Feature values can be strings or integers
FeatureValue: TypeAlias = str | int

# Node feature data: node -> value mapping
NodeFeatureData: TypeAlias = dict[Node, FeatureValue]

# Edge feature data: node -> {target_node -> value} or node -> {target_nodes}
EdgeFeatureData: TypeAlias = dict[Node, dict[Node, FeatureValue] | set[Node]]

# Metadata from .tf files
MetaData: TypeAlias = dict[str, str]

# Feature metadata collection
FeatureMetaData: TypeAlias = dict[str, MetaData]

# Numpy array types for memory-mapped storage
NodeArray: TypeAlias = NDArray[np.uint32]
IndexArray: TypeAlias = NDArray[np.uint32]
OffsetArray: TypeAlias = NDArray[np.uint64]

# Slot range tuple (start, end) - inclusive
SlotRange: TypeAlias = tuple[Node, Node]

# Search result: tuple of nodes matching a query
SearchResult: TypeAlias = tuple[Node, ...]

# Section specification: (type, feature1, feature2, ...)
SectionSpec: TypeAlias = tuple[str, ...]

# Node type to nodes mapping
NodesByType: TypeAlias = dict[str, tuple[Node, ...]]

__all__ = [
    "Node",
    "FeatureValue",
    "NodeFeatureData",
    "EdgeFeatureData",
    "MetaData",
    "FeatureMetaData",
    "NodeArray",
    "IndexArray",
    "OffsetArray",
    "SlotRange",
    "SearchResult",
    "SectionSpec",
    "NodesByType",
]
