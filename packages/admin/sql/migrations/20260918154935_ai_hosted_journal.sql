-- No public write endpoints are enabled by this migration. Provisioning is a
-- trusted server operation: corpus_documents itself has no ownership column.
INSERT INTO storage.buckets(id,name,public) VALUES ('corpus-ai-drafts','corpus-ai-drafts',false)
    ON CONFLICT(id) DO NOTHING;
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM storage.buckets WHERE id='corpus-ai-drafts' AND public) THEN
        RAISE EXCEPTION 'AI draft bucket must be private';
    END IF;
END $$;
CREATE POLICY corpus_ai_objects_private ON storage.objects AS RESTRICTIVE FOR ALL TO PUBLIC
    USING (bucket_id <> 'corpus-ai-drafts') WITH CHECK (bucket_id <> 'corpus-ai-drafts');
CREATE TABLE public.corpus_ai_drafts (
    document_id uuid PRIMARY KEY REFERENCES public.corpus_documents(id) ON DELETE RESTRICT,
    owner uuid NOT NULL REFERENCES public.users(id) ON DELETE RESTRICT,
    corpus text NOT NULL,
    bucket text NOT NULL CHECK (bucket = 'corpus-ai-drafts'),
    object_key text NOT NULL,
    revision uuid NOT NULL,
    digest text NOT NULL CHECK (digest <> ''),
    version text NOT NULL CHECK (version <> ''),
    state text NOT NULL DEFAULT 'draft' CHECK (state IN ('draft','locked','published')),
    UNIQUE (owner, corpus),
    CHECK (object_key = owner::text || '/ai/' || document_id::text || '/' || revision::text || '.corpus')
);
CREATE TABLE public.corpus_ai_operations (
    id uuid PRIMARY KEY,
    document_id uuid NOT NULL REFERENCES public.corpus_ai_drafts(document_id) ON DELETE RESTRICT,
    owner uuid NOT NULL REFERENCES public.users(id) ON DELETE RESTRICT,
    intent jsonb NOT NULL,
    proof text NOT NULL CHECK (proof ~ '^[0-9a-f]{64}$'),
    reverts uuid UNIQUE REFERENCES public.corpus_ai_operations(id) ON DELETE RESTRICT,
    receipt jsonb,
    applied_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK ((intent->>'id')::uuid = id AND (intent->>'owner')::uuid = owner),
    CHECK (applied_at IS NULL OR receipt IS NOT NULL)
);
CREATE INDEX corpus_ai_operations_document ON public.corpus_ai_operations(document_id);
CREATE INDEX corpus_ai_operations_pending ON public.corpus_ai_operations(owner, created_at, id)
    WHERE applied_at IS NULL;
ALTER TABLE public.corpus_changes ADD COLUMN ai_operation_id uuid
    REFERENCES public.corpus_ai_operations(id) ON DELETE RESTRICT;
CREATE UNIQUE INDEX corpus_changes_ai_field ON public.corpus_changes(ai_operation_id,field)
    WHERE ai_operation_id IS NOT NULL;
CREATE INDEX corpus_changes_ai_operation ON public.corpus_changes(ai_operation_id)
    WHERE ai_operation_id IS NOT NULL;
-- Preserve legacy visibility; new AI rows must also satisfy ownership.
CREATE POLICY corpus_changes_ai_private ON public.corpus_changes AS RESTRICTIVE
    FOR SELECT TO PUBLIC USING (ai_operation_id IS NULL OR applied_by = (SELECT auth.uid()));
-- TRUNCATE bypasses RLS and must not let browser roles erase the durable log.
REVOKE TRUNCATE ON public.corpus_changes FROM anon, authenticated;
ALTER TABLE public.corpus_ai_drafts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.corpus_ai_operations ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.corpus_ai_drafts, public.corpus_ai_operations FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE ON public.corpus_ai_drafts, public.corpus_ai_operations TO service_role;

