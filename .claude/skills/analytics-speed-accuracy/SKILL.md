---
name: analytics-speed-accuracy
description: Static orchestration skill that makes the LIVE ANALYTICS PAGE (app/deliverability.html of ~/navreo-signals, live at navreo-signals.onrender.com/app/deliverability.html) load in under 2 seconds AND stop showing outdated insights or numbers. Seven fixed steps — full insight-by-insight accuracy audit, sub-2s first paint (cron-primed / snapshot-restored heavy endpoints), freshness stamps + staleness gates on every insight, source-of-truth reconcile, efficiency sweep — then a front-end + back-end tester audit that must score the page 9/10+ on Stability, Data validity, Code efficiency AND Features-working-as-intended before the loop closes. Every done-rule verified on the LIVE UI. Loop Training Mode toggle (ON by default). Use when the user says "run the analytics speed loop", "speed up the analytics page", "audit the analytics insights", "fix stale analytics numbers", or "/analytics-speed-accuracy". NOT the campaigns list (campaigns-view-stability), NOT the one-off data reconcile (analytics-accuracy-reconcile), NOT the inbox manager embedded on the same page (inbox-manager-* skills).
---

# analytics-speed-accuracy

Make the **analytics page** (`app/deliverability.html`, the live P3 hub at `navreo-signals.onrender.com/app/deliverability.html`) load in **< 2 s** and guarantee **every insight and number it shows is accurate or honestly dated**. Static loop — fixed steps, each with a done-rule, Loop Training Mode controls pausing.

---

## ⚙️ LOOP TRAINING MODE  →  **ON**

Flip it by editing this one line:

    LOOP_TRAINING_MODE = ON        # ON = approve every step · OFF = run autonomous

**When ON**
- Pause at the end of **every** step and wait for Bjion's explicit approval before starting the next.
- Before running a step, check its done-rule first. **If it already passes, skip it** — say so and move on.
- Only (re-)run steps that fail their done-rule.
- Retry cap applies (below). Never loop a step forever.

**When OFF**
- Run all steps autonomously, no pauses. Still check every done-rule, still honour the retry cap, report at the end.

**Retry cap (both modes):** any single step retries **max 3** times against its LIVE done-rule. On cap-hit, record FAILED with the reason, keep going, surface it in the final report.

---

## THE GOAL

On the live page: a hard reload paints the shell **and every section that has data in under 2 seconds**; sections still building show an honest "loading/building" state, never a blank or a wrong number. **Every insight carries a visible freshness stamp**, nothing older than its freshness budget renders unlabelled, and every headline number reconciles against its source of truth (Smartlead / Supabase) for the **same window the filter says**. A front-end + back-end tester panel scores the page **≥ 9/10 on Stability, Data validity, Code efficiency and Features-working-as-intended**.

## SAFETY RAILS (absolute, both modes)

- **Read-only surface**: the analytics page never writes. This loop never sends, deletes, or edits campaigns/leads/mailboxes anywhere. The embedded inbox manager (`deliverability-tab.js`) is out of scope — touch it only where its deferred load costs first-paint time.
- **Ship-then-verify-LIVE law**: push to `~/navreo-signals` main → Render auto-deploys (~1–2 min) → poll `/api/version` (cookie-gated; mint per `signals-live-verify-recipe`) until the commit matches → verify on the live host. A local render or source grep is never done-evidence.
- **No in-process heavy sweeps on web** (512 MB Render starter OOM-loops — `web-instance-oom-crashloop`): any precompute/warm/backfill lands in a cron or the existing background sync loops, never the request path.
- **Collision census is ghost-inflated** (`collision-bar-live-truth`): the page may only present LIVE-confirmed collision numbers; never surface the daily `collision_ledger` census as a real backlog.
- Every update reported to Bjion includes a browser link **confirmed to load and render** first (`updates-need-verified-link`).

## GROUND TRUTH (audited 2026-08-02, commit b98f863)

- The page boots **incrementally** (`boot()`, deliverability.html ~2467): first paint is immediate from fallback globals, each of ~10 endpoints paints its own section on arrival via a debounced `renderAll()`. Fast reads (`deliverability-trends`, `campaigns-unified`, `_audit`, `sources?slim=1`, `signals/daily`, `collisions`) land ~0.4 s.
- The heavy three: `/api/analytics-hub?days=30` and `/api/campaign-scorecard` can take **30–70 s** on a cold/busy Supabase (they gate the "Live data unavailable" bar); `/api/client-windows` builds **2–4 min** on a cold server (client polls 20×20 s). Scorecard already has a Supabase-table sync loop (`_scorecard_sync_loop`) + SWR; hub has `_ANALYTICS_HUB_SWR` keyed by days; client-windows is Supabase-persisted so deploys restore instantly (`deliverability-client-range-filters`).
- Six question lanes: *Where can we improve the most · Do you have enough leads · Are your emails landing · Which campaigns and messages are winning · Who actually replies · How many meetings did it book.* The messaging/who/offer insights are **cron-generated** book-scope rows read from `/api/cockpit/insights` with a `generated_at` the UI currently **never shows** — the page has **zero** "as of"/age stamps today (grep-verified).
- Until client-windows lands, sections run in a **lifetime/fleet fallback** while the sticky 7/14/30 filter still shows a window — the exact window-mismatch trap that caused the "stark gap" incident (`analytics-tool-vs-smartlead-reconciled`).
- `deliverability-tab.js` (8,231 lines, the engine-room manager) is loaded by this page, deferred (~line 612).

