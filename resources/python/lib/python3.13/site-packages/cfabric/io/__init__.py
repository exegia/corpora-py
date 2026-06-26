"""Data loading and compilation for Context-Fabric.

This module provides functionality to load .tf files and compile
to/from the memory-mapped .cfm format.
"""

from cfabric.io.loader import Data, MEM_MSG
from cfabric.io.compiler import Compiler, compile_corpus

__all__ = ["Data", "MEM_MSG", "Compiler", "compile_corpus"]
