-- Shared JobStore for /convert and /ingest (issue #140).
-- corpora-py reads and writes this table with the service-role key
-- (PostgREST /rest/v1/conversion_jobs). RLS is enabled with no policies
-- so anon/authenticated JWTs cannot see other users' jobs; the service
-- role bypasses RLS and JobManager enforces owner in application code.
--
-- Apply against the same Supabase project whose JWT this API verifies
-- (PROJECT_REF / SUPABASE_URL). The root `supabase/` dir is CLI scratch
-- and is gitignored; this file is the tracked source of truth.

create table if not exists public.conversion_jobs (
  id text primary key,
  source_format text not null,
  name text not null,
  status text not null,
  created_at double precision not null,
  started_at double precision,
  finished_at double precision,
  result_key text,
  error text,
  logs jsonb not null default '[]'::jsonb,
  owner text,
  display_name text
);

create index if not exists conversion_jobs_owner_created_at_idx
  on public.conversion_jobs (owner, created_at desc);

create index if not exists conversion_jobs_finished_at_idx
  on public.conversion_jobs (finished_at);

alter table public.conversion_jobs enable row level security;
