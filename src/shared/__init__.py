"""shared — common code for both admin and client workspaces.

Contains:
- supabase: low-level client + auth wrappers
- auth: high-level signin / signup / signout + CurrentUser
- models: enums and dataclasses
- schemas: pydantic models
- utils: constants, epub parsing helpers
- corpus: git dataset fetcher
"""

__version__ = "0.1.11"

from . import auth, corpus, models, schemas, utils

# Lazy import for supabase to avoid import-time side effects (the module
# creates a live Supabase client at import time of its client submodule) and
# to tolerate packaging oddities or circular import edge cases during __init__.


def __getattr__(name):
    if name == "supabase":
        import importlib

        # Use import_module (not "from . import") to avoid recursion issues
        # with module __getattr__ during submodule loading.
        mod = importlib.import_module(f".{name}", __package__ or __name__)
        # Cache so future attribute access does not re-enter __getattr__.
        globals()[name] = mod
        return mod
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["auth", "supabase", "models", "schemas", "utils", "corpus", "__version__"]
