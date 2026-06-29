"""shared.models — shared data models and enums."""

from .enums import BookCategory, BookSourceType, SectionType

# book.py defines docstrings + structural models; import explicitly when needed
try:
    from . import book  # noqa: F401
except Exception:
    pass

__all__ = ["BookCategory", "BookSourceType", "SectionType"]
