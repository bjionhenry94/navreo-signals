---
name: signals-verify-jobs-ship
description: Static orchestration skill for the Navreo signals tool — replace the mocked email-verification buttons on deliverability.html with REAL ListMint + MillionVerifier pipelines (export campaign leads → verify → remove confirmed-bad → document), and add a shared background-actions sidebar (shell.js) on deliverability.html + notifications.html that shows every background action's live status so the user is never left guessing. One fixed step list, each step with a checkable done-rule, retry caps, and a Loop Training Mode toggle. Use when the user says "run the verify jobs ship", "fix the real email verification", "add the background actions sidebar", or "/signals-verify-jobs-ship".
---

# Signals: Real Email Verification + Background-Actions Sidebar

## ⚙ Loop Training Mode: **OFF**   ← flip this line to ON to pause at every step

**ON (default):** pause at EVERY step boundary and wait for the user's explicit approval
before continuing. Before starting a step, check its done-rule first — if it already
passes, report "Step N already passes, skipping" and move to the next pause. Only re-run
steps whose done-rule fails. Show what you're about to do before doing it.

**OFF:** run all steps end-to-end with no pauses. The done-rule checks, skip-if-passing
behaviour, and retry caps stay exactly the same — only the pauses go.

**Retry cap (both modes):** each step retries **max 3** times against its done-rule.
On cap-hit: record the step as FAILED with the reason, continue to the next step if it
doesn't depend on the failed one, and surface every FAILED step in the final report.
Never silently exceed the cap. Never declare the skill done on a cap-hit.

**Destructive-action gate (both modes, non-negotiable):** the only leads ever deleted
from a Smartlead campaign are ones a verifier returns as hard-**bad** (MillionVerifier
"invalid", ListMint `invalid` / `catch_all_invalid`). Catch-all-valid / unknown /
risky results are NEVER deleted — they're reported. In Training
Mode ON, additionally show the confirmed-bad list and get approval before the delete.

## Goal

Two user-visible outcomes on https://navreo-signals.onrender.com:

1. **No more mocks.** The "✓ ListMint" / "✓ MillionVerifier → ListMint" buttons on
   `app/deliverability.html` actually verify the campaign's leads and remove
   confirmed-bad ones — with the result documented (counts + who was removed).
2. **Background transparency.** Any action that runs in the background shows up in a
   collapsible right-hand sidebar on `deliverability.html` AND `notifications.html`:
   what was triggered, live status (queued → running → done/failed), final counts.
   It survives scrolling, navigating between the two pages, and reload — because the
   job state lives server-side, not in the tab.

## Ground truth (verified 2026-07-09 — re-verify in Step 1, don't trust blindly)

- Working copy: `~/navreo-signals/` (the git/Render repo). There is ALSO an iCloud copy
  of the app — after any merge, diff-check the two (see memory `signals-deploy-repo`).
  Local dev: `python3 app/server.py`, then `http://localhost:7901/app/deliverability.html`.
- **The verify buttons are a frontend simulation.** `app/deliverability-tab.js:2141`
  `simulateVerify(campId, mode)` fabricates results; buttons rendered at ~:2585-2587
  (`data-act="verify-campaign"`). The user saw "Verify failed: signal is aborted
  without reason" — the mock's failure path, not a real API error. Nothing ever calls
  MillionVerifier and no lead is ever removed.
- **Both verifiers are real and keyed.** `~/.navreo-keys.env` (auto-loaded) has
  `MILLIONVERIFIER_API_KEY` and `LISTMINT_API_KEY` (added 2026-07-09). Keep the UI's
  original two actions: "✓ ListMint" and "✓ MillionVerifier → ListMint" (MV first,
  ListMint confirms catch-alls — ListMint's differentiator is real-time catch-all
  verification with statuses `valid | invalid | catch_all_valid | catch_all_invalid`).
  **ListMint endpoint spec (proven live 2026-07-09, docs:
  listmint.notion.site/Listmint-Clay-API-Docs-27d143e1957380e5b034e17d0c23dcf8):**
  base `https://api.listmint.io/api/`; auth = `?api-key=` QUERY param (header form
  is rejected); `POST /checkAuth` proves the key; `POST /verify-emails?return=true`
  body `{"emails":[...]}` → `results[{email, result}]`. Batches parallelise
  server-side (4 emails ≈ 2.7s). Never guess other endpoints.
