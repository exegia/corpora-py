"""Warp features for Context-Fabric.

Warp features (otype, oslots) are fundamental structural features
that define the node type hierarchy and slot containment.
"""

from cfabric.features.warp.otype import OtypeFeature
from cfabric.features.warp.oslots import OslotsFeature

__all__ = ["OtypeFeature", "OslotsFeature"]
