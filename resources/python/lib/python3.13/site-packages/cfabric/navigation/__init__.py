"""Corpus navigation for Context-Fabric.

This module provides the N, L, and T APIs for navigating nodes,
localities, and text.
"""

from cfabric.navigation.nodes import Nodes
from cfabric.navigation.locality import Locality
from cfabric.navigation.text import Text

__all__ = ["Nodes", "Locality", "Text"]
