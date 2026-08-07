---
name: campaigns-perf-loadspeed
description: Static orchestration skill that fixes the load-speed and navigation glitchiness on the Navreo signals tool (app/campaigns.html + app/server.py) — the page jumps around because data loads in serial waterfalls and paints only after everything resolves. Six fixed steps (parallelise fetches, paint a skeleton shell, cache semi-static endpoints, de-dupe redundant refetch, gzip the server, verify it's faster), each with a checkable done-rule, plus a Loop Training Mode toggle (ON by default). Use when the user says "fix the campaigns page speed", "the tool is glitchy/slow to load", "make navigation smoother", "run the perf pass", or "/campaigns-perf-loadspeed".
---

# campaigns-perf-loadspeed

Fix the load-speed and navigation feel of the signals tool. **Goal: the page paints instantly and content settles in place instead of jumping around as data trickles in.**

Files: `app/campaigns.html` (all UI + fetch logic) and `app/server.py` (JSON API + static server). Verify against the running app at `http://localhost:7901/app/campaigns.html`.

**Root cause (already diagnosed — don't re-diagnose, fix):** every view (`renderList`, `renderDraftCampaign`, the wizard) runs 3–5 `await fetch()` calls **in serial**, sets `main.innerHTML` **only after all of them resolve**, uses `cache:"no-store"` on every call, refetches the same endpoints across views, and the server gzips nothing. Net effect: blank screen → everything pops in at once → layout shift.

---

## ⚙️ LOOP TRAINING MODE  →  **OFF**

Flip it by editing this one line:

    LOOP_TRAINING_MODE = OFF       # ON = approve every step · OFF = run autonomous

**When ON**
- Pause at the end of **every** step and wait for my explicit approval before starting the next.
- Before running a step, check its done-rule first. **If it already passes, skip it** — say so and move on.
- Only (re-)run steps that fail their done-rule.
- Retry cap still applies (below). Never loop a step forever.

**When OFF**
- Run all steps autonomously, no pauses.
- Still check every step's done-rule and still honour the retry cap. Report at the end, not between steps.

**Retry cap (both modes):** any single step retries **max 3** times against its done-rule. On cap-hit, stop that step, record it FAILED with the reason, keep going, and surface it in the final report. Never silently exceed.

---

## THE GOAL

Navigating the app should feel instant and stable. Done means: **each view paints a skeleton immediately, its data loads in parallel (not serially), semi-static data is cached so it isn't refetched on every navigation, and the same endpoint is never fetched twice in one navigation** — and a before/after measurement proves the main views are faster than they are now. No behaviour changes, only speed and stability.

**Convention (reuse, don't reinvent):** keep the existing `DB.*` / `window._clients` in-memory cache pattern that's already used for `campaignDrafts`, `dests`, and `_clients` — extend it, don't replace it. Keep the same `main.innerHTML = \`…\`` render approach; just paint it in two passes (shell first, hydrate after).

---

## THE STEPS

### Step 1 — Parallelise the fetch waterfalls
- In `renderList()` (~line 924), `renderDraftCampaign()` (~line 245), and the wizard prime (~line 1685), collapse the chains of serial `await fetch()` into a single `await Promise.all([...])`. Endpoints that don't depend on each other's results must fire together.
- Done-rule: none of those three functions contain two or more **consecutive** top-level `await fetch(` statements — each cluster is wrapped in `Promise.all`. Check: `grep -n "await fetch" campaigns.html` shows no back-to-back independent awaits in those functions; the views still render identical content. Anchors: `campaigns.html:924`, `:245`, `:1685`.

### Step 2 — Paint a skeleton shell first, hydrate after
- Split each of `renderList` / `renderDraftCampaign` into: (a) set `main.innerHTML` to a lightweight skeleton (same overall layout boxes with fixed/min heights and muted placeholders) **synchronously before any await**, then (b) fill the real values once `Promise.all` resolves.
- Reserve height on the stat rows, the list rows, and the tab body so real content **swaps in place** rather than pushing layout down.
- Done-rule: on hash change, something visible paints before the network resolves (verify with `preview_snapshot` immediately after navigation), and the layout does not visibly jump when data arrives (compare two `preview_snapshot`s ~before/after hydrate — the container boxes keep the same positions). Anchors: `main.innerHTML =` at `:277`, `:968`, `:1075`.

### Step 3 — Cache semi-static endpoints (stop refetching every navigation)
- `/api/clients`, `/api/outreach-destinations` (and `/api/campaign-drafts` where already cached in `DB`) are near-static within a session. Fetch each **once per session** into the existing `DB.*` / `window._*` store and reuse it; only bypass the cache on an explicit user refresh or after a mutation to that resource.
- Drop `cache:"no-store"` on these GETs so the browser can also cache them.
- Done-rule: navigating list → campaign → list refetches `/api/clients` and `/api/outreach-destinations` **at most once** total (verify with `preview_network` — count requests across a round-trip). Data still updates after a create/edit that mutates the cached resource. Anchors: `_clients` cache at `:931`, `DB.dests` at `:252`.

### Step 4 — De-dupe redundant per-navigation refetch
- `/api/sources` and `/api/lead-counts` are fetched in `renderList`, again in `renderDraftCampaign`, and again in the wizard. Add a tiny in-flight/short-TTL request cache (e.g. a `cachedGet(url)` helper that memoises the promise for the current navigation) and route those repeated GETs through it.
- Done-rule: a single navigation into a campaign detail fires `/api/sources` and `/api/lead-counts` **once each**, not two or three times (verify with `preview_network`). Numbers shown are unchanged. Anchors: `/api/sources` at `:264 :485 :938 :1194`, `/api/lead-counts` at `:271 :940`.

### Step 5 — Gzip the server responses
- In `server.py`, gzip HTML and JSON responses when the request sends `Accept-Encoding: gzip` (set `Content-Encoding: gzip`, adjust `Content-Length`). Cover both the static file path and the JSON writer at `:3078`.
- Done-rule: `curl -s -H "Accept-Encoding: gzip" -o /dev/null -w "%{size_download}\n" http://localhost:7901/app/campaigns.html` returns markedly fewer bytes than the uncompressed ~195 KB, the response carries `Content-Encoding: gzip`, and the page still loads clean in the browser (no console errors). Anchor: JSON writer `server.py:3078`, static file serve path.

### Step 6 — Prove it's faster (before/after)
- Capture a baseline **before** starting (or from git stash of the old file) and an after: time-to-first-paint and time-to-fully-loaded for (a) the campaigns list and (b) a campaign detail view. Use `preview_eval` with `performance.now()` around the render, or Navigation Timing, and `preview_network` request counts.
- Done-rule: **after < before** on first-paint for both views, total request count per navigation is lower (Steps 3–4), and transferred bytes are lower (Step 5). Record the numbers in the final report. If any metric isn't better, that step's fix is incomplete — loop back within the retry cap.

---

## HOW TO RUN

1. Read the mode line above. If **ON** (default), work one step at a time and stop for my approval after each; skip any step whose done-rule already passes. If **OFF**, run all six in order without pausing.
2. Start the app if it isn't up (`preview_start`, serve `app/` on `:7901`). Capture the Step 6 baseline **first** so you have a before-number.
3. For each step: make the edits, then check the done-rule — run the grep/curl assertions and, for the visual/timing steps, use `preview_snapshot` / `preview_network` / `preview_eval` against `http://localhost:7901/app/campaigns.html`. Retry up to 3× on failure, then mark FAILED and continue.
4. After any `campaigns.html` / `server.py` change, reload the preview and check the console before calling the step done. Never claim a step passed without running its assertion.

## OVERALL DONE-RULE

- Waterfalls are parallelised (Step 1), every view paints a skeleton before data and doesn't jump on hydrate (Step 2), semi-static + repeated endpoints are cached/de-duped (Steps 3–4), responses are gzipped (Step 5).
- Step 6 before/after shows **faster first-paint, fewer requests, and fewer bytes** on both the list and detail views — with the numbers recorded.
- App behaviour is unchanged: same content, no console errors, server boots clean.
- Final report: one line per step — DONE / SKIPPED (already passed) / FAILED (with reason) — plus the before/after table.
