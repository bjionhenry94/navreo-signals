---
name: setter-needs-review-replied-last
description: Static orchestration skill that fixes the Appointment Setter "Needs review" tab so it only holds prospects whose most recent thread message is a reply FROM the lead — read-time filter + reconciled counts, rows we already answered routed to Sent/Auto-sent, no destructive DB rewrite. One fixed step list, each step with a checkable done-rule, retry caps, and a Loop Training Mode toggle. Use when the user says "fix the setter needs-review tab", "needs review should only be leads who replied last", "the setter shows leads we already answered", or "/setter-needs-review-replied-last".
---

# Setter "Needs review" = they replied last

The "Needs review" tab is meant to hold only prospects where the ball is in our court — the lead replied and we haven't answered yet. Today it's a static filter on `setter_queue.status = 'needs_review'`, so a row lingers there even after we've replied (e.g. a human answered directly in Smartlead). This skill makes the tab and its count reflect the real conversation state, computed at READ TIME from the `thread` jsonb already on each row. Static loop — fixed steps, each has a done-rule, Training Mode controls the pauses.

## ⚙ Loop Training Mode: **OFF**   ← flip this line to ON to pause at every step

**ON:** pause at EVERY step boundary and wait for the user's explicit approval before continuing. Before starting a step, check its done-rule first — if it already passes, report "Step N already passes, skipping" and move on. Only re-run steps whose done-rule fails. Show what you're about to do before doing it.

**OFF:** run all steps end-to-end with no pauses. The done-rule checks, skip-if-passing behaviour, and retry caps stay exactly the same — only the pauses go.

**Retry cap (both modes):** each step retries **max 3** times against its done-rule. On cap-hit: record the step as FAILED with the reason, continue to the next step if it doesn't depend on the failed one, and surface every FAILED step in the final report. Never silently exceed the cap. Never declare the skill done on a cap-hit.

**Non-destructive gate (both modes, non-negotiable):** this fix NEVER writes to the database. The stored `setter_queue.status` column is left exactly as-is on every row — no migration, no bulk PATCH, no per-row status rewrite. The reclassification is purely presentation (how rows are filtered into pills and how counts are tallied) at GET time. Any temptation to "just persist the corrected status" is out of scope and forbidden. (Also: a `setter_queue` PATCH carrying a derived key with no real column dies silently — see `reference_setter_queue_schema_freeze_gotcha`. Never write derived keys back.)

## Goal

> The Setter "Needs review" tab and its headline count show ONLY prospects whose chronologically-last thread message is an inbound `REPLY` from the lead. Every row where our `SENT` is the newest message has left Needs review and now appears under **Sent** (human sent our last reply) or **Auto-sent** (the agent sent it). Counts across pills stay reconciled — the rows that left `needs_review` show up in Sent/Auto-sent, and **All stays at its original total (136 at time of brief)**. Verified live on the deployed host, with the stored `status` column provably untouched. Anything less than all of that = not done. On a retry cap-hit, stop and report the gap honestly — do not declare done.

## Ground truth (verified 2026-07-16 — re-verify in Step 1, line numbers drift)

