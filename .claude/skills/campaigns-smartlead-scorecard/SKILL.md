---
name: campaigns-smartlead-scorecard
description: Static orchestration skill that puts a Smartlead-style performance scorecard on the Navreo signals CAMPAIGNS LIST page (the "Signal campaigns." landing view, renderList() in app/campaigns.html) — a per-campaign stat block for every campaign (completion ring + coloured stat columns) showing six metrics, plus a collective all-campaigns summary strip across the top with the same six aggregated into Smartlead-style tiles and at least one over-time trend line. The six metrics are completion %, emails sent, reply rate, emails-sent-per-positive-reply (ratio e.g. "1 per 180"), meetings booked, and bounce rate. Reuses the existing velocityChart(rows, srcs) helper, the 4-stat funnel pattern, and destLogo(kind); adds only read-only aggregates to app/server.py. Meetings has no confirmed data source — it MUST be pinned in Step 1 or gated with a "no source" state, never faked. One fixed step list, each with a checkable done-rule, retry caps, and a Loop Training Mode toggle (ON by default). Use when the user says "build the campaigns scorecard", "add the Smartlead-style stats to the campaigns page", "put per-campaign metrics on the list view", "show completion/reply/bounce per campaign", or "/campaigns-smartlead-scorecard".
---

# campaigns-smartlead-scorecard

Put a **Smartlead-style performance scorecard** on the signals **campaigns list page** — the "Signal campaigns." landing view rendered by **`renderList()` in `app/campaigns.html`**. Every metric is read from Smartlead's own numbers. **Nothing is ever fabricated.**

