-- Warm-call sideboard (owner ask 2026-08-15): enrichment cache + per-client
-- qualification context. Applied to Supabase 2026-08-15 via the management API.
--
-- setter_lead_enrichment: one row per lead the setter has TRIED to enrich
-- (phone + provider payload). A row existing - even with an empty phone -
-- means "already paid/attempted, never re-pay" (auth/credit failures are NOT
-- banked; see setter.py _enrich_on_reply). phone_source: prospeo | getleads |
-- backfill-smartlead | backfill-folk.
create table if not exists setter_lead_enrichment (
  lead_email text primary key,
  phone text,
  phone_source text,
  company_domain text,
  enriched_at timestamptz not null default now(),
  payload jsonb
);

-- setter_client_context: what the sideboard says about THE CLIENT (hide/show
-- block) and the icp rules behind the Likely-qualified chip. One row per
-- workspace; seeded with defaults Bjion refines per client later.
-- icp jsonb: {headcount_min, headcount_max, countries[], industries[], note}
create table if not exists setter_client_context (
  workspace text primary key,
  client_label text,
  about text,
  offer text,
  icp jsonb,
  updated_at timestamptz not null default now()
);

-- 2026-08-17: rep-filed call dispositions (SDR panel round 2) - connected |
-- voicemail | bad; "bad" strikes the number in the UI instead of vouching
-- for it. Applied via the management API 2026-08-17.
alter table setter_lead_enrichment
  add column if not exists phone_status text,
  add column if not exists phone_status_at timestamptz;
