---
name: campaigns-perf-leads-grid
description: Static orchestration skill for the Navreo signals tool (app/campaigns.html + app/server.py). Two surfaces — (1) rebuild the homepage "Performance" card into a single minimalist five-series dual-axis graph (Emails sent solid, Leads added dashed, Reply rate, Positives, Meetings) with bounce dropped, a compact stat row, and working campaign + date-range filters, backed by a real per-day/per-campaign perf endpoint; (2) turn BOTH Leads tabs (app-signal + external Smartlead/HeyReach people) into a read-only Airtable-style grid with search, sort, per-column filter, column show/hide, and pagination. One fixed step list, each step with a checkable done-rule, a retry cap, and a Loop Training Mode toggle (ON by default). Use when the user says "run the campaigns perf + leads grid ship", "rebuild the performance graph", "add the leads grid", or "/campaigns-perf-leads-grid".
---

# Campaigns: Five-Series Performance Graph + Airtable-Style Leads Grid

Static orchestration loop. The steps below are fixed; each has a done-rule; Loop Training Mode controls whether you pause between them. Files: `app/campaigns.html` (all UI) and `app/server.py` (backend). Live host: `https://navreo-signals.onrender.com`. Local dev: `python3 app/server.py` → `http://localhost:7901/app/campaigns.html`.

---

## ⚙️ LOOP TRAINING MODE  →  **ON** (default)

Flip it by editing this one line:

    LOOP_TRAINING_MODE = OFF       # ON = approve every step · OFF = run autonomous

**When ON (default)**
- Pause at the end of **every** step and wait for my explicit approval before starting the next.
- Before running a step, check its done-rule **first**. If it already passes, say "Step N already passes, skipping" and move to the next pause. Do not re-do work that's already green.
- Only (re-)run steps whose done-rule fails.
- Show what you're about to change before you change it.
- Retry cap still applies (below). Never loop a step forever.

**When OFF**
- Run all steps end-to-end, no pauses.
- Still check every step's done-rule, still skip already-passing steps, still honour the retry cap. Report at the end, not between steps.

**Retry cap (both modes):** any single step retries **max 3** times against its done-rule. On cap-hit: stop that step, record it FAILED with the reason, continue to the next step **if** it doesn't depend on the failed one, and surface every FAILED step in the final report. Never silently exceed the cap. Never declare the skill done while any done-rule fails.

---

## THE GOAL

Two user-visible outcomes on the rendered page (not source):

1. **Homepage top = one minimalist five-line graph.** A single hero graph plotting FIVE per-day series on a **dual axis**: **Emails sent** (solid main line, left/count axis), **Leads added** (dashed, left/count axis), **Reply rate** (right/% axis), **Positives** and **Meetings** (plotted so they stay visible against the thousands-scale sent line). **Bounce rate is gone** from this graph (deliverability.html still owns bounce). Any series with no daily data draws as a **labelled ABSENT line** — never a fabricated zero (reuse the existing null-gap logic). Below the graph: **one compact stat row** (leads · sent · reply % · positives · meetings). **Removed:** the plain-English verdict line, the gap-explainer paragraph, and the separate "Totals for the campaigns you run in this tool" collective strip. **Two controls above the graph:** a single-select **campaign dropdown** (All + each campaign) and a **date-range control** (7 / 30 / 90 / custom) — both re-query and redraw.

2. **Both Leads tabs = a read-only Airtable-style grid.** The app-signal leads tab AND the external Smartlead/HeyReach "people" tab each render their rows as a grid with: **search-rows box, column Sort, per-column Filter, column show/hide, and pagination.** Columns adapt to whatever fields each flavor carries. The grid is **read-only for lead data** — no lead mutations, no sends, no deletes introduced by the grid. The external tab stays read-only; the app-signal tab keeps its existing send/verdict actions working, but the grid rebuild adds **no** new writes.

**Done means all six Verification checks (a–f) below pass on the real rendered page.** Not source. Not a grep of deployed JS. The rendered page is the only proof of done.

---

## GROUND TRUTH  (anchors verified from the brief — line numbers DRIFT, re-verify every one in Step 1)

