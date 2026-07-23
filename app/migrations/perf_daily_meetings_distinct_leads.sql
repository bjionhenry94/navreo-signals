-- Meetings/day = distinct booked LEADS, dated by their FIRST Call Booked /
-- Meeting Request reply — one per person. The old series counted reply ROWS
-- per day, so a chatty thread (one person, five CB/MR replies) plotted as
-- five meetings and never reconciled with the cockpit's meetings tile.
-- The inner group-by is deliberately UNBOUNDED by the window: a lead who
-- booked before p_start and replied again inside the window must not recount.
-- Signature and return shape unchanged; rep keeps positives/replies_all.
CREATE OR REPLACE FUNCTION public.perf_daily_series_v2(p_start date, p_end date, p_campaign text DEFAULT NULL::text, p_source_ids text[] DEFAULT NULL::text[])
 RETURNS TABLE(d date, sent bigint, positives bigint, meetings bigint, leads_added bigint, replies_all bigint, sent_30d bigint, replies_30d bigint, bounces_30d bigint)
 LANGUAGE sql
 STABLE
AS $function$
  with days as (select generate_series(p_start, p_end, interval '1 day')::date as d),
  sm as (
    select (sent_at at time zone 'utc')::date d, count(*) n
    from sent_messages
    where sent_at >= ((p_start::timestamp) at time zone 'utc')
      and sent_at <  (((p_end + 1)::timestamp) at time zone 'utc')
      and (p_campaign is null or smartlead_campaign_id::text = p_campaign)
    group by 1),
  rep as (
    select (replied_at at time zone 'utc')::date d,
           count(*) filter (where category in ('Interested','Call Booked','Meeting Request','Information Request')) positives,
           count(*) replies_all
    from replies
    where replied_at >= ((p_start::timestamp) at time zone 'utc')
      and replied_at <  (((p_end + 1)::timestamp) at time zone 'utc')
      and (p_campaign is null or smartlead_campaign_id::text = p_campaign)
    group by 1),
  mtg as (
    select b.d, count(*) n from (
      select (min(replied_at) at time zone 'utc')::date d
      from replies
      where category in ('Call Booked','Meeting Request')
        and (p_campaign is null or smartlead_campaign_id::text = p_campaign)
      group by smartlead_campaign_id, email) b
    where b.d between p_start and p_end
    group by 1),
  sl as (
    select (pulled_at at time zone 'utc')::date d, count(*) n
    from signal_leads
    where pulled_at >= ((p_start::timestamp) at time zone 'utc')
      and pulled_at <  (((p_end + 1)::timestamp) at time zone 'utc')
      and (p_source_ids is null or source_id = any(p_source_ids))
    group by 1),
  msd as (
    select stat_date d, sum(sent_30d) sent_30d, sum(replies_30d) replies_30d, sum(bounces_30d) bounces_30d
    from mailbox_stats_daily where stat_date between p_start and p_end group by 1)
  select days.d,
    coalesce(sm.n,0)::bigint, coalesce(rep.positives,0)::bigint, coalesce(mtg.n,0)::bigint,
    coalesce(sl.n,0)::bigint, coalesce(rep.replies_all,0)::bigint,
    coalesce(msd.sent_30d,0)::bigint, coalesce(msd.replies_30d,0)::bigint, coalesce(msd.bounces_30d,0)::bigint
  from days
  left join sm on sm.d=days.d left join rep on rep.d=days.d
  left join mtg on mtg.d=days.d
  left join sl on sl.d=days.d left join msd on msd.d=days.d
  order by days.d;
$function$;
