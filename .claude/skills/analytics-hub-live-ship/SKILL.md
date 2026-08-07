---
name: analytics-hub-live-ship
description: Static orchestration skill — take the chosen P3 "Funnel" analytics hub prototype (app/prototypes/analytics-hub-p3.html) live on real data, make the daily lilly-optimiser run generate its insights, and REPLACE app/deliverability.html with it (deliverability functions — especially "Today's to-do" — integrated). Minimal design throughout; if it needs explaining, it's too complicated. Judged by a simulated panel of 5 non-technical founders and sales leaders at a 9/10 bar on actionable insights, easy to digest, and beauty of design. Use when the user says "take the analytics hub live", "wire P3 to real data", "replace the deliverability page", or "/analytics-hub-live-ship".
---

# Analytics Hub — Live Ship

## Loop Training Mode — TOGGLE (flip this line to change behaviour)

**Loop Training Mode: OFF** ← flipped 2026-07-27 per Bjion ("go, training off"). Change to `ON` to pause at every step.

- **ON**: pause at EVERY step and wait for Bjion's explicit approval before
  continuing. Before starting a step, check its done-rule first — if it already
  passes, report "Step N already passes, skipping" and move to the next pause.
  Only re-run steps that fail. Show what you're about to do before doing it.
- **OFF**: run all steps end-to-end with no pauses, but still check every
  done-rule and respect the retry cap.
- **Retry cap (both modes)**: max **3 retries per step**. On cap-hit, HALT that
  step, record it FAILED with honest scores/reasons, and surface it in the final
  report. Never inflate a score to pass. Never loop forever.

## Goal