Two pieces, both styled after Smartlead's own layout:
- **Per-campaign stat block** for every live campaign — a completion **ring** on the left and **coloured stat columns** (numerals with sub-percentages) on the right, exactly the way Smartlead renders a campaign row.
- **Collective summary strip** across the **top** of the list — the same metrics aggregated across every campaign into Smartlead-style **stat tiles**, plus **trend lines** showing how the collective numbers move over time (Smartlead's "Performance Metrics" tiles-plus-chart dashboard).

Six metrics, both places:
1. **Completion %** — shown as the ring.
2. **Emails sent** — count.
3. **Reply rate** — %.
4. **Sends per positive reply** — `emails sent ÷ positive replies`, shown as a ratio, e.g. **"1 per 180"**.
5. **Meetings booked** — count (see the meetings gate, Step 1).
6. **Bounce rate** — %.

No per-campaign filter control is needed on the collective strip — it always aggregates all campaigns.

## Files & where the numbers come from

- `app/campaigns.html` — all UI. The list view is `renderList()`.
- `app/server.py` — add a small **read-only** aggregate here only if a metric can't be computed client-side. Five of the six metrics are Smartlead-native and already surfaced in `server.py` **around line 2222**: `sent` / `positive` / `replied` / `completion_pct` / `reply_rate`. Bounce rate is Smartlead-native too — read it, don't invent it. **Meetings is the exception** (Step 1).
- **Reuse, don't reinvent:** the per-campaign Overview already has `velocityChart(rows, srcs)` and a **4-stat funnel** pattern — copy those for the collective trend lines and tiles rather than writing new chart code. Destination logos come from **`destLogo(kind)`**.

## 🚨 DEPLOY-REPO GOTCHA (load-bearing — read before any edit)

The **running code is the `navreo-signals` repo**, served at **`https://navreo-signals.onrender.com`** (Render auto-deploys on push to `main`). The local dev server runs at **`http://127.0.0.1:7955`**.

**NEVER edit the iCloud copy** under `Bjion [2023]/Navreo/Claude/Navreo` — it **reverts edits** and is **not the live code**. Every edit goes to the `navreo-signals` checkout. Verify against the running app in **list view** (`/app/campaigns.html`, **no `#` hash**). Leave the iCloud copy untouched.

---

## ⚙️ LOOP TRAINING MODE  →  **OFF** (flipped by user)

Flip it by editing this one line:

    LOOP_TRAINING_MODE = OFF       # ON = approve every step · OFF = run autonomous

**When ON**
- Pause at the end of **every** step and wait for my explicit approval before starting the next.
- Before running a step, check its done-rule first. **If it already passes, skip it** — say so and move on.
- Only (re-)run steps that fail their done-rule.
- Retry cap applies (see below). Never loop a step forever.

**When OFF**
- Run all steps autonomously, no pauses.
- Still check every step's done-rule and still honour the retry cap. Report at the end, not between steps.

**Retry cap (both modes):** any single step retries **max 3** times against its done-rule. On cap-hit, stop that step, record it as **FAILED** with the reason and the best result so far, keep going, and surface it in the final report. Never silently exceed.

---

## THE GOAL

On the campaigns home page a **non-technical user sees at a glance how each campaign is performing** — across completion, emails sent, reply rate, sends-per-positive-reply, meetings, and bounce rate — in **Smartlead's familiar format**, with a **collective all-campaigns summary** and **trend lines** across the top.

Done means: every live campaign shows all six per-campaign metrics in the Smartlead-style block (ring + stat columns); the top strip aggregates the same six and each aggregate **independently matches** the value read back from the Smartlead dashboard within rounding; at least one trend line shows **real** over-time movement; the meetings tile is either **traceable to a real source** or **explicitly gated "no source"**; and it's browser-verified with no console errors, iCloud copy untouched.

---

## THE STEPS

### Step 1 — Pin the meetings data source (DO THIS FIRST — it gates the meetings tile)

Meetings-booked is the **one metric with no confirmed source**. Before building its tile, resolve where the number comes from. Candidates, in order of preference:
- a **Calendly** booked-events count (per campaign / overall),
- the **setter** tab's booked-meeting count,
- a **Folk** booked-meeting count, or
- a **manual tag** already applied to leads (e.g. a Smartlead lead category / interest status meaning "meeting booked").

Investigate what actually exists and is joinable to a campaign. Decide one of:
- **(a) Real source found** — pin exactly which field/endpoint supplies the count and how it maps to a campaign, and the meetings tile will show that real number; **or**
- **(b) No real source** — the meetings tile is **gated with a visible "no source" state** (e.g. "—" with a "meetings source not connected" note). It shows **no number** rather than a fabricated one.
- Done-rule: a written decision is recorded — either the pinned source (field + how it maps to campaign) **or** an explicit "no source → gate the tile" ruling. Under LOOP TRAINING MODE = ON, **surface this decision for approval before building the tile.** No number is ever invented.

### Step 2 — Per-campaign stat block (six metrics, Smartlead style)

- In `renderList()`, render for **every live campaign** a Smartlead-style block: **completion ring** (metric 1) on the left, **coloured stat columns** on the right for **emails sent** (count), **reply rate** (% with sub-percentage), **sends per positive reply** (ratio "1 per N", = sent ÷ positive; show "—" when positive = 0), **meetings booked** (per Step 1 — real number or gated state), and **bounce rate** (%).
- Pull the five native metrics from the existing `server.py` surface (`sent` / `positive` / `replied` / `completion_pct` / `reply_rate` around line 2222) plus bounce; add a read-only aggregate endpoint **only** if a field isn't already reachable client-side.
- Match Smartlead's visual treatment: ring for completion, coloured numerals with sub-percentages. Reuse existing styles/classes where they exist.
- Done-rule: every live campaign row shows all six metrics in the ring + stat-column layout; "1 per N" computes correctly (spot-check one campaign by hand: sent ÷ positive); meetings renders its Step-1 real number or its gated state; no console errors.

### Step 3 — Collective summary strip (aggregate tiles across the top)

- Across the **top** of the list, above the campaign rows, render Smartlead-style **stat tiles** aggregating the same six metrics across **all** campaigns: total emails sent, overall completion %, overall reply rate, overall sends-per-positive (Σsent ÷ Σpositive), total meetings (or gated), overall bounce rate. Use `destLogo(kind)` where a destination split is shown.
- Aggregate correctly: rates are **recomputed from summed numerators/denominators**, never averaged-of-averages.
- Done-rule: the strip renders all six aggregate tiles; each aggregate equals the sum/derived value of the per-campaign numbers on the same page (spot-check 2 metrics by hand); no console errors. (Independent reconciliation against the Smartlead dashboard is Step 5.)

### Step 4 — Trend lines (collective metrics over time)

- Add **trend lines** to the collective strip showing how the aggregate metrics move over time, reusing **`velocityChart(rows, srcs)`** and the Overview's day-wise/funnel pattern — **do not write new chart code**. Source the over-time data from the existing velocity / day-wise data feed the Overview already uses.
- Degrade gracefully with only one day of data (dots + "builds as daily data accumulates"), exactly like the Overview chart.
- Done-rule: **at least one trend line renders real over-time movement** from the existing velocity/day-wise data — not a flat placeholder or hard-coded series; single-day data shows the graceful fallback, not a broken axis; no console errors.

### Step 5 — Reconcile aggregates against the Smartlead dashboard (not the app's own labels)

- For each of the six collective aggregates, read the corresponding value **back from the Smartlead dashboard** (via the Smartlead MCP / API — e.g. campaign analytics, overall stats) and confirm the app's aggregate **matches within rounding**. Compare against **Smartlead's numbers**, not the app's own labels.
- For meetings: if a real source was pinned in Step 1, reconcile it against that source; if gated, confirm the tile shows the gated state (nothing to reconcile).
- Done-rule: all five native aggregates (sent, completion %, reply rate, sends-per-positive, bounce rate) match the Smartlead dashboard within rounding; meetings either matches its pinned source or is correctly gated. Record the compared pairs (app value vs Smartlead value) in the report.

### Step 6 — No-fabrication & plain-English pass

- Confirm **every** displayed number traces to a Smartlead (or Step-1-pinned) source. Grep the new markup for any hard-coded metric values or placeholder numbers — there must be none.
- Labels are plain English (Navreo house rule): a non-technical user understands each without a glossary. No "ESP", "webhook", "payload", "verdict".
- Done-rule: `grep -iE "esp|webhook|payload|verdict"` over the new user-facing markup returns nothing; no hard-coded metric literals in the scorecard code; the meetings tile shows a real number or the gated state, never a fabricated count.

### Step 7 — Browser-verify on the running app (list view, no console errors)

- Load the **list view** on the running app — local `http://127.0.0.1:7955/app/campaigns.html` (or `https://navreo-signals.onrender.com/app/campaigns.html`), **no `#` hash**. Reload, then check: per-campaign blocks render for every live campaign (Step 2), the collective strip + tiles render (Step 3), at least one trend line renders (Step 4).
- Read console + network for errors; capture a screenshot as done-evidence (a rendered page is the only done-evidence for UI work — a grep of deployed JS is a deploy check only).
- Done-rule: list view renders all three pieces with **no console errors**; screenshot captured; the **iCloud copy is confirmed untouched** (all edits went to the `navreo-signals` checkout).

### Step 8 — Ship it

- Push live: apply the edits to a clean `navreo-signals` checkout and push to `main` (Render auto-deploys). Keep the commit scoped to this feature only — do **not** sweep in unrelated working-folder edits, and **never** touch the iCloud copy.
- Done-rule: `origin/main` HEAD is the new commit; `https://navreo-signals.onrender.com/app/campaigns.html` serves the scorecard (poll until a unique marker string appears). Report the commit hash.

---

## HOW TO RUN

1. Read the mode line. If **ON**, work one step at a time and stop for my approval after each; skip any step whose done-rule already passes. If **OFF**, run all eight in order without pausing.
2. **Step 1 is a gate** — pin the meetings source (or the "no source" ruling) before building the meetings tile in Step 2.
3. For each step: edit **only** in the `navreo-signals` checkout (`app/campaigns.html`, and `app/server.py` only for read-only aggregates), then check the done-rule — grep the string assertions and, for visual steps, reload the running list view and take a screenshot + console check. Retry up to the cap (max 3), then mark FAILED and continue.
4. Verify against the running app after every browser-observable change before calling a step done. Never fabricate a metric — if a number can't be sourced, gate it.

## OVERALL DONE-RULE (all five, or it isn't done)

1. The rendered **list view** shows, for **every live campaign**, all six per-campaign metrics in the Smartlead-style block (completion ring + stat columns).
2. The top **collective strip** shows the same six aggregated across all campaigns, and each aggregate **independently matches** the sum/derived value read back from the **Smartlead dashboard** (not the app's own labels) within rounding.
3. **At least one trend line** renders real over-time movement of the collective metrics from the existing velocity/day-wise data — not a placeholder.
4. The **meetings tile** shows a number traceable to the real source pinned in Step 1, **or** is explicitly gated with a "no source" state — never a fabricated count.
5. **Browser-verified** on `navreo-signals.onrender.com` (or the local running app), list view, **no console errors**, **iCloud copy left untouched**.

Final report: one line per step — DONE / SKIPPED (already passed) / FAILED (with reason) — plus the meetings-source ruling, the Step-5 app-vs-Smartlead reconciliation pairs, and the shipped commit hash.
