-- Server-mediated conversation state. Never grant browser roles direct access.
CREATE TABLE public.corpus_ai_threads (
    id uuid PRIMARY KEY,
    owner uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    corpus text NOT NULL,
    created_at timestamptz NOT NULL,
    revision bigint NOT NULL DEFAULT 0 CHECK (revision >= 0),
    data jsonb NOT NULL CHECK (jsonb_typeof(data) = 'object'),
    CONSTRAINT thread_identity CHECK (
        data->'thread'->>'id' IS NOT NULL
        AND data->'thread'->>'id' = id::text
        AND data->'thread'->>'corpus' IS NOT NULL
        AND data->'thread'->>'corpus' = corpus
    )
);
CREATE INDEX corpus_ai_threads_owner_corpus_created
    ON public.corpus_ai_threads(owner, corpus, created_at DESC, id DESC);
ALTER TABLE public.corpus_ai_threads ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.corpus_ai_threads FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE ON public.corpus_ai_threads TO service_role;
COMMENT ON TABLE public.corpus_ai_threads IS
    'Owned bounded AI conversations; API enforces owner and current corpus access. No provider credentials.';
