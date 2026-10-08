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
        db.execute(
            "CREATE SCHEMA auth; CREATE TABLE auth.users(id uuid PRIMARY KEY); CREATE TABLE auth.sessions(id uuid PRIMARY KEY, user_id uuid REFERENCES auth.users(id), not_after timestamptz)"
        )
        db.execute(Path("specs/reference-linking/supabase-proposal.sql").read_text())
    yield dsn
    with psycopg.connect(dsn, autocommit=True) as db:
        db.execute("DROP SCHEMA reference_working CASCADE; DROP SCHEMA auth CASCADE")
        db.execute("DROP ROLE anon; DROP ROLE authenticated; DROP ROLE service_role")


@pytest.fixture
def stores(database, monkeypatch, tmp_path):
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
    from psycopg.types.json import Jsonb
    from test_events import fixture as event_fixture

    from corpora_py.linking_access import endpoint_scope, evidence_endpoints

    _, ref, resolver = reference_fixture(tmp_path)
    _, _, conversion, detector = event_fixture(tmp_path)
    from corpora_py.linking_events import prepare_conversion

    report, _ = prepare_conversion(conversion, detector, detector_revision="1", reason="fixture")
    scopes = {
        endpoint_scope(e)[0]: endpoint_scope(e)[1]
        for e in evidence_endpoints((ref, resolver.snapshots, report))
    }
    with psycopg.connect(database) as db:
        for actor in (creator, reviewer):
            for key, scope in scopes.items():
                db.execute(
                    "INSERT INTO reference_working.resource_access VALUES (%s, %s, %s, %s)",
                    (space, actor, key, Jsonb(scope)),
                )
    sessions = {"creator": uuid4(), "reviewer": uuid4()}
    with psycopg.connect(database) as db:
        for token, actor in (("creator", creator), ("reviewer", reviewer)):
            db.execute("INSERT INTO auth.sessions VALUES (%s, %s, NULL)", (sessions[token], actor))
    subjects = {"creator": creator, "reviewer": reviewer}

    def verify(token, **kwargs):
        if token not in subjects:
            raise linking_postgres.AuthError("invalid or expired token")
        return {"sub": str(subjects[token]), "session_id": str(sessions[token])}

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


