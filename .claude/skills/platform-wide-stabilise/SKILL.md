---
name: platform-wide-stabilise
description: Static orchestration skill that stabilises the ENTIRE Navreo signals platform (~/navreo-signals, live at navreo-signals.onrender.com) — removes dead code and unused UI, consolidates duplicate data pulls into one source of truth per metric (e.g. daily-sent-per-client pulled by both the campaigns page and the analytics page), and moves slow Smartlead reads behind a Supabase stale-while-revalidate cache without making the platform feel stale — then a front-end + back-end tester panel must score the platform 9/10+ on Stability, Data validity, Code efficiency, AND Features-working-as-intended before the loop can close. Every done-rule is verified in the LIVE UI. Includes a Loop Training Mode toggle (ON by default). Trigger with "/platform-wide-stabilise", "run the platform stabilise loop", or "stabilise the whole platform".
---

# platform-wide-stabilise

Stabilise the **whole platform** — every page `~/navreo-signals` serves (campaigns,
setter, deliverability/analytics, notifications, lists, strategy, unified, optimise,
offer, settings) and the backend behind them (`app/server.py` ~1.0MB, `app/setter.py`
~580KB). Three workstreams: **delete** (dead code, unused UI), **consolidate** (one
source of truth per metric), **cache** (Supabase-first reads, minimal Smartlead pulls).
Static loop — fixed steps, each with a done-rule; Loop Training Mode controls pausing.

---

## ⚙️ LOOP TRAINING MODE  →  **OFF**

Flip it by editing this one line:

    LOOP_TRAINING_MODE = OFF       # ON = approve every step · OFF = run autonomous

**When ON**
- Pause at **every** step and wait for my explicit approval in chat before continuing.
- Before running a step, check its done-rule first. **If it already passes, skip it** —
  say so and move on.
- Only (re-)run steps that fail their done-rule.
- Retry cap applies (below). Never loop a step forever.

**When OFF**
- Run all steps autonomously, no pauses.
- Still check every step's done-rule and still honour the retry cap. Report at the
  end, not between steps.

**Retry cap (both modes):** any single step retries **max 3** times against its LIVE
done-rule; the panel gate in Step 6 caps at **3 optimise→re-vote rounds**. On cap-hit,
stop that step, record it FAILED with the reason and best result reached, keep going,
and surface it in the final report. Never silently exceed.

---

## THE GOAL

Fewer bugs and faster code across the entire platform: no dead pages or unused UI
shipped to production, every metric computed in exactly ONE place and consumed
everywhere else, slow Smartlead reads served Supabase-first (instant, with honest
freshness) — held to a tester-panel bar of **≥ 9/10 on each of Stability, Data
validity, Code efficiency, and Features working as intended**.

## Hard safety rails (every step, no exceptions)

- **NEVER send to real prospects.** Test send paths with `is_test` rows only; check
  `row.status` before ANY Smartlead write. No leads deleted, nothing sent, no
  un-reverted state changes on real client data.
- **Ship-and-verify-LIVE law.** Local renders, greps, and green labels are never
  done-evidence. Push, poll `/api/version` for the redeploy, mint a `navreo_session`
  cookie past the login gate, then verify on **navreo-signals.onrender.com**.
- Web is a **512MB Render starter** — batch sweeps live in crons, never in-process
  on web. Supabase clips at **1000 rows** per query — paginate anything bigger.
- The setter's real test gate is `python3 app/test_setter.py` (pytest lies).
- **Deletion gate:** a file/feature/endpoint may only be deleted after proving zero
  inbound references (server routes, HTML links, fetch calls, crons, skills) AND, in
  Loop Training Mode ON, after my explicit approval of the kill list.

---

## STEP 0 — Run the platform + read-only audit (blocking)

Open every live page and USE it before touching code. Build three maps:

- **Dead map** — pages/endpoints/branches nothing references. Pre-audited starters
  (2026-08-02): `app/campaigns-classic.html` and `app/deliverability-proto.html`
  have zero server.py references → candidates. `app/mock_deliv.py` (DELIV_MOCK test
  fixture) and `app/roi-calculator.html` (public lead-magnet, allowlisted) are LIVE
  — keep. Everything else must be proven, not assumed.
- **Duplicate map** — every metric computed in 2+ places, with file:line for each.
  Known instance: daily-emails-sent-per-client is pulled by campaigns.html AND the
  analytics page (deliverability.html) separately; the `/api/client-windows` engine
  already exists as the Supabase-persisted per-client source — route dupes there.
- **Cache map** — from the live walk, record per page: load time, which requests hit
  Smartlead live, which felt slow, which data could be minutes-old without harm.
  CACHE (Supabase-first + background refresh): campaign lists/stats, analytics
  aggregates, mailbox health, per-client windows, lead stats. NEVER cache-only:
  send actions, draft-to-send reply state, `row.status` checks before a Smartlead
  write, anything the user is about to act on irreversibly.

