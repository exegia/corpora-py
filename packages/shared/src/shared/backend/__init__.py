"""shared.supabase — low-level synchronous Supabase client + typed auth helpers.

The client uses the service role key and is intended for server / trusted code.
Per-user sessions are passed explicitly via JWTs (see shared.auth).
"""

from . import authentication, client, storage

__all__ = [
    "authentication",
    "client",
    "supabase",
    "storage"
]  # client module re-exports the instance?

# convenience: many modules do `from shared.supabase.client import supabase`
try:
    from .client import supabase  # noqa: F401
except Exception:
    supabase = None  # type: ignore
