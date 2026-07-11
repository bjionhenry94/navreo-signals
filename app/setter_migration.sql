create table if not exists setter_agents (
  id text primary key,
  doc jsonb not null,
  updated_at timestamptz default now()
);
alter table setter_agents enable row level security;

create table if not exists setter_queue (
  id bigint generated always as identity primary key,
  workspace text not null default 'navreo',
  smartlead_campaign_id bigint not null,
  agent_id text,
  lead_email text not null,
  lead_first_name text,
  lead_last_name text,
  company_domain text,
  message_id text not null default '',
  reply_subject text,
  reply_body text,
  replied_at timestamptz,
  category text,
  thread jsonb,
  smartlead_lead_id bigint,
  email_stats_id text,
  classification jsonb,
  guardrails jsonb,
  timezone text,
  slots jsonb,
  draft_subject text,
  draft_body text,
  decision text,
  decision_reason text,
  status text not null default 'new',
  added_to_subsequence boolean not null default false,
  sent_at timestamptz,
  sent_body text,
  error text,
  is_test boolean not null default false,
  created_at timestamptz default now(),
  updated_at timestamptz default now(),
  unique (workspace, smartlead_campaign_id, lead_email, message_id)
);
alter table setter_queue enable row level security;
create index if not exists setter_queue_status_idx on setter_queue (status, created_at desc);
