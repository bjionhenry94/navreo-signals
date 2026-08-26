-- analytics_hub_v4 (2026-08-09, meeting-attribution-truth): mtg_base now
-- counts calendly-synced booking events (see
-- meetings_calendly_booking_events.sql for the rule). Function name stays
-- analytics_hub_v1 (the server calls it by name). Rest identical to v3.
CREATE OR REPLACE FUNCTION public.analytics_hub_v1(p_days int DEFAULT 30)
RETURNS jsonb
LANGUAGE sql
STABLE
AS $function$
with params as (
  select least(greatest(coalesce(p_days,30),7),30) as nd
),
bounds as (
  select (current_date - (nd - 1)) as d0, current_date as d1,
         ((current_date - (nd - 1))::timestamp at time zone 'utc') as t0
  from params
),
cmap as (
  select smartlead_campaign_id::text as cid, name, status,
         coalesce(nullif(client,''),'__unassigned') as client,
         coalesce(total,0) as total, coalesce(completed,0) as completed
  from campaign_scorecard
),
days as (select generate_series((select d0 from bounds),(select d1 from bounds), interval '1 day')::date as d),
rep as (
  select (r.replied_at at time zone 'utc')::date as d,
         coalesce(c.client,'__unassigned') as client,
         count(*) as replies_all
  from replies r left join cmap c on c.cid = r.smartlead_campaign_id::text
  where r.replied_at >= (select t0 from bounds)
  group by 1,2
),
pos_base as (
  -- ONE positive per LEAD (owner ruling 2026-08-26): Smartlead counts a
  -- campaign's positives as distinct interested leads, and the archive holds
  -- several positive rows per lead (a lead who replies twice, or replies on two
  -- variants) — so each lead counts ONCE, dated at their FIRST positive reply.
  -- Mirrors mtg_base's per-person rule; unbounded scan on purpose so a lead whose
  -- first positive predates the window is not recounted inside it.
  select r.smartlead_campaign_id::text as cid, lower(r.email) as email,
         (min(r.replied_at) at time zone 'utc')::date as d
  from replies r
  where r.category in ('Interested','Call Booked','Meeting Request','Information Request')
  group by 1,2
),
pos as (
  select b.d, coalesce(c.client,'__unassigned') as client, count(*) as positives
  from pos_base b left join cmap c on c.cid = b.cid
  where b.d >= (select d0 from bounds)
  group by 1,2
),
mtg_base as (
  -- Call Booked ONLY (owner ruling 2026-07-30). v4 (2026-08-09): calendly-
  -- synced rows (raw->>'source'='calendly', one per real booking event, dated
  -- at booking time) count one meeting per booking DAY; leads with only
  -- legacy categorised rows keep the first-reply-one-per-person rule
  -- (unbounded on purpose: a pre-window booker must not recount).
  select distinct r.smartlead_campaign_id::text as cid, lower(r.email) as email,
         (r.replied_at at time zone 'utc')::date as d
  from replies r
  where r.category = 'Call Booked' and r.raw->>'source' = 'calendly'
  union all
  select r.smartlead_campaign_id::text, lower(r.email),
         (min(r.replied_at) at time zone 'utc')::date
  from replies r
  where r.category = 'Call Booked'
    and coalesce(r.raw->>'source','') <> 'calendly'
    and not exists (select 1 from replies r2
                    where lower(r2.email) = lower(r.email)
                      and r2.category = 'Call Booked'
                      and r2.raw->>'source' = 'calendly')
  group by 1,2
),
mtg as (
  select b.d, coalesce(c.client,'__unassigned') as client, count(*) as n
  from mtg_base b left join cmap c on c.cid = b.cid
  where b.d >= (select d0 from bounds)
  group by 1,2
),
facts as (
  select d, client, replies_all as n, 'replies'::text as metric from rep
  union all select d, client, positives, 'interested' from pos
  union all select d, client, n,         'meetings'   from mtg
),
factsx as (
  select coalesce(client,'__all') as client, d, metric, sum(n) as n
  from facts
  group by grouping sets ((client, d, metric), (d, metric))
),
clients_ranked as (
  select client, sum(n) as tot
  from factsx where client <> '__all' and client <> '__unassigned' and metric = 'replies'
  group by 1 order by tot desc
),
series_arr as (
  select cl.client, m.metric, jsonb_agg(coalesce(fx.n,0) order by dy.d) as arr
  from (select distinct client from factsx where client <> '__unassigned') cl
  cross join (values ('replies'),('interested'),('meetings')) as m(metric)
  cross join days dy
  left join factsx fx on fx.client = cl.client and fx.metric = m.metric and fx.d = dy.d
  group by 1,2
),
series_json as (
  select jsonb_object_agg(client, o) as v
  from (select client, jsonb_object_agg(metric, arr) as o from series_arr group by client) t
),
wk_base as (
  -- weekday of the send that earned each reply (latest send at or before it)
  select coalesce(client,'__all') as client, extract(isodow from sd)::int as dow, count(*) as n
  from (
    select coalesce(c.client,'__unassigned') as client,
           (max(m.sent_at) at time zone 'utc')::date as sd
    from replies r
    left join cmap c on c.cid = r.smartlead_campaign_id::text
    join sent_messages m on m.smartlead_campaign_id::text = r.smartlead_campaign_id::text
                        and lower(m.email) = lower(r.email) and m.sent_at <= r.replied_at
    where r.replied_at >= (select t0 from bounds)
    group by coalesce(c.client,'__unassigned'), r.id
  ) b
  group by grouping sets ((client, dow), (dow))
),
wk_json as (
  select jsonb_object_agg(client, arr) as v
  from (
    select cl.client, jsonb_agg(coalesce(w.n,0) order by g.dow) as arr
    from (select distinct client from wk_base where client <> '__unassigned') cl
    cross join generate_series(1,7) as g(dow)
    left join wk_base w on w.client = cl.client and w.dow = g.dow
    group by cl.client
  ) t
),
lat as (
  select coalesce(c.client,'__all') as client,
         round(avg(extract(epoch from (q.sent_at - q.replied_at)) / 60))::int as avg_mins,
         round((count(*) filter (where q.sent_at - q.replied_at <= interval '60 minutes'))::numeric
               / nullif(count(*),0), 2) as fast_share,
         count(*) as n
  from setter_queue q join cmap c on c.cid = q.smartlead_campaign_id::text
  where q.status in ('sent','auto_sent') and coalesce(q.is_test,false) = false
    and q.sent_at is not null and q.replied_at is not null and q.sent_at > q.replied_at
    and q.sent_at >= now() - interval '7 days'
  group by grouping sets ((c.client), ())
),
lat_json as (
  select jsonb_object_agg(client, jsonb_build_object(
           'avg_mins', avg_mins, 'fast_share', fast_share, 'n', n)) as v
  from lat where client <> '__unassigned'
),
mm as (
  -- prev month is capped at the same day-of-month so a part-way month compares
  -- like-for-like (July 1-27 vs June 1-27), never partial-vs-full.
  -- Inner subquery labels each row first ('__unassigned' when off-scorecard),
  -- so the () grouping set alone produces the NULL→'__all' row — a raw LEFT
  -- join here would have collided subsequence rows into '__all' twice.
  select client,
         count(*) filter (where date_trunc('month', s.d) = date_trunc('month', current_date)) as this,
         count(*) filter (where date_trunc('month', s.d) = date_trunc('month', current_date - interval '1 month')
                            and extract(day from s.d) <= extract(day from current_date)) as prev
  from (select coalesce(c.client,'__unassigned') as client, b.d
        from mtg_base b left join cmap c on c.cid = b.cid) s
  group by grouping sets ((client), ())
),
mm_top as (
  select client, name, n from (
    select coalesce(c.client,'__all') as client, c.name, count(*) as n,
           row_number() over (partition by coalesce(c.client,'__all') order by count(*) desc) as rn
    from mtg_base b left join cmap c on c.cid = b.cid
    where date_trunc('month', b.d) = date_trunc('month', current_date)
    group by grouping sets ((c.client, c.name), (c.name))
  ) t where rn = 1 and name is not null
),
mm_json as (
  select jsonb_object_agg(coalesce(m.client,'__all'), jsonb_build_object(
           'this', m.this, 'prev', m.prev,
           'top_campaign', t.name, 'top_n', t.n)) as v
  from mm m left join mm_top t on t.client = coalesce(m.client,'__all')
  where coalesce(m.client,'__all') <> '__unassigned'
),
camp_clients as (
  select jsonb_object_agg(cid, client) as v
  from cmap where status = 'ACTIVE' or coalesce(total,0) > 0
)
select jsonb_build_object(
  'days',             (select jsonb_agg(to_char(d,'YYYY-MM-DD') order by d) from days),
  'clients',          (select coalesce(jsonb_agg(client order by tot desc),'[]'::jsonb) from clients_ranked),
  'campaign_clients', (select v from camp_clients),
  'series',           (select v from series_json),
  'weekday',          (select v from wk_json),
  'latency',          (select v from lat_json),
  'meetings_monthly', (select v from mm_json),
  'asof',             to_char(now() at time zone 'utc','YYYY-MM-DD"T"HH24:MI:SS"Z"')
);
$function$;
