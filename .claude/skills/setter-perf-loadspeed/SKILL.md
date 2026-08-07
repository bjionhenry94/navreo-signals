---
name: setter-perf-loadspeed
description: Static orchestration skill that makes the Appointment Setter page (app/setter.html + app/setter.py) load close to instantly — parallelise the serial init, defer the on-load reply-sweep off the critical path, drop the redundant double queue-fetch, split/cache/minify inline assets, and cut the backend N+1 external calls — then deploy live and prove it faster with a 7-tester QA panel. One fixed step list, each step with a checkable done-rule, retry caps, and a Loop Training Mode toggle (ON by default). Use when the user says "make the setter page faster", "the setter loads slow", "run the setter perf pass", "speed up the appointment setter", or "/setter-perf-loadspeed".
---

# setter-perf-loadspeed

Make the Appointment Setter page — its conversations, dialogs, and windows — load close to instantly on the **live Render host**, with no feature lost. Static loop: fixed steps, each has a done-rule, Training Mode controls the pauses.

**Files (deploy repo `/Users/bjionhenry/navreo-signals` — push to `main` = live on Render):** `app/setter.html` (2,372 lines / 120K, fully inline) and `app/setter.py` (6,091 lines, the queue/thread/poll endpoints). **NEVER touch the iCloud copy under `Mobile Documents` — it reverts edits and is never live** (memory `signals-deploy-repo`, iCloud≠live). Measure everything against `https://navreo-signals.onrender.com/app/setter.html`.

## ⚙️ LOOP TRAINING MODE  →  **OFF**   ← flip this one line to ON to approve every step

    LOOP_TRAINING_MODE = OFF       # ON = approve every step · OFF = run autonomous

**When ON:** pause at the end of **every** step and wait for explicit approval before the next. Before running a step, check its done-rule first — **if it already passes, say "Step N already passes, skipping" and move on.** Only (re-)run steps that fail. Show what you're about to do before doing it.

**When OFF:** run all steps end-to-end, no pauses. Done-rule checks, skip-if-passing, and retry caps stay identical — only the pauses go. Report at the end.

**Retry cap (both modes):** each step retries **max 3** times against its done-rule. On cap-hit: record the step FAILED with the numeric gap, continue to the next step if it doesn't depend on the failed one, surface every FAILED step in the final report. **Never silently exceed the cap. Never declare the skill done on a cap-hit — a cap-hit is reported as FAILED with the gap.**

---

## THE DONE-RULE (single source of truth)

> On the live host post-deploy: **initial load ≤ 2.5s** (DOMContentLoaded) **AND every subsequent action ≤ 500ms** perceived (open-a-conversation, switch-a-pill, open-a-dialog), read from the browser Network/Performance panel — never a "feels faster" claim. **AND** a 7-tester QA panel scores median improvement **≥ +3** with **every** after-score **≥ 8/10**. **AND** no feature is lost (full live-UI walk passes). **AND** the double queue-fetch and serial-blocking-poll are gone from the deployed code. All five, or it isn't done.

**Hard gates (both modes, non-negotiable):**
- **No feature removed, no returned data changed — only how fast it loads.**
- **The automatic reply-check MUST still fire on every page load** (owner ruling 2026-07-15). Deferring it *off the critical path* is allowed; **removing it is not.**
- **No destructive schema changes** to `setter_queue` or any table — a row-dict key without a matching column dies silently (memory `setter_queue-schema-freeze`).
- **Any new POST/PATCH route reads `self._post_body`, never `rfile.read`** — an undrained body 501s the keep-alive socket (memory `server-POST-body-drain`).

---

## Ground truth (verified 2026-07-15 — re-verify in Step 1, line numbers drift)