- **Data source:** Supabase table `setter_queue`. Constant `QUEUE_TABLE = "setter_queue"` at `app/setter.py:57`. Schema `app/setter_migration.sql:8-44`. Tabs read entirely from Supabase (Smartlead is only the upstream poller).
- **The static filter (the bug):** list endpoint `route_queue_get` at `app/setter.py:3377-3395` appends `&status=eq.<status>` at `:3389`. Counts `_compute_kpis` at `app/setter.py:3285-3327`; per-pill map at `:3295-3301` via `_pill_count` (`:3273-3282`), a header-only DB count with a PostgREST filter — **cannot express thread-direction logic in SQL**, so counts must be tallied in Python from fetched rows.
- **The signal already exists:** each row's `thread` jsonb is normalized+sorted-by-time with per-message `type` = `"REPLY"` (inbound, from lead) / `"SENT"` (outbound, from us) at `app/setter.py:1243-1257`; `thread` stored as `norm[-50:]` (`:1307`). Direction of the LAST message = `sorted_thread[-1]["type"]`. Hydration also computes `answered_since_reply` (`app/setter.py:1284-1293`) — a `SENT` exists after the target `REPLY` — but that's live-thread-time, not the stored-row read path we need.
- **Frontend:** pill/tab definitions `app/setter.html:508-512`; default tab `currentStatus="needs_review"` at `:456`; fetch `GET /api/setter/queue?status=<currentStatus>` at `:787-799`; counts consumed from `KPIS.counts`; chip render/click `:840-847`. Comment on bucket semantics `:504-506` and `app/setter.py:3291-3294`.
- **Eligibility (leave untouched):** a row only enters the queue if `category ∈ CORE_FOUR = {"Interested","Information Request","Meeting Request","positive-re-reply"}` (`app/setter.py:63-66`, enforced `:2066`). KPI counts filter `is_test=eq.false` (`_pill_count :3276`). Keep both exactly.
- **Read-time annotation precedent:** `_annotate_queue_row` (`app/setter.py:3335-3362`) already derives UI-only fields from stored columns and returns them in GET payloads only, never writing back — mirror this pattern for the direction/bucket derivation.
- **UNKNOWN → resolve in Step 1:** how to classify a later `SENT` as human-sent vs agent-sent, to pick Sent vs Auto-sent. Hypothesis: a row still stored `needs_review` but with a `SENT` after the last `REPLY` usually means a HUMAN answered directly in Smartlead → **Sent**; agent auto-sends already stamp `status='auto_sent'`. Confirm by inspecting real rows: is there a stable `from_name` / marker on the agent's outbound `SENT` in `thread`? Pick the concrete discriminator before building; default a genuinely-ambiguous later-SENT to **Sent** (human) and record the assumption.
- **Deploy mechanics:** deploy = git push to the deploy repo → Render redeploys; **iCloud copy is NOT live and reverts edits** — edit only the deploy-repo working copy. Push is what makes it live. Any interruption = a redeploy. See memory `signals-deploy-repo`, `reference_setter_live_verify_auth`, `project_verify_resilience_ship`.
- **Live-verify auth:** the deployed Setter is auth-gated (401 headless). Mint `navreo_session` cookie from the keys file (`~/.navreo-keys.env`, SRK present) per `reference_signals_session_cookie_mint` to read `/api/setter/queue` and KPIs headlessly; or use the browser tools logged-in for the rendered proof.

## Steps

### Step 1 — Re-verify ground truth & resolve the human-vs-agent discriminator
Confirm every Ground-truth bullet against current code (line numbers drift). Pull a handful of REAL `setter_queue` rows currently in `needs_review` (via Supabase read) and inspect each `thread`: identify rows where `sorted_by_time[-1]["type"] == "SENT"` (we replied last) vs `"REPLY"` (they replied last). For the "we replied last" rows, determine the concrete discriminator that separates a human-sent last `SENT` from an agent-sent one (from_name pattern, a marker, or the fact that agent sends already move status to `auto_sent`). Write down the exact rule you'll use.
- **Done-rule:** (a) all Ground-truth locations re-confirmed or corrected in place; (b) at least one real `needs_review` row found whose last thread message is `SENT` (proves the bug is real and reproducible) OR an explicit note that none currently exist with the sample pulled; (c) the human-vs-agent classifier is written as a concrete, code-able rule with the assumed default recorded. FAILED if the classifier stays hand-wavy.

