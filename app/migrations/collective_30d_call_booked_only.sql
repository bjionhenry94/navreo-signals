-- collective_30d: homepage 30-day strip. Previously counted every row in the
-- meetings table (booked_at last 30d) — that table is fed by an external
-- pipeline (smartlead-tag + Fathom) whose smartlead-tag rows include Meeting
-- Request and other non-booked categories, so the strip over-reported.
-- Now: meetings = distinct booked LEADS from the reply archive, Call Booked
-- ONLY (owner ruling 2026-07-30: a Meeting Request is not a meeting until the
-- call is actually booked). Same definition as perf_daily_series_v2 and
-- analytics_hub_v1 so every surface agrees.
-- This definition previously lived only in Supabase; checked in 2026-07-30.
CREATE OR REPLACE FUNCTION public.collective_30d()
 RETURNS json
 LANGUAGE sql
 STABLE
AS $function$
  with latest as (select max(stat_date) d from mailbox_stats_daily),
  fleet as (
    select
      coalesce(sum(sent_30d),0)::bigint            as sent,
      coalesce(sum(replies_30d),0)::bigint         as replies,
      coalesce(sum(positive_replies_30d),0)::bigint as positives,
      coalesce(sum(bounces_30d),0)::bigint         as bounces
    from mailbox_stats_daily
    where stat_date = (select d from latest)
  )
  select json_build_object(
    'snapshot_date',    (select d from latest),
    'sent',             fleet.sent,
    'replies',          fleet.replies,
    'positives',        fleet.positives,
    'bounces',          fleet.bounces,
    'reply_pct',        case when fleet.sent > 0 then round(100.0*fleet.replies/fleet.sent, 2) else 0 end,
    'bounce_pct',       case when fleet.sent > 0 then round(100.0*fleet.bounces/fleet.sent, 2) else 0 end,
    'meetings',         (select count(distinct (smartlead_campaign_id, lower(email)))
                           from replies
                          where category = 'Call Booked'
                            and workspace = 'navreo'
                            and replied_at >= now() - interval '30 days'),
    'signals_sourced',  (select count(*) from signal_leads where pulled_at >= now() - interval '30 days')
  ) from fleet;
$function$