- **`app/setter.html:2356` `init()`** runs serially: `await loadAgentsAndCampaigns()` → `await loadQueue()` → `await fetchJson("/api/setter/poll", {method:"POST"})` (a **live Smartlead reply sweep**) → `setTimeout(2500ms)` → `loadQueue()` **again**. Queue loads twice; the live sweep sits on the load path.
- **`app/setter.html:783` `loadQueue()`** fires the queue endpoint **twice in parallel every reload**: `/api/setter/queue?status=…&limit=200` (current pill) + `/api/setter/queue?limit=200` (all-statuses copy, only used for client-side search). Double payload.
- **`app/setter.html`** is fully inline: 3 `<script>`, 2 `<style>` blocks, served whole every load — no split, no browser cache benefit.
- **`app/setter.py` (6,091 lines)** backs the queue/thread endpoints: `GET_ROUTES`/`POST_ROUTES` dicts, paginated Smartlead loops (`for _ in range(max_pages)` ~:1166), per-row thread hydration, Calendly availability fetches (~:1350–1453). Likely N+1 external calls per queue load. `fetchJson` helper at `:723`; queue action/redraft/poll POST routes at `:1517–1620`.
- **`app/server.py`** static server + JSON API; setter routes dispatched at `:12970` (GET) and `:13375` (POST); `/api/setter/poll` bg thread at `:10377`, `_setter_poll_bg`. gzip status **unknown — Step 1 must check** whether responses are compressed.
- Deploy: `git push origin main` → Render auto-deploy. Live-verify = poll the deployed artifact, not the local file (memory `setter-live-verify-auth`, `signals-deploy-repo`).
- Session cookie for authed live checks: mint `navreo_session` from the SRK in `~/.navreo-keys.env` (memory `signals-session-cookie-mint`); `/api/version` is auth-gated (401 headless — not a failure).
- **Unknown → resolve in Step 1:** exact current line numbers; whether the queue GET already caches anything server-side; whether Calendly/thread hydration is per-row or batched; gzip on/off.

---

## THE STEPS

### Step 1 — Re-verify ground truth + capture the live BASELINE
- Confirm every Ground-truth bullet against current code (`grep -n` the anchors; line numbers drift). Resolve the unknowns: is the queue GET cached server-side? is thread/Calendly hydration per-row (N+1) or batched? is gzip on?
- On the **live host** `https://navreo-signals.onrender.com/app/setter.html`, in the browser, measure and **write down**: DOMContentLoaded time, and perceived time for (a) open-a-conversation, (b) switch-a-pill, (c) open-a-dialog — read from the Network/Performance panel. This is the immutable BASELINE.
- **Done-rule:** (a) each Ground-truth anchor confirmed at its current line or corrected; (b) the three unknowns answered in writing; (c) baseline numbers recorded for load + all three actions, sourced from the Network panel (not a guess). Retry cap 3.