---

## THE STEPS

### Step 1 — Insight inventory + accuracy audit (report, no code)
- Enumerate **every** rendered insight/number across the six lanes on the live page. For each: its endpoint, its data source (live Smartlead / Supabase table / SWR cache / cron row / fallback global), its age at render, the window it claims vs the window it actually covers, and an accuracy verdict — spot-diffed against the source of truth for the same window (Smartlead analytics endpoints / Supabase tables, tolerance ±2 %).
- Measure the live load: hard-reload timings per endpoint + time-to-first-paint and time-to-all-sections, cold and warm.
- **Done-rule:** one table in chat — every insight with source, age, window-honesty, accuracy verdict, plus the measured endpoint timings — delivered with the live link. This table is the worklist for Steps 2–4.

### Step 2 — First paint < 2 s, heavy endpoints never block or blank
- Server: the heavy three answer fast even after a deploy — cron-primed SWR + Supabase-persisted snapshots (extend the client-windows / scorecard-table pattern to the hub; all warming in crons per the OOM rail). Cap request-thread waits so no analytics endpoint hangs a route.
- Client: keep the incremental boot; any section still waiting shows an explicit "building — updates in ~Xs" state, never a blank tile or a fallback number posing as current.
- **Done-rule (LIVE):** hard reload → shell + every section that has data painted **< 2 s** (network/Performance panel proof); immediately after a fresh deploy the heavy endpoints serve their persisted snapshot **< 2 s** instead of a 30–70 s compute; no request-path warming.

### Step 3 — Freshness truth: nothing outdated renders unlabelled
- Every insight gets a visible "as of"/age stamp fed by its real timestamp (`generated_at` for cron rows, computed-at for SWR/snapshot payloads). Set a freshness budget per class (cron insights ≤ 24 h, windowed numbers ≤ their window's refresh cycle); anything over budget renders visibly dated or triggers a background refresh — never silently as-if-current.
- Kill the window lie: while client-windows is building, affected sections say so explicitly — lifetime/fleet fallback numbers may not appear under a 7/14/30 label.
- **Done-rule (LIVE):** every rendered insight shows its age; DOM shows no over-budget number without a stale label; with client-windows cold, no section presents fallback data under a window label.

### Step 4 — Accuracy reconcile: fix what Step 1 flagged
- For every insight Step 1 marked inaccurate or window-dishonest: find whether the page, the cache, or the source is wrong; fix that side. One source of truth per number, a one-line code comment naming it.
- **Done-rule (LIVE):** re-run the Step 1 diff — every headline number within ±2 % of its source of truth (exact where the source is exact) for the stated window, on the live host.

### Step 5 — Code-efficiency sweep
- Over ONLY this surface (deliverability.html boot/render path + the endpoints touched above): dedupe fetches, delete dead branches, confirm every SWR actually short-circuits, confirm the deferred `deliverability-tab.js` load costs first paint nothing.
- **Done-rule:** no behaviour change (Steps 2–4 done-rules still pass live after the sweep), no duplicate calls in the network tab on one load, diff net-negative or neutral on the touched surface.

### Step 6 — Tester audit: 9/10 on four dimensions
- Run a Workflow panel: **front-end tester** (paint timing, hydration races, error/building states, filter behaviour) + **back-end tester** (endpoint latency, cache/snapshot correctness, cron health, OOM safety) + one **data-validity auditor** who independently re-diffs live numbers against Smartlead/Supabase. Each scores the page /10 on **Stability**, **Data validity**, **Code efficiency**, **Features working as intended**, with concrete findings.
- Apply the highest-impact findings, redeploy, re-vote. **Done-rule:** every dimension averages **≥ 9.0 with no individual score below 8**, within max 3 fix-and-revote rounds (cap-hit = FAILED with last scores).

### Step 7 — Final live re-audit
- Hard-reload the live page twice (cold + warm): re-time first paint, re-check every stamp, re-spot-diff three insights at random from the Step 1 inventory. **Done-rule:** < 2 s paint both times, no unlabelled stale data, spot-diffs pass, and `/api/version` confirms the audited commit is the one serving — reported with the verified live link.

## FINAL REPORT

One line per step — DONE / SKIPPED (already passed) / FAILED (reason + retry count) — the Step 1 vs Step 7 timing and accuracy deltas, the panel's final four-dimension scores per tester, and the live-host commit hash the verification ran against.
