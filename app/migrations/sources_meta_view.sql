-- sources_meta: the sources table minus each doc's `prospects` array.
-- Egress audit 2026-09-03: the UI list (/api/sources) read `sources?select=doc`
-- ~670x/day at ~30 MB per response and then stripped `prospects` in Python
-- (server.py _compute_sources_full). Meta is ~391 KB; prospects are the rest.
-- Read-only, additive; the app falls back to the base table if this view is
-- missing. Pull/dedupe paths that genuinely need prospects still read `sources`.
create or replace view public.sources_meta as
  select id, (doc - 'prospects') as doc, updated_at
  from public.sources;
grant select on public.sources_meta to service_role, authenticated, anon;