### Step 2 — Parallelise `init()` and defer the reply-sweep off the critical path
- Collapse `init()`'s serial chain: fire `loadAgentsAndCampaigns()` and `loadQueue()'`s first paint together (`Promise.all`) instead of one-after-the-other. Move the POST `/api/setter/poll` sweep **off the critical path** — fire-and-forget AFTER first paint, then reconcile with one delayed `loadQueue()` as today. **The sweep must still fire on every load** (owner ruling — deferred, not removed).
- **Done-rule:** (a) `init()` no longer awaits `loadAgentsAndCampaigns` and `loadQueue` back-to-back — they resolve in parallel; (b) `/api/setter/poll` is still called on every load (grep confirms the call survives) but does not block first render; (c) the reply-check still visibly runs (new replies still appear after load in the live walk). Retry cap 3.

### Step 3 — Drop the redundant double queue-fetch
- `loadQueue()` fetches the queue twice (current-pill + all-statuses). Serve the search need without a second full round-trip: derive the search corpus from the already-fetched rows, OR make the all-statuses copy lazy (fetched only when a search actually starts), OR have the server return both slices in one response. **No returned data may change** — search must still match rows under other pills.
- **Done-rule:** (a) a normal page load / pill switch issues **one** `/api/setter/queue` request, not two (verify with the Network panel across a load + pill switch); (b) searching across all pills still finds a match sitting under a different pill (live test). Retry cap 3.

### Step 4 — Split / cache / minify the inline assets so the shell paints first
- Extract the large inline `<script>`/`<style>` into cacheable static files served with far-future cache headers (reuse `/app/shell.js`-style serving already in server.py), so the browser caches them across loads and the HTML shell paints before the JS parses. Minify where cheap. Keep behaviour identical.
- **Done-rule:** (a) the setter HTML shell paints visible layout before the queue data resolves (browser screenshot immediately after navigation shows structure, not blank); (b) the extracted asset(s) return a cache header (`curl -I` on the deployed asset shows `Cache-Control`); (c) no console errors on load. Retry cap 3.

### Step 5 — Cut the backend N+1 + enable gzip
- In `setter.py`, batch or cache the per-row thread hydration / Calendly availability calls so one queue load isn't O(rows) external calls (cache within the request, or fetch in one batched call, or defer non-visible-row hydration). If gzip is off on JSON/static responses in `server.py`, turn it on. **No schema change; any new POST/PATCH route reads `self._post_body`.**
- **Done-rule:** (a) one queue load makes measurably fewer external Smartlead/Calendly calls than baseline (count in `setter.py` logs / instrumentation); (b) the `/api/setter/queue` response is gzip-encoded (`curl -I --compressed` shows `Content-Encoding: gzip`); (c) returned queue data is byte-identical in content to baseline (same rows/fields). Retry cap 3.

### Step 6 — Deploy live + marker-grep the deployed artifact
- `git add -A && git commit && git push origin main`. Wait for the Render deploy to go live (poll the deployed page / a deploy marker — pushing to iCloud is NOT deploying). Reconcile the deploy repo ↔ iCloud copy per memory `signals-deploy-repo` (never let a parallel session's WIP ride along — check `git status` is clean of unrelated changes before commit).
- **Done-rule:** (a) the deployed `setter.html` served from the live host contains the new code — **grep the fetched live artifact confirms the double queue-fetch and serial-blocking-poll are GONE** and the parallelised init is present; (b) the page loads with no console errors on the live host. Retry cap 3.

### Step 7 — Live proof: AFTER measurements + no-regression walk
- On the **live host**, re-measure the exact Step-1 metrics from the Network panel: initial load ≤ 2.5s, and open-a-conversation / switch-a-pill / open-a-dialog each ≤ 500ms perceived. Then walk the whole flow on the rendered page: queue loads, the auto reply-check fires on load, pill + client filters work, and **draft → approve → send actually reaches Smartlead** (read the result back from Smartlead's thread, NOT the app's own "sent" label — memory `setter-approve-nonjson-2xx-send`). Screenshot the rendered evidence.
- **Done-rule:** (a) load ≤ 2.5s AND all three actions ≤ 500ms, each number from the Network panel; (b) every regression-walk item passes on rendered browser state; (c) send delivery confirmed from the Smartlead destination. Any miss = FAILED with the numeric gap. Retry cap 3.

### Step 8 — 7-tester QA panel: before vs after
- Spawn **7 QA-tester subagents**. Give each the BASELINE screenshots/timings (before) and the live post-deploy page (after). Each scores perceived speed 1–10 for before and after, independently. Compute the median improvement.
- **Done-rule:** median (after − before) improvement **≥ +3** AND **every** after-score **≥ 8/10**. Below either bar = FAILED, report the distribution and the gap — do not declare done. Round cap: **max 2** full panel rounds (a second only if a fix landed between them).

---

## Final report (always, both modes)

One summary: each step passed / skipped / FAILED; the **real numbers** — baseline vs after for load + all three actions (ms, from the Network panel), the count of `/api/setter/queue` requests per load before/after, external-call count before/after, gzip on/off, the 7 tester before/after scores + median improvement; artifacts — the deploy commit SHA, the live URL, screenshots of rendered before/after, the Smartlead delivery confirmation; and any FAILED step with its numeric gap. Name the numbers — "a summary" is not a spec. **If any done-rule fails or any cap is hit, the headline is FAILED with the gap, never done.**

## Hard don'ts
- **Never touch the iCloud copy** under `Mobile Documents` — deploy repo `/Users/bjionhenry/navreo-signals` only, push to `main` = live.
- **Never remove the on-load reply-check** — deferring it off the critical path is the only allowed change (owner ruling 2026-07-15).
- **Never change what data the endpoints return** — this is a speed pass, not a behaviour change. Same rows, same fields.
- **Never make a schema change** to `setter_queue` or any table; **never add a POST/PATCH route that reads `rfile.read`** instead of `self._post_body`.
- **Never declare done from the app's own success label** — read timings from the Network panel and send-delivery from Smartlead's thread.
- **Never report done on a cap-hit or while any of the five done-rules fails** — report FAILED with the numeric gap.
- **Never let a parallel deploy-session's WIP ride along in the commit** — verify `git status` before pushing.
