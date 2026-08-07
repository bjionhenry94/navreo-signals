---
name: setter-dismiss-speedup
description: Static orchestration skill that makes the Appointment Setter's Dismiss button feel instant (under 1 second) instead of leaving the user staring at "Dismissing…" wondering if it worked. Frontend-first fix in ~/navreo-signals (app/setter.html doDismiss + app/setter.py route_queue_action) — optimistic row removal with rollback on error, plus an optional backend round-trip trim. One fixed step list, each step with a checkable done-rule, retry caps, and a Loop Training Mode toggle. Use when the user says "run the dismiss speedup", "the dismiss button is slow", "make dismiss instant", or "/setter-dismiss-speedup".
---

# Setter Dismiss Speedup

## ⚙️ Loop Training Mode: **OFF**   ← flip this line to ON to pause at every step

**How the toggle works (read this before running any step):**

- **ON (current setting):** Pause at EVERY step. Show what the step will do, wait for
  Bjion's explicit approval before executing it. After executing, show the done-rule
  check result and wait again before moving on.
- **OFF:** Run all steps autonomously with no pauses. Done-rule checks and retry caps
  still apply exactly as written.
- **Both modes:** Before running any step, first evaluate its done-rule. If it already
  passes, SKIP the step (say so in one line) and move on. Only re-run steps whose
  done-rule fails. Each step may be retried at most **2 times** after its first failure
  (3 attempts total). If a step is still failing after the cap, STOP the loop and report
  what's blocking — never loop forever.

## Goal

Clicking **Dismiss** on a reply in the Appointment Setter must visibly action in
**under 1 second** — the row disappears (or flips to Dismissed) immediately, even if
the network write is still in flight. Cosmetic/optimistic is acceptable; silent data
loss is not (a failed write must visibly restore the row and show an error).

## Ground truth (verified 2026-07-16, don't re-derive)

- Repo: `~/navreo-signals` (push = deploy to Render; iCloud copy is NOT the live app).
- Frontend: `app/setter.html` → `doDismiss()` (~line 1725). Today it: disables the
  button ("Dismissing…") → awaits `POST /api/setter/queue/action {action:"dismiss"}` →
  then `loadQueue()` (full queue refetch) before the row visibly changes.
- Backend: `app/setter.py` → `route_queue_action()` (~line 4151). Dismiss does a
  Supabase **GET** of the row, then `_apply_patch` (**PATCH**) — two sequential
  round-trips over urllib (no keep-alive).
- Known gotchas: schema-freeze (never patch a key that isn't a real column — dies
  silently); new POST routes must read `self._post_body`, never `rfile.read`;
  `_thread_rep_ids` governs any row-count logic since thread-collapse (aa4383d).

## Steps

### Step 1 — Baseline timing (the "before" number)
Start the app against the live host or locally, open the Setter tab, and measure
click-to-visible-change for Dismiss on a test row (use the Browser pane: click, then
time until the row leaves the list / status flips). Also capture the network time of
`POST /api/setter/queue/action` from read_network_requests. Record both numbers.
- **Done-rule:** A written baseline exists with (a) perceived click-to-change seconds
  and (b) the POST's network milliseconds, measured on a real Dismiss click.

### Step 2 — Optimistic frontend dismiss
Edit `doDismiss()` in `app/setter.html`: on click, immediately remove the row from the
local queue state (respecting `_thread_rep_ids` thread-collapse counts) and re-render —
no full `loadQueue()` on the success path. Fire the POST in the background. On failure:
restore the row exactly where it was, re-render, and show the existing
`showError`/`showDetailError` messages. Keep `delete EDITED_DRAFTS[id]` on success only.
- **Done-rule:** In the code, the row-removal render happens BEFORE the fetch resolves,
  and the error path re-inserts the row. No unconditional `loadQueue()` remains in the
  dismiss success path.

### Step 3 — Backend round-trip trim (optional but cheap)
In `route_queue_action()`, for the `dismiss` action only, skip the preliminary GET and
PATCH directly with `?id=eq.{qid}` returning the updated row (Prefer: return=
representation), 404 if zero rows came back. Do NOT touch send/subsequence/save_draft
paths. Respect the schema-freeze rule (only `status` is patched).
- **Done-rule:** Dismiss handles the request with exactly one Supabase call, existing
  behaviour (404 on missing row, 200 `{ok, status:"dismissed"}`) unchanged, and
  `python3 -m pyflakes app/setter.py` (or a syntax check) passes.

### Step 4 — Deploy and live verification (the "after" number)
Commit and push (`push = deploy`), confirm the deploy landed (poll `shell.js`
Last-Modified or the boot ledger — never trust the iCloud copy), then repeat Step 1's
measurement on the LIVE host with the Browser pane: click Dismiss on a test row, time
the visible change, screenshot the row gone, then reload the page and confirm the row
is still dismissed (the write really persisted). Also verify the failure path once if
cheaply possible (e.g. dismiss a row while offline/devtools-blocked → row comes back
with an error).
- **Done-rule:** On the live host, click-to-visible-change is **< 1 second**, the
  dismissal survives a page reload, and the before/after numbers are reported
  side by side.

## Done-rule for the whole loop

All four step done-rules pass, and Bjion has been shown the before/after timing
comparison with live-host proof (screenshot or network log). If Step 3 was skipped
because Steps 2+4 already achieved < 1s, say so explicitly — that still counts as done.
