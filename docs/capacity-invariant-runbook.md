# Capacity ≥ Sent — Runbook

Why "amount sent" could exceed the "hard" daily capacity on the analytics hub, what
was fixed, how to verify, and what still needs an authed DB session.

## The finding (audit)

The mailbox cap **is** a hard limit inside Smartlead. The capacity **number on the
chart** is a separately reconstructed estimate, and it was being recorded/aligned in
ways that land *below* the day's real sends — so `sent > capacity` was a
capacity-data defect, not (usually) real over-sending. Eight mechanisms, dominant
three: UTC-vs-Smartlead-timezone day mismatch; historical capacity joined to *today's*
roster (detached boxes' past sends lose their ceiling); and the live pause-aware
"today" anchor dropping the ceiling below already-banked sends. Full contract:
[capacity-sent-metric-contract.md](capacity-sent-metric-contract.md).

## What shipped (code-only, live now after deploy)

1. **High-water writer** (`_cap_hw_merge`, `_cap_blob_upsert`). Each day's per-workspace
   and per-client capacity is now a high-water merge with append-only provenance
   `snaps` (`{cap, asof, src}`), tracking `cap_min` (lowest positive authorized cap in
   force) and `cap_max` (high-water). A later same-day snapshot the tiering engine
   *lowered* can no longer erase an earlier higher ceiling sends went out under. Sent is
   never an input, so capacity can never silently rise to absorb an over-send.
2. **Today anchor** (`fleet_capacity_get`). The live pause-aware pool now `max()`-es
   with the recorded value, so a late pause can't retroactively drop today's ceiling
   below banked sends.
3. **Invariant check** (`capacity_invariant_check`, `GET /api/capacity-invariant`).
   Per `(client, day)` vs Smartlead daily sent:
   - `clean` sent ≤ `cap_min` (safe under any intraday ordering — the ONLY clear).
   - `suspect` `cap_min` < sent ≤ `cap_max` — daily totals can't prove/disprove an
     intraday breach; **flagged, never cleared**.
   - `violation` sent > `cap_max` — no authorized cap explains it → real enforcement
     defect.
   - `no_capacity` sent but no snapshot → a missed/failed writer run.
   High-water (display) never clears a day; only `cap_min` does — so the check cannot
   hide a genuine over-send.
4. **Ongoing detection** — `client_windows_cron_refresh` (every ~3h) runs the check and
   logs `[capacity-invariant] NOT CLEAN …` with top violations to stderr.

## How to verify (Step 8 — needs Supabase/Smartlead auth)

    curl -s "$SIGNALS/api/capacity-invariant?days=30" | jq '{ok, counts}'

- `ok:true` with `counts.violation:0, suspect:0, no_capacity:0` → invariant holds.
- Any `violation` row is a real over-send to investigate in Smartlead (its `snaps` show
  the authorized caps that day). `suspect`/`no_capacity` rows are data-quality gaps, not
  proof of over-sending.
- Independence: the check reads capacity from the stored blob and sent straight from the
  `client_windows` Smartlead series — not the writer's own intermediate output.

## Fix 2 — per-client capacity attribution undercount (2026-08-22)

Confirmed cause of the Amplifyy `sent > capacity` flags: `_navreo_cap_from_sweep`
**dropped** every mailbox that was on the client's active campaigns (present in the
Smartlead membership sweep, which already stores each box's real `message_per_day`) but
**absent from the pause-aware mirror** (`box_caps`) — `if cap is None: continue`. Mirror
sync gaps therefore silently undercounted a client's capacity. Amplifyy physically sent
7,203 in a day (a lower bound on true capacity) while its recorded per-client capacity
read 5,590.

Fix: keep the mirror cap as primary; when a swept box is missing from the mirror, fall
back to its Smartlead cap from the sweep instead of dropping it. Pause-safe — a
paused/parked mailbox reports `message_per_day = 0` in both the mirror and the sweep, so
the `cap <= 0` skip drops it; only a mirror-absent box with a POSITIVE cap (confirmed
active) is added. Improves today + future per-client capacity; already-snapshotted
historical days keep their recorded value.

## Deferred — needs the user's authed DB session (Steps 7 + remaining root causes)

These need live Supabase (OAuth) and/or a migration + backfill:

1. **Timezone re-key (#1).** Change the writer day key from UTC `date.today()` to the
   Smartlead **account-timezone** date, so capacity and sent share one 24h window.
   Backfill historical blob days accordingly.
2. **As-of-day roster (#2).** `fleet_capacity_daily.sql` joins `mailbox_stats_daily` to
   **current** `mailboxes.campaign_count > 0`. Change to the roster **as of each
   stat_date** (needs a per-day membership source or a `campaign_count` history) so a
   box that sent then but is detached now still contributes to that day's ceiling.
3. **Historical backfill.** Re-emit the `client_capacity_hist_v1` blob for the audited
   range with the corrected key + roster, dry-run first (row-level diffs, old→new,
   run id), then apply idempotently once.
4. **SUSPECT → exact.** To upgrade `suspect` to `clean`/`violation`, collect
   per-snapshot **cumulative sent at each `asof`** (intraday checkpoints) so sends are
   checked against the cap in force at send time, not the day-wide bound.

## Run 1 — 2026-08-22 (live service-role REST)

First live invariant check, 30d, against production blobs `client_capacity_hist_v1`
and `client_windows`: **clean 60 · suspect 0 · violation 6 · no_capacity 94** (after a
2-row backfill of KRG+Asteri 2026-07-23 reconstructed from `fleet_capacity_daily`).

**6 real violations (sent > every authorized cap that day):**

| Client | Day | Sent | Cap | Excess |
|---|---|---|---|---|
| Amplifyy | 2026-08-17 | 7,203 | 5,590 | +1,613 (+29%) |
| Amplifyy | 2026-07-28 | 5,992 | 4,496 | +1,496 (+33%) |
| Amplifyy | 2026-07-27 | 5,921 | 4,498 | +1,423 (+32%) |
| Amplifyy | 2026-07-29 | 5,369 | 4,496 | +873 (+19%) |
| Amplifyy | 2026-07-24 | 4,792 | 4,290 | +502 (+12%) |
| KRG | 2026-08-21 | 2,559 | 2,441 | +118 (+4.8%) |

- **Amplifyy (5 days, +12–33%)** — far beyond ~1% TZ drift → a likely REAL over-send.
  **OPEN ITEM:** in Smartlead, pull Amplifyy's campaigns' per-mailbox
  `message_per_day` and per-day sends for those dates. Two outcomes: (a) mailboxes
  were attached to Amplifyy that the per-client capacity snapshot missed → an
  attribution data-fix; or (b) boxes genuinely sent above cap → a real deliverability
  incident (Amplifyy is pay-per-meeting; over-sending burns domains). Amplifyy is a
  navreo sub-client, so its per-client history is NOT reconstructable from stored data.
- **KRG +4.8%** — small enough to be roster/TZ drift; low priority.

**94 no_capacity** — days with sent but no capacity snapshot, because
`mailbox_stats_daily` itself has no rows for them (the sync-death gaps: Jul-30, Aug 4–8,
10, 12–15, 18–20). Not reconstructable without re-pulling historical per-box caps from
Smartlead (which may not serve them retroactively). These are a known DATA GAP, not
proof of over-sending — left flagged rather than filled with a guess that could mask a
real breach.

## Ownership / rerun

- Writer crons: `sync_mailboxes.py` (04:30 UTC, all workspaces),
  `run_google_caps.py` (05:15), `run_outlook_caps.py` (06:00) — each high-water merges.
- Detection: automatic in the 3-hourly `client_windows_cron_refresh`.
- Manual check any time: `GET /api/capacity-invariant?days=N`.
