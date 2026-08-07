---
name: campaigns-unified-home
description: Static orchestration skill that redesigns the top-level view of the Navreo signals tool (app/campaigns.html + app/server.py, live at navreo-signals.onrender.com) into ONE pane for ALL outbound campaigns — a live mirror of every Smartlead + HeyReach campaign, signals reframed as campaign SOURCES, the Status rail + Lead-activity panel replaced by a single multi-line performance graph fed from Supabase, and source rows deep-linking to their list in lists.html with a visible reuse affordance. Built and scored by a simulated 8-tester panel (avg intuitiveness ≥8/10). Fixed step list, checkable done-rules, retry caps, Loop Training Mode toggle. Use when the user says "run the campaigns homepage redesign", "unify the campaigns view", "run the unified home loop", or "/campaigns-unified-home".
---

# campaigns-unified-home

Redesign the campaigns.html homepage so it stops being a signals/campaigns collision and becomes **one pane for ALL outbound campaigns**. Static loop — the steps below are fixed, each has a done-rule, and Loop Training Mode controls whether you pause between them.

Files: `app/campaigns.html`, `app/lists.html`, `app/server.py`. Working copy = the iCloud project dir (authoritative). Live host: `https://navreo-signals.onrender.com/app/campaigns.html`. Data: Supabase project `fnykldftbkrccihdjayl` (fed by the existing Smartlead + HeyReach daily syncs).

---

## ⚙️ LOOP TRAINING MODE  →  **ON** (default)

Flip it by editing this one line:

    LOOP_TRAINING_MODE = ON        # ON = approve every step · OFF = run autonomous

**When ON**
- Pause at the end of **every** step and wait for my explicit approval before starting the next.
- Before running a step, check its done-rule first. **If it already passes, skip it** — say so and move on.
- Only (re-)run steps that fail their done-rule.
- Retry cap applies (see below). Never loop a step forever.

**When OFF**
- Run all steps autonomously, no pauses.
- Still check every step's done-rule and still honour the retry cap. Report at the end, not between steps.

