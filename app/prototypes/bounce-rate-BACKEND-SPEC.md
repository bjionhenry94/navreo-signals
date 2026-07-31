# Per-campaign daily bounce series — backend spec

**Why:** the bounce widget's date toggle (7d / 14d / 30d) moves the trend, but the
campaign/client list under it is lifetime cumulative and never changes. Five
non-technical reviewers hit this across two rounds; three called it a trap in the
same words — *"I'd have quoted a 7-day number in a board meeting that was
actually an all-time number."* The prototypes ship on lifetime data with an
inline label; this spec removes the need for that label.

## What exists today

| Need | Source | Windowed? |
|---|---|---|
| Fleet bounce %, per day | `/api/deliverability-trends` → `series.bounce_pct[]` (Smartlead `analytics/day-wise-overall-stats`, stored in `fleet_daily_stats`) | ✅ yes |
| Per-campaign bounced/sent | `campaign_scorecard` table, synced by `_scorecard_sync_all()` | ❌ **lifetime only** |

`server.py` is explicit about the gap (~line 7132): *"no reliable per-campaign
daily rate in the data layer"*. The only per-campaign daily rollup in the repo is
HeyReach's (`heyreach_campaign_stats`, ~line 12153) — LinkedIn, not email, so it
does not apply.

## The change

**1 · New table `campaign_daily_stats`**

```sql
create table campaign_daily_stats (
  smartlead_campaign_id bigint  not null,
  stat_date             date    not null,
  sent                  integer not null default 0,
  bounced               integer not null default 0,
  replied               integer not null default 0,
  workspace             text,
  updated_at            timestamptz not null default now(),
  primary key (smartlead_campaign_id, stat_date)
);
create index on campaign_daily_stats (stat_date);
```

Mirrors `fleet_daily_stats`, keyed per campaign. Composite PK makes the writer
idempotent via `on_conflict=...&Prefer: resolution=merge-duplicates`, matching
how `_snapshot_from_blob()` already upserts.

**2 · Writer, folded into the existing scorecard sync**

`_scorecard_sync_all()` already walks every campaign on `_SCORECARD_SYNC_INTERVAL_S`.
Add a per-campaign day-wise fetch on the same walk — no new cron:

- Endpoint: `/campaigns/{id}/analytics?start_date=&end_date=` (the codebase
  already calls `/campaigns/{cid}/analytics` and `/campaigns/{n}/variant-statistics`,
  so auth, `ws_key_for_campaign()` and `_smartlead_json()` are all in place).
- Fetch a trailing 35-day window (30 shown + 5 slack for late bounce processing);
  re-upserting the whole window each pass self-heals any backfill Smartlead does.
- Rate: reuse the existing per-call sleep pattern (`_HEY_SLEEP_S` equivalent).
  At ~12 active campaigns this is ~12 extra calls per sync cycle.

**Cost note:** if the campaign count grows past ~100, split the sweep — only
campaigns with `status = ACTIVE` need daily granularity; finished ones can keep
the lifetime scorecard row.

**3 · Read path**

Extend `/api/campaign-scorecard` with an optional `?days=7|14|30`:

- absent → today's behaviour, lifetime `campaign_scorecard` (nothing breaks)
- present → `sum(sent)`, `sum(bounced)` from `campaign_daily_stats` over the
  window, same response shape so the client needs no new parsing.

**4 · Client**

Drop the `slice()`-only filtering for the list and refetch on toggle (or preload
all three windows, as `HUBCACHE` already does for the weekday presets). Then
delete these labels from all three prototypes:

- P1 — *"· whole history of each list, not the date filter above"*
- P2 — *"(each client's whole list history, not the date filter above)"*
- P3 — *"· each client's whole list history, not the date filter above"*

## Acceptance

1. Toggling 7d/14d/30d changes **both** the trend and the campaign/client rows.
2. A campaign that bounced badly last month but is clean this week drops out of
   the 7d view.
3. `?days=` absent returns byte-identical output to today.
4. Re-running the sync twice produces no duplicate rows (idempotent upsert).
5. The three "not the date filter above" labels are gone.

## Out of scope

Backfill of history predating the first sync. `campaign_daily_stats` starts
accumulating from deploy; the 35-day rolling window fills within ~5 weeks, and
Smartlead's own day-wise analytics backfills instantly for the window requested,
so the first sync populates 35 days immediately.
