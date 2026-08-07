---
name: campaigns-view-stability
description: Static orchestration skill that hardens the CAMPAIGNS LIST view (app/campaigns.html in ~/navreo-signals, live at navreo-signals.onrender.com/app/campaigns.html) against six owner-reported bugs — stale "Review N" badge after dismiss/in-progress (plus yellow In-progress count), an "All" option in the status filter, count-free filter labels, variance bars in almost every "Why?" panel, 100%-complete campaigns leaking through the Active filter, and status-blind search — then runs a front-end + back-end tester panel that must score the surface 9/10+ on Stability, Data validity, and Code efficiency before the loop can close. Every done-rule is verified on the LIVE UI. Includes a Loop Training Mode toggle (ON by default). Use when the user says "run the campaigns view stability loop", "fix the six campaigns-view bugs", or "/campaigns-view-stability".
---

# campaigns-view-stability

Harden the **campaigns list view** (`app/campaigns.html` in `~/navreo-signals`, backed by `app/server.py`) — the list/filter/search surface, **not** the campaign detail page. Six fixed bug-fixes, one expert-panel quality gate. Static loop — the steps below are fixed, each has a done-rule, and Loop Training Mode controls whether you pause between them.

**Ship-and-verify-LIVE law.** iCloud reverts local edits and interruptions count as redeploys, so treat every change as ship-then-verify on **`navreo-signals.onrender.com/app/campaigns.html`**. A local render, a source grep, or a green "success" label is NEVER done-evidence — the only proof is the live rendered DOM / live network panel. Push to the deploy path Render builds from, wait for the redeploy (poll `/api/version`; mint a `navreo_session` cookie to get past the login gate), then verify live.

**No-permanent-actions law (audit & verify).** Never delete leads, never send messages, never write to Smartlead. Dismissing or ack-ing a real optimisation IS a state change — during audits, exercise dismiss/in-progress only on a row you immediately revert, or on the demo/test client. Check `row.status` before anything that could touch a send path.

---

## ⚙️ LOOP TRAINING MODE  →  **OFF**

Flip it by editing this one line:

    LOOP_TRAINING_MODE = OFF       # ON = approve every step · OFF = run autonomous

**When ON**
- Pause at **every** step and wait for my explicit approval before continuing.
- Before running a step, check its done-rule first. **If it already passes, skip it** — say so and move on.
- Only (re-)run steps that fail their done-rule.
- Retry cap applies (see below). Never loop a step forever.

**When OFF**
- Run all steps autonomously, no pauses.
- Still check every step's done-rule and still honour the retry cap. Report at the end, not between steps.

**Retry cap (both modes):** any single step retries **max 3** times against its LIVE done-rule (the panel gate in Step 7 caps at **3 optimise→re-vote rounds**). On cap-hit, stop that step, record it as FAILED with the reason and best result reached, keep going, and surface it in the final report. Never silently exceed.

---

## THE GOAL

On the **live** campaigns list: acting on an optimisation instantly updates its row's badge (dismiss shrinks "Review N"; in-progress shows a **yellow** In-progress count); the status filter offers **All** with **no counts** on any option; the "Why?" panel shows the per-variant variance bars whenever the insight is variant-related (almost always); no 100%-complete campaign hides under Active; and search finds any campaign regardless of the active status filter — with a front-end + back-end tester panel scoring the surface **≥ 9/10 on each of Stability, Data validity, and Code efficiency**.

---

## STEP 0 — Read-only audit + drift gate (blocking)

Reproduce all six issues on the live UI before touching code, and reconcile local source against the deployed build.

- Open `navreo-signals.onrender.com/app/campaigns.html` live; for each of the six issues below, attempt to reproduce it and record PASS (bug confirmed) / CANNOT-REPRO with evidence (DOM read or screenshot). Obey the no-permanent-actions law — revert any dismiss/ack used to test issue 1.
- **Drift check (audited 2026-08-01):** local source already carries three of the six fixes — status select lists `["all","All statuses"]` (`:2798`), `liveBucket` classifies ≥100% completion as `completed` (`:2871–2872`), and the filter fn skips the status gate whenever a search query is present (`:2896`). If the live page agrees, Steps 2/5/6 SKIP; if live disagrees, that's deploy drift — ship what's local first, then re-check. Counts are still baked into filter labels (`:3004`) — Step 3 is expected live work.
- Map the local anchors to the live build: "Review N" badge `:3096–3104`, inline panel + action-state machinery `:4920–4960`, `:5276`, status select `:2798–2799`, per-status counts `:2987–3005`, status normalisation `liveBucket` `:2850–2872` + `liveStatus` shape `:2358`, "Why?" variant bars `whyBarsHTML` `:5225–5273`, list controls/search state `view` `:2366` + filter fn `:2892–2896`. Line numbers rot — treat them as grep hints, not gospel.
- Done-rule: every issue has a recorded repro verdict with live evidence, drift (if any) is recorded, and every anchor above maps to a real element in the source Render actually builds from.

---

## THE STEPS