*Done-rule: all three maps written down with file:line anchors and live-load timings;
the kill list, dedupe list, and cache list are each explicit before any edit.*

## STEP 1 — Delete dead code and unused UI

Remove everything on the approved kill list: unreferenced pages, dead endpoints,
superseded branches, unused helpers, commented-out blocks, UI elements no flow
reaches. Deleting beats refactoring; behaviour of live features must not change.

*Done-rule: kill-list files gone; repo-wide grep shows zero dangling references; the
sweep commit is net-negative lines; every live page still loads and its primary flow
works in the live UI.*

## STEP 2 — Consolidate: one source of truth per metric

For each duplicate-map entry, pick ONE producer (prefer an existing engine, e.g.
`/api/client-windows`) and repoint every consumer at it. Same number, same window,
same label everywhere it appears. Kill the orphaned per-page pull code as you go.

*Done-rule: for each consolidated metric, the value shown on every consuming live
page is identical for the same window (spot-check daily-sent-per-client on the
campaigns page vs the analytics page); the duplicate pull paths are deleted.*

## STEP 3 — Supabase cache layer: fast reads, honest freshness

For each cache-map CACHE entry: reads serve Supabase-first instantly; a background
refresh (cron or on-demand revalidate, never a web-process sweep) re-pulls Smartlead
and upserts with a `fetched_at` stamp. Where age can exceed a few minutes, the UI
shows a quiet "updated Xm ago". Stale-while-revalidate, never stale-and-silent.
NEVER-cache entries keep hitting live and are documented as such in the code.

*Done-rule: cached pages render data in under ~1s on live; Render logs over a
10-minute live session show Smartlead calls only from refresh paths, not per-page-view;
a forced-stale row visibly updates after its refresh cycle; freshness stamps render.*

## STEP 4 — Efficiency pass on hot paths

With the platform quieter, sweep the hot paths the audit flagged: redundant
re-renders/refetches on the big pages, N+1 Supabase queries, duplicated helpers in
server.py/setter.py, oversized responses. Respect the 512MB ceiling. Keep behaviour
identical — this step deletes and tightens, it does not add features.

*Done-rule: `python3 app/test_setter.py` green plus the repo's other test files for
touched areas; net-negative or neutral line count; Steps 1–3 done-rules still pass.*

## STEP 5 — Full live regression walk

Walk every page on the live deploy end-to-end as a user: campaigns list + detail,
setter queue + a redraft (draft-only), deliverability with client+range filters,
notifications, lists, strategy, unified, optimise, offer, settings. Attempt to break
each primary flow.

*Done-rule: every page loads, every primary flow completes, zero console errors on
the walked paths, with a one-line "tried X, saw Y" note per page.*

## STEP 6 — Tester panel to 9/10 (quality gate)

Convene **5 testers** as parallel subagents — 2 front-end (pages: rendering,
perceived speed, UX, stale-feel) and 3 back-end (server.py/setter.py/crons: memory,
concurrency, query efficiency, cache correctness). Each independently scores four
axes 1–10 with specific findings:

- **Stability** — no crashes, no 5xx under normal use, degraded-data handled, no
  OOM-risk sweeps on web.
- **Data validity** — numbers agree with the backing truth AND with each other
  across pages; freshness honest; nothing double-counted.
- **Code efficiency** — dead code gone, one pull per metric, cache-first reads,
  no wasted refetches.
- **Features working as intended** — every surviving feature does its job on live;
  nothing broke in the deletes/consolidation.

If any tester scores any axis **< 9**: apply the highest-value fixes, redeploy,
re-verify Steps 1–5 still pass live, re-vote. Max **3** optimise→re-vote rounds.

*Done-rule: **every tester ≥ 9/10 on all four axes** on the final vote, with Steps
1–5 still green after the last fix.*

---

## HOW TO RUN

1. Read the mode line. If **ON** (default): do Step 0, present the three maps, and
   stop for approval; then one step at a time, pausing after each; skip any step
   whose done-rule already passes. If **OFF**: run 0→6 in order, no pauses.
2. Every step: edit → push → poll `/api/version` → verify the done-rule on the live
   host (read_page / screenshot / network panel). 3 retries max, then FAILED and move on.
3. Interruptions count as redeploys — re-confirm live state after any interruption
   before calling a step done.

## OVERALL DONE-RULE

Dead code gone, every duplicated metric consolidated to one producer, the cache layer
live with honest freshness, all six step done-rules passing on
**navreo-signals.onrender.com**, and the panel at **9/10+ from every tester on all
four axes**. No permanent actions on real data at any point. Final report: one line
per step — DONE / SKIPPED (already passed) / FAILED (reason + retries used) — the
panel scores axis-by-axis, before/after line counts and page-load timings, and a
browser link I have confirmed loads.
