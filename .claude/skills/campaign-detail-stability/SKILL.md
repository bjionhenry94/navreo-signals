---
name: campaign-detail-stability
description: Static orchestration skill that stabilises the DETAILED CAMPAIGN VIEW (campaignPageHTML / #/c/<id> in app/campaigns.html + app/server.py of ~/navreo-signals, live at navreo-signals.onrender.com/app/campaigns.html#/c/<id>). Seven fixed steps — Set-live/Pause/Stop header controls, sequence copy always visible, ALL variants cyclable (off + deleted included), variant-performance served Supabase-first instead of live Smartlead crawls, progress-bar count truth, redundant-code + efficiency sweep — then a front-end + back-end tester audit that must score the page 9/10+ on Stability, Data validity AND Code efficiency before the loop closes. Every done-rule verified on the LIVE UI, no permanent actions. Loop Training Mode toggle (ON by default). Use when the user says "run the campaign detail stability loop", "fix the campaign view bugs", "stabilise the campaign page", or "/campaign-detail-stability". NOT the campaigns LIST (campaigns-view-stability) and NOT the four header/leads changes (campaign-detail-optimise).
---

# campaign-detail-stability

Stabilise the **detailed campaign view** (`campaignPageHTML(c, tab)` at `app/campaigns.html:3389`, hash route `#/c/<id>`, backed by `app/server.py`), fix the seven owner-reported issues, strip redundant code, then pass a front-end + back-end audit at 9/10 on three dimensions. Static loop — fixed steps, each with a done-rule, Loop Training Mode controls pausing.

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

On the live page (`navreo-signals.onrender.com/app/campaigns.html#/c/<id>`): the header lets you **Set live / Pause / Stop** the campaign; the **sequence copy always renders** (loud error + retry, never a silent dead-end); **every variant cycles** on the Messaging tab — live, switched-off (0 % split, labelled) and deleted (labelled); the **variant-performance breakdown answers fast from Supabase** instead of crawling Smartlead on every cold load; the **progress bar's completed / in-progress / not-started counts are proven correct** against the platform; redundant code is gone; and a front-end + back-end tester panel scores the page **≥ 9/10 on Stability, Data validity and Code efficiency**.

## SAFETY RAILS (absolute, both modes)

- **No permanent actions ever**: never delete leads, never send/schedule messages. Sequence-copy edits are out of this loop's scope and need Bjion's explicit line-item approval; if ever approved they MUST use the ID-intact recipe (verified 2026-08-02): fresh `get_campaign_sequences` immediately before → POST `{"sequences":[...]}` translating `sequence_variants`→`seq_variants`, `delayInDays`→`delay_in_days` → every step id + variant id echoed unchanged (a dropped id orphans that variant's stats forever, no recovery; disable = keep id + `variant_distribution_percentage: 0`) → verify by re-GET (ids identical) + `get_campaign_variant_statistics` (history intact); worked example in `lilly-bot` → "THE ID-INTACT RECIPE". Status writes may ONLY hit Smartlead `POST /campaigns/{id}/status` (the constraint in `execute_pause_action`, server.py ~3092, predates the ID-intact discovery and stays until deliberately rebuilt).
- **Live status test protocol**: exercise buttons only as *pause → verify → restore to the exact prior status*, on a **Navreo-workspace** campaign, never a client's. **Never START a campaign that was not ACTIVE at the start of the same test** (an accidental ACTIVE window sends real email). STOP is live-tested only with Bjion's explicit line-item approval.
- Ship-then-verify-LIVE law: push to `~/navreo-signals` main → Render auto-deploys (~1–2 min) → poll `/api/version` (cookie-gated; mint per `signals-live-verify-recipe` memory) until the commit matches → verify on the live host. A local render or source grep is never done-evidence.
- **No in-process heavy sweeps on web** (512 MB Render starter OOM-loops — see `web-instance-oom-crashloop`): any precompute/backfill for Step 4 lands in a cron, never the request path.

## GROUND TRUTH (re-audited 2026-08-01, commit e8cb41b)

- Steps 1–3 below were scoped 30 Jul and **never shipped** — no `/api/campaign-status` route exists; `_cockpit_sequence_copy` (server.py ~8425) still calls `_smartlead_json` unwrapped (a raise → dead connection; client `hydrateSequenceCopy`, campaigns.html ~4059, goes silent after one 7 s retry) and still **strips `is_deleted` variants** from the Messaging tab.
- Reuse, don't rebuild: `_smartlead_json` (429 backoff, workspace-federated), `ws_key_for_campaign`, the confirm-token pattern (`{"confirm":"PAUSE"}`), `_COCKPIT_LIVE_STATUS_SWR` (45 s TTL — invalidate the id after a status write or the header lies for 45 s).
- **Item 6 root cause** (slow variant performance): `_variant_paths` (server.py 8115) live-calls Smartlead `/campaigns/{n}/sequences` + up to **12** per-booker `_vp_sent_bodies_from_history` message-history crawls; `_cockpit_messaging` (8278) adds `variant-statistics` + `/sequences` + up to 6 `_meeting_step_from_history` lookups — all on the request thread when `_COCKPIT_MESSAGING_SWR` is cold. Supabase already stores resolved attribution per booker (`replies.raw->>vpath2`, stamped by `_vp_stamp_path`) and step stamps — the cache exists, it just isn't the primary read path.
- **Item 7 root cause candidate** (progress bar): the audience split (campaigns.html 3995–4017) blends two sources — `lead_statuses` from the Supabase RPC `cockpit_campaign_detail` vs platform totals from `c.stats.leads` (Smartlead) — and derives Not-started as `max(accounted, contact-record total, platform total) − accounted`. PAUSED folds into "In progress". Whether these equal Smartlead's own per-status numbers has never been checked.
- Variant test fixtures: 3723450 (deleted A–E, only F/G live), 3723446 (seven 0 %-split variants), 3421811 (KRG workspace, ACTIVE, step-1 A/B 50/50 — healthy reference).
- The variant-performance TABLE (`_cockpit_messaging`) already folds deleted variants in (shipped 5dab7a4); the sequence-COPY endpoint feeding the cycling pills does not. Don't confuse the two.

---

## THE STEPS

### Step 1 — Set live / Pause / Stop from the header
- Server: one auth-gated route `POST /api/campaign-status` body `{"id": <smartlead_id>, "status": "START"|"PAUSED"|"STOPPED", "confirm": "<same word as status>"}`. Only calls Smartlead `POST /campaigns/{id}/status` via `_smartlead_json` (federates workspaces). 400 without confirm; surface Smartlead's error body; on success invalidate that id in `_COCKPIT_LIVE_STATUS_SWR` and return the fresh status.
- Client: buttons in `.campaign-header-right` driven by live status — Active → Pause · Stop; Paused/Stopped → Set live · Stop; Completed → Set live. Two-step confirm in the UI, busy state, then header + list chip refresh from the re-fetched status. Stop is labelled honestly ("Stop (mark completed)").
- **Done-rule (LIVE):** on a Navreo test campaign, Pause flips the live Smartlead status and the header reflects it without a hard reload; restore to prior status the same way; Smartlead API independently confirms both transitions. Set-live/Stop wiring verified in the live DOM; STOP live-tested only with explicit approval.

### Step 2 — Sequence copy always visible
- Server: wrap the Smartlead read in `_cockpit_sequence_copy` so it can never raise (degrade instead); cap the request-thread wait so the route answers in seconds, not minutes.
- Client: failure renders an explicit state in `#sequence-root` — "Couldn't pull the live copy from Smartlead" + a **Try again** control — instead of silence; ≥ 3 total attempts with backoff; re-entering the Messaging tab re-fetches when no healthy copy is cached.
- **Done-rule (LIVE):** healthy path renders full copy for 3421811; forced-failure path (bogus id, e.g. `?id=1`) returns a fast degraded JSON (no 500, no hang) and the UI shows the labelled error + working retry — verified in live DOM + network panel.

### Step 3 — Cycle ALL variants, including non-live
- Server: sequence-copy endpoint includes `is_deleted` variants (flagged `deleted: true`) and each variant's split %; never drop a variant that has copy.
- Client: pills for every variant — live first, then off (`(off)`), then deleted (`(deleted)`); default-active = first live; cycling shows each variant's subject + body. Single-variant steps unchanged.
- **Done-rule (LIVE):** on 3723446 all eleven step-1 pills render with the seven 0 % ones labelled off; on 3723450 the five deleted variants cycle and are labelled; on 3421811 A/B render unlabelled. Verified in the live DOM.

### Step 4 — Variant performance answers from Supabase, not a Smartlead crawl
- Make Supabase the **primary** read path for the breakdown (meetings per emails sent, best combinations): serve `by_variant` / `combinations` from the already-stamped `replies.raw->>vpath2` rows + archived reply data; Smartlead message-history crawls happen only for the (few) unstamped bookers, moved off the request thread into the existing cron cycle (OOM rail above). Keep the honest attributed / removed / traceless buckets exactly as they are — this step changes WHERE the data is read from, never what it claims.
- **Done-rule (LIVE):** cold-cache `GET /api/cockpit/messaging?id=3421811` (and one other booked-meeting campaign) answers in **< 5 s** (was: up to 12+ sequential Smartlead crawls), numbers match the pre-change output for the same campaign (spot-diff `by_variant`, `combinations`, `booked`), and zero Smartlead message-history calls fire on a warm-stamped campaign (server log proof).

### Step 5 — Progress bar count truth
- Audit, don't assume: for 2–3 reference campaigns pull Smartlead's own per-status lead numbers (statistics endpoints) and diff them against the bar's completed / in-progress / not-started / blocked. Fix whichever side is wrong — likely candidates: the `max(...)` base blending contact-record vs platform totals, PAUSED folded into in-progress, statuses the RPC doesn't bucket. One source of truth per segment, labelled if estimated.
- **Done-rule (LIVE):** for the reference campaigns each rendered segment is within ±2 % of Smartlead's own per-status numbers (or exactly equal where the platform gives exact counts), the segments sum to the stated total, and a one-line code comment records which source each segment reads from.

### Step 6 — Redundant-code + efficiency sweep
- Over ONLY the campaign-detail surface (campaignPageHTML + its hydrate functions + the cockpit endpoints touched above): delete dead branches and duplicate hydrations, collapse repeated fetches (one detail payload, not N), ensure every SWR cache actually short-circuits, remove leftover TEMP diag routes (`vpdebug`, commits 4821164/3264971) if Bjion confirms they're done with.
- **Done-rule:** no behaviour change (Steps 1–5 done-rules still pass live after the sweep), the network tab shows no duplicate cockpit calls on one detail open, and the diff is net-negative or neutral in lines on the touched surface.

### Step 7 — Tester audit: 9/10 on three dimensions
- Run a Workflow panel: **front-end tester** (DOM, hydration races, error states, perceived speed) + **back-end tester** (endpoint latency, caching, thread-safety, data provenance) + one **data-validity auditor** who re-diffs live numbers against Smartlead/Supabase. Each scores the detailed campaign view /10 on **Stability**, **Data validity**, **Code efficiency**, with concrete findings.
- Apply the highest-impact findings, redeploy, re-vote. **Done-rule:** every dimension averages **≥ 9.0 with no individual score below 8**, within max 3 fix-and-revote rounds (cap-hit = FAILED with last scores).

### Step 8 — Final live re-audit
- Re-walk all seven original complaints on the live UI and try to recreate each (within the safety rails). **Done-rule:** none reproduce — status controls work, sequence copy renders or fails loudly with retry, all variants cycle, the breakdown answers fast from Supabase, the progress bar matches the platform — and `/api/version` confirms the audited commit is the one serving.

## FINAL REPORT

One line per step — DONE / SKIPPED (already passed) / FAILED (reason + retry count) — the panel's final three-dimension scores per tester, and the live-host commit hash the verification ran against.