### Step 2 — Build the read-time direction helper (backend)
Add a pure helper in `app/setter.py` (mirroring `_annotate_queue_row`, GET-only, never persisted) that takes a stored row and returns: `last_msg_inbound` (bool — is `sorted_thread[-1]["type"] == "REPLY"`), and for the not-inbound case an `effective_pill` of `"sent"` or `"auto_sent"` per the Step-1 classifier. Treat a row with an empty/absent `thread` as staying in its stored bucket (no reclassification without evidence). Sort the thread by `time` defensively (don't trust stored order); unparseable/missing times must not crash — fall back to keeping the stored bucket.
- **Done-rule:** (a) helper exists and is unit-exercised on the Step-1 sample rows, returning `last_msg_inbound=False` + correct `effective_pill` for the we-replied-last rows and `True` for genuine awaiting-us rows; (b) empty-thread and bad-time rows return the safe stored-bucket fallback, no exception; (c) the helper writes nothing back to Supabase. FAILED if any sample row misclassifies.

### Step 3 — Apply the helper to the LIST endpoint
In `route_queue_get` (`app/setter.py:3377+`): when `status == "needs_review"`, after fetching the stored `needs_review` rows, DROP any row whose `last_msg_inbound` is False. When `status in ("sent","auto_sent")`, ADD in the reclassified rows (stored `needs_review` but `effective_pill == that status`). Keep the `is_test` and CORE_FOUR behaviour and the `_annotate_queue_row` annotation exactly as before. Empty `status` (All) returns everything unchanged.
- **Done-rule:** (a) `GET /api/setter/queue?status=needs_review` returns zero rows whose last thread message is `SENT`; (b) `GET ...?status=sent` and `?status=auto_sent` now include the reclassified rows; (c) `GET ...?status=` (All) row set is byte-identical to before the change. FAILED if All changes or a we-replied-last row survives in needs_review.

### Step 4 — Reconcile the COUNTS
Rework `_compute_kpis` so the `counts` pills for `needs_review` / `sent` / `auto_sent` reflect the SAME reclassification (not the raw `status=eq.` SQL counts). Since PostgREST can't filter on thread direction, fetch the relevant real rows (workspace, `is_test=false`) with `thread`, run the helper, and tally in Python. `all` and `dismissed` counts stay as-is. Cap the fetch defensively but ensure it covers the full population (≈136 rows — well within one page).
- **Done-rule:** independently (from a direct Supabase read, NOT the KPI endpoint's own output): `needs_review_new` = count of rows whose last msg is inbound; `moved` = old `needs_review` count − `needs_review_new`; confirm the endpoint now reports `needs_review = needs_review_new`, `sent + auto_sent` rose by exactly `moved`, and `all` is unchanged. Lettered pass (a) needs_review dropped by `moved`; (b) sent+auto_sent up by `moved`; (c) all unchanged. FAILED if the arithmetic doesn't reconcile.

### Step 5 — Deploy live
Edit only the deploy-repo working copy (never the iCloud copy). Commit + push; wait for Render to redeploy; marker-grep the deployed artifact to confirm the new helper is live. Reconcile repo↔iCloud per memory `signals-deploy-repo`.
- **Done-rule:** the deployed host serves the new code — a marker string from the helper is present in the deployed `setter.py` (or the live `/api/setter/queue?status=needs_review` behaviour matches Step 3), confirmed AFTER the redeploy completes, not from local. FAILED if only iCloud/local reflects the change.

### Step 6 — Live proof on the deployed host
On the real deployed Setter (logged-in browser, or headless with a minted `navreo_session` cookie): render the page and confirm (a) the "Needs review" count is the lowered `needs_review_new` from Step 4; (b) a specific prospect that was in Needs review pre-fix but where we replied last now appears under Sent or Auto-sent and is GONE from Needs review; (c) the total/All still reads its original value. Capture a browser screenshot as evidence.
- **Done-rule:** all three (a)(b)(c) observed on the deployed host with a screenshot, plus a direct Supabase read confirming the stored `status` of the spot-checked row is STILL `needs_review` (proving the DB was not rewritten). FAILED if any part is unverified or if the row's stored status changed.

## Final report (always, both modes)

One summary listing: each step passed / skipped / FAILED with reason; the real numbers — old `needs_review` count, new `needs_review` count, `moved`, resulting `sent` and `auto_sent` counts, unchanged `all`; the git commit/push id and deployed-marker confirmation; the spot-checked prospect (name/id) and where it moved; the screenshot path; and confirmation the stored `status` column was untouched (with the read-back proof). Name the actual numbers — "counts reconciled" alone is not a report.

## Hard don'ts

- **Never write to the database.** No migration, no bulk PATCH, no per-row `status` rewrite — the fix is read-time filter + count logic only. Stored `setter_queue.status` stays exactly as found.
- Never write a derived key back to `setter_queue` (schema-freeze silent-death, `reference_setter_queue_schema_freeze_gotcha`).
- Never change the `All` count or the CORE_FOUR eligibility gate or the `is_test` handling.
- Never trust stored thread order — sort by `time`; never let an unparseable time crash hydration (fall back to the stored bucket).
- Never edit the iCloud copy or declare done from a local/iCloud change — only the pushed, redeployed host is live.
- Never declare done on the app's own KPI label — the count reconciliation and the "not rewritten" proof must be read independently from Supabase.
- Never exceed a retry cap or report done while any done-rule fails; a cap-hit is reported as FAILED with the gap.
