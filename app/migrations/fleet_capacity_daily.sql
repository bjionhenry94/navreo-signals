-- fleet_capacity_daily(p_start): per-day, per-workspace sending CAPACITY.
--
-- Capacity for a day = the summed per-box daily send cap (message_per_day, the
-- snapshot in mailbox_stats_daily for that stat_date) over every mailbox that is
-- ATTACHED TO A CAMPAIGN (mailboxes.campaign_count > 0). Boxes on no campaign
-- can't send, so they don't count toward usable capacity (Bjion, 2026-08-19).
--
-- The campaign attachment (campaign_count) is read from the CURRENT mailboxes
-- registry and applied across the window, so the per-day shape reflects each
-- box's historical cap (warm-up ramps it up) for today's attached roster.
-- Aggregation lives in the DB because PostgREST has aggregates disabled.
--
-- Consumed by /api/fleet-capacity (server.py) -> the day-by-day capacity ceiling
-- on the Analytics chart. Read-only, STABLE.
create or replace function public.fleet_capacity_daily(p_start date)
returns table(stat_date date, workspace text, cap integer, boxes integer)
language sql stable as $fn$
  select msd.stat_date, m.workspace,
         sum(msd.message_per_day)::int as cap,
         count(*)::int as boxes
  from mailbox_stats_daily msd
  join mailboxes m on m.smartlead_id = msd.smartlead_id
  where m.campaign_count > 0 and msd.stat_date >= p_start
  group by msd.stat_date, m.workspace
  order by msd.stat_date, m.workspace;
$fn$;

grant execute on function public.fleet_capacity_daily(date) to service_role, authenticated, anon;
