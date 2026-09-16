-- client_monthly_stats — the month-by-month row every client's Campaign
-- Dashboard (/app/dashboard.html) reads. Written by app/monthly_stats.py from
-- the daily cron (app/run_daily.py) after the capacity write; never computed
-- on a web request (512 MB Render instance — no heavy compute inline).
--
-- One row per (client, month). `month` is the FIRST day of the calendar month.
-- sent/replied/bounced come from Smartlead day-wise-overall-stats scoped to the
-- client's campaign ids (the same path _daywise_series / _report_range_stats
-- use); positive/meetings come from the replies archive under the analytics
-- hub's positive-category mapping; campaigns_active counts the client's
-- campaigns that sent anything in the month.
create table if not exists public.client_monthly_stats (
  client           text        not null,
  month            date        not null,
  sent             integer     not null default 0,
  replied          integer     not null default 0,
  bounced          integer     not null default 0,
  positive         integer     not null default 0,
  meetings         integer     not null default 0,
  campaigns_active integer     not null default 0,
  updated_at       timestamptz not null default now(),
  primary key (client, month)
);

create index if not exists client_monthly_stats_month_idx
  on public.client_monthly_stats (month);

grant select, insert, update, delete on public.client_monthly_stats to service_role;

-- campaign_contact_months(p_ids): per-campaign, per-month count of prospects
-- first contacted, for a set of smartlead campaign ids. PostgREST has
-- aggregates disabled, so the group-by lives in the DB (same reason
-- fleet_capacity_daily does). Consumed by app/monthly_stats.py to derive
-- client_monthly_stats.campaigns_active and each client's FIRST campaign month
-- without dragging ~1.1M contact_history rows over the wire.
create or replace function public.campaign_contact_months(p_ids bigint[])
returns table(smartlead_campaign_id bigint, month date, leads integer)
language sql stable as $fn$
  select ch.smartlead_campaign_id,
         date_trunc('month', ch.first_contacted_at)::date as month,
         count(*)::int as leads
  from contact_history ch
  where ch.smartlead_campaign_id = any(p_ids)
    and ch.first_contacted_at is not null
  group by 1, 2
  order by 1, 2;
$fn$;

grant execute on function public.campaign_contact_months(bigint[]) to service_role, authenticated, anon;
