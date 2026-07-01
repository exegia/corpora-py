"""shared.supabase — low-level synchronous Supabase client + typed auth helpers.

The client uses the service role key and is intended for server / trusted code.
Per-user sessions are passed explicitly via JWTs (see shared.auth).
"""

import api

from . import background_tasks, websocket

__all__ = ["background_tasks", "websocket", "api"]
