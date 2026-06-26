"""Pre-computation logic for Context-Fabric.

This module provides functions to compute derived data structures
such as levels, order, rank, and section boundaries.
"""

from cfabric.precompute.prepare import (
    levels,
    order,
    rank,
    levUp,
    levDown,
    boundary,
    characters,
    sections,
    sectionsFromApi,
    structure,
)

__all__ = [
    "levels",
    "order",
    "rank",
    "levUp",
    "levDown",
    "boundary",
    "characters",
    "sections",
    "sectionsFromApi",
    "structure",
]
