---
name: setter-speed-stability
description: Static orchestration skill that fixes the five live Appointment Setter bugs in one pass - regenerate taking 30s+ (target 5-10s), the Send Follow-Up section auto-opening on every reload, sends erroring with "Couldn't send the reply - Request failed (502)" / blanking every conversation / crashing the tool, and the message pane jumping around as conversation history loads. One fixed step list, each step with a checkable done-rule, retry caps, and a Loop Training Mode toggle (ON by default). Use when the user says "the setter is buggy", "fix the setter bugs", "sends are 502ing", "the setter UI jumps around", "run the setter stability pass", or "/setter-speed-stability".
---

# setter-speed-stability

Make the live Appointment Setter fast and calm: regenerate in 5–10s, reload lands on a quiet page, sends never 502 or blank the queue, and the message pane never jumps. Static loop — fixed steps, each has a done-rule, Training Mode controls the pauses.

**Files (deploy repo `/Users/bjionhenry/navreo-signals` — push to `main` = live on Render):** `app/setter.html` (frontend, fully inline) and `app/setter.py` (queue/thread/send/redraft endpoints), dispatched via `app/server.py`. **NEVER touch the iCloud copy under `Mobile Documents` — it diverges, reverts edits, and is never live.** Measure everything against `https://navreo-signals.onrender.com/app/setter.html` (mint a `navreo_session` cookie from the SRK in `~/.navreo-keys.env`; poll `/api/version` to confirm a deploy landed).

## ⚙️ LOOP TRAINING MODE  →  **OFF**   ← flip this one word to ON to approve every step

    LOOP_TRAINING_MODE = OFF       # ON = approve every step · OFF = run autonomous

**When ON:** pause at the end of **every** step and wait for explicit approval before continuing. Before running a step, check its done-rule first — **if it already passes, say "Step N already passes, skipping" and move on.** Only (re-)run steps that fail. Show what you're about to do before doing it.

**When OFF:** run all steps end-to-end, no pauses. Done-rule checks, skip-if-passing, and retry caps stay identical — only the pauses go. Report at the end.

**Retry cap (both modes):** each step retries **max 3** times against its done-rule. On cap-hit: record the step FAILED with the numeric gap, continue to the next step if it doesn't depend on the failed one, and surface every FAILED step in the final report. **Never silently exceed the cap. Never declare the skill done on a cap-hit.**

---

## THE DONE-RULE (single source of truth)

> On the live host post-deploy, all five, or it isn't done:
> 1. **Regenerate:** 5 timed regenerates on real Needs-review rows — **p50 ≤ 10s, max ≤ 15s, 0 errors** (measured client-side, POST → `done` status).
> 2. **Quiet reload:** 3 consecutive page reloads — the Send Follow-Up section **stays closed** every time (opens only by user click).
> 3. **Sends don't crash:** 3 consecutive real sends — **0 × 502, 0 × queue-blank**; a deliberately failed send shows a plain-English inline error while **every conversation stays on screen**.
> 4. **No jumping:** opening a conversation and scrolling while history loads causes **no visible layout shift** (thread-pane CLS ≈ 0; scroll position held).
> 5. **Overall:** measured perf (regen time + send round-trip + open-a-conversation) improved **≥ 30%** vs the Step-1 baseline, AND a 7-tester QA panel scores the live experience with **every after-score ≥ 9/10**.

**Hard gates (both modes, non-negotiable):**
- **No feature removed, no returned data changed** — same rows, same fields, just faster and calmer.
- **No destructive schema changes** to `setter_queue` or any table (schema-freeze memory: an unmatched row-dict key dies silently).
- **Any new POST/PATCH route reads `self._post_body`, never `rfile.read`** — an undrained body 501s the keep-alive socket.
- **Never declare send success from the app's own label** — read delivery back from Smartlead's thread.
- **Row ids are NOT stable** (re-intake deletes+reinserts) — identify a reply by email+message_id, captured at render time.

**Live-send permission (granted by Bjion in the brief):** when a step needs a real send, pick a **"not interested"-type reply** and send **"No worries."** — that exact class of reply, nothing else, no other lead contact.

---

## Ground truth (from sibling skills, verified 2026-07-15/16 — re-verify in Step 1, line numbers drift)

- **Regen slowness:** `_redraft_sync` (`app/setter.py`) runs **three serial gpt-5-mini calls** — classify (~1237), draft (~1103), proofread (~1313) — no `reasoning_effort` tuning, no token cap; the chain self-measures at 25–42s. `http_json` (`app/server.py:213`) uses `urlopen(timeout=60)`, nothing retries. `runRedraftJob` (`setter.html:~3475`) sleeps **2000ms before its first status check** — a hard 2s floor.
- **502s:** Render's proxy 502s when a request outlives its window or the (effectively serial) Python server is blocked by another long call — the send path does live Smartlead round-trips inline. Suspects: `_send_reply` blocking on Smartlead, redraft jobs hogging the worker, an undrained POST body. **Step 1 must pin which.**
- **Queue-blank on error:** the frontend re-renders the queue from a fetch response; a non-2xx/HTML error body on that path can clear the list. Repro and pin in Step 1.
- **Send Follow-Up auto-open + layout jump:** frontend-only behaviours in `setter.html` — find the open-by-default trigger and the unreserved thread-pane heights in Step 1.
- Deploy: `git push origin main` → Render auto-deploy; live-verify per the signals live-verify recipe. Check `git status` is clean of unrelated WIP before committing.

