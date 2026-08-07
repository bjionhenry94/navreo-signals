---
name: setter-all-workspaces-loop
description: One static orchestration loop that makes the Appointment Setter manage replies from EVERY workspace added to the tool, not just the three sub-brands (Navreo/Amplifyy/Arnic) that happen to live inside the single "navreo" Smartlead workspace. Federates the setter's queue read and reply intake off the hardcoded WORKSPACE="navreo" pin so any enabled workspace's replies enter the setter — verified in a strict NO-SEND (monitor/is_test) mode that proves management works without a single Smartlead send. Fixed goal → steps → done-rules, retry cap, Loop Training Mode ON by default. Use for "why do only three clients show in the setter", "make every workspace show in the setter", "let any workspace be managed in the setter", or "/setter-all-workspaces-loop".
---

# Setter — All Workspaces Loop

A static, pre-baked loop. Read it top to bottom once; it does not change between runs. Goal, steps, and done-rules are fixed below.

---

## ⚙️ LOOP TRAINING MODE  →  **ON**

Flip this one word to change how the whole loop runs. Default is **ON**. To change it later, edit the line above to `→ OFF` (or back to `→ ON`). Nothing else in this file needs touching.

**When ON (default — training):**
- **Pause at every step.** Do the step, show the done-rule result, then STOP and wait for Bjion's explicit approval before moving to the next step. Never chain two steps in one turn.
- **Skip any step that already passes its done-rule.** Check the done-rule first; if it's already green, say "Step N already passes, skipping" and move on. Don't redo finished work.
- **Only re-run steps that FAIL.** If a step's done-rule fails, fix and re-run *that step only* — not the whole loop.
- **Retry cap applies** (see below).

**When OFF (autonomous):**
- **No pauses.** Run every step start to finish without waiting for approval.
- **Keep every done-rule check.** A failed done-rule still blocks progress to the next step.
- **Keep the retry cap.** Autonomous ≠ infinite.
- Report once at the end: which steps ran, which were skipped, which failed.

**Retry cap (both modes):**
- Max **3 attempts per step**. On the 3rd failure, STOP the loop, report the step, its done-rule, the last failure output, and the best guess at the blocker. Never attempt a 4th.
- Max **2 full rounds** (Step 1 → Step 6). After round 2, stop and report even if not everything is green.
- Never widen scope to "fix it another way" after a cap is hit. Report and stop.

---

## 🎯 Goal

Any workspace added to the tool can be **managed in the Appointment Setter** — its replies enter the setter queue and its client name appears in the client filter — exactly the way the campaigns page already federates over every enabled workspace. Today only **Navreo, Amplifyy, Arnic** show, and that is not an allowlist: they are the three sub-brands that live inside the *one* shared `navreo` Smartlead workspace. Every other client (Grout, Qwintiq, …) is its own federated workspace whose replies the setter never reads.

## 🔒 Hard safety rails — apply to EVERY step, no exceptions

- **NEVER send to a real prospect. This loop sends nothing, ever.** Every newly-federated (non-`navreo`) workspace row enters the setter as **`is_test = True` / monitor-only**, and `is_test` rows *never* hit Smartlead regardless of dry-run (`_send_reply`, `app/setter.py:2767-2780`). The done-rules assert **zero Smartlead sends** occurred.
- The verification is: *temporarily allow other workspaces' replies in, confirm they appear in the setter, and send nothing.* Do not flip any monitor row to sendable in this loop — that is a separate, explicit decision after the loop proves management works.
- Repo: `~/navreo-signals`. Live-verify recipe: mint a `navreo_session` cookie, poll `/api/version` until the deploy lands (memory: [[signals-live-verify-recipe]]).
- The web instance is a **512MB Render starter**. Do NOT federate the intake by looping every workspace on a web request — that multiplies Smartlead calls and OOM-crash-loops the web process (memory: [[web-instance-oom-crashloop]]). Intake federation belongs in the **poll/cron path**, not the web hot path.
- Client-workspace replies have **no navreo-style backstop** — they arrive via the Make webhook into `replies` tagged with their own workspace (memory: [[client-workspace-reply-backstop-gap]]). So intake mostly *reads rows that already exist*; you are widening a filter, not building a new puller.

## 📍 Where the code actually is (settled — do not re-derive)

The three-client symptom has ONE cause: the setter is hard-scoped to a single workspace.

1. **The gate — `app/setter.py:71`:** `WORKSPACE = "navreo"`. Repeated as `workspace=eq.{WORKSPACE}` at ~40 sites. Two are load-bearing for the symptom:
   - **Queue read — `_fetch_queue_rows()`, `app/setter.py:6258`** (query built there, served by `queue_response()` ~6501 → `/api/setter/queue`). This is what fills the "Needs review / Sent / …" list, and the dropdown is derived from it.
   - **Reply intake — `run_poll()`, `app/setter.py:4446`** — `replies WHERE workspace=eq.navreo`. This decides which replies ever become `setter_queue` rows.
