---
name: setter-thread-collapse
description: Static orchestration skill that makes the Appointment Setter inbox show ONE row per lead-thread instead of one row per reply — read-time collapse of setter_queue rows to a single representative per (smartlead_campaign_id, lower(trim(lead_email))) thread, applied to both the list endpoint and every pill count, composing with the shipped who-replied-last reclassification. Non-destructive: all 137 stored rows stay untouched. One fixed step list, each step with a checkable done-rule, retry caps, and a Loop Training Mode toggle. Use when the user says "collapse setter threads", "one row per lead in the setter inbox", "the setter shows duplicate rows per reply", "fix the PowerArena duplicates", or "/setter-thread-collapse".
---

# Setter inbox: one row per lead-thread

The intake upsert keys on `(workspace, smartlead_campaign_id, lead_email, message_id)` (`app/setter.py:1975` and `:2313`), and `message_id` is per-reply — so every inbound reply deliberately creates a new `setter_queue` row. One conversation accumulates many rows: PowerArena lead `weichien@powerarena.com` / campaign `3477409` has 5 (rows 197/199/214 `needs_review` + 224/227 `dismissed`). This skill collapses each thread to its newest-reply row at READ TIME only, so the inbox and every pill count show exactly one row per lead-per-campaign conversation. Static loop — fixed steps, each has a done-rule, Training Mode controls the pauses.

## ⚙ Loop Training Mode: **OFF**   ← flip this line to ON to pause at every step

**ON:** pause at EVERY step boundary and wait for the user's explicit approval before continuing. Before starting a step, check its done-rule first — if it already passes, report "Step N already passes, skipping" and move on. Only re-run steps whose done-rule fails. Show what you're about to do before doing it.

**OFF:** run all steps end-to-end with no pauses. The done-rule checks, skip-if-passing behaviour, and retry caps stay exactly the same — only the pauses go.

**Retry cap (both modes):** each step retries **max 3** times against its done-rule. On cap-hit: record the step as FAILED with the reason, continue to the next step if it doesn't depend on the failed one, and surface every FAILED step in the final report. Never silently exceed the cap. Never declare the skill done on a cap-hit.

**Non-destructive gate (both modes, non-negotiable):** this fix NEVER writes to the database. Do NOT change the intake upsert or its unique constraint; do NOT delete, merge, or rewrite any `setter_queue` row; all 137 stored rows stay exactly as they are. The collapse is purely presentation (which rows are returned and how counts are tallied) at GET time. (Schema-freeze gotcha still applies: never write a derived key back — `reference_setter_queue_schema_freeze_gotcha`.)

## Goal

> The Setter inbox and every pill count show exactly one row per lead-per-campaign thread — its latest-reply state — with no duplicate/stale reply-rows of the same conversation ever appearing. `All` drops from 137 rows to 110 threads; each thread appears in exactly one pill; PowerArena surfaces once under Dismissed. Verified live on the deployed host with the 137 stored rows provably untouched. Anything less than all of that = not done. On a retry cap-hit, stop and report the gap honestly — do not declare done.

## The collapse rule (the spec — implement exactly this)

- **Thread key:** `(smartlead_campaign_id, lower(trim(lead_email)))` — one thread per lead PER campaign. The 5 leads who appear in two campaigns stay as two threads (user ruling).
- **Representative row:** the thread's row with the most recent `replied_at`; tie-break latest `created_at`, then highest `id`.
- **Pill placement:** the representative's OWN (reclassified) status decides the single pill it appears in. PowerArena's newest reply (row 227) was dismissed → the thread surfaces once under **Dismissed**, and its three stale `needs_review` siblings (197/199/214) vanish from Needs review.
- **Order of operations (composition, critical):** collapse to the representative row per thread FIRST, then run the existing who-replied-last reclassification (`_queue_direction` / `_reclassify_queue`, and the `_reclass` count task in `_compute_kpis`) on that survivor. A thread where we genuinely replied last must still route to Sent/Auto-sent.
- **Scope:** apply to BOTH the list endpoint `route_queue_get` and every pill count in `_compute_kpis`, including `All` — every pill counts distinct threads, each thread in exactly one pill, pill counts sum to the thread total.
- **Leave untouched:** the `is_test` filter and CORE_FOUR eligibility, exactly as they are.

