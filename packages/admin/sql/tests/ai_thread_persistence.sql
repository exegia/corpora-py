\set ON_ERROR_STOP on
BEGIN;
INSERT INTO auth.users VALUES ('11111111-1111-1111-1111-111111111111');
SET ROLE service_role;
INSERT INTO public.corpus_ai_threads(id,owner,corpus,created_at,data)
VALUES ('22222222-2222-2222-2222-222222222222','11111111-1111-1111-1111-111111111111','published',now(),'{"thread":{"id":"22222222-2222-2222-2222-222222222222","corpus":"published"}}');
DO $$
DECLARE affected int;
BEGIN
 UPDATE public.corpus_ai_threads SET revision=1 WHERE owner='11111111-1111-1111-1111-111111111111' AND revision=0;
 GET DIAGNOSTICS affected = ROW_COUNT;
 ASSERT affected = 1;
 UPDATE public.corpus_ai_threads SET revision=2 WHERE owner='11111111-1111-1111-1111-111111111111' AND revision=0;
 GET DIAGNOSTICS affected = ROW_COUNT;
 ASSERT affected = 0;
END $$;
RESET ROLE;
DO $$
BEGIN
 ASSERT (SELECT relrowsecurity FROM pg_class WHERE oid='public.corpus_ai_threads'::regclass);
 ASSERT NOT has_table_privilege('anon','public.corpus_ai_threads','SELECT');
 ASSERT NOT has_table_privilege('authenticated','public.corpus_ai_threads','INSERT');
 ASSERT NOT has_table_privilege('authenticated','public.corpus_ai_threads','UPDATE');
 ASSERT NOT has_table_privilege('service_role','public.corpus_ai_threads','DELETE');
END $$;
ROLLBACK;
