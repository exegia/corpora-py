"""Opt-in trusted linking configuration; never creates tables or contacts a project on import."""

import argparse
import getpass
import os
from pathlib import Path
from uuid import UUID


def load_runtime():
    from .linking_runtime import LinkingInventory, LinkingRuntime

    required = ("LINKING_DATABASE_URL", "LINKING_INVENTORY", "SUPABASE_JWKS_URL")
    values = {name: os.environ.get(name) for name in required}
    if any(not value for value in values.values()):
        raise ValueError("linking requires a database, trusted inventory and JWKS configuration")
    path = Path(values["LINKING_INVENTORY"] or "")
    inventory = LinkingInventory.model_validate_json(path.read_bytes())
    return LinkingRuntime(
        dsn=values["LINKING_DATABASE_URL"] or "",
        jwks_url=values["SUPABASE_JWKS_URL"] or "",
        audience=os.environ.get("SUPABASE_JWT_AUDIENCE", "authenticated"),
        inventory=inventory,
    )


def configure_from_environment(app) -> None:
    if os.environ.get("LINKING_ENABLED", "").lower() not in ("1", "true"):
        return
    app.state.linking_runtime = load_runtime()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Apply a trusted inventory's exact resource grants; no schema deployment."
    )
    parser.add_argument("--space", type=UUID, required=True)
    parser.add_argument("--user", type=UUID, required=True)
    parser.add_argument("--expected-version", type=int)
    args = parser.parse_args()
    runtime = load_runtime()
    token = getpass.getpass("Admin access token: ")
    store = runtime.store(args.space, token)
    version = runtime.synchronize_entitlements(
        store, args.user, expected_version=args.expected_version
    )
    print(f"Grant version: {version}")


if __name__ == "__main__":
    main()