2. **The frontend needs NO change.** `renderClientFilter()` (`app/setter.html:1787-1801`) builds the dropdown from `distinct(clientForRow(row))` over whatever the queue returns; `clientForRow()` (`1116-1131`) already generalises to any client. Add workspaces to the queue and the dropdown grows on its own.
3. **The pattern to copy — `app/server.py:6587`:** `for w in ws_enabled():` in `_compute_campaigns_unified()`. That federation over `ws_enabled()` (`server.py:846`) is exactly why the campaigns page shows every client and the setter does not.
4. **Tables:** intake source `replies` (has a `workspace` column); UI reads `setter_queue` (`QUEUE_TABLE`, `app/setter.py:73`; upsert conflict key `workspace,smartlead_campaign_id,lead_email,message_id`, ~2844). No-send guard column: `is_test`.
5. **Load-bearing constant sites beyond the two queries:** dedup `_existing_row` (~2663/2672) and KPI counts (~5668/5719). Most other `WORKSPACE` sites already read `row.get("workspace")` and only fall back to the constant — leave those; just make sure per-row work keys off the row's own workspace, never the module constant.

Do not "fix" this in `setter.html`. The renderer is correct.

---

## 🪜 Steps (each has its own machine-checkable done-rule — that is what Loop Training Mode gates on)

**1 · Frame & reproduce (read-only, zero risk).** Mint a session, `GET /api/setter/queue`, confirm every row is `workspace = navreo` and the dropdown shows only the three sub-brands. Then enumerate `ws_enabled()` and find at least one *other* enabled workspace that has ≥1 row in `replies` which is **not** in `setter_queue`.
  - *Done-rule:* written confirmation, pinned to evidence, that (a) the live queue is navreo-only, and (b) a named non-navreo enabled workspace has ≥1 reply not yet in the setter. If (b) can't be found, stop and report — there is nothing to federate yet.

**2 · Federate the queue read.** Parameterise `_fetch_queue_rows()` (`app/setter.py:6258`) so it returns rows across all enabled workspaces (default = all; keep an optional single-workspace filter for callers that want it). Frontend untouched.
  - *Done-rule:* with mixed-workspace rows present in `setter_queue`, `/api/setter/queue` returns >1 distinct `workspace` value and `renderClientFilter()` lists every client present — verified live. No console errors, no 502.

**3 · Federate intake as MONITOR-ONLY (the "temporarily allow in" step).** In the **poll/cron path only**, widen `run_poll()` (`app/setter.py:4446`) to read `replies` for every `ws_enabled()` workspace (or `workspace=in.(…)`), and stamp every non-`navreo` row **`is_test = True`** on upsert so it can never send. `navreo` rows keep their existing behaviour unchanged.
  - *Done-rule:* one poll run ingests ≥1 non-navreo reply into `setter_queue`; every newly-ingested non-navreo row has `is_test = True`; the navreo queue count is unchanged (no regression); the run did not run on a web request. Verify the poll doesn't spike web-instance memory.

**4 · De-pin the load-bearing per-row sites.** Make dedup (`_existing_row`, ~2663/2672), KPI counts (~5668/5719), and any send/thread lookup key off **each row's own `workspace`**, not the `WORKSPACE` constant. Leave the ~40 sites that already fall back correctly.
  - *Done-rule:* a non-navreo row round-trips through dedup without duplicating or colliding with a navreo row of the same campaign/email; KPI counts reflect all workspaces; no code path silently drops a non-navreo row back to `navreo`.

**5 · Live verify in the setter — appears, sends nothing.** With Steps 2-4 deployed (poll `/api/version`), open the live setter: confirm at least one **new** client (a non-navreo workspace) appears in the dropdown and its replies are in the queue, reviewable end to end.
  - *Done-rule (both halves required):*
    - **Appears:** the new client shows in the client filter and its reply(ies) render in the queue with full conversation history.
    - **Zero sends:** every newly-federated row is `is_test = True`; a Smartlead-write audit over the test window shows **0 sends** for any non-navreo row; attempting a send on such a row is refused by the `is_test` guard, not delivered.

**6 · Reversibility & hand-off.** The monitor gate is deliberate: management is proven, sending for new workspaces stays OFF until Bjion explicitly clears it. Document, in the PR/commit message and to Bjion in chat, (a) the one flag that flips a workspace from monitor-only to sendable, and (b) the one-line revert that restores navreo-only scoping if needed.
  - *Done-rule:* the flip-to-sendable path and the revert path are each a single, named, documented change; nothing in this loop has already flipped a new workspace to sendable.

---

## ✅ Overall done-rule (the loop is finished when ALL hold)

1. Any `ws_enabled()` workspace's replies enter `setter_queue` and its client appears in the setter's client filter.
2. Every newly-federated (non-navreo) row is `is_test = True` / monitor-only.
3. A Smartlead-write audit over the whole run shows **0 sends** — nothing was sent to any prospect, real or test, from a non-navreo workspace.
4. The navreo experience is byte-for-byte unchanged (queue count, sends, KPIs).
5. Steps 5-6 verified live against the deployed build, and the revert path is documented.

If a retry or round cap is hit before all five hold, STOP and report against this list — do not improvise a different fix.
