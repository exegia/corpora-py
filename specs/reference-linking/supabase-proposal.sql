-- OFFLINE PROPOSAL ONLY. Not a migration; do not apply to a live project.
-- PostgreSQL/Supabase roles assumed. Server adapter and authorization are pending.
BEGIN;
CREATE SCHEMA reference_working;
REVOKE ALL ON SCHEMA reference_working FROM PUBLIC, anon, authenticated;

CREATE TABLE reference_working.spaces (
    id uuid PRIMARY KEY,
    authority_id text NOT NULL CHECK (length(btrim(authority_id)) > 0),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE reference_working.memberships (
    space_id uuid NOT NULL REFERENCES reference_working.spaces(id),
    user_id uuid NOT NULL REFERENCES auth.users(id),
    capability text NOT NULL CHECK (capability IN ('contribute', 'review', 'publish', 'admin')),
    PRIMARY KEY (space_id, user_id, capability)
);
CREATE INDEX memberships_user_space ON reference_working.memberships(user_id, space_id);

CREATE TABLE reference_working.heads (
    space_id uuid NOT NULL REFERENCES reference_working.spaces(id),
    reference_id uuid NOT NULL,
    current_version bigint NOT NULL CHECK (current_version > 0),
    PRIMARY KEY (space_id, reference_id)
);
CREATE TABLE reference_working.revisions (
    space_id uuid NOT NULL,
    reference_id uuid NOT NULL,
    version bigint NOT NULL CHECK (version > 0),
    actor_id uuid NOT NULL, -- verified principal; retained after account deletion
    recorded_at timestamptz NOT NULL DEFAULT now(),
    reason text NOT NULL CHECK (length(btrim(reason)) > 0),
    action text NOT NULL CHECK (action IN ('edit', 'resolve', 'approve', 'reject', 'publish', 'withdraw', 'reopen')),
    reference jsonb NOT NULL CHECK (jsonb_typeof(reference) = 'object'),
    validation jsonb,
    conversion jsonb,
    PRIMARY KEY (space_id, reference_id, version),
    FOREIGN KEY (space_id, reference_id) REFERENCES reference_working.heads(space_id, reference_id)
        DEFERRABLE INITIALLY DEFERRED,
    CHECK (reference ?& ARRAY['id', 'schema_version', 'resolution', 'review', 'publication']),
    CHECK ((reference ->> 'id')::uuid = reference_id),
    CHECK (reference ->> 'schema_version' = '0.1.0'),
    CHECK (reference ->> 'resolution' IN ('resolved', 'ambiguous', 'unresolved', 'unavailable')),
    CHECK (reference ->> 'review' IN ('pending', 'approved', 'rejected')),
    CHECK (reference ->> 'publication' IN ('draft', 'published', 'withdrawn')),
    CHECK (reference ->> 'publication' <> 'published' OR reference ->> 'review' = 'approved'),
    CHECK (jsonb_typeof(reference -> 'id') = 'string'
        AND jsonb_typeof(reference -> 'schema_version') = 'string'
        AND jsonb_typeof(reference -> 'resolution') = 'string'
        AND jsonb_typeof(reference -> 'review') = 'string'
        AND jsonb_typeof(reference -> 'publication') = 'string')
);
ALTER TABLE reference_working.heads ADD CONSTRAINT heads_revision
    FOREIGN KEY (space_id, reference_id, current_version)
    REFERENCES reference_working.revisions(space_id, reference_id, version)
    DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE reference_working.conversion_events (
    space_id uuid NOT NULL REFERENCES reference_working.spaces(id),
    authority_id text NOT NULL,
    event_id uuid NOT NULL,
    fingerprint text NOT NULL CHECK (fingerprint ~ '^[0-9a-f]{64}$'),
    detector_revision text NOT NULL,
    report jsonb NOT NULL CHECK (jsonb_typeof(report) = 'object'),
    actor_id uuid NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (space_id, authority_id, event_id)
);
CREATE TABLE reference_working.publication_events (
    space_id uuid NOT NULL,
    authority_id text NOT NULL,
    event_id uuid NOT NULL,
    reference_id uuid NOT NULL,
    approval_version bigint NOT NULL,
    resulting_version bigint NOT NULL,
    action text NOT NULL CHECK (action IN ('acknowledge', 'withdraw')),
    snapshot_sha256 text NOT NULL CHECK (snapshot_sha256 ~ '^[0-9a-f]{64}$'),
    actor_id uuid NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    reason text NOT NULL CHECK (length(btrim(reason)) > 0),
    PRIMARY KEY (space_id, authority_id, event_id),
    FOREIGN KEY (space_id, reference_id, approval_version)
        REFERENCES reference_working.revisions(space_id, reference_id, version),
    FOREIGN KEY (space_id, reference_id, resulting_version)
        REFERENCES reference_working.revisions(space_id, reference_id, version)
);

-- Deny client access, including accidental future schema exposure. No RPCs yet.
ALTER TABLE reference_working.spaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE reference_working.memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE reference_working.heads ENABLE ROW LEVEL SECURITY;
ALTER TABLE reference_working.revisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE reference_working.conversion_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE reference_working.publication_events ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON ALL TABLES IN SCHEMA reference_working FROM PUBLIC, anon, authenticated;
GRANT USAGE ON SCHEMA reference_working TO service_role;
GRANT SELECT ON ALL TABLES IN SCHEMA reference_working TO service_role;
GRANT INSERT ON reference_working.heads, reference_working.revisions,
    reference_working.conversion_events, reference_working.publication_events TO service_role;
GRANT UPDATE (current_version) ON reference_working.heads TO service_role;
-- Space/member administration deliberately has no service-role write grant here.
-- History/event rows have no UPDATE or DELETE grants. Owners remain privileged.
COMMIT;