## Ground truth (from the brief, 2026-07-16 — re-verify in Step 1, line numbers drift)

- **Intake upsert (do NOT touch):** `app/setter.py:1975` and `:2313`, keyed on `(workspace, smartlead_campaign_id, lead_email, message_id)` — per-reply rows are intentional at write time.
- **Read paths to change:** list endpoint `route_queue_get`; counts `_compute_kpis` (PostgREST header-counts can't express the collapse — tally in Python from fetched rows, as the shipped `_reclass` task already does).
- **Already shipped this session (compose, don't break):** who-replied-last reclassification `_queue_direction` / `_reclassify_queue` on the list path and the `_reclass` count task in `_compute_kpis` (see `setter-needs-review-replied-last`, commit `dbfc971`).
- **Known numbers (corrected + live-verified 2026-07-16, ship `aa4383d`):** 137 stored non-test rows → **115** distinct threads under the ruled key (the brief's 110 was an email-only dedup; the 5 two-campaign leads add 5). Post-collapse stored buckets: needs_review 57, sent 8, auto_sent 0, dismissed 22, new 13, no_action 15; after who-replied-last on the 57 survivors: 31 stay, 26 → Sent. Final pills: 31/34/0/22, All 115. Named case: `weichien@powerarena.com` / campaign `3477409`, rows 197/199/214 `needs_review` + 224/227 `dismissed`, representative = 227.
- **Deploy mechanics:** edit ONLY the deploy repo `~/navreo-signals` (the iCloud copy is stale, not live, and REVERTS edits); git push to `main` deploys to Render. Any interruption = a redeploy (`project_verify_resilience_ship`).
- **Live-verify auth:** deployed Setter is auth-gated (401 headless). Mint a `navreo_session` cookie from `~/.navreo-keys.env` per `reference_signals_session_cookie_mint` to read `/api/setter/queue` and KPIs headlessly; browser tools logged-in for the rendered proof.

## Steps

### Step 1 — Re-verify ground truth & baseline the numbers
In `~/navreo-signals`, confirm every Ground-truth location (line numbers drift) and how `_queue_direction` / `_reclassify_queue` and the `_reclass` count task hook in today. From a direct Supabase read of `setter_queue`, compute the baseline: total row count (expect 137), distinct-thread count under the thread key (expect 110), the duplicated threads (expect 21) and the stale-sibling count per pill, and the PowerArena rows (197/199/214/224/227 with their statuses and `replied_at` ordering proving 227 is the representative). Record any `replied_at` nulls and decide their sort placement (null sorts oldest) before coding.
- **Done-rule:** (a) all code locations re-confirmed or corrected in place; (b) Supabase baseline computed and written down: 137 rows, 110 threads (or the corrected live numbers, noted explicitly), per-pill expected post-collapse counts derived independently; (c) PowerArena representative confirmed = row 227 under the spec's tie-break; (d) null-`replied_at` handling decided. FAILED if the expected post-collapse counts aren't derived before any code changes.

### Step 2 — Build the pure collapse helper (backend)
Add a pure helper in `app/setter.py` that takes a list of stored rows and returns one representative per thread key `(smartlead_campaign_id, lower(trim(lead_email)))`, chosen by most recent `replied_at`, tie-break latest `created_at`, then highest `id`. Defensive: null/unparseable `replied_at` never crashes (falls to the bottom of the ordering); missing/empty `lead_email` rows pass through uncollapsed rather than clumping into one fake thread. GET-only, never persisted.
- **Done-rule:** (a) helper exists and is unit-exercised on the Step-1 PowerArena rows, returning exactly row 227; (b) exercised on the full 137-row baseline it returns exactly the expected thread count (110) with every representative matching the independently-derived answer; (c) null-`replied_at` and empty-email rows handled per spec without exception; (d) writes nothing to Supabase. FAILED if any representative disagrees with the Step-1 derivation.

### Step 3 — Apply the collapse to the LIST endpoint
In `route_queue_get`: fetch the candidate rows (keeping `is_test` and CORE_FOUR behaviour untouched), collapse to representatives FIRST, then run the existing who-replied-last reclassification on the survivors, then filter to the requested pill by the survivor's reclassified status. This must hold for `needs_review`, `sent`, `auto_sent`, `dismissed`, and `All` — note the collapse needs visibility across statuses (a `needs_review` request must still know a newer `dismissed` sibling exists), so fetch broadly enough per workspace before filtering.
- **Done-rule:** via minted cookie against the running code (local or deployed): (a) for each of the five pills, no two returned rows share a thread key, and each returned row is its thread's representative; (b) `?status=dismissed` contains the PowerArena thread exactly once (row 227's data) and `?status=needs_review` contains none of 197/199/214; (c) `All` returns 110 rows; (d) a thread where we replied last still lands in Sent/Auto-sent (reclassification composes). FAILED if any pill still shows two rows of one thread or the composition breaks.

### Step 4 — Reconcile the COUNTS
Rework `_compute_kpis` so every pill count — including `All` — counts distinct threads via the same collapse-then-reclassify path (extend or mirror the existing `_reclass` Python tally; PostgREST can't express this in SQL). Each thread must land in exactly one pill.
- **Done-rule:** independently from a direct Supabase read (NOT the KPI endpoint's own labels): (a) `All` = 110 distinct threads; (b) each pill count equals the number of threads whose representative (after reclassification) lands in that pill; (c) the pill counts sum to 110; (d) `needs_review` dropped by the collapsed stale siblings (~9 from the 21 duplicated threads, exact number from Step 1). FAILED if the arithmetic doesn't reconcile.

### Step 5 — Deploy live
Commit and push to `main` in `~/navreo-signals` (never the iCloud copy); wait for Render to redeploy; confirm the new code is live (marker-grep the deployed artifact or observe the changed `/api/setter/queue` behaviour post-redeploy, not from local).
- **Done-rule:** the deployed host demonstrably serves the collapse — confirmed AFTER the redeploy completes. FAILED if only local/iCloud reflects the change.

### Step 6 — Live proof + non-destructive proof
Against the deployed host: (a) with the minted cookie, re-run the Step-3 read-backs on all five pills (no duplicate thread keys, representatives only); (b) in the rendered UI (logged-in browser), search `weichien` — exactly one Hubert row appears, under Dismissed — and the Needs-review pill shows the lowered collapsed count; screenshot as evidence. Then the non-destructive read: direct Supabase `count(*)` on `setter_queue` still returns 137, and rows 197/199/214/224/227 all still exist with unchanged `status`.
- **Done-rule:** all of: five-pill live read-back clean, PowerArena once-and-only-once under Dismissed in the UI with screenshot, Needs-review pill count = the Step-4 number, 137-row count intact, all five PowerArena rows present with original statuses. FAILED if any part is unverified.

## Final report (always, both modes)

One summary listing: each step passed / skipped / FAILED with reason; the real numbers — 137 rows → N threads, old vs new count per pill and their sum, the needs_review drop; the git commit/push id and deployed confirmation; the PowerArena read-back (which pill, which row's data); the screenshot path; and the non-destructive proof (137 count + the five rows' unchanged statuses). Name the actual numbers — "counts reconciled" alone is not a report.

## Hard don'ts

- **Never write to the database.** No intake-upsert change, no unique-constraint change, no delete/merge/rewrite of any `setter_queue` row — all 137 rows stay exactly as found. Read-time only.
- Never write a derived key back to `setter_queue` (schema-freeze silent-death, `reference_setter_queue_schema_freeze_gotcha`).
- Never reclassify before collapsing — the order is collapse first, then who-replied-last on the survivor, or the two shipped behaviours stop composing.
- Never key threads on email alone — the key is `(smartlead_campaign_id, lower(trim(lead_email)))`; the 5 two-campaign leads stay as two threads.
- Never change the CORE_FOUR eligibility gate or the `is_test` handling.
- Never edit the iCloud copy or declare done from a local change — only the pushed, redeployed host is live.
- Never declare done on the app's own KPI labels — count reconciliation and the non-destructive proof must be read independently from Supabase.
- Never exceed a retry cap or report done while any done-rule fails; a cap-hit is reported as FAILED with the gap.