---

## THE STEPS

### Step 1 — Re-verify ground truth + capture the live BASELINE
- Confirm every Ground-truth bullet against current code (`grep -n` the anchors). Pin the three unknowns in writing: (a) the exact cause of the send 502, (b) the exact code path that blanks the queue on a failed send, (c) what opens Send Follow-Up on load and what makes the pane jump.
- On the live host, measure and **write down**: time of one regenerate, one send round-trip, one open-a-conversation (Network panel, not a guess); screenshot the Send Follow-Up state right after reload and the pane mid-history-load.
- **Done-rule:** every anchor confirmed/corrected; all three unknowns answered with file:line; baseline numbers + screenshots recorded. Retry cap 3.

### Step 2 — Regenerate in 5–10s
- Collapse the three serial LLM calls: merge classify+draft+proofread into fewer calls or run independent ones in parallel; set `reasoning_effort`/token caps where quality survives; add one retry on timeout in `http_json` for the redraft path. Cut the 2000ms pre-poll sleep to ≤300ms with fast-interval polling.
- **Done-rule:** 5 timed regenerates locally-triggered against live code: p50 ≤ 10s, max ≤ 15s, 0 "read operation timed out". Draft quality spot-check on 2 outputs reads as good as before. Retry cap 3.

### Step 3 — Quiet reload: Send Follow-Up stays closed
- Make the section **collapsed by default** on load; it opens only on user click. If any state persists, persist "closed" — never force-open on render.
- **Done-rule:** 3 consecutive reloads, section closed each time; clicking it still opens and works. Retry cap 3.

### Step 4 — Sends that never 502 and never blank the queue
- Fix the pinned 502 cause: move the inline Smartlead send off the blocking path (background job + status poll, mirroring the redraft pattern) or bound it well inside the proxy window with a retry. Frontend: a failed send must show a plain-English inline error on that row and **leave the rendered queue untouched** — never re-render the list from an error response.
- **Done-rule:** (a) 3 real sends, 0 × 502 (use the "not interested" → "No worries." permission); (b) one forced-failure send (bad payload or stubbed 502) leaves every conversation on screen with an inline error; (c) delivery of the real sends confirmed from Smartlead's thread. Retry cap 3.

### Step 5 — No jumping: stable message pane
- Reserve space before history resolves: fixed/min-height skeleton for the thread pane, explicit heights on avatars/attachments, `overflow-anchor` or manual scroll-position restore so late-loading history never shoves the composer or the scroll position. Sending a message must not reflow the pane.
- **Done-rule:** open-a-conversation + scroll during load + one send, screen-recorded or stepped-screenshotted: no visible shift, composer stays put, scroll position held. Retry cap 3.

### Step 6 — Deploy + live proof of the whole done-rule
- Commit + `git push origin main`; confirm the deploy via `/api/version`. Then run the **entire DONE-RULE (items 1–4) on the live host** and re-measure the Step-1 metrics for item 5's ≥30% check. Screenshot the evidence.
- **Done-rule:** done-rule items 1–4 pass live; combined metrics ≥30% better than baseline, each number named. Retry cap 3.

### Step 7 — 7-tester QA panel
- Spawn 7 QA-tester subagents. Give each the Step-1 baseline evidence (before) and the live post-deploy page (after). Each independently scores the live experience 1–10 on speed, calmness (no jumping), and error-free sending.
- **Done-rule:** **every** after-score ≥ 9/10. Below the bar = FAILED with the distribution; fix, then at most **1** more panel round. Round cap: 2.

---

## Final report (always, both modes)

One summary: each step passed / skipped / FAILED; the real numbers — regen p50/max before vs after, send round-trip before vs after, open-a-conversation before vs after, the ≥30% math, 502 count across live sends, reload-test results, the 7 tester scores; artifacts — deploy commit SHA, live URL, before/after screenshots, Smartlead delivery confirmations. **If any done-rule fails or any cap is hit, the headline is FAILED with the gap, never done.**

## Hard don'ts
- **Never touch the iCloud copy** — deploy repo `/Users/bjionhenry/navreo-signals` only.
- **Never contact any lead beyond the granted permission** — "not interested"-type replies answered with "No worries.", nothing else.
- **Never change what data the endpoints return, never schema-change `setter_queue`, never read `rfile.read` on a POST/PATCH.**
- **Never trust the app's own success label** — timings from the Network panel, delivery from Smartlead's thread.
- **Never re-render the queue from an error response** — that is the blank-screen bug, not a fix.
- **Never report done on a cap-hit or while any done-rule item fails.**
- **Never let a parallel session's WIP ride along in the commit.**