- **Deploy gotcha (non-negotiable):** the iCloud copy of the app silently **REVERTS** edits. Every interruption/save is effectively a redeploy. After any change, deploy and confirm on the live host (or the live dev server) — a local-file grep is a deploy check only, never done-evidence. (memory: `browser-verify-before-done`, `signals-deploy-repo`.)
- **Homepage Performance card / chart:** `campaigns.html` — `perfChart` ~L1514, card ~L2044. This is where the graph, the verdict line, the gap paragraph, and the collective-totals strip live.
- **Backend perf source:** `server.py` — `perf_daily()` ~L5559 and `rpc/perf_daily_series` ~L5575. **Today they return only `sent` / `reply_rate` / `bounce_rate`, fleet-wide.** They do **not** emit daily `leads_added`, `positives`, or `meetings`, and do **not** accept a per-campaign filter. Both gaps must be closed in Step 2.
- **Leads tabs:** `campaigns.html` — external Smartlead/HeyReach "people" tab ~L763; app-signal leads tab ~L802. App-signal fields: **name / title / company / domain / linkedin_url / country / email / icebreaker** (exact match to the reference screenshot). The external tab is already read-only.
- **Data sources for the new daily series (source each from its real store — nothing estimated):**
  - **Leads added** — per day from `signal_leads` / `contact_history` (day the lead was added), scoped to the campaign when filtered.
  - **Positives** and **Meetings** — from the **same Supabase sources the scorecard / `optimiser_notifications` already read** (do not invent a new store; find where the scorecard already computes these and group them by day).
- **Null-gap / absent-line pattern already exists** in the current chart code — keep it as the mechanism for the labelled ABSENT line. Do not replace it with zeros.

---

## THE STEPS

### Step 1 — Re-verify ground truth
Open the current code and confirm every anchor above (line numbers drift). Specifically pin down: (a) exact line of `perfChart` + the card, and where the verdict line / gap paragraph / collective-totals strip render; (b) the current `perf_daily()` return shape and the `perf_daily_series` RPC signature; (c) the exact per-day query the scorecard/`optimiser_notifications` already use for **positives** and **meetings**, and the store + date column for **leads added** (`signal_leads` / `contact_history`); (d) the existing null-gap logic in the chart; (e) the two Leads-tab render paths and the app-signal tab's existing send/verdict handlers.
- **Done-rule:** you can name the file+line for the chart, the verdict/gap/collective blocks, `perf_daily()` + the RPC, the real positives/meetings/leads-added queries, the null-gap code, and both leads-render paths — each confirmed against current source, not this doc.

