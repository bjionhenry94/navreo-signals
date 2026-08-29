-- Onboarding autosave (app/onboarding.html → server-side persistence).
-- Apply against the navreo-signals Supabase project. id/jsonb-doc shaped,
-- matching the campaign_drafts / sources / clients convention already in use.
-- The whole record (name, stage, status, timestamps AND the raw hub state)
-- lives in `doc`, so the CSM Clients view needs no extra columns.

create table if not exists onboarding_drafts (
  id text primary key,
  doc jsonb not null,
  updated_at timestamptz default now()
);

-- newest-touched first drives the CSM "Clients" list ordering
create index if not exists onboarding_drafts_updated_idx
  on onboarding_drafts (updated_at desc);

alter table onboarding_drafts enable row level security;