CREATE FUNCTION public.corpora_ai_storage(p_action text, p_owner uuid, p_payload jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
DECLARE
    d public.corpus_ai_drafts%ROWTYPE;
    o public.corpus_ai_operations%ROWTYPE;
    i jsonb;
    e jsonb;
    b jsonb;
    a jsonb;
    result jsonb;
    moment timestamptz;
    affected integer;
    operation_id uuid;
BEGIN
    IF p_owner IS NULL THEN RAISE EXCEPTION 'AI_NOT_FOUND'; END IF;
    IF p_action = 'register' THEN
        -- Only trusted provisioning code may bind a document after checking its
        -- source ownership and uploading/verifying this immutable object.
        INSERT INTO public.corpus_ai_drafts(document_id,owner,corpus,bucket,object_key,revision,digest,version)
        VALUES ((p_payload->>'document_id')::uuid,p_owner,p_payload->>'corpus',p_payload->>'bucket',
            p_payload->>'object_key',(p_payload->>'revision')::uuid,p_payload->>'digest',p_payload->>'version')
        ON CONFLICT (document_id) DO NOTHING;
        SELECT * INTO d FROM public.corpus_ai_drafts WHERE document_id=(p_payload->>'document_id')::uuid AND owner=p_owner;
        IF NOT FOUND THEN RAISE EXCEPTION 'AI_NOT_FOUND'; END IF;
        IF (to_jsonb(d) - 'owner' - 'state') <> p_payload THEN RAISE EXCEPTION 'AI_CONFLICT'; END IF;
        RETURN to_jsonb(d);
    ELSIF p_action = 'resolve' THEN
        SELECT * INTO d FROM public.corpus_ai_drafts WHERE owner=p_owner AND corpus=p_payload->>'corpus';
        RETURN CASE WHEN FOUND THEN to_jsonb(d) ELSE NULL END;
    ELSIF p_action = 'pending' THEN
        IF (p_payload->>'limit')::int NOT BETWEEN 1 AND 100 THEN RAISE EXCEPTION 'AI_INVALID'; END IF;
        SELECT coalesce(jsonb_agg(jsonb_build_object('intent',q.intent,'applied_at',q.applied_at) ORDER BY q.created_at,q.id),'[]') INTO result
        FROM (SELECT * FROM public.corpus_ai_operations WHERE owner=p_owner AND applied_at IS NULL
            ORDER BY created_at,id LIMIT (p_payload->>'limit')::int) q;
        RETURN result;
    ELSIF p_action IN ('get','receipt') THEN
        SELECT * INTO o FROM public.corpus_ai_operations WHERE id=(p_payload->>'id')::uuid AND owner=p_owner;
        IF NOT FOUND THEN RETURN NULL; END IF;
        IF p_action='receipt' THEN RETURN o.receipt; END IF;
        RETURN jsonb_build_object('intent',o.intent,'applied_at',o.applied_at);
    ELSIF p_action='insert' THEN
        i := p_payload->'intent';
        operation_id := (i->>'id')::uuid;
        IF (i->>'owner')::uuid IS DISTINCT FROM p_owner THEN RAISE EXCEPTION 'AI_INVALID'; END IF;
        SELECT * INTO d FROM public.corpus_ai_drafts
            WHERE owner=p_owner AND corpus=i->'suggestion'->'scope'->>'corpus' FOR UPDATE;
        IF NOT FOUND THEN RAISE EXCEPTION 'AI_NOT_FOUND'; END IF;
        IF d.state <> 'draft' THEN RAISE EXCEPTION 'AI_LOCKED'; END IF;
        SELECT * INTO o FROM public.corpus_ai_operations WHERE id=operation_id;
        IF FOUND THEN
            IF o.owner <> p_owner OR o.document_id <> d.document_id THEN RAISE EXCEPTION 'AI_NOT_FOUND'; END IF;
            -- Concurrent identical attempts may have staged different after
            -- revisions. Return the first immutable intent; engine checks payload.
            RETURN jsonb_build_object('intent',o.intent,'applied_at',o.applied_at);
        END IF;
        b := i->'plan'->'before'; a := i->'plan'->'after';
        IF (b->>'revision')::uuid IS DISTINCT FROM d.revision OR b->>'digest' IS DISTINCT FROM d.digest
            OR b->>'version' IS DISTINCT FROM d.version THEN RAISE EXCEPTION 'AI_CONFLICT'; END IF;
        IF a->>'revision' IS NOT DISTINCT FROM b->>'revision' OR a->>'digest' IS NOT DISTINCT FROM b->>'digest'
            OR a->>'version' IS NOT DISTINCT FROM b->>'version' THEN RAISE EXCEPTION 'AI_INVALID'; END IF;
        -- Never reuse a historical revision, even if its values were restored.
        IF EXISTS (SELECT 1 FROM public.corpus_ai_operations prior WHERE prior.document_id=d.document_id
            AND (prior.intent->'plan'->'before'->>'revision'=a->>'revision'
                OR prior.intent->'plan'->'after'->>'revision'=a->>'revision'))
            THEN RAISE EXCEPTION 'AI_CONFLICT'; END IF;
        IF jsonb_typeof(p_payload->'entries') IS DISTINCT FROM 'array'
            OR jsonb_array_length(p_payload->'entries')=0
            OR jsonb_array_length(p_payload->'entries') <> jsonb_array_length(i->'suggestion'->'diff')
            THEN RAISE EXCEPTION 'AI_INVALID'; END IF;
        IF i->>'reverts' IS NOT NULL THEN
            PERFORM 1 FROM public.corpus_ai_operations WHERE id=(i->>'reverts')::uuid AND owner=p_owner
                AND document_id=d.document_id AND applied_at IS NOT NULL;
            IF NOT FOUND THEN RAISE EXCEPTION 'AI_NOT_FOUND'; END IF;
        END IF;
        INSERT INTO public.corpus_ai_operations(id,document_id,owner,intent,proof,reverts)
            VALUES(operation_id,d.document_id,p_owner,i,p_payload->>'proof',(i->>'reverts')::uuid);
        FOR e IN SELECT value FROM jsonb_array_elements(p_payload->'entries') LOOP
            IF e->>'corpus' IS DISTINCT FROM d.corpus OR (e->>'applied_by')::uuid IS DISTINCT FROM p_owner
                OR e->'resp' IS DISTINCT FROM jsonb_build_array('#corpora-ai','#'||p_owner::text)
                OR e->>'version' IS DISTINCT FROM a->>'version'
                OR e->>'node_id' IS DISTINCT FROM i->'suggestion'->>'target_node'
                OR NOT EXISTS (SELECT 1 FROM jsonb_array_elements(i->'suggestion'->'diff') r
                    WHERE r->>'field'=e->>'field' AND r->'old' IS NOT DISTINCT FROM e->'previous_value'
                        AND r->'new' IS NOT DISTINCT FROM e->'new_value')
                THEN RAISE EXCEPTION 'AI_INVALID'; END IF;
            IF i->>'reverts' IS NULL AND e->>'reverts' IS NOT NULL THEN RAISE EXCEPTION 'AI_INVALID'; END IF;
            IF i->>'reverts' IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM public.corpus_changes c WHERE c.id=(e->>'reverts')::uuid
                AND c.ai_operation_id=(i->>'reverts')::uuid AND c.document_id=d.document_id
                AND c.applied_by=p_owner AND c.field=e->>'field' AND c.node_id=(e->>'node_id')::bigint
                AND c.new_value IS NOT DISTINCT FROM e->>'previous_value'
                AND c.previous_value IS NOT DISTINCT FROM e->>'new_value') THEN RAISE EXCEPTION 'AI_INVALID'; END IF;
            INSERT INTO public.corpus_changes(id,document_id,ai_operation_id,reverts_change_id,version,node_id,node_type,
                field,previous_value,new_value,kind,status,resp,applied_by,suggestion_id,thread_id,rule,rationale,diff,scope,content_hash_before,source)
            VALUES ((e->>'change_id')::uuid,d.document_id,operation_id,(e->>'reverts')::uuid,a->>'version',
                (i->'suggestion'->>'target_node')::bigint,i->'suggestion'->'scope'->>'node_type',
                e->>'field',e->>'previous_value',e->>'new_value',i->'suggestion'->>'kind','pending',
                ARRAY['#corpora-ai','#'||p_owner::text],p_owner,i->'suggestion'->>'id',
                split_part(i->'suggestion'->>'id',':',1),i->'suggestion'->'finding'->>'rule',
                i->'suggestion'->>'rationale',i->'suggestion'->'diff',i->'suggestion'->'scope',b->>'content_hash','ai_panel');
        END LOOP;
        RETURN jsonb_build_object('intent',i,'applied_at',NULL);
    ELSIF p_action IN ('publish','finish','set_state') THEN
        IF p_action='set_state' THEN
            SELECT * INTO d FROM public.corpus_ai_drafts WHERE owner=p_owner AND corpus=p_payload->>'corpus' FOR UPDATE;
            IF NOT FOUND THEN RAISE EXCEPTION 'AI_NOT_FOUND'; END IF;
            UPDATE public.corpus_ai_drafts SET state=p_payload->>'state' WHERE document_id=d.document_id RETURNING * INTO d;
            RETURN to_jsonb(d);
        END IF;
        SELECT * INTO o FROM public.corpus_ai_operations WHERE id=(p_payload->>'id')::uuid AND owner=p_owner;
        IF NOT FOUND THEN RAISE EXCEPTION 'AI_NOT_FOUND'; END IF;
        SELECT * INTO d FROM public.corpus_ai_drafts WHERE document_id=o.document_id AND owner=p_owner FOR UPDATE;
        IF NOT FOUND THEN RAISE EXCEPTION 'AI_NOT_FOUND'; END IF;
        SELECT * INTO o FROM public.corpus_ai_operations WHERE id=o.id FOR UPDATE;
        IF p_action='publish' THEN
            IF d.state <> 'draft' THEN RAISE EXCEPTION 'AI_LOCKED'; END IF;
            IF o.proof IS DISTINCT FROM p_payload->>'proof' THEN RAISE EXCEPTION 'AI_CONFLICT'; END IF;
            IF o.receipt IS NOT NULL THEN RETURN 'true'::jsonb; END IF;
            b := o.intent->'plan'->'before'; a := o.intent->'plan'->'after';
            IF (b->>'revision')::uuid IS DISTINCT FROM d.revision OR b->>'digest' IS DISTINCT FROM d.digest
                OR b->>'version' IS DISTINCT FROM d.version THEN RETURN 'false'::jsonb; END IF;
            -- Staged object must have been uploaded without upsert and its digest
            -- verified by the server before this pointer may become visible.
            IF p_payload->>'object_key' IS DISTINCT FROM
                p_owner::text||'/ai/'||d.document_id::text||'/'||(a->>'revision')||'.corpus'
                THEN RAISE EXCEPTION 'AI_INVALID'; END IF;
            moment := clock_timestamp();
            UPDATE public.corpus_ai_drafts SET revision=(a->>'revision')::uuid,digest=a->>'digest',
                version=a->>'version',object_key=p_payload->>'object_key' WHERE document_id=d.document_id;
            UPDATE public.corpus_ai_operations SET receipt=jsonb_build_object('proof',o.proof,'applied_at',moment)
                WHERE id=o.id;
            RETURN 'true'::jsonb;
        END IF;
        -- Finishing an already published operation remains possible after a
        -- document is locked; it records history and does not change HEAD.
        IF o.applied_at IS NOT NULL THEN RETURN jsonb_build_object('intent',o.intent,'applied_at',o.applied_at); END IF;
        IF o.receipt IS NULL OR o.receipt->>'proof' IS DISTINCT FROM o.proof THEN RAISE EXCEPTION 'AI_CONFLICT'; END IF;
        moment := (o.receipt->>'applied_at')::timestamptz;
        UPDATE public.corpus_changes SET status='applied',applied_at=moment WHERE ai_operation_id=o.id AND status='pending';
        GET DIAGNOSTICS affected = ROW_COUNT;
        IF affected <> jsonb_array_length(o.intent->'suggestion'->'diff') THEN RAISE EXCEPTION 'AI_CONFLICT'; END IF;
        UPDATE public.corpus_ai_operations SET applied_at=moment WHERE id=o.id;
        RETURN jsonb_build_object('intent',o.intent,'applied_at',moment);
    ELSE
        RAISE EXCEPTION 'AI_INVALID';
    END IF;
END $$;
REVOKE ALL ON FUNCTION public.corpora_ai_storage(text,uuid,jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.corpora_ai_storage(text,uuid,jsonb) TO service_role;
COMMENT ON FUNCTION public.corpora_ai_storage(text,uuid,jsonb) IS
    'Server-only AI journal and draft pointer transactions. Immutable object upload/verification precedes publish.';
NOTIFY pgrst, 'reload schema';