### Step 1 — Live-updating optimisation badge + yellow In-progress count
- When an action inside a row's optimisation panel is dismissed or put in progress, **recount and re-render that row's badge immediately** (no reload): dismissals drop out of N; in-progress actions render as a separate count, e.g. `Review 2 · In-progress 1`.
- When the in-progress count is > 0, that part of the badge turns **yellow** (use the existing paused/amber token family, e.g. `#DFA000`, not a new colour).
- Done-rule (LIVE): on the deployed page, dismiss a test action → the badge count visibly drops without reload; mark one in-progress → a yellow In-progress count appears on the badge. Both observed in the live DOM, then reverted.

### Step 2 — "All" in the status filter
- The status filter must offer **All** and it must actually widen the list to every status.
- Done-rule (LIVE): live status filter shows an All option; selecting it renders campaigns of every status (spot-check at least one Active, one Paused, one Completed visible together).

### Step 3 — Count-free filter labels
- Remove the per-status numbers from the campaign status filter (the `counts` machinery at `:2987–3005` feeding option labels). Labels read "Active", "Paused", … — no `(123)`. Prune the counting code itself if nothing else consumes it — this stage is about removing redundancy, not hiding it.
- Done-rule (LIVE): no digit appears in any status-filter option/chip label in the live DOM.

### Step 4 — Variance in (almost) every "Why?" panel
- The "Why?" dropdown must render the per-variant variance bars (`whyBarsHTML`, `:5225–5273`) for **every** variant-related insight; only genuinely non-variant insights (e.g. list-audit, unanswered-positives) may omit them.
- Done-rule (LIVE): open ≥5 "Why?" panels across different campaigns live — every variant-related one shows variance bars; any panel without bars is demonstrably a non-variant insight.

### Step 5 — 100%-complete campaigns classify as Completed
- A campaign whose live completion is 100% (all leads finished the sequence — `liveStatus` `completion`/`completed`/`total`, `:2358`) must classify as **Completed** in `liveBucket` (`:2850–2872`) even if Smartlead still labels it ACTIVE — so it leaves the Active filter and appears under Completed.
- Done-rule (LIVE): under the live Active filter, **zero** rows show 100% completion; at least one such campaign is findable under Completed.

### Step 6 — Status-blind search
- Typing in the campaign search must match against **all** campaigns irrespective of the current status filter (search overrides / widens status; sort order intact).
- Done-rule (LIVE): with the filter on Active, searching the name of a known Completed campaign returns it.

### Step 7 — Front-end + back-end tester panel (quality gate)
- Convene **5 testers** (3 front-end, 2 back-end) as parallel subagents (Workflow/Agent tool). Each independently audits the code touched by Steps 1–6 (plus the list-render/filter/search paths around them, and `app/server.py` endpoints the page calls) and returns **three scores /10** with top issues per axis:
  - **Stability** — no crashes, no stale renders, degraded-data paths handled, no OOM-risk sweeps (web is a 512MB Render starter).
  - **Data validity** — counts, statuses, completion %, and variance bars agree with the backing API/Supabase truth; no ghost or double-counted numbers.
  - **Code efficiency** — redundant code removed, no wasted re-renders/refetches, filter/search paths do one pass, dead branches pruned.
- If any tester scores any axis **< 9**: apply the highest-value fixes, redeploy, re-verify Steps 1–6 still pass live, and re-vote. Max **3** optimise→re-vote rounds.
- Done-rule: **every tester scores ≥ 9/10 on all three axes** on the final vote, with the six live done-rules still passing after the last optimisation.

---

## THE VERIFICATION (all LIVE on navreo-signals.onrender.com — DOM/network, not source, not a label)

1. Dismiss updates the row badge instantly; in-progress renders a **yellow** count on the badge (tested then reverted).
2. Status filter has a working **All**.
3. No counts anywhere in the status-filter labels.
4. Variance bars in every variant-related "Why?" panel (≥5 sampled).
5. No 100%-complete campaign under Active; such campaigns surface under Completed.
6. Search finds campaigns of any status while a narrower filter is active.
7. Panel verdict: five testers (3 FE, 2 BE), all ≥ 9/10 on **Stability, Data validity, and Code efficiency**, recorded axis-by-axis.

All seven verified live, or it isn't done.

---

## HOW TO RUN

1. Read the mode line above. If **ON** (default), do **Step 0 first**, then work one step at a time and stop for approval after each; skip any step whose LIVE done-rule already passes. If **OFF**, run Step 0 then Steps 1–7 in order without pausing.
2. For each step: edit the source Render actually builds from (`app/campaigns.html`, `app/server.py` only if a fix truly needs it), push, wait for the redeploy (`/api/version`), then check the done-rule against the live host with `read_page`/screenshot/network panel. Retry up to 3× on live-failure, then mark FAILED and continue.
3. Because interruptions = redeploys, re-confirm the live page after any interruption before calling a step done.

## OVERALL DONE-RULE

- All six fixes in place, the tester panel at **9/10+ on Stability, Data validity, and Code efficiency for every voter**, and each of the **seven live verifications** passing on `navreo-signals.onrender.com`.
- No permanent actions taken at any point: no leads deleted, nothing sent, no un-reverted dismiss/ack on real client data.
- Final report: one line per step (0–7) — DONE / SKIPPED (already passed) / FAILED (with reason and retries used) — plus the seven-check verification ticks and the five panel scores.