def test_conversion_event_retries_concurrency_and_changed_input(stores, tmp_path):
    from test_events import fixture as event_fixture

    from corpora_py.linking_postgres_events import PostgreSQLConversionEventRegistry

    factory, _, _, _, _ = stores
    _, _, conversion, detector = event_fixture(tmp_path)
    registry = PostgreSQLConversionEventRegistry(factory())
    event_id = uuid4()

    def register(_):
        return registry.register(
            conversion, detector, event_id=event_id, detector_revision="1", reason="conversion"
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, retry = list(pool.map(register, range(2)))
    assert first == retry == registry.get(event_id)
    ref = first.report.references[0].reference
    factory("reviewer").reject(ref.id, expected_version=1, reason="review")
    assert register(None) == first
    assert factory().get(ref.id).review == "rejected"
    with pytest.raises(VersionConflictError):
        registry.register(
            conversion, detector, event_id=event_id, detector_revision="2", reason="changed"
        )
    assert len(factory().history(ref.id)) == 2


def test_conversion_event_failure_rolls_back_all_references(stores, database, tmp_path):
    from test_events import fixture as event_fixture

    from corpora_py.linking_postgres_events import PostgreSQLConversionEventRegistry

    factory, space, _, _, _ = stores
    _, _, conversion, detector = event_fixture(tmp_path)
    registry = PostgreSQLConversionEventRegistry(factory())
    event_id = uuid4()
    with psycopg.connect(database) as db:
        db.execute(
            "ALTER TABLE reference_working.conversion_events ADD CONSTRAINT fixture_event_failure CHECK (detector_revision <> 'fail')"
        )
    try:
        with pytest.raises(psycopg.errors.CheckViolation):
            registry.register(
                conversion, detector, event_id=event_id, detector_revision="fail", reason="rollback"
            )
        assert registry.get(event_id) is None
        with psycopg.connect(database) as db:
            assert (
                db.execute(
                    "SELECT count(*) FROM reference_working.heads WHERE space_id = %s", (space,)
                ).fetchone()[0]
                == 0
            )
    finally:
        with psycopg.connect(database) as db:
            db.execute(
                "ALTER TABLE reference_working.conversion_events DROP CONSTRAINT fixture_event_failure"
            )


def test_publication_permissions_replay_withdrawal_and_reopen(stores, database, tmp_path):
    from corpora_py.linking_postgres_events import PostgreSQLPublicationLedger
    from corpora_py.linking_publication import PublicationSnapshot

    factory, space, _, creator, _ = stores
    _, ref, resolver = reference_fixture(tmp_path)
    factory().save(ref, expected_version=None)
    factory("reviewer").approve(ref.id, expected_version=1, resolver=resolver, reason="verified")
    ledger = PostgreSQLPublicationLedger(factory())
    payload = ledger.export_current([ref.id])
    event_id = uuid4()
    with pytest.raises(PermissionError):
        ledger.acknowledge_snapshot(
            payload, ref.id, event_id=event_id, expected_version=2, reason="ack"
        )
    with psycopg.connect(database) as db:
        db.execute(
            "INSERT INTO reference_working.memberships VALUES (%s, %s, 'publish')", (space, creator)
        )

    def acknowledge(_):
        return ledger.acknowledge_snapshot(
            payload, ref.id, event_id=event_id, expected_version=2, reason="ack"
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        event, replay = list(pool.map(acknowledge, range(2)))
    assert event == replay
    assert factory().get(ref.id).publication == "published"
    with pytest.raises(ValueError):
        ledger.acknowledge_snapshot(
            payload, ref.id, event_id=event_id, expected_version=2, reason="changed"
        )
    with pytest.raises(ValueError, match="reconciliation"):
        factory().save(ref, expected_version=3)
    withdrawn = ledger.withdraw(ref.id, event_id=uuid4(), expected_version=3, reason="remove")
    assert withdrawn.artifact_digest == event.artifact_digest
    assert ledger.pending_removals() == (withdrawn,)
    assert len(ledger.history(ref.id)) == 2
    assert PublicationSnapshot.model_validate_json(ledger.export_current([ref.id])).entries == ()
    assert factory().reopen(ref.id, expected_version=4, reason="revise") == 5


def test_publication_event_failure_rolls_back_working_state(stores, database, tmp_path):
    from corpora_py.linking_postgres_events import PostgreSQLPublicationLedger

    factory, space, _, creator, _ = stores
    _, ref, resolver = reference_fixture(tmp_path)
    factory().save(ref, expected_version=None)
    factory("reviewer").approve(ref.id, expected_version=1, resolver=resolver, reason="verified")
    with psycopg.connect(database) as db:
        db.execute(
            "INSERT INTO reference_working.memberships VALUES (%s, %s, 'publish')", (space, creator)
        )
        db.execute(
            "ALTER TABLE reference_working.publication_events ADD CONSTRAINT fixture_publication_failure CHECK (reason <> 'fail')"
        )
    ledger = PostgreSQLPublicationLedger(factory())
    try:
        with pytest.raises(psycopg.errors.CheckViolation):
            ledger.acknowledge_snapshot(
                ledger.export_current([ref.id]),
                ref.id,
                event_id=uuid4(),
                expected_version=2,
                reason="fail",
            )
        assert ledger.history(ref.id) == ()
        assert len(factory().history(ref.id)) == 2
        assert factory().get(ref.id).publication == "draft"
    finally:
        with psycopg.connect(database) as db:
            db.execute(
                "ALTER TABLE reference_working.publication_events DROP CONSTRAINT fixture_publication_failure"
            )


def revoke_resource(database, space, actor, endpoint):
    from corpora_py.linking_access import endpoint_scope

    with psycopg.connect(database) as db:
        db.execute(
            "DELETE FROM reference_working.resource_access WHERE space_id = %s AND user_id = %s AND resource_key = %s",
            (space, actor, endpoint_scope(endpoint)[0]),
        )


def test_resource_revocation_blocks_history_writes_and_review(stores, database, tmp_path):
    factory, space, _, creator, subjects = stores
    _, ref, resolver = reference_fixture(tmp_path)
    factory().save(ref, expected_version=None)
    revoke_resource(database, space, creator, ref.source)
    with pytest.raises(PermissionError, match="resource access"):
        factory().history(ref.id)
    with pytest.raises(PermissionError, match="resource access"):
        factory().save(ref, expected_version=1)
    revoke_resource(database, space, subjects["reviewer"], ref.target)
    with pytest.raises(PermissionError, match="resource access"):
        factory("reviewer").approve(ref.id, expected_version=1, resolver=resolver, reason="denied")
    with psycopg.connect(database) as db:
        assert (
            db.execute(
                "SELECT count(*) FROM reference_working.revisions WHERE space_id = %s", (space,)
            ).fetchone()[0]
            == 1
        )


def test_work_grant_does_not_allow_other_document_versions_or_resolver_candidates(stores, tmp_path):
    from corpora_linking import Endpoint, ResolutionResult

    factory, _, _, _, _ = stores
    _, ref, resolver = reference_fixture(tmp_path)
    hidden = Endpoint(
        work_id="book", edition_id="e", package_id="secret", revision="2", document_id="private"
    )
    with pytest.raises(PermissionError):
        factory().save(ref.model_copy(update={"target": hidden}), expected_version=None)
    factory().save(ref, expected_version=None)

    class HiddenResolver:
        def resolve(self, endpoint):
            if endpoint == ref.target:
                return ResolutionResult(status="resolved", candidates=(hidden,))
            return resolver.resolve(endpoint)

    with pytest.raises(PermissionError):
        factory().resolve_target(
            ref.id, expected_version=1, resolver=HiddenResolver(), reason="denied candidate"
        )
    assert len(factory().history(ref.id)) == 1


def test_conversion_original_mapping_requires_its_own_access(stores, database):
    from psycopg.types.json import Jsonb
    from test_conversion import fixture as conversion_fixture

    from corpora_py.linking_access import endpoint_scope
    from corpora_py.linking_conversion import ConversionInput
    from corpora_py.linking_postgres_events import PostgreSQLConversionEventRegistry

    factory, space, _, creator, _ = stores
    snapshot, mapping, detector = conversion_fixture()
    key, scope = endpoint_scope(snapshot.endpoint)
    with psycopg.connect(database) as db:
        db.execute(
            "INSERT INTO reference_working.resource_access VALUES (%s, %s, %s, %s)",
            (space, creator, key, Jsonb(scope)),
        )
    registry = PostgreSQLConversionEventRegistry(factory())
    with pytest.raises(PermissionError):
        registry.register(
            ConversionInput(converted=snapshot, mappings=(mapping,)),
            detector,
            event_id=uuid4(),
            detector_revision="1",
            reason="denied original",
        )
    with psycopg.connect(database) as db:
        assert (
            db.execute(
                "SELECT count(*) FROM reference_working.heads WHERE space_id = %s", (space,)
            ).fetchone()[0]
            == 0
        )


def test_resource_revocation_blocks_conversion_get_and_retry(stores, database, tmp_path):
    from test_events import fixture as event_fixture

    from corpora_py.linking_postgres_events import PostgreSQLConversionEventRegistry

    factory, space, _, creator, _ = stores
    _, _, conversion, detector = event_fixture(tmp_path)
    registry = PostgreSQLConversionEventRegistry(factory())
    event_id = uuid4()
    registry.register(
        conversion, detector, event_id=event_id, detector_revision="1", reason="conversion"
    )
    revoke_resource(database, space, creator, conversion.converted.endpoint)
    with pytest.raises(PermissionError):
        registry.get(event_id)
    with pytest.raises(PermissionError):
        registry.register(
            conversion, detector, event_id=event_id, detector_revision="1", reason="retry"
        )


def test_resource_revocation_blocks_publication_export_and_event_replay(stores, database, tmp_path):
    from corpora_py.linking_postgres_events import PostgreSQLPublicationLedger

    factory, space, _, creator, _ = stores
    _, ref, resolver = reference_fixture(tmp_path)
    factory().save(ref, expected_version=None)
    factory("reviewer").approve(ref.id, expected_version=1, resolver=resolver, reason="verified")
    with psycopg.connect(database) as db:
        db.execute(
            "INSERT INTO reference_working.memberships VALUES (%s, %s, 'publish')", (space, creator)
        )
    ledger = PostgreSQLPublicationLedger(factory())
    payload = ledger.export_current([ref.id])
    event_id = uuid4()
    ledger.acknowledge_snapshot(
        payload, ref.id, event_id=event_id, expected_version=2, reason="ack"
    )
    revoke_resource(database, space, creator, ref.source)
    for operation in (
        lambda: ledger.export_current([ref.id]),
        lambda: ledger.history(ref.id),
        lambda: ledger.acknowledge_snapshot(
            payload, ref.id, event_id=event_id, expected_version=2, reason="ack"
        ),
        lambda: ledger.withdraw(ref.id, event_id=uuid4(), expected_version=3, reason="denied"),
    ):
        with pytest.raises(PermissionError):
            operation()


def test_resource_lock_serializes_revocation(stores, database, tmp_path):
    factory, space, _, creator, _ = stores
    _, ref, _ = reference_fixture(tmp_path)
    with psycopg.connect(database) as authorized:
        authorized.execute("SET ROLE service_role")
        actor = factory()._authorize(authorized, "contribute")
        factory()._check_access(authorized, actor, ref)
        with psycopg.connect(database) as revoker:
            revoker.execute("SET LOCAL lock_timeout = '100ms'")
            with pytest.raises(psycopg.errors.LockNotAvailable):
                revoker.execute(
                    "DELETE FROM reference_working.resource_access WHERE space_id = %s AND user_id = %s",
                    (space, creator),
                )


@pytest.mark.parametrize("change", ["delete", "expire", "wrong_user"])
def test_session_revocation_rejects_still_signed_tokens(stores, database, tmp_path, change):
    factory, _, _, creator, subjects = stores
    _, ref, _ = reference_fixture(tmp_path)
    store = factory()
    store.save(ref, expected_version=None)
    with psycopg.connect(database) as db:
        if change == "delete":
            db.execute("DELETE FROM auth.sessions WHERE user_id = %s", (creator,))
        elif change == "expire":
            db.execute(
                "UPDATE auth.sessions SET not_after = now() - interval '1 second' WHERE user_id = %s",
                (creator,),
            )
        else:
            db.execute(
                "UPDATE auth.sessions SET user_id = %s WHERE user_id = %s",
                (subjects["reviewer"], creator),
            )
    with pytest.raises(linking_postgres.AuthError):
        store.history(ref.id)
    with pytest.raises(linking_postgres.AuthError):
        store.save(ref, expected_version=1)


def test_session_claim_is_required_before_database_access(stores, monkeypatch):
    factory, _, _, creator, _ = stores
    monkeypatch.setattr(
        linking_postgres, "verify_jwt", lambda *args, **kwargs: {"sub": str(creator)}
    )
    with pytest.raises(linking_postgres.AuthError, match="session_id"):
        factory()


def test_entitlement_sync_requires_admin_and_uses_cas(stores, database, tmp_path):
    from corpora_py.linking_entitlements import (
        EntitlementSnapshot,
        PostgreSQLEntitlementSynchronizer,
    )

    factory, space, _, creator, subjects = stores
    _, ref, _ = reference_fixture(tmp_path)
    scope = ref.source.model_copy(update={"locators": ()})
    snapshot = EntitlementSnapshot(
        provider_id="fixture", provider_revision="inventory-1", resources=(scope, ref.target)
    )
    synchronizer = PostgreSQLEntitlementSynchronizer(factory(), provider_id="fixture")
    with pytest.raises(PermissionError):
        synchronizer.synchronize(subjects["reviewer"], snapshot, expected_version=None)
    with psycopg.connect(database) as db:
        db.execute(
            "INSERT INTO reference_working.memberships VALUES (%s, %s, 'admin')", (space, creator)
        )
    reviewer = subjects["reviewer"]
    assert synchronizer.synchronize(reviewer, snapshot, expected_version=None) == 1
    reordered = snapshot.model_copy(update={"resources": tuple(reversed(snapshot.resources))})
    assert synchronizer.synchronize(reviewer, reordered, expected_version=1) == 1
    with pytest.raises(VersionConflictError):
        synchronizer.synchronize(reviewer, snapshot, expected_version=None)
    denied = snapshot.model_copy(update={"provider_revision": "inventory-2", "resources": ()})
    assert synchronizer.synchronize(reviewer, denied, expected_version=1) == 2
    factory().save(ref, expected_version=None)
    with pytest.raises(PermissionError):
        factory("reviewer").get(ref.id)
    with pytest.raises(ValueError, match="provider"):
        PostgreSQLEntitlementSynchronizer(factory(), provider_id="other").synchronize(
            reviewer, snapshot.model_copy(update={"provider_id": "other"}), expected_version=2
        )


def test_entitlement_sync_failure_restores_prior_grants(stores, database):
    from corpora_linking import Endpoint

    from corpora_py.linking_entitlements import (
        EntitlementSnapshot,
        PostgreSQLEntitlementSynchronizer,
    )

    factory, space, _, creator, subjects = stores
    with psycopg.connect(database) as db:
        db.execute(
            "INSERT INTO reference_working.memberships VALUES (%s, %s, 'admin')", (space, creator)
        )
        db.execute(
            "ALTER TABLE reference_working.entitlement_heads ADD CONSTRAINT fixture_sync_failure CHECK (provider_revision <> 'fail')"
        )
        count = db.execute(
            "SELECT count(*) FROM reference_working.resource_access WHERE space_id = %s AND user_id = %s",
            (space, subjects["reviewer"]),
        ).fetchone()[0]
    try:
        snapshot = EntitlementSnapshot(
            provider_id="fixture", provider_revision="fail", resources=(Endpoint(work_id="new"),)
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            PostgreSQLEntitlementSynchronizer(factory(), provider_id="fixture").synchronize(
                subjects["reviewer"], snapshot, expected_version=None
            )
        with psycopg.connect(database) as db:
            assert (
                db.execute(
                    "SELECT count(*) FROM reference_working.resource_access WHERE space_id = %s AND user_id = %s",
                    (space, subjects["reviewer"]),
                ).fetchone()[0]
                == count
            )
    finally:
        with psycopg.connect(database) as db:
            db.execute(
                "ALTER TABLE reference_working.entitlement_heads DROP CONSTRAINT fixture_sync_failure"
            )


def test_entitlement_sync_concurrency_and_drift_repair(stores, database, tmp_path):
    from corpora_py.linking_entitlements import (
        EntitlementSnapshot,
        PostgreSQLEntitlementSynchronizer,
    )

    factory, space, _, creator, subjects = stores
    _, ref, _ = reference_fixture(tmp_path)
    snapshot = EntitlementSnapshot(
        provider_id="fixture", provider_revision="1", resources=(ref.target,)
    )
    with psycopg.connect(database) as db:
        db.execute(
            "INSERT INTO reference_working.memberships VALUES (%s, %s, 'admin')", (space, creator)
        )
    synchronizer = PostgreSQLEntitlementSynchronizer(factory(), provider_id="fixture")

    def sync(_):
        try:
            return synchronizer.synchronize(subjects["reviewer"], snapshot, expected_version=None)
        except VersionConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(sync, range(2)), key=str) == [1, "conflict"]
    revoke_resource(database, space, subjects["reviewer"], ref.target)
    assert synchronizer.synchronize(subjects["reviewer"], snapshot, expected_version=1) == 2
    assert synchronizer.synchronize(subjects["reviewer"], snapshot, expected_version=2) == 2


def discovery_fixture(stores, database, tmp_path):
    from corpora_linking import Endpoint, SnapshotCatalog, identify_scholarly_citation
    from psycopg.types.json import Jsonb
    from test_scholarly import fixture as scholarly_fixture

    from corpora_py.linking_access import endpoint_scope
    from corpora_py.linking_postgres_discoveries import PostgreSQLDiscoveryStore

    factory, space, _, creator, subjects = stores
    snapshot, mention, provenance = scholarly_fixture()
    discovery = identify_scholarly_citation(
        snapshot, mention, SnapshotCatalog(), provenance=provenance
    )
    with psycopg.connect(database) as db:
        for actor in subjects.values():
            for endpoint in (
                snapshot.endpoint,
                Endpoint(work_id="book"),
                Endpoint(work_id="other"),
            ):
                key, scope = endpoint_scope(endpoint)
                db.execute(
                    "INSERT INTO reference_working.resource_access VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                    (space, actor, key, Jsonb(scope)),
                )
    return factory, PostgreSQLDiscoveryStore(factory()), snapshot, discovery


def test_postgres_unknown_discovery_retry_refresh_and_work_selection(stores, database, tmp_path):
    from corpora_linking import CatalogEntry, SnapshotCatalog

    from corpora_py.linking_postgres_discoveries import PostgreSQLDiscoveryStore

    factory, discoveries, snapshot, discovery = discovery_fixture(stores, database, tmp_path)
    event_id = uuid4()
    first = discoveries.register(discovery, snapshot, event_id=event_id, reason="unknown")
    catalog = SnapshotCatalog(
        entries=(
            CatalogEntry(work_id="book", names=(discovery.mention.cited_name,)),
            CatalogEntry(work_id="other", names=(discovery.mention.cited_name,)),
        )
    )
    identified = discoveries.refresh_identification(
        discovery.id, snapshot, catalog, expected_version=1, reason="bibliography"
    )
    assert identified.discovery.id == discovery.id
    with pytest.raises(PermissionError):
        discoveries.select_work(
            discovery.id, "book", expected_version=2, reason="creator cannot review"
        )
    reviewer = PostgreSQLDiscoveryStore(factory("reviewer"))
    selected = reviewer.select_work(
        discovery.id, "book", expected_version=2, reason="work verified"
    )
    reference = factory().get(selected.selected_reference_id)
    assert reference.review == "pending" and reference.resolution == "unresolved"
    assert discoveries.register(discovery, snapshot, event_id=event_id, reason="retry") == first
    assert [item.action for item in discoveries.history(discovery.id)] == [
        "register",
        "identify",
        "select",
    ]
    assert len(selected.discovery.hypotheses) == 2


def test_postgres_discovery_concurrent_retry_and_selection(stores, database, tmp_path):
    from corpora_linking import CatalogEntry, SnapshotCatalog

    from corpora_py.linking_postgres_discoveries import PostgreSQLDiscoveryStore

    factory, discoveries, snapshot, discovery = discovery_fixture(stores, database, tmp_path)
    event_id = uuid4()

    def register(_):
        return discoveries.register(discovery, snapshot, event_id=event_id, reason="unknown")

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(register, range(2)))
    assert results[0] == results[1]
    discoveries.refresh_identification(
        discovery.id,
        snapshot,
        SnapshotCatalog(
            entries=(
                CatalogEntry(work_id="book", names=(discovery.mention.cited_name,)),
                CatalogEntry(work_id="other", names=(discovery.mention.cited_name,)),
            )
        ),
        expected_version=1,
        reason="catalog",
    )
    reviewer = PostgreSQLDiscoveryStore(factory("reviewer"))

    def select(work):
        try:
            return reviewer.select_work(discovery.id, work, expected_version=2, reason="choice")
        except VersionConflictError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(item is not None for item in pool.map(select, ("book", "other"))) == 1
    assert len(discoveries.history(discovery.id)) == 3


def test_postgres_discovery_access_revocation_and_space_isolation(stores, database, tmp_path):
    from corpora_py.linking_postgres_discoveries import PostgreSQLDiscoveryStore

    factory, discoveries, snapshot, discovery = discovery_fixture(stores, database, tmp_path)
    event_id = uuid4()
    discoveries.register(discovery, snapshot, event_id=event_id, reason="unknown")
    with pytest.raises(PermissionError):
        PostgreSQLDiscoveryStore(factory(selected_space=stores[2])).get(discovery.id)
    revoke_resource(database, stores[1], stores[3], snapshot.endpoint)
    for operation in (
        lambda: discoveries.history(discovery.id),
        lambda: discoveries.register(discovery, snapshot, event_id=event_id, reason="retry"),
    ):
        with pytest.raises(PermissionError):
            operation()


def test_postgres_discovery_selection_failure_rolls_back_reference(stores, database, tmp_path):
    from corpora_linking import CatalogEntry, SnapshotCatalog

    from corpora_py.linking_postgres_discoveries import PostgreSQLDiscoveryStore

    factory, discoveries, snapshot, discovery = discovery_fixture(stores, database, tmp_path)
    discoveries.register(discovery, snapshot, event_id=uuid4(), reason="unknown")
    identified = discoveries.refresh_identification(
        discovery.id,
        snapshot,
        SnapshotCatalog(
            entries=(CatalogEntry(work_id="book", names=(discovery.mention.cited_name,)),)
        ),
        expected_version=1,
        reason="catalog",
    )
    with psycopg.connect(database) as db:
        db.execute(
            "ALTER TABLE reference_working.discovery_revisions ADD CONSTRAINT fixture_discovery_failure CHECK (version <> 3) NOT VALID"
        )
    try:
        with pytest.raises(psycopg.errors.CheckViolation):
            PostgreSQLDiscoveryStore(factory("reviewer")).select_work(
                discovery.id, "book", expected_version=2, reason="choice"
            )
        assert factory().get(identified.discovery.hypotheses[0].id) is None
        assert len(discoveries.history(discovery.id)) == 2
    finally:
        with psycopg.connect(database) as db:
            db.execute(
                "ALTER TABLE reference_working.discovery_revisions DROP CONSTRAINT fixture_discovery_failure"
            )


def test_authenticated_http_manual_retrieval_review_and_publication(stores, database, tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from corpora_py.linking_api import router
    from corpora_py.linking_runtime import LinkingInventory, configure_linking

    factory, space, _, creator, _ = stores
    _, ref, resolver = reference_fixture(tmp_path)
    app = FastAPI()
    app.include_router(router)
    store = factory()
    configure_linking(
        app,
        dsn=store.dsn,
        jwks_url="https://fixture.invalid/jwks",
        audience="authenticated",
        inventory=LinkingInventory(catalog=resolver.catalog.entries, snapshots=resolver.snapshots),
    )
    client = TestClient(app)
    prefix = f"/linking/{space}"
    creator_headers = {"Authorization": "Bearer creator"}
    reviewer_headers = {"Authorization": "Bearer reviewer"}
    body = {"reference": ref.model_dump(mode="json"), "reason": "manual"}
    assert client.post(prefix + "/references", json=body).status_code == 401
    response = client.post(prefix + "/references", json=body, headers=creator_headers)
    assert response.status_code == 200, response.text
    assert response.json()["reference"]["provenance"]["agent_id"] == str(creator)
    selected = client.post(
        prefix + "/retrieve", json=ref.source.model_dump(mode="json"), headers=creator_headers
    )
    assert selected.status_code == 200 and selected.json()["text"] == "Quote"
    decision = {"expected_version": 1, "reason": "reviewed"}
    assert (
        client.post(
            prefix + f"/references/{ref.id}/approve", json=decision, headers=creator_headers
        ).status_code
        == 403
    )
    assert (
        client.post(
            prefix + f"/references/{ref.id}/approve", json=decision, headers=reviewer_headers
        ).status_code
        == 200
    )
    exported = client.post(
        prefix + "/export", json={"reference_ids": [str(ref.id)]}, headers=creator_headers
    )
    assert exported.status_code == 200
    assert factory().get(ref.id).publication == "draft"
    with psycopg.connect(database) as db:
        db.execute(
            "INSERT INTO reference_working.memberships VALUES (%s, %s, 'publish')", (space, creator)
        )
    ack = {
        "expected_version": 2,
        "reason": "distributed",
        "event_id": str(uuid4()),
        "snapshot": exported.text,
    }
    assert (
        client.post(
            prefix + f"/publication/{ref.id}/acknowledge", json=ack, headers=creator_headers
        ).status_code
        == 200
    )
    with psycopg.connect(database) as db:
        db.execute("DELETE FROM auth.sessions WHERE user_id = %s", (creator,))
    assert client.get(prefix + f"/references/{ref.id}", headers=creator_headers).status_code == 401


def test_http_conversion_uses_server_asset_and_curated_detector_context(stores, database):
    from corpora_linking import BibleBook, Endpoint
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from psycopg.types.json import Jsonb

    from corpora_py.linking_access import endpoint_scope
    from corpora_py.linking_api import router
    from corpora_py.linking_pdf import sha256_revision
    from corpora_py.linking_runtime import (
        AssetRecord,
        BibleDetectionContext,
        LinkingInventory,
        configure_linking,
    )

    factory, space, _, creator, _ = stores
    data = b"<html><head></head><body><p>Compare John <em>3:16</em>.</p></body></html>"
    original = Endpoint(
        work_id="essay",
        edition_id="e",
        package_id="html",
        revision=sha256_revision(data),
        document_id="asset",
    )
    converted = Endpoint(
        work_id="essay",
        edition_id="e",
        package_id="text",
        revision=sha256_revision(b"Compare John 3:16.\n"),
        document_id="body",
    )
    with psycopg.connect(database) as db:
        for endpoint in (original, converted):
            key, scope = endpoint_scope(endpoint)
            db.execute(
                "INSERT INTO reference_working.resource_access VALUES (%s, %s, %s, %s)",
                (space, creator, key, Jsonb(scope)),
            )
    app = FastAPI()
    app.include_router(router)
    context = BibleDetectionContext(
        books=(BibleBook(work_id="john", aliases=("John",)),),
        profile="fixture",
        scheme_id="fixture",
        scheme_version="1",
        detector_revision="1",
    )
    configure_linking(
        app,
        dsn=factory().dsn,
        jwks_url="https://fixture.invalid/jwks",
        audience="authenticated",
        inventory=LinkingInventory(
            bible=context, assets=(AssetRecord(endpoint=original, format="html", data=data),)
        ),
    )
    client = TestClient(app)
    body = {
        "original": original.model_dump(mode="json"),
        "converted": converted.model_dump(mode="json"),
        "asset_id": "html",
        "event_id": str(uuid4()),
        "reason": "converted",
    }
    url = f"/linking/{space}/conversion-events"
    headers = {"Authorization": "Bearer creator"}
    first = client.post(url, json=body, headers=headers)
    assert first.status_code == 200, first.text
    assert len(first.json()["report"]["references"]) == 1
    assert client.post(url, json=body, headers=headers).json() == first.json()


def test_unconfigured_http_linking_is_unavailable():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from corpora_py.linking_api import router

    app = FastAPI()
    app.include_router(router)
    response = TestClient(app).post(f"/linking/{uuid4()}/retrieve", json={"work_id": "book"})
    assert response.status_code == 503
    assert response.json()["detail"] == "Reference linking is unavailable"


def test_http_native_browser_and_unknown_scholarly_conversion_retry(stores, database):
    from corpora_linking import Endpoint, ScholarlyCitationMention, TextLocator
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from psycopg.types.json import Jsonb

    from corpora_py.linking_access import endpoint_scope
    from corpora_py.linking_api import router
    from corpora_py.linking_html_ranges import _stream
    from corpora_py.linking_pdf import sha256_revision
    from corpora_py.linking_runtime import AssetRecord, LinkingInventory, configure_linking

    factory, space, _, creator, _ = stores
    data = b"<html><head></head><body><p>Read <em>Unknown book</em>.</p></body></html>"
    text, spans = _stream(data)
    original = Endpoint(
        work_id="essay",
        edition_id="e",
        package_id="html",
        revision=sha256_revision(data),
        document_id="asset",
    )
    converted = Endpoint(
        work_id="essay",
        edition_id="e",
        package_id="text",
        revision=sha256_revision(text.encode()),
        document_id="body",
    )
    with psycopg.connect(database) as db:
        for endpoint in (original, converted):
            key, scope = endpoint_scope(endpoint)
            db.execute(
                "INSERT INTO reference_working.resource_access VALUES (%s, %s, %s, %s)",
                (space, creator, key, Jsonb(scope)),
            )

    class Recognizer:
        def recognize(self, snapshot):
            start = snapshot.text.index("Unknown book")
            return (
                ScholarlyCitationMention(
                    selection=TextLocator(
                        stream_id="body", start=start, end=start + 12, exact="Unknown book"
                    ),
                    cited_name="Unknown book",
                ),
            )

    app = FastAPI()
    app.include_router(router)
    configure_linking(
        app,
        dsn=factory().dsn,
        jwks_url="https://fixture.invalid/jwks",
        audience="authenticated",
        inventory=LinkingInventory(
            assets=(AssetRecord(endpoint=original, format="html", data=data),)
        ),
        scholarly_recognizer=Recognizer(),
        scholarly_revision="fixture-v1",
    )
    client = TestClient(app)
    headers = {"Authorization": "Bearer creator"}
    prefix = f"/linking/{space}"
    body = {
        "original": original.model_dump(mode="json"),
        "converted": converted.model_dump(mode="json"),
        "asset_id": "html",
        "event_ids": [str(uuid4())],
        "reason": "ingest",
    }
    first = client.post(prefix + "/scholarly-conversion-events", json=body, headers=headers)
    assert first.status_code == 200, first.text
    assert first.json()["discoveries"][0]["discovery"]["hypotheses"] == []
    assert (
        client.post(prefix + "/scholarly-conversion-events", json=body, headers=headers).json()
        == first.json()
    )
    path, _, _, node = spans[1]
    capture = {
        "original": original.model_dump(mode="json"),
        "asset_id": "html",
        "captured_nodes": [(entry[0], entry[3]) for entry in spans],
        "start_path": path,
        "end_path": path,
        "start_utf16": 0,
        "end_utf16": len(node),
    }
    selected = client.post(prefix + "/browser-selection", json=capture, headers=headers)
    assert selected.status_code == 200, selected.text
    assert selected.json()["text"] == "Unknown book"
    capture["captured_nodes"] = []
    assert (
        client.post(prefix + "/browser-selection", json=capture, headers=headers).status_code == 422
    )


def test_http_import_requires_server_reconciliation_and_explicit_version(stores, tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from corpora_py.linking_api import router
    from corpora_py.linking_publication import SnapshotPublicationAdapter
    from corpora_py.linking_runtime import LinkingInventory, configure_linking

    factory, space, _, _, _ = stores
    _, ref, _ = reference_fixture(tmp_path)
    published = ref.model_copy(update={"review": "approved"})
    snapshot = SnapshotPublicationAdapter("upstream").export((published,)).decode()
    app = FastAPI()
    app.include_router(router)
    configure_linking(
        app,
        dsn=factory().dsn,
        jwks_url="https://fixture.invalid/jwks",
        audience="authenticated",
        inventory=LinkingInventory(),
    )
    client = TestClient(app)
    headers = {"Authorization": "Bearer creator"}
    url = f"/linking/{space}/import"
    body = {"snapshot": snapshot, "reference_id": str(ref.id), "reason": "import"}
    assert client.post(url, json=body, headers=headers).status_code == 200
    assert factory().get(ref.id).review == "pending"
    assert factory().get(ref.id).publication == "draft"
    assert client.post(url, json=body, headers=headers).status_code == 409
    body["expected_version"] = 1
    assert client.post(url, json=body, headers=headers).status_code == 200


def test_http_cusx_publication_validates_advertised_destination(stores, database):
    import json

    from corpora_linking import Provenance, Reference, StructuralLocator
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from psycopg.types.json import Jsonb
    from test_cusx import fixture

    from corpora_py.linking_access import endpoint_scope
    from corpora_py.linking_api import router
    from corpora_py.linking_cusx import AnchorBinding, bind_cusx_anchors
    from corpora_py.linking_pdf import sha256_revision
    from corpora_py.linking_publication import SnapshotPublicationAdapter
    from corpora_py.linking_runtime import AssetRecord, LinkingInventory, configure_linking

    factory, space, _, creator, _ = stores
    data, snapshot, selection = fixture()
    # Pinned package revision is opaque; inventory separately verifies file bytes.
    data = bind_cusx_anchors(
        data, snapshot, (AnchorBinding(selection=selection, anchor_id="verse"),)
    )
    ref = Reference(
        source=selection,
        target=snapshot.endpoint.model_copy(
            update={"locators": (StructuralLocator(anchor_id="verse"),)}
        ),
        provenance=Provenance(origin="manual", agent_id=str(creator), method="selection"),
        resolution="resolved",
        review="approved",
    )
    with psycopg.connect(database) as db:
        key, scope = endpoint_scope(snapshot.endpoint)
        db.execute(
            "INSERT INTO reference_working.resource_access VALUES (%s, %s, %s, %s)",
            (space, creator, key, Jsonb(scope)),
        )

    # Use the existing validated review store contract; the HTTP publisher reads it.
    class Resolver:
        def resolve(self, request):
            from corpora_linking import ResolutionResult

            return ResolutionResult(status="resolved", candidates=(request,))

    factory().save(
        ref.model_copy(update={"review": "pending", "resolution": "unresolved"}),
        expected_version=None,
        reason="selection",
    )
    with psycopg.connect(database) as db:
        db.execute(
            "INSERT INTO reference_working.memberships VALUES (%s, %s, 'review')", (space, creator)
        )
    factory().approve(ref.id, expected_version=1, resolver=Resolver(), reason="verified fixture")
    app = FastAPI()
    app.include_router(router)
    configure_linking(
        app,
        dsn=factory().dsn,
        jwks_url="https://fixture.invalid/jwks",
        audience="authenticated",
        inventory=LinkingInventory(
            snapshots=(snapshot,),
            assets=(
                AssetRecord(
                    endpoint=snapshot.endpoint,
                    format="cusx",
                    data=data,
                    checksum=sha256_revision(data),
                ),
            ),
        ),
    )
    client = TestClient(app)
    assert app.state.linking_runtime.resolver(factory()).retrieve(ref.target) == selection.locators[0].exact
    body = {"source": snapshot.endpoint.model_dump(mode="json"), "reference_ids": [str(ref.id)]}
    response = client.post(
        f"/linking/{space}/export-cusx", json=body, headers={"Authorization": "Bearer creator"}
    )
    assert response.status_code == 200, response.text
    assert f"urn:uuid:{ref.id}" in response.json()["cusx"]
    assert response.json()["snapshot"]["entries"][0]["reference"]["id"] == str(ref.id)
    assert factory().get(ref.id).publication == "draft"
    assert (
        SnapshotPublicationAdapter("test")
        .plan_import(
            json.dumps(response.json()["snapshot"]).encode(),
            factory(),
        )[0]
        .outcome
        == "unchanged"
    )


def test_delivery_receipts_are_separate_admin_provider_evidence(stores, database, tmp_path):
    from corpora_py.linking_delivery import DeliveryEvidence, PostgreSQLDeliveryReceipts
    from corpora_py.linking_postgres_events import PostgreSQLPublicationLedger

    factory, space, _, creator, _ = stores
    _, ref, resolver = reference_fixture(tmp_path)
    factory().save(ref, expected_version=None)
    factory("reviewer").approve(ref.id, expected_version=1, resolver=resolver, reason="review")
    with psycopg.connect(database) as db:
        db.execute(
            "INSERT INTO reference_working.memberships VALUES (%s, %s, 'publish')", (space, creator)
        )
    ledger = PostgreSQLPublicationLedger(factory())
    snapshot = ledger.export_current((ref.id,))
    event = ledger.acknowledge_snapshot(
        snapshot, ref.id, event_id=uuid4(), expected_version=2, reason="editorial acknowledgment"
    )
    receipts = PostgreSQLDeliveryReceipts(factory(), provider_id="fixture-delivery")
    evidence = DeliveryEvidence(
        receipt_id=uuid4(),
        publication_event_id=event.event_id,
        destination_id="fixture-bucket",
        provider_id="fixture-delivery",
        provider_receipt="opaque-provider-proof",
        artifact_digest=event.artifact_digest,
        status="delivered",
    )
    assert receipts.history(ref.id) == ()
    with pytest.raises(PermissionError):
        receipts.record(evidence)
    with psycopg.connect(database) as db:
        db.execute(
            "INSERT INTO reference_working.memberships VALUES (%s, %s, 'admin')", (space, creator)
        )
    first = receipts.record(evidence)
    assert receipts.record(evidence) == first
    assert len(receipts.history(ref.id)) == 1
    with pytest.raises(ValueError, match="different evidence"):
        receipts.record(evidence.model_copy(update={"destination_id": "other"}))
    with pytest.raises(ValueError, match="artifact"):
        receipts.record(
            evidence.model_copy(update={"receipt_id": uuid4(), "artifact_digest": "sha256:wrong"})
        )
    with pytest.raises(ValueError, match="contradicts"):
        receipts.record(evidence.model_copy(update={"receipt_id": uuid4(), "status": "removed"}))
    withdrawal = ledger.withdraw(ref.id, event_id=uuid4(), expected_version=3, reason="remove")
    removal = receipts.record(
        evidence.model_copy(
            update={
                "receipt_id": uuid4(),
                "publication_event_id": withdrawal.event_id,
                "status": "removed",
                "provider_receipt": "removal-proof",
            }
        )
    )
    assert removal.publication.action == "withdraw"
    assert len(receipts.history(ref.id)) == 2
