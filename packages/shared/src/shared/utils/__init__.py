"""shared.utils — shared utilities.

- constant: environment / config constants loaded from .env.*
- parse_epub: EPUB metadata + page extraction (used by admin converters)
"""

from . import constant
from .parse_epub import extract_pages, get_metadata

__all__ = ["constant", "extract_pages", "get_metadata"]
