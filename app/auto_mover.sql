-- Variant Auto-Mover — storage (Step 3, 2026-09-02)
--
-- Two tables and one helper:
--   auto_mover_campaign_prefs — the per-campaign switch (inherit | on | off).
--     `inherit` means "follow the global switch" (ui_prefs.auto_mover_enabled);
--     a row is only written when a human picks on/off, so absence == inherit.
--   auto_mover_moves          — the ledger. EVERY move the mover makes lands
--     here with its before/after distribution AND before/after per-version
--     counters, so R1 (counter preservation) can be checked after the fact and
--     the General page can show the last 50 moves with any open issue.
--   auto_mover_last_write()   — the human-off provenance hook (v3 spec
--     docs/variant-fair-test-law-v3.md:63-71): a 0% share that matches the
--     mover's own last write is system-off, not human-off. Without this the
--     mover's own partial-verdict drops would later read as human decisions
--     and freeze those versions forever.
--
-- Applied in Supabase (project fnykldftbkrccihdjayl). Re-runnable.

create table if not exists auto_mover_campaign_prefs (
  campaign_id text primary key,
  mode        text not null default 'inherit'
              check (mode in ('inherit', 'on', 'off')),
  set_by      text,
  set_at      timestamptz not null default now()
);

create table if not exists auto_mover_moves (
  id               bigserial primary key,
  campaign_id      text,
  step             int,
  action           text,          -- scale_winner | back_winner | split_leaders
  winner           text,          -- the crowned version label (null on a tie)
  mode             text,          -- full | partial | tie  (from pill_best_opener)
  via              text,          -- evidence.via — which path picked the winner
  laggards         jsonb,
  leaders          jsonb,
  dropped          jsonb,
  pcts_before      jsonb,         -- {label: pct} distribution before the save
  pcts_after       jsonb,         -- {label: pct} distribution after the save
  counters_before  jsonb,         -- {label: {sent, replies, positives}}
  counters_after   jsonb,
  notification_id  text,
  evidence         jsonb,         -- the full pill_best_opener evidence dict
  actor            text,          -- auto-mover@navreo.ai, or a human's email
  outcome          text,          -- moved | skipped | failed | issue
  issue_kind       text,          -- breaker | counter_drop | flap | human_owned | …
  notion_task_url  text,
  created_at       timestamptz not null default now()
);

create index if not exists auto_mover_moves_campaign_idx
  on auto_mover_moves (campaign_id, created_at desc);
create index if not exists auto_mover_moves_created_idx
  on auto_mover_moves (created_at desc);
-- the General page's "open issues" lane reads only the flagged rows
create index if not exists auto_mover_moves_issue_idx
  on auto_mover_moves (created_at desc)
  where outcome = 'issue' or issue_kind is not null;

-- {label: pct} the mover itself last wrote for this campaign+step, or {}.
-- Consulted by the human-off provenance check before treating a 0% share as
-- a sticky human decision.
create or replace function auto_mover_last_write(p_campaign_id text, p_step int)
returns jsonb
language sql
stable
as $$
  select coalesce((
    select m.pcts_after
      from auto_mover_moves m
     where m.campaign_id = p_campaign_id
       and m.step = p_step
       and m.outcome = 'moved'
       and m.pcts_after is not null
     order by m.created_at desc
     limit 1
  ), '{}'::jsonb)
$$;
