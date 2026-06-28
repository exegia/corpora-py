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

from . import auth, corpus, models, schemas, supabase, utils

__all__ = ["auth", "supabase", "models", "schemas", "utils", "corpus", "__version__"]
