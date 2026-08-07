---
name: deliverability-glance-dashboard
description: Static orchestration skill for the Navreo signals tool — redesign app/deliverability.html into a daily-glance health dashboard. Top of page = the few metrics that actually measure deliverability health (reply rate, bounce rate, emails sent/day, inbox issues) each with a 30-day trend sparkline so brewing problems are visible BEFORE they bite. Everything that should normally be zero (campaigns under 1%, SMTP fails, missing SPF/DKIM/DMARC, blacklists) stops being a permanent section and becomes a to-do item that only appears when non-zero. One fixed step list, each step with a checkable done-rule, retry caps, and a Loop Training Mode toggle. Done when a simulated email-infrastructure expert scores it 8/10+ as their daily log-in-and-spot-problems page. Use when the user says "run the glance dashboard", "simplify the deliverability dashboard", "add deliverability trends", or "/deliverability-glance-dashboard".
---

# Deliverability: Daily-Glance Health Dashboard

## ⚙ Loop Training Mode: **OFF**   ← flip this line to ON to pause at every step

**ON:** pause at EVERY step boundary and wait for the user's explicit approval
before continuing. Before starting a step, check its done-rule first — if it already
passes, report "Step N already passes, skipping" and move to the next pause. Only re-run
steps whose done-rule fails. Show what you're about to do before doing it.

**OFF (current):** run all steps end-to-end with no pauses. The done-rule checks, skip-if-passing
behaviour, and retry caps stay exactly the same — only the pauses go.

**Retry cap (both modes):** each step retries **max 3** times against its done-rule.
On cap-hit: record the step as FAILED with the reason, continue to the next step if it
doesn't depend on the failed one, and surface every FAILED step in the final report.
Never silently exceed the cap. Never declare the skill done on a cap-hit.

## Goal

The person responsible for deliverability logs into
https://navreo-signals.onrender.com/app/deliverability.html once a day and can answer,
in under 30 seconds, "is anything brewing?" Concretely:

1. **Health first.** The top of the page shows the main health indicators — reply rate,
   bounce rate, emails sent per day, inbox/domain issues — as the dominant visual element.
2. **Trends, not snapshots.** Each headline metric carries a ~30-day trend (sparkline +
   direction vs the prior week), because a bounce rate drifting 0.8% → 1.4% → 1.9% is the
   problem-before-it-arrives the user wants to catch. Today's dashboard has zero
   time-series visuals.
3. **Zero-should-be-zero sections become to-dos.** Campaigns under 1%, SMTP fails,
   missing SPF/DKIM/DMARC, blacklisted domains, etc. are exceptions, not furniture. When
   they're 0 they occupy no space (at most one "all clear" line); when non-zero they
   appear as items in Today's to-do with their existing fix actions intact.
4. **Less overall.** The Overview gets visibly shorter and calmer, not rearranged-but-
   equally-dense.

**Verification bar:** a simulated email-infrastructure expert, asked "would you use this
as your daily log-in page to spot problems before they arise?", scores it **8/10 or
higher**.

## Ground truth (verified 2026-07-10 — re-verify in Step 1, don't trust blindly)

- Working copy: `~/navreo-signals/` (the git/Render repo). There is ALSO an iCloud copy —
  after any merge, diff-check the two (memory `signals-deploy-repo`). Local dev:
  `python3 app/server.py` → `http://localhost:7901/app/deliverability.html`.
- The page is rendered entirely by `app/deliverability-tab.js` (~6,560 lines).
  `renderOverviewPanel()` (~:3708) composes the Overview in order: `renderCoach`,
  `renderVerdict`, `renderBanner`, `renderHealthStrip`, `renderFleetTiles`
  (the "Fleet by the numbers" grid, ~:2516-2594 — Reply rate, Bounce rate, Blacklisted
  domains, Missing SPF/DKIM/DMARC, DMARC enforcing…), `renderTodo`, `renderHistoryFold`.
  Three heavy sections already moved to sub-tabs (Blacklisted domains / Inbox and domain
  manager / Performance by batch, ~:1120).
- Data comes from an audit snapshot: GET `/api/deliverability/_audit` (cached
  server-side, `server.py:~7420-7460`; refresh via POST `_audit/refresh`; backend =
  navreo-email-deliverability-audit.onrender.com). The snapshot is point-in-time — there
  is NO stored history today. Candidate trend sources, in preference order:
  (a) Smartlead day-wise analytics (`get_day_wise_overall_stats` /
  campaign-analytics-by-date endpoints) — real per-day sent/reply/bounce with instant
  30-day backfill; (b) the Supabase Smartlead daily sync tables (memory
  `smartlead-supabase-daily-sync`); (c) a new daily snapshot row persisted per audit for
  fleet-level counts that Smartlead can't backfill (inbox issues, auth misses).
- Conventions that already passed panels (memory `deliverability-visual-pass`): NO
  emoji-as-severity, colour IS severity, Signals-tab language. Follow them.
- Recent shipped work that must keep working: real verify pipeline + background-jobs
  sidebar (`/api/jobs`, shell.js), glossary popovers, "Mark done" ack flow, deep links
  into the moved sub-tabs, `app_activity_log` writes.
- UX sims are agent-simulated reviews, never `preview_click` puppeteering (memory
  `signals-push-ux`).

## Steps

