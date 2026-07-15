-- tier1-live-ship Step 2 (backend): campaign-ideas persistence + recontact review runs.
-- Apply against the navreo-signals Supabase project. Both tables are id/jsonb-doc
-- shaped, matching the sources/campaign_drafts/clients convention already in use.

create table if not exists campaign_idea_suggestions (
  id text primary key,
  campaign_id text not null,
  idea jsonb not null,
  status text not null default 'suggested',  -- 'suggested' | 'dismissed'
  created_at timestamptz default now()
);
create index if not exists campaign_idea_suggestions_campaign_idx
  on campaign_idea_suggestions (campaign_id);
alter table campaign_idea_suggestions enable row level security;

create table if not exists recontact_runs (
  id text primary key,
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz default now()
);
alter table recontact_runs enable row level security;