- Real mutating deliverability actions go through `liveAction(path, …)`
  (`deliverability-tab.js:681`), which POSTs to `/api/deliverability/<action>`;
  `server.py:~6242` forwards those to the standalone audit service
  (`navreo-email-deliverability-audit.onrender.com`). The verify pipeline does NOT
  belong there — implement it directly in `app/server.py` (it needs Smartlead + MV +
  `app_activity_log`, all of which server.py already talks to).
- Documentation channel exists: `app_activity_log` Supabase table, written via the
  helper around `server.py:782-823` (service-role only, RLS on).
- `app/shell.js` (~274 lines) is loaded by BOTH `deliverability.html:17` and
  `notifications.html:360` — the sidebar goes there so both pages get it for free.
  Careful: notifications.html deliberately guards against unshipped shell.js helpers
  (`notifications.html:490-509`) — keep the sidebar self-contained and additive.
- Smartlead API: 200 req/min cap; lead export/delete endpoints exist (the MCP tools
  `export_campaign_leads` / `delete_campaign_lead` mirror them). MV verification of a
  list is the same flow `lilly-email-verification` uses — reuse its endpoint knowledge.

## Steps

### Step 1 — Re-verify ground truth
Confirm every bullet above against the current code (line numbers drift). Identify the
exact click-handler path for `data-act="verify-campaign"` and the campaign ids currently
flagged (the `uncleanedVerifyCamps` derivation, ~:1052).
Then resolve the ListMint unknown: find the real API base URL + auth header (dashboard
docs; ask the user if unreachable) and run ONE live single-email verification with
`LISTMINT_API_KEY` to prove the key and capture the exact request/response shape.
- **Done-rule:** you can name (a) the function that currently fakes verification,
  (b) the file+line where the buttons dispatch, (c) the app_activity_log write helper
  signature, (d) that both `MILLIONVERIFIER_API_KEY` and `LISTMINT_API_KEY` resolve in
  the server's env, and (e) a captured real ListMint API response for one test email.

### Step 2 — Backend: job registry + real verify pipeline (`app/server.py`)
Build two things:
1. **Job registry.** In-memory dict of background jobs
   `{id, kind, label, status: queued|running|done|failed, started_at, finished_at,
   detail, counts}` + `GET /api/jobs` (all jobs this server session, newest first) and
   `GET /api/jobs/<id>`. Every existing background-thread action that server.py owns
   should register here too if trivial to wire — but the verify job is the required one.