### Step 1 — Re-verify ground truth + prove a trend source
Confirm the bullets above against current code (line numbers drift). Then prove ONE
trend source live: call the chosen Smartlead day-wise endpoint (or query the Supabase
sync tables) and capture 30 days of real per-day `{date, sent, replies, bounces}` for
the fleet. Decide what fleet-level counts (inbox issues, auth misses, blacklists) need a
new daily snapshot row because they can't be backfilled, and name the table it will go in.
- **Done-rule:** you can show (a) the current Overview section list with live line
  numbers, (b) a captured real 30-day per-day series from the chosen source, and
  (c) a one-paragraph data plan naming exactly which metric comes from which source.

### Step 2 — Backend: `/api/deliverability-trends` (`app/server.py`)
One endpoint the page can call: GET `/api/deliverability-trends?days=30` →
`{series: {sent: [...], reply_pct: [...], bounce_pct: [...], issues: [...]}, asof}` —
per-day points, server-cached (~1h TTL) so a page load never fans out to Smartlead.
If Step 1 chose a snapshot table for non-backfillable counts: write one row per audit
refresh (piggyback on the existing `_audit` cache fill — do NOT add a new cron; the
edge-function schedule rule in memory `signals-activity-ledger` applies).
- **Done-rule:** `curl localhost:7901/api/deliverability-trends` returns ≥14 real daily
  points for sent/reply/bounce with values matching a spot-check against Smartlead; a
  second call within the TTL returns instantly from cache.

### Step 3 — Frontend: health header with trends (`app/deliverability-tab.js`)
Replace the top of the Overview with a single **health header**: the verdict line plus
exactly four KPI cards — **Reply rate**, **Bounce rate**, **Sent / day**, **Inbox
issues** (dead + blocked + auth-missing rolled up). Each card: big current value,
severity colour from the existing thresholds (reply ≥1% good; bounce <2% good, ≥3% bad),
a 30-day sparkline (inline SVG, no chart library), and a delta vs the prior 7-day
average ("↑ 0.3pt vs last week") whose colour reflects whether the direction is good
for THAT metric (bounce ↑ = red, reply ↑ = green). Threshold shown as a faint reference
line on the sparkline so drift toward the limit is visible before it's crossed.
Sparklines degrade gracefully (card still renders, no error) if the trends endpoint has
<7 points or fails. Read the `dataviz` skill before drawing the first sparkline.
- **Done-rule:** on localhost, the four cards render above everything else with real
  sparklines whose last point equals the card's current value; killing the trends
  endpoint still renders the cards minus sparklines; zero console errors.

### Step 4 — Demote zero-state sections to to-dos
Go through the Overview below the health header and reclassify:
- **Exception content** (campaigns under 1%, SMTP/connection fails, missing
  SPF/DKIM/DMARC, DMARC-enforcing gaps, blacklisted domains, sending-deviation flags):
  remove their permanent tiles/folds from the Overview. When any count is non-zero it
  becomes an item in **Today's to-do** (existing card style) carrying the SAME fix
  actions, glossary popovers, and deep links the tile had. When all are zero, one quiet
  "All checks clear — SPF/DKIM/DMARC, SMTP, blacklists" line replaces them.
- **Keep** (below the header, in this order): Today's to-do, the coach/banner only when
  they carry a non-default message, Recent actions fold. Everything else that survives
  must justify itself as either a health indicator (header) or an action (to-do).
- Nothing is deleted from the codebase that the sub-tabs or verify pipeline still use —
  this step moves rendering, it does not remove capabilities.
- **Done-rule:** with a healthy mock dataset the Overview is ≤2 screens at 1440×900 and
  contains no tile whose value is a zero; with a broken mock dataset every previously
  surfaced problem still appears (as a to-do item) with its fix action clickable; the
  existing e2e/deliverability flow tests still pass.

### Step 5 — Expert panel (the user's stated verification)
Run a simulated review panel: 3 email-infrastructure-expert personas (agent-simulated,
not preview_click), each given the daily-driver framing: "You log in every morning to
spot deliverability problems before they arise. Score 1-10 and name what you'd miss."
Feed them the page in BOTH states (healthy fleet, brewing-problem fleet — e.g. bounce
trending 0.9→1.7% over 10 days must be called out by the header). Average must be
**≥8/10** and no persona may report missing a brewing problem the old dashboard caught.
Iterate on the specific complaints (max 3 iterations per the retry cap), re-running only
the failing personas.
- **Done-rule:** panel average ≥8/10, every persona confirms the brewing-bounce scenario
  is spottable in <30s, and no previously-catchable problem class is invisible.

### Step 6 — Deploy
Commit in `~/navreo-signals`, push to Render, wait for the deploy, verify
`https://navreo-signals.onrender.com/api/deliverability-trends` returns 200 with real
points and the live page shows the health header. Then diff-check the iCloud copy
against the repo and reconcile (memory `signals-deploy-repo`).
- **Done-rule:** live URL shows the four trend cards with data; verify buttons and the
  jobs sidebar still work on production; repo↔iCloud diff for touched files is empty.

## Final report (always, both modes)
One summary: steps passed/skipped/FAILED, the panel scores with each persona's one-line
verdict, before/after Overview length (screens at 1440×900), which sections were demoted
to to-dos, the trend data source chosen, and anything deferred.

## Hard don'ts
- Never remove a problem's fix action while demoting its section — every exception must
  remain actionable from the to-do item it becomes.
- Never add a new cron/scheduler for snapshots — piggyback on the existing audit refresh
  (single-writer rule, memory `signals-activity-ledger`).
- Never use emoji as severity; colour is severity (memory `deliverability-visual-pass`).
- Never pull in a charting library — sparklines are inline SVG.
- Never break the shipped verify pipeline, jobs sidebar, ack flow, or sub-tab deep links.
- Never use preview_click to simulate the expert panel.
- Never exceed a retry cap or report done while any done-rule fails.
