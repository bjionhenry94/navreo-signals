---
name: campaigns-health-dashboard
description: Static orchestration skill that adds a health dashboard to the Navreo signals CAMPAIGNS LIST page (app/campaigns.html renderList view) — a line-graph across the top showing lead activity over time (found / pushed / pulled) and a status bar down the side summarising every useful signal-health stat — so a non-technical user can tell at a glance what's being found, what's being pushed into campaigns, what's being pulled, and whether their campaigns are healthy. One fixed step list, each with a checkable done-rule, verified by a 5 non-technical user usability test scoring ease-of-use and ease-of-understanding out of ten. Includes a Loop Training Mode toggle (ON by default). Use when the user says "build the campaigns health dashboard", "add the line graph and status bar to the campaigns page", "show the status of my leads", or "/campaigns-health-dashboard".
---

# campaigns-health-dashboard

Add a **health dashboard** to the signals **campaigns list page** (the "Signal campaigns." landing view, `renderList()` in `app/campaigns.html`). Goal: **a non-technical user can look at this one screen and instantly understand the status of their leads** — what's being found, what's being pushed into campaigns, what's being pulled, and whether anything is stuck or unhealthy.

Files: `app/campaigns.html` (all UI; the list view is `renderList()`) and, only if a stat can't be computed client-side, a small read-only aggregate in `app/server.py`. Verify against the running app at `http://localhost:7901/app/campaigns.html` (list view, no `#` hash).

Reuse, don't reinvent: the per-campaign Overview already has a `velocityChart(rows, srcs)` helper and a 4-stat funnel. Copy those patterns for the cross-campaign versions rather than writing new chart/stat code. Destination logos live at `icons/smartlead.png` (email) and `icons/heyreach.png` (LinkedIn) — use `destLogo(kind)`.

---

## ⚙️ LOOP TRAINING MODE  →  **OFF** (flipped by user 2026-07-06)

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

**Retry cap (both modes):** any single step retries **max 3** times against its done-rule. The usability step (Step 5) allows **max 4** build-and-retest rounds. On cap-hit, stop that step, record it as FAILED with the reason and the best result so far, keep going, and surface it in the final report. Never silently exceed.

---

## THE GOAL

One screen that answers, without jargon and without clicking in:

- **Found** — how many people the signals have surfaced (and the trend over time).
- **Pushed** — how many have been sent into outreach, split by tool (📧 Smartlead email / 💼 HeyReach LinkedIn).
- **Pulled** — what the daily run is bringing in (today, and the recent trend).
- **Waiting / Skipped** — how many leads are sitting in Leads unreviewed, and how many were skipped.
- **Health** — which campaigns are running vs paused, when each last pulled, and anything stuck (running but nothing found lately, or a destination not set).

Done means the list page shows a **top line-graph** and a **side status bar** carrying all of the above, the numbers reconcile with the per-campaign Overview, and **five non-technical testers rate it ≥ 8/10** on both ease-of-use and ease-of-understanding.

Numbers must be plain English (Navreo house rule): every stat gets a one-line, jargon-free meaning. "Sent to outreach", not "pushed to ESP".

---

## THE STEPS

### Step 1 — Aggregate the cross-campaign numbers
- On the list view, compute per-campaign and total: **found** (all leads), **pushed** (sent to outreach, split Smartlead vs HeyReach), **waiting** (unreviewed, not sent), **skipped** (rejected), plus each campaign's **running/paused** state and **last-pull** time.
- Prefer client-side aggregation from what the list already fetches (campaign drafts + `/api/lead-counts`); fetch `/api/leads?campaign_id=…` per campaign only if a number isn't otherwise available. Add a read-only `/api/overview` in `server.py` **only** if per-campaign fetches are too slow or missing a field.
- Done-rule: a single in-memory object holds the totals + per-campaign rows; the totals equal the sum of the per-campaign Overview cards for the same campaigns (spot-check 2 campaigns). No console errors.