**Retry cap (both modes):** any single step retries **max 3** times against its done-rule (Step 7's panel gets **max 3 build-and-retest rounds**). On cap-hit, stop that step, record it FAILED with the reason, keep going, surface it in the final report. Never silently exceed.

---

## THE GOAL

Opening campaigns.html shows one clean top-level page: **every Smartlead + HeyReach campaign in one list** (app-created and external together, external rows read-only), **one continuous multi-line performance graph** (emails sent/day, reply rate, bounce rate), **no Status rail, no Lead-activity panel**, and inside any campaign each source click-throughs to its list in All Files (lists.html) where a visible "push into new campaign / reuse" affordance exists.

**Rulings (baked in, 2026-07-12):**
1. Top level live-mirrors EVERY Smartlead + HeyReach campaign — not just app-created `campaign_drafts`. Borrow from the local-only `app/unified.html` prototype (commit `249d321`, platform-keyed live mirror). It is NOT deployed; it's source material.
2. A signal is **not** a separate entity anywhere in the UI — it is a SOURCE to a campaign. Rename/reframe all top-level "Signal campaigns" language accordingly.
3. Graph lines come from per-day Supabase data. **Never fabricate a series** — a missing metric renders as an absent/empty line with a label saying so.
4. Panel removal is **UI-level only** — no server.py endpoint dies without a grep proving no other page (lists.html, deliverability, notifications, setter, shell.js) consumes it.
5. Deep-link reuse affordance is **navigate-and-surface ONLY** (dashboard-terminal principle) — no in-app push execution; real actions happen in Claude Code.
6. Orchestration/judgment on **Fable 5**; execution subagents on **model: sonnet**.

**Gotchas:** the deploy repo has previously REVERTED edits synced from iCloud — always verify the deployed bundle actually contains the change. Per-step reply/bounce table in the detail Overview (~line 1721) stays put. A rendered page in a real browser is the only done-evidence for UI work; grep of deployed JS counts only as a deploy check.

---

## THE STEPS

### Step 1 — Source→list linkage recon + build
Verify how/whether a source pull produces an addressable list today. Sources store NO list_id (POST `/api/sources` body: type, mechanism, name, campaign_id, titles, params, config) and lists.html has NO deep-link handler (lists open only via in-page `openGrid(listId)`). Add the missing linkage: a `list_id` on sources (or an equivalent join), populated on pull, plus backfill for existing sources where the join is derivable.
- Done-rule: a fresh or backfilled source row carries a resolvable list id; `GET` on a campaign's sources returns it; documented in a code comment where the join lives.

### Step 2 — Backend: live mirror + per-day performance endpoint
In `server.py`: (a) an endpoint returning EVERY Smartlead + HeyReach campaign merged with app-created drafts, platform-keyed, external ones flagged read-only (borrow unified.html's mirror logic from `249d321`); (b) an endpoint returning per-day **emails sent, reply rate, bounce rate** read from Supabase `fnykldftbkrccihdjayl` — return nulls, never zeros-as-fake, for days/metrics with no data.
- Done-rule: both endpoints return live JSON locally; campaign count in (a) reconciles with fresh `get_campaigns` (Smartlead) + `get_all_campaigns` (HeyReach) reads; (b) spot-checks against a direct Supabase SQL read for 2 days.

### Step 3 — Top-level UI rebuild
In `campaigns.html`: render the unified campaign list from Step 2a (one list, external rows read-only); **remove** the 290px right-side Status panel (`renderList`, ~line 1580) and the top Lead-activity panel/chart (`#dash-chart`, ~line 1556) **and their copies in `listSkeleton` (~line 380)**; add ONE continuous multi-line graph (sent/day, reply rate, bounce rate as separate lines) fed by Step 2b, missing metrics shown as labelled absent lines; rename all "Signal campaigns" top-level language to source-framing.
- Done-rule: `grep -n "Signal campaign" app/campaigns.html` returns nothing top-level; no Status/Lead-activity markup in page OR skeleton; local browser render shows the unified list + one graph.

### Step 4 — Source deep links + lists.html route + reuse affordance
Add a lists.html deep-link route (`#list=<id>` or `?list=`) that opens `openGrid(listId)` on load. Make every source row in a campaign's Sources tab (tab layout otherwise unchanged) a click-through to that route using Step 1's list_id. On the list view, add a visible "push into new campaign / reuse" affordance — navigate-and-surface only, no push execution.
- Done-rule: in a local browser, clicking a source lands on lists.html with the CORRECT grid open (title matches the source's list) and the reuse affordance visible.

### Step 5 — Endpoint-safety grep
For anything removed or replaced in Steps 2–3, grep lists.html, deliverability, notifications, setter pages and shell.js for consumers before deleting any server.py endpoint. Keep any endpoint another page uses.
- Done-rule: a recorded grep result per removed/candidate endpoint showing zero external consumers (or the endpoint kept); server boots clean.

### Step 6 — Deploy + deployed-bundle verification
Push to the deploy repo and confirm the LIVE bundle contains the changes (iCloud-revert gotcha: diff the deployed file against the working copy, or grep the served JS for a change marker). Then browser-render the live page.
- Done-rule: `https://navreo-signals.onrender.com/app/campaigns.html` rendered in a real browser shows the Step 3 layout; served source contains the new markers; no console errors.

### Step 7 — 8-tester panel (build-and-score)
Spawn 8 simulated user-testers (**model: sonnet** subagents; mix of go-to-market engineers and non-technical founders) against the LIVE built UI. Each attempts 3 core tasks: (a) find a given campaign's performance, (b) reach a source's underlying list from inside a campaign, (c) spin up a new campaign (creates it in HeyReach or Smartlead). Each scores intuitiveness /10 with failure notes. Record per-tester scores + notes to a results file in the project. If any task attempt fails or avg <8/10, fix the UI (judgment on Fable, edits via sonnet executors) and re-run the panel — max 3 rounds.
- Done-rule: all 24 attempts succeed AND avg intuitiveness ≥8/10, recorded in the results file.

### Step 8 — Final verification (all five, or it isn't done)
1. **Live browser proof**: navreo-signals.onrender.com/app/campaigns.html rendered — Status + Lead-activity gone, multi-line graph present, campaign list populated; on-page count reconciled against fresh Smartlead `get_campaigns` + HeyReach `get_all_campaigns` reads (tolerance = campaigns created/deleted mid-check).
2. **Data honesty**: ≥2 datapoints per graph line spot-checked against direct Supabase SQL for the same day — never against the app's own labels.
3. **Deep link**: in the browser, source click → lists.html with the CORRECT list open + reuse affordance visible.
4. **Panel**: Step 7's done-rule holds, results file exists.
5. **Hygiene grep**: no other page consumed any removed endpoint; listSkeleton matches the new layout (no vestigial Status/Lead-activity skeletons).
- Done-rule: all five pass, each with its evidence artefact (screenshot / SQL output / grep log / results file) named in the final report.

---

## HOW TO RUN

1. Read the mode line above. If **ON**, work one step at a time and stop for approval after each; skip any step whose done-rule already passes. If **OFF**, run all eight in order without pausing.
2. Execution subagents (edits, testers, greps at scale) run **model: sonnet**; keep judgment, scoring synthesis, and go/no-go calls on Fable.
3. UI done-evidence = a rendered page in a real browser (local for Steps 3–4, LIVE for Steps 6–8). Grep of deployed JS is a deploy check only, never done-evidence.
4. Retry up to the cap on failure, then mark FAILED and continue.

## OVERALL DONE-RULE

All five Step 8 checks pass. Final report: one line per step — DONE / SKIPPED (already passed) / FAILED (with reason) — plus the tester panel's per-tester scores and the paths of every evidence artefact.