The P3 Funnel page, live on real data, IS the analytics page — and it replaces
`app/deliverability.html` outright, absorbing the deliverability functions
(above all **Today's to-do**) so nothing users could do there is lost. A
non-technical founder opens it and — zero training — sees what's working, what
isn't, and what to do today to book more meetings. Language a 16-year-old
understands. Less explanation, more intuitive design: **if it needs explaining,
it's already too complicated.** The daily lilly-optimiser run feeds it fresh
insights so the page never depends on someone remembering to run anything.

## Fixed context (verified 2026-07-27 — re-verify in Step 1, don't trust blindly)

- Source of truth is `~/navreo-signals` (push to `main` → Render auto-deploy,
  ~1–2 min). The iCloud copy is DEPRECATED — never edit it. Live verify via the
  `navreo_session` cookie mint + `/api/version` poll recipe (memory:
  `signals-live-verify-recipe`). Other sessions push concurrently — check
  `git log origin/main..` before reasoning about a push range.
- **P3 is THE prototype** (Bjion ruling 2026-07-27): iterate only
  `app/prototypes/analytics-hub-p3.html`. Shape, top to bottom: slim verdict
  header → hero LINE GRAPH (daily Sent/Replies/Interested/Meetings/Bounces,
  legend-chip show/hide, Sent off by default, presets 7/14/30d, default 30d) →
  question sections starting "Where can we improve the most?" (funnel + orange
  leak) → other question lanes → verbatim inbox & domain manager table. Client
  filter chips (All · Arnic · Qwintiq) govern everything except that table.
  Controls: client-side filter only, ≤3 date presets, 30-day cap.
- P3 currently runs on inline MOCK data (banner says so) — zero API calls today.
- `app/deliverability.html` is a thin shell; the real page lives in
  `app/deliverability-tab.js` (~8k lines): "Today's to-do" (`renderTodo`,
  `dlv-todo-*`, mark done/undone via `logAction`), the inbox & domain manager
  table, warmup/verify/dismiss actions — all against live `/api/*` endpoints.
- Insights layer: Supabase `campaign_insights` (scope + insight_key + payload,
  live/superseded/expired, `expires_at`, per-user `insight_dismissals`). The
  lilly-optimiser skill owns the cache/fingerprint/supersede/expiry contract
  and the SPECIFICITY CONTRACT for act lines — this skill extends that
  contract, never forks it. The server renders insights via `/api/cockpit/*`
  (SWR-cached `_cockpit_insights`). Daily pipeline: pg_cron → pg_net →
  `POST /api/cron/pull-all` (`cron_pull_all`, mirrors `run_daily.py`).
- House rules: no emoji in UI; colour IS severity; charts are inline SVG, no
  libraries; read `dataviz` + `navreo-design-system` before the first line of
  markup; panels are agent-simulated, never preview_click puppeteering.

## Steps

### Step 1 — Baseline map
Read `analytics-hub-p3.html` end to end; map EVERY widget/number on it to its
real source (existing `/api/*` endpoint, Supabase table, or "missing — needs a
new read-only endpoint"). Read the to-do + table code paths in
`deliverability-tab.js` and list every user-facing deliverability function the
replacement must keep. Check `campaign_insights` for any scope/key already
generating what this page needs — the user suspects some insights may already
exist; find out instead of assuming.
**Done-rule**: a ≤1-page note with (a) every P3 widget → named real source,
(b) the deliverability function inventory, (c) a verdict per insight: already
generated vs must be added to the daily run.

### Step 2 — Wire real data
Replace P3's mock fixture with live fetches. Reuse existing endpoints first;
add only read-only endpoints in `server.py` where the map says one is missing.
Hero graph on the real day-wise series; funnel on real pipeline counts; client
chips filter on the real client mapping; insight slots render live
`campaign_insights` rows. Remove the mock banner. Loading and empty states are
designed, not apologised for — no spinners with paragraphs.
**Done-rule**: page loads on real data at 1440×900 with zero console errors;
every number back-solves against its source endpoint; client chips and date
presets filter correctly; no production writes from render.

### Step 3 — Insights on the daily run
For each Step-1 "must be added" insight: extend the lilly-optimiser daily run
(SKILL.md + whatever the cron pipeline executes) to generate it into
`campaign_insights` under an analytics-hub scope, obeying the existing
contract verbatim — fingerprint reuse, supersede-not-stack, minimality caps,
`expires_at`, per-user dismissals, specificity contract on every act line.
Skip entirely if Step 1 found everything already generated.
**Done-rule**: one optimiser run leaves live rows the page renders; an
immediate second run reuses the cache (no duplicate rows); expired/stale rows
never render.

### Step 4 — Absorb deliverability + replace the page
Integrate **Today's to-do** (count badge, mark done/undone, action logging —
against the same live endpoints) and the verbatim inbox & domain manager table
into the P3 page, placed per the P3 shape. Then make `app/deliverability.html`
serve the new page; old bookmarks and hash routes land somewhere sensible, no
dead ends. Keep it minimal: absorbing functions must not import explanation —
if a deliverability feature needs a paragraph to survive the move, redesign it.
**Done-rule**: every function from Step 1's inventory works on the new page
(to-do actions verified against the live API); the old URL shows the new page;
the table markup is byte-identical to production; nothing on the page needs
explaining.

### Step 5 — Founder panel
Spawn 5 simulated panelists as subagents: **3 non-technical founders** (do
their own outreach, allergic to dashboards) and **2 sales leaders** (judge
tools by whether their team would open them daily). Scenario: *"Five minutes
before your next call you open this page. What's working, what isn't, and what
will you do today to book more meetings?"* Each scores the page 1–10 on
**actionable insights**, **easy to digest**, **beauty of the design**, plus
the single worst moment. If a panelist had to ask what anything means,
easy-to-digest caps at 8. Fix worst moments and re-panel (a retry, max 3).
Over-simplification that hides a needed answer is a defect too.
**Done-rule**: 9/10+ on all three axes from all five panelists. Cap-hit =
FAILED-BAR with honest final scores; never inflate.

### Step 6 — Deploy + verify live
Push to `main` (`git fetch` + ff-only merge first; stage only this loop's
files; confirm the diff is exactly this work). Poll `/api/version` until the
serving commit matches, then cookie-fetch the live page and confirm real data
renders and the to-do responds. Deliver the report in chat: live URL, panel
scorecard, what the daily run now generates, and anything FAILED at cap.
**Done-rule**: live URL serving the new page on the pushed commit, verified
with the cookie recipe, report delivered in chat.

## Done-rule (whole loop)

DONE when the live `deliverability.html` URL serves the P3 analytics page on
real data with the to-do and table fully working, the daily lilly-optimiser
run generates its insights (or Step 1 proved it already did), the panel bar is
met (or cap-hit honestly reported as FAILED-BAR), and Step 6's report is
delivered.

## Hard don'ts

- Never resurrect P1/P2/P4/P5 — P3 only.
- Never redesign, restyle, or "improve" the inbox & domain manager table.
- Never add explainer paragraphs, study-me legends, or tooltips required to
  understand anything — fix the design instead.
- Never use a chart library, emoji in UI, or jargon a 16-year-old wouldn't get.
- Never fork the campaign_insights contract — extend lilly-optimiser's rules.
- Never delete deliverability functions to hit "minimal" — integrate or
  redesign, and flag to Bjion anything that truly should die.
- Never simulate the panel with preview_click puppeteering.
- Never exceed a retry cap or report done while any done-rule fails.
- Never edit the iCloud copy of the repo.