### Step 2 — Top line-graph (activity over time)
- Add a graph across the **top** of the list, above the campaign rows: daily lines for **Found**, **Pushed**, and **Pulled** aggregated across all campaigns, plus a bold **All/Total** line, with a legend. Reuse the Overview `velocityChart` bucket-by-date approach.
- Degrade gracefully when there's only one day of data (dots + "builds as daily runs accumulate"), exactly like the Overview chart does.
- Done-rule: the graph renders on the list view with ≥1 line and a legend; single-day data shows the graceful fallback, not a broken axis; no console errors.

### Step 3 — Side status bar (health at a glance)
- Add a **status bar down the side** of the list (right or left column) showing: **People found**, **Sent to outreach** (with `destLogo` split 📧 N / 💼 N), **Waiting in Leads**, **Skipped**, **Campaigns running** (N running · M paused), and **Last pull** ("found today: N" + newest pull time).
- Flag anything unhealthy in plain English: a running campaign with **no destination set**, or **nothing found in the last few days**, gets a small ⚠ line naming the campaign and the fix.
- Done-rule: the panel renders with every stat above; the split add-up matches "Sent to outreach"; at least the destination-missing and stale-pull warnings fire when their condition is true (test by eyeballing a campaign that matches). No console errors.

### Step 4 — Plain-English pass
- Every number on the page has a one-line, jargon-free label a non-technical user understands. No "ESP", "enrichment", "webhook", "API", "verdict".
- Keep the existing list rows (name · N leads · date · Running/Remove) intact; the dashboard sits around them, it doesn't replace them.
- Done-rule: read every label aloud — none needs a glossary; `grep -iE "esp|webhook|enrichment|verdict|payload" ` over the new markup returns nothing user-facing.

### Step 5 — Usability test (5 non-technical users)
- Simulate **five distinct non-technical testers** (e.g. a founder, a VA, a sales rep, an ops manager, a first-time user). Show each the list page and ask them to, using only what's on screen:
  1. say roughly **how many leads have been found**,
  2. say **how many have been pushed into campaigns** (and to which tool),
  3. say **what's being pulled** / whether new leads are still coming in,
  4. say **whether any campaign looks unhealthy** and why.
- Each tester scores **ease-of-use /10** and **ease-of-understanding /10**, and their four answers are checked against the real numbers.
- Done-rule: **average ≥ 8/10 on BOTH** scores across the 5 testers **AND** all 5 answer questions 1–3 correctly (Q4 correct for ≥4/5). If it fails, apply the testers' top confusions as concrete UI fixes and retest — **max 4 rounds** (retry cap), then stop and report the best result.
- Never use `preview_click` to fake a human reading the screen; judge comprehension from the rendered content and labels.

### Step 6 — Ship it
- Push the change live: apply the SAME edits to a clean checkout of the `navreo-signals` GitHub repo (Render auto-deploys on push to `main`). Keep the commit scoped to this feature only — do **not** sweep in unrelated edits sitting in the working folder.
- Done-rule: `origin/main` HEAD is the new commit; the live site `https://navreo-signals.onrender.com/app/campaigns.html` serves the graph + status bar (poll until a unique marker string appears). Report the commit hash.

---

## HOW TO RUN

1. Read the mode line above. If **ON**, work one step at a time and stop for my approval after each; skip any step whose done-rule already passes. If **OFF**, run all six in order without pausing.
2. For each step: make the edits in `app/campaigns.html` (and `server.py` only if Step 1 requires it), then check the done-rule — grep for the string assertions and, for visual steps, reload `http://localhost:7901/app/campaigns.html` and take a `preview_snapshot`/`preview_screenshot` + console check. Retry up to the cap, then mark FAILED and continue.
3. Verify against the running app after every browser-observable change (reload, check console, snapshot) before calling a step done.

## OVERALL DONE-RULE

- The campaigns list page shows a **top line-graph** (found / pushed / pulled / All) and a **side status bar** (found · sent split by tool · waiting · skipped · running-vs-paused · last pull · health warnings), numbers reconciling with the per-campaign Overview.
- **Five non-technical testers average ≥ 8/10** on ease-of-use **and** ease-of-understanding, and can read found/pushed/pulled straight off the screen.
- Server boots, list page loads with **no console errors**, and (Step 6) the change is **live** on the deployed URL.
- Final report: one line per step — DONE / SKIPPED (already passed) / FAILED (with reason) — plus the per-tester scores and the shipped commit hash.