2. **`POST /api/verify-campaign` body `{campaign_id, mode}`** where mode is
   `listmint` (ListMint on every lead) or `mv` (MillionVerifier bulk first, then
   ListMint re-checks only MV's catch-all/unknown results). Spawns a thread that:
   exports the campaign's active leads from Smartlead → runs the mode's verifier
   chain (poll bulk jobs until finished) → classifies (good / catch-all-valid /
   unknown / **bad**, where ListMint `invalid` and `catch_all_invalid` and MV
   hard-invalid are bad) → deletes ONLY hard-bad leads from the campaign
   (respect 200/min cap) → writes ONE `app_activity_log` row with
   `{campaign_id, total, good, catch_all, unknown, bad_removed, removed_emails}` →
   marks the job done with those counts. Any exception marks the job `failed` with the
   real error string (never "aborted without reason").
- **Done-rule:** `curl -X POST localhost:7901/api/verify-campaign` with a real flagged
  campaign id returns `{job_id}` immediately; polling `/api/jobs/<id>` shows
  queued→running→done with non-fabricated counts; the app_activity_log row exists.
  (For this local check a dry-run flag `{"dry_run": true}` that skips the delete is
  allowed — the real delete is proven in Step 6.)

### Step 3 — Frontend: wire the real buttons (`app/deliverability-tab.js`)
Delete `simulateVerify` and the fake result plumbing on the click path. Keep the two
existing per-campaign buttons ("✓ ListMint" and "✓ MillionVerifier → ListMint") but
make them real. Click → POST `/api/verify-campaign` with the matching `mode`
→ immediately registers the job in the sidebar (Step 4)
→ button shows a spinner tied to the job status → on done, the result box renders the
REAL counts (kept / catch-all-unknown kept / bad removed) and "Details and who's
affected" lists the actual removed emails. On failed, show the real error. Keep the
existing glossary popovers and the "Mark done" ack flow working.
- **Done-rule:** `grep -n "simulateVerify" app/deliverability-tab.js` returns nothing;
  clicking the button on localhost against a real campaign produces a result box whose
  numbers match the app_activity_log row exactly.

### Step 4 — Shared background-actions sidebar (`app/shell.js`)
Self-contained widget appended by shell.js on any page that loads it:
- Collapsed by default to a small fixed tab on the right edge (e.g. "⚙ Actions · N")
  with a running-count badge; click to slide open, click to hide. State (open/closed)
  in localStorage.
- Content: list from `GET /api/jobs` — label, status pill, started/finished time,
  final counts or error. Poll every 4s while any job is queued/running; drop to 30s
  when idle; stop when the panel is closed AND nothing is running.
- Auto-pops open (or badge-pulses) when a new job starts, and shows a done/failed
  state change even if the user scrolled away or switched between the two pages.
- Must not touch or depend on the guarded helpers notifications.html warns about;
  plain fetch, no shared-state assumptions. No emoji-as-severity — follow the
  existing colour-as-severity convention from the deliverability visual pass.
- **Done-rule:** with a job running, the sidebar shows it live on BOTH
  `deliverability.html` and `notifications.html`; reloading mid-job still shows the
  running job; when it finishes, the sidebar entry flips to done with counts, with
  zero console errors on either page.

### Step 5 — Deploy
Commit in `~/navreo-signals`, push to the Render remote, wait for the deploy to go
live, then diff-check the iCloud copy against the repo and reconcile (memory
`signals-deploy-repo`).
- **Done-rule:** `https://navreo-signals.onrender.com/api/jobs` returns 200 JSON, the
  deliverability page shows the single real verify button, and repo↔iCloud diff for
  the touched files is empty.

### Step 6 — Live proof (the user's stated verification)
On production, run the real verification on the SMALLEST flagged campaign first
(at audit time: "Navreo | Agencies & Consultancies | CEO | Clay - [May 2026]", 94
sent) — cheapest MV spend, smallest blast radius. Training Mode ON: present the
confirmed-bad list before the delete fires (use dry_run first, then real). Then:
1. Confirm in Smartlead that the confirmed-bad leads are actually gone from the
   campaign (fetch leads, assert absence).
2. Confirm the `app_activity_log` row documents exactly who was removed.
3. Confirm the sidebar showed the job queued→running→done with matching counts,
   on both pages.
If the first campaign proves clean end-to-end, offer (don't auto-run) the remaining
flagged campaigns as a batch.
- **Done-rule:** all three confirmations pass with matching numbers across
  Smartlead, app_activity_log, and the sidebar. A screenshot/snapshot of the final
  sidebar + result box is included in the report.

## Final report (always, both modes)
One summary: steps passed/skipped/FAILED, real verification numbers per campaign
(total / kept / bad removed), MV credits spent, the app_activity_log row ids, and
anything deferred (e.g. remaining flagged campaigns not yet verified).

## Hard don'ts
- Never delete a lead whose verifier verdict isn't hard-bad. Never bulk-delete by guess.
- Never leave the mock path reachable as a silent fallback — if a verifier is down or
  its endpoint is undiscovered, the job fails loudly with the real error.
- Never guess ListMint endpoints in production code — only use the request shape
  proven live in Step 1.
- Never add a second writer to schedules owned elsewhere; this skill adds no crons.
- Never exceed a retry cap or report done while any done-rule fails.