### Step 2 — Backend: per-day, per-campaign perf endpoint (`app/server.py` + RPC)
Extend the perf backend so it emits daily arrays for **all five** series and accepts filters:
1. Add daily **`leads_added`**, **`positives`**, **`meetings`** arrays alongside the existing `sent` / `reply_rate` (keep `bounce_rate` available for deliverability but the homepage graph won't plot it), each sourced from its real store (Step 1(c)) — **nothing estimated**.
2. Add a **per-campaign filter** (new `p_campaign` param on the RPC or the equivalent in `perf_daily()`; `All` = no filter) and a **date-range** (start/end or days-back + custom).
3. Expose it at **`/api/perf-daily`** honouring both `campaign` and the date params.
4. A metric with **no daily rows** returns an explicit null/absent marker per day (so the frontend can draw the labelled gap) — **never a zero-filled array**.
- **Done-rule:** `curl "localhost:7901/api/perf-daily?campaign=<id>&days=30"` returns JSON carrying daily `leads_added`, `positives`, and `meetings` arrays plus `sent` and `reply_rate`; changing `campaign` changes the numbers; changing the date param changes the window length; and the returned counts **match a direct Supabase/RPC query** for the same campaign+window (verify against the DB, not against the graph).

### Step 3 — Frontend: rebuild the graph + controls + stat row (`app/campaigns.html`)
1. **Five-series dual-axis chart** at `perfChart`: **sent** = solid main line + **leads-added** = dashed line on the **left/count axis**; **reply rate** on the **right/% axis**; **positives** + **meetings** plotted so they stay visible against the thousands-scale sent line (their own scaling/axis as needed — the point is legibility, not a fabricated scale). **Remove bounce** from this graph entirely.
2. **Absent = labelled gap:** any series the endpoint marks absent for a day renders via the existing null-gap logic as a **labelled ABSENT line**, never a zero.
3. **Strip the clutter:** delete the plain-English **verdict line**, the **gap-explainer paragraph**, and the separate **"Totals for the campaigns you run in this tool" collective strip**.
4. **One compact stat row** under the graph: **leads · sent · reply % · positives · meetings**.
5. **Two controls above the graph:** single-select **campaign dropdown** (All + each campaign) and a **date-range control** (presets 7 / 30 / 90 + custom). Changing either re-queries `/api/perf-daily` and redraws.
- **Done-rule:** on localhost the graph shows exactly the five series (sent solid, leads-added dashed, reply rate, positives, meetings), no bounce; the verdict line / gap paragraph / collective strip are gone; the compact stat row is present; changing the campaign dropdown redraws to that campaign's series (visibly differs from All) and changing the range changes the window; zero console errors.

### Step 4 — Leads tabs: read-only Airtable-style grid (`app/campaigns.html`)
Rebuild BOTH leads flavors as a grid, columns adapting to each flavor's real fields:
- **App-signal tab** (~L802): columns name / title / company / domain / linkedin_url / country / email / icebreaker (match the reference screenshot in spirit).
- **External Smartlead/HeyReach "people" tab** (~L763): columns = whatever fields that flavor carries.
- **Grid capabilities (both):** search-rows box · column **Sort** · per-column **Filter** · column **show/hide** · **pagination** (row-range pager).
- **Read-only for lead data:** the grid introduces **no** lead mutations, sends, or deletes. External tab stays read-only. The app-signal tab's existing **send/verdict actions keep working**, but the grid rebuild adds no new write paths.
- **Done-rule:** on localhost both tabs render as a grid; search / sort / per-column filter / column toggle / pagination all function; the app-signal send/verdict controls still work; no grid interaction issues a write to lead data (confirm by watching the network tab — no unexpected POST/PUT/DELETE on a grid action).

### Step 5 — Deploy + iCloud reconcile
Deploy to the live host. Then **diff-check the iCloud copy against the deployed repo** and reconcile — the iCloud copy reverts edits, so confirm the live host actually serves the new code (memory: `signals-deploy-repo`).
- **Done-rule:** `https://navreo-signals.onrender.com/api/perf-daily?...` returns 200 JSON with the new arrays; the deployed `campaigns.html` serves the new graph + grid; repo↔iCloud diff for the touched files is empty.

### Step 6 — Live proof (the user's six-part Verification — ALL on the rendered page)
Prove every one of these on the **real rendered page** (live host or live dev server), never from source:
- **(a)** Homepage graph shows exactly the five series — **sent solid, leads-added dashed**, plus reply rate, positives, meetings — with **bounce gone**.
- **(b)** Hit **`/api/perf-daily`** directly and confirm the JSON carries daily **leads_added, positives, meetings** arrays and honours the **campaign + date** params — with the numbers **matched against a direct Supabase/RPC query**, not read back off the graph.
- **(c)** Changing the **campaign dropdown** redraws the graph to that campaign's series (**differs from All**); changing the **date range** changes the window.
- **(d)** The top **no longer** renders the verdict line, the gap paragraph, or the collective-totals strip — and the **one compact stat row** is present.
- **(e)** Force/observe a metric with **no daily rows** and confirm it draws as a **labelled absent line, never a zero**.
- **(f)** On **BOTH** the app-signal leads tab and the external read-only leads tab, interactively confirm **search, sort, per-column filter, column show/hide, and pagination** all work on the live grid, and that **no grid action writes lead data**.
- **Done-rule:** all six (a–f) pass, evidenced with a browser snapshot/screenshot per surface and the direct-DB comparison for (b). All six, or it isn't done.

---

## HOW TO RUN

1. Read the LOOP TRAINING MODE line. If **ON**, work one step at a time and stop for approval after each; skip any step whose done-rule already passes. If **OFF**, run all six in order without pausing.
2. For each step: make the edits, then check the done-rule — for backend steps `curl`/RPC + a direct DB comparison; for UI steps reload the preview and check console + a browser snapshot. Retry up to 3× on failure, then mark FAILED and continue.
3. Because iCloud reverts edits, treat every browser-observable claim as unproven until you've reloaded the deployed/dev page and seen it. Never accept a local-file grep as done-evidence.

## OVERALL DONE-RULE

- Graph: single five-series dual-axis chart (sent solid, leads-added dashed, reply rate, positives, meetings), bounce gone, absent-as-labelled-gap, compact stat row, working campaign + date filters — all verified on the rendered page.
- Backend: `/api/perf-daily` emits real daily leads_added/positives/meetings and honours campaign + date, numbers matched to a direct DB query.
- Leads: both tabs render a read-only searchable/sortable/per-column-filterable/column-toggle-able/paginated grid; no grid action mutates lead data.
- All six Verification checks (a–f) pass on the real rendered page.
- Final report: one line per step — DONE / SKIPPED (already passed) / FAILED (with reason) — plus the (a–f) evidence.

## HARD DON'TS

- **Never fabricate a datapoint** — an absent metric is a labelled gap, never a zero.
- **Never leave bounce on the homepage graph** (deliverability.html keeps bounce; this graph drops it).
- **Never let the leads grid mutate lead data** — no sends/deletes/edits introduced by the grid rebuild; keep the app-signal tab's existing actions but add no new writes.
- **Never trust a local-file grep as proof** — the rendered page (live host or live dev server) is the only done-evidence.
- **Never estimate positives / meetings / leads-added** — source each from its real Supabase store.
- **Never exceed a retry cap, and never report done while any (a–f) check fails.**
