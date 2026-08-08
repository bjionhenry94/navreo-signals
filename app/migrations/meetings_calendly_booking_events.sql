-- meetings_calendly_booking_events (2026-08-09, meeting-attribution-truth):
-- calendly_sync.py now writes one synthetic Call Booked row per REAL booking
-- event (raw->>'source' = 'calendly', replied_at = the Calendly booking time).
-- Counting upgrade, applied identically to perf_daily_series_v2 and
-- analytics_hub_v1's mtg_base:
--   * a lead WITH calendly rows counts one meeting per booking DAY
--     (distinct campaign+email+date — same-day duplicate calendar events
--     collapse; a genuine re-book weeks later counts again, matching the
--     owner's manual log), dated at booking time. Their legacy categorised
--     rows are ignored — they describe the same booking.
--   * a lead with ONLY legacy Call Booked rows keeps the 2026-07-30 rule:
--     one per person, dated by their FIRST Call Booked reply.
-- collective_30d needs no change (distinct campaign+email dedup already
-- absorbs the synthetic rows).

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
  mtg_events as (
    -- calendly-synced bookings: one per booking day per lead per campaign
    select distinct smartlead_campaign_id, lower(email) em,
           (replied_at at time zone 'utc')::date d
    from replies
    where category = 'Call Booked'
      and workspace = 'navreo'
      and raw->>'source' = 'calendly'
      and (p_campaign is null or smartlead_campaign_id::text = p_campaign)
    union all
    -- legacy-only leads: first Call Booked reply, one per person (unbounded
    -- by the window on purpose — a pre-window booker must not recount)
    select r.smartlead_campaign_id, lower(r.email),
           (min(r.replied_at) at time zone 'utc')::date
    from replies r
    where r.category = 'Call Booked'
      and r.workspace = 'navreo'
      and coalesce(r.raw->>'source','') <> 'calendly'
      and (p_campaign is null or r.smartlead_campaign_id::text = p_campaign)
      -- email-only guard: a person's calendly booking absorbs their legacy
      -- rows even when the categorised reply sat on a sibling campaign id
      and not exists (select 1 from replies r2
                      where lower(r2.email) = lower(r.email)
                        and r2.category = 'Call Booked'
                        and r2.raw->>'source' = 'calendly')
    group by r.smartlead_campaign_id, lower(r.email)),
  mtg as (
    select b.d, count(*) n from mtg_events b
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
