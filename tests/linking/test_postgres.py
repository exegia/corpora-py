"""Opt-in real database tests. Only run against a disposable loopback database."""

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest

psycopg = pytest.importorskip("psycopg")

from test_store import fixture as reference_fixture  # noqa: E402

from corpora_py import linking_postgres  # noqa: E402
from corpora_py.linking_store import VersionConflictError  # noqa: E402


@pytest.fixture(scope="module")
def database():
    dsn = os.environ.get("LINKING_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set LINKING_TEST_POSTGRES_DSN to a disposable local database")
    settings = psycopg.conninfo.conninfo_to_dict(dsn)
    if settings.get("host") not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("PostgreSQL tests require an explicit loopback host")
    with psycopg.connect(dsn, autocommit=True) as db:
        db.execute(
            "CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS"
        )
        db.execute("CREATE SCHEMA auth; CREATE TABLE auth.users(id uuid PRIMARY KEY)")
        db.execute(Path("specs/reference-linking/supabase-proposal.sql").read_text())
    yield dsn
    with psycopg.connect(dsn, autocommit=True) as db:
        db.execute("DROP SCHEMA reference_working CASCADE; DROP SCHEMA auth CASCADE")
        db.execute("DROP ROLE anon; DROP ROLE authenticated; DROP ROLE service_role")


@pytest.fixture
def stores(database, monkeypatch):
    space, other_space, creator, reviewer = (uuid4() for _ in range(4))
    with psycopg.connect(database) as db:
        db.execute("INSERT INTO auth.users VALUES (%s), (%s)", (creator, reviewer))
        db.execute(
            "INSERT INTO reference_working.spaces(id, authority_id) VALUES (%s, 'test'), (%s, 'other')",
            (space, other_space),
        )
        db.execute(
            "INSERT INTO reference_working.memberships VALUES (%s, %s, 'contribute'), (%s, %s, 'review')",
            (space, creator, space, reviewer),
        )
    subjects = {"creator": creator, "reviewer": reviewer}

    def verify(token, **kwargs):
        if token not in subjects:
            raise linking_postgres.AuthError("invalid or expired token")
        return {"sub": str(subjects[token])}

    monkeypatch.setattr(linking_postgres, "verify_jwt", verify)
    server_dsn = psycopg.conninfo.make_conninfo(database, options="-c role=service_role")

    def store(token="creator", selected_space=space):
        return linking_postgres.PostgreSQLReferenceStore(
            server_dsn,
            space_id=selected_space,
            token=token,
            jwks_url="https://fixture.invalid/jwks",
            audience="authenticated",
        )

    return store, space, other_space, creator, subjects


def test_lifecycle_cas_and_audit(stores, tmp_path):
    factory, _, _, creator, _ = stores
    _, ref, resolver = reference_fixture(tmp_path)
    store = factory()
    assert store.save(ref, expected_version=None) == 1
    assert store.save(ref, expected_version=1) == 1
    with pytest.raises(PermissionError):
        store.approve(ref.id, expected_version=1, resolver=resolver, reason="forged review")
    assert (
        factory("reviewer").approve(
            ref.id, expected_version=1, resolver=resolver, reason="verified"
        )
        == 2
    )
    history = store.history(ref.id)
    assert history[0].actor_id == str(creator)
    assert history[1].reference.review == "approved"
    assert history[1].validation.source.status == "resolved"
    with pytest.raises(VersionConflictError):
        store.save(ref, expected_version=1)
    assert len(store.history(ref.id)) == 2


def test_authentication_and_space_isolation(stores, tmp_path):
    factory, _, other_space, _, subjects = stores
    _, ref, _ = reference_fixture(tmp_path)
    with pytest.raises(linking_postgres.AuthError):
        factory("expired")
    store = factory()
    store.save(ref, expected_version=None)
    with pytest.raises(PermissionError):
        factory(selected_space=other_space).history(ref.id)
    subjects.clear()
    with pytest.raises(linking_postgres.AuthError):
        store.get(ref.id)


def test_concurrent_creation_and_edits(stores, tmp_path):
    factory, _, _, _, _ = stores
    _, ref, _ = reference_fixture(tmp_path)

    def create(_):
        try:
            return factory().save(ref, expected_version=None)
        except VersionConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(create, range(2)))
    assert sorted(results, key=str) == [1, "conflict"]

    def edit(label):
        changed = ref.model_copy(update={"relationship": label})
        try:
            return factory().save(changed, expected_version=1)
        except VersionConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(edit, ["a", "b"]))
    assert sorted(results, key=str) == [2, "conflict"]
    assert len(factory().history(ref.id)) == 2


def test_stale_review_rollback_and_membership_revocation(stores, database, tmp_path):
    factory, space, _, creator, _ = stores
    _, ref, resolver = reference_fixture(tmp_path)
    factory().save(ref, expected_version=None)
    from corpora_linking import SnapshotResolver

    with pytest.raises(ValueError, match="verified current source"):
        factory("reviewer").approve(
            ref.id,
            expected_version=1,
            resolver=SnapshotResolver(catalog=resolver.catalog),
            reason="stale",
        )
    assert len(factory().history(ref.id)) == 1
    with psycopg.connect(database) as db:
        db.execute(
            "DELETE FROM reference_working.memberships WHERE space_id = %s AND user_id = %s",
            (space, creator),
        )
    with pytest.raises(PermissionError):
        factory().save(ref, expected_version=1)


def test_client_permissions_and_append_only_grants(database):
    for role in ("anon", "authenticated"):
        with psycopg.connect(database) as db:
            db.execute(f"SET ROLE {role}")
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                db.execute("SELECT * FROM reference_working.revisions")
    with psycopg.connect(database) as db:
        db.execute("SET ROLE service_role")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            db.execute("DELETE FROM reference_working.revisions")
    with psycopg.connect(database) as db:
        db.execute("SET ROLE service_role")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            db.execute("UPDATE reference_working.revisions SET reason = 'rewrite'")


def test_membership_lock_serializes_revocation(stores, database):
    factory, space, _, creator, _ = stores
    with psycopg.connect(database) as authorized:
        authorized.execute("SET ROLE service_role")
        factory()._authorize(authorized, "contribute")
        with psycopg.connect(database) as revoker:
            revoker.execute("SET LOCAL lock_timeout = '100ms'")
            with pytest.raises(psycopg.errors.LockNotAvailable):
                revoker.execute(
                    "DELETE FROM reference_working.memberships WHERE space_id = %s AND user_id = %s",
                    (space, creator),
                )


def test_creation_failure_rolls_back_head(stores, database, tmp_path):
    factory, space, _, _, _ = stores
    _, ref, _ = reference_fixture(tmp_path)
    with psycopg.connect(database) as db:
        db.execute(
            "ALTER TABLE reference_working.revisions ADD CONSTRAINT fixture_failure CHECK (reason <> 'force rollback')"
        )
    try:
        with pytest.raises(psycopg.errors.CheckViolation):
            factory().save(ref, expected_version=None, reason="force rollback")
        with psycopg.connect(database) as db:
            assert (
                db.execute(
                    "SELECT count(*) FROM reference_working.heads WHERE space_id = %s AND reference_id = %s",
                    (space, ref.id),
                ).fetchone()[0]
                == 0
            )
        assert factory().history(ref.id) == ()
    finally:
        with psycopg.connect(database) as db:
            db.execute("ALTER TABLE reference_working.revisions DROP CONSTRAINT fixture_failure")
