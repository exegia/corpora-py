<<<<<<< HEAD
"""shared.corpus — dataset acquisition utilities."""

from .fetch_from_git import fetch_datasets_from_git

__all__ = ["fetch_datasets_from_git"]
=======
"""shared.corpus — dataset acquisition and validation utilities."""

from .fetch_from_git import fetch_datasets_from_git
from .validate import (
    CorpusStats,
    CorpusValidationError,
    FeatureSamples,
    ValidationResult,
    validate_corpus,
)

__all__ = [
    "CorpusStats",
    "CorpusValidationError",
    "FeatureSamples",
    "ValidationResult",
    "fetch_datasets_from_git",
    "validate_corpus",
]
>>>>>>> origin/dev
