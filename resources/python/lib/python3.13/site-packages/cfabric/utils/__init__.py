"""Utility modules for Context-Fabric.

This module provides helper functions, file operations, and other utilities.
"""

from cfabric.utils.helpers import (
    itemize,
    fitemize,
    collectFormats,
    check32,
    console,
    makeExamples,
    flattenToSet,
    deepSize,
)
from cfabric.utils.files import (
    expanduser,
    unexpanduser,
    LOCATIONS,
    setDir,
    expandDir,
    dirExists,
    normpath,
    splitExt,
    scanDir,
)
from cfabric.utils.logging import SILENT_D, DEEP, silentConvert, configure_logging
from cfabric.utils.attrs import AttrDict, deepdict
from cfabric.utils.cli import readArgs

__all__ = [
    # helpers
    "itemize",
    "fitemize",
    "collectFormats",
    "check32",
    "console",
    "makeExamples",
    "flattenToSet",
    "deepSize",
    # files
    "expanduser",
    "unexpanduser",
    "LOCATIONS",
    "setDir",
    "expandDir",
    "dirExists",
    "normpath",
    "splitExt",
    "scanDir",
    # logging
    "SILENT_D",
    "DEEP",
    "silentConvert",
    "configure_logging",
    # attrs
    "AttrDict",
    "deepdict",
    # cli
    "readArgs",
]
