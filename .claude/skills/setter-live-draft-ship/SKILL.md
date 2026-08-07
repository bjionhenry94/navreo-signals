---
name: setter-live-draft-ship
description: Static orchestration skill that takes the Appointment Setter live in draft-only mode — positive-only intake (core-four Smartlead categories gating both the poll sweep and the webhook), a one-time 7-day positive backfill, and a Client dropdown on the setter queue derived from the campaign-name prefix. Draft-only is a hard gate — autopilot stays OFF, every agent stays mode=review, the only send path is Bjion manually clicking Send. One fixed step list, each step with a checkable done-rule, retry caps, and a Loop Training Mode toggle. Use when the user says "run the setter live ship", "take the setter live", "ship the positive-only setter", or "/setter-live-draft-ship".
---

# Setter Live Draft-Only Ship

The setter (training+brain shipped 2026-07-14, master switch OFF) is ready to work real traffic, but its intake is indiscriminate: every categorised reply enters `setter_queue`. This loop ships it live in draft-only mode — only positive replies enter, a 7-day positive backfill seeds the queue, and the queue becomes filterable by client. Nothing sends without Bjion clicking Send. Static loop — fixed steps, each has a done-rule, Training Mode controls the pauses.

**Model routing (user ruling 2026-07-13):** judgment — pass/fail calls against done-rules, verification sign-off — runs on Fable 5 (the orchestrating session). Execution — code edits, SQL pulls, test runs, deploy mechanics — runs on Sonnet 5 subagents (`model: sonnet`).

## ⚙ Loop Training Mode: **OFF**   ← flip this line to ON to pause at every step for approval

**ON:** pause at EVERY step boundary and wait for the user's explicit approval before continuing. Before starting a step, check its done-rule first — if it already passes, report "Step N already passes, skipping" and move on. Only re-run steps whose done-rule fails. Show what you're about to do before doing it.

**OFF:** run all steps end-to-end with no pauses. The done-rule checks, skip-if-passing behaviour, and retry caps stay exactly the same — only the pauses go.

**Retry cap (both modes):** each step retries **max 3** times against its done-rule. On cap-hit: record the step as FAILED with the reason, continue to the next step if it doesn't depend on the failed one, and surface every FAILED step in the final report. Never silently exceed the cap. Never declare the skill done on a cap-hit.

**Draft-only gates (both modes, non-negotiable — ruling Bjion 2026-07-14):**
- `autopilot_enabled` stays **OFF** for the entire loop and after it. Never flip it, even "to test".
- Every agent stays `mode=review`. No change may introduce or trigger ANY auto-send path.
- The ONLY send path is Bjion manually clicking Send on a reviewed draft — it stays live and functional.
- Verification never emails a real prospect. Manual send is proven ONLY via an `is_test` row to a self-owned address.
- Never touch the Make categoriser, never re-tag categorised replies, never touch training pages / share links / grading features.

## Goal

The live setter queue at navreo-signals.onrender.com/app/setter.html fills with only positive replies (plus a 7-day positive backfill), filterable by client, every reply drafted but nothing ever sent without Bjion clicking Send.

### THE DONE-RULE (single source of truth — the 6-check bar, none trusting the app's own labels)
> (1) `/api/version` on navreo-signals.onrender.com returns the shipped commit; (2) after a live "Check for new replies" run, a **direct Supabase read** of `setter_queue` shows every non-test row created since ship has `category` in the core-four set and **zero** rows outside it; (3) the backfill row-count matches an **independent SQL count** of qualifying last-7-day positive replies in `replies`, with **zero** duplicate (workspace, campaign, email, message-id) tuples; (4) in **Bjion's authenticated Chrome**, the rendered setter page shows the Client dropdown, and selecting one client shows only rows whose campaign name carries that prefix, spot-checked against SQL; (5) SQL shows **zero** `auto_sent` rows since ship, and settings read-back shows `autopilot_enabled=false` with every agent `mode=review`; (6) manual Send proven working on an `is_test` row to a self-owned address only, with SQL confirming no real lead was emailed during verification. **All 6, or it isn't done.** On any cap-hit, report the gap honestly — never declare done.

## Ground truth (verified 2026-07-14 — re-verify in Step 1, line numbers drift)

- **Core four (exact `replies.category` strings, verified live 2026-07-14):** `Interested`, `Information Request`, `Meeting Request`, `positive-re-reply`. Ruling Bjion 2026-07-14: core four ONLY — `Call Booked`, `Contact Forward`, `Contact In Future`, and all negatives stay out.
- **Intake paths to gate:** the poll sweep `run_poll` (app/setter.py:1849) and the Smartlead webhook `handle_inbound`. Webhook payloads arrive BEFORE the Make categoriser runs (~15-min lag) — an uncategorised webhook reply is left for the poll to pick up once categorised; a never-categorised reply stays out by design (accepted risk).
- **Client derivation (ruling Bjion 2026-07-14):** client = campaign-name prefix — text before the first `-`, `–`, `—` or `|` (e.g. "Amplifyy - Hiring Signal…" → Amplifyy). NO stored client field; every campaigns/replies row carries `client_id='navreo'`, so the name prefix is the only source. Derive live in the UI.
- **Backfill scope:** positive (core-four) replies from the last 7 days (~80 rows as of 2026-07-14), campaigns assigned to enabled agents only, bypassing the `campaign_assigned_at` skip for the backfill ONLY, deduped via the existing `_existing_row` check. Drafts generated, nothing sent. One-time.
- **Deploy repo = `~/navreo-signals` ONLY.** The iCloud copy under …/Navreo/Claude/Navreo/app/ is deprecated — never edit it; its setter.py already differs from the repo. The repo working tree holds ANOTHER SESSION'S uncommitted work (campaigns.html, server.py, notifications.html, unified.html) — ship via `git worktree add --detach <path> origin/main`, commit ONLY your own setter.py/setter.html hunks, push to main (Render auto-deploys), confirm via `/api/version`.
- **Verification surfaces:** anonymous page requests 302 to login — ALL rendered-page verification goes through Bjion's authenticated Chrome via claude-in-chrome (the in-app Browser pane has no session). Data checks go direct to Supabase (`fnykldftbkrccihdjayl`), never through the app's own labels. Tests: `python3 app/test_setter.py` (415 as of 2026-07-14).

## Steps

### Step 1 — Re-verify ground truth in a detached worktree
Sonnet execution agent: `git -C ~/navreo-signals fetch origin && git worktree add --detach <scratch-path> origin/main`; work in the worktree from here on. Confirm `run_poll` and `handle_inbound` locations (line drift), the `_existing_row` signature, the `campaign_assigned_at` skip, and how `setter_queue.category` is populated. SQL-confirm the four category strings exist verbatim in `replies.category` and count last-7-day core-four replies on enabled-agent campaigns (the backfill expectation, ~80). Snapshot `__settings__` and every agent's `mode` as rollback reference.
- **Done-rule:** (a) worktree on detached origin/main, setter.py + setter.html present; (b) every Ground-truth bullet confirmed or corrected in writing with fresh line numbers; (c) the SQL backfill count recorded; (d) settings + agent-mode snapshot saved to the skill folder.

### Step 2 — Positive-only intake gate
One `CORE_FOUR` constant (the four exact strings) applied in BOTH paths: `run_poll` skips any reply whose category is not in the set; `handle_inbound` checks the reply's category from `replies` — not in set → skip; uncategorised (categoriser lag) → skip WITHOUT marking processed, so the next poll picks it up once categorised. No change to the Make categoriser, no re-tagging.
- **Done-rule:** unit tests prove (a) each core-four category enters the queue via both paths; (b) `Call Booked`, `Contact Forward`, `Contact In Future`, a negative, and an uncategorised reply all stay out; (c) an uncategorised webhook reply is later picked up by a poll pass once categorised; (d) all pre-existing tests still green.

### Step 3 — Client dropdown
setter.html queue header: a Client dropdown populated live from the loaded rows' campaign-name prefixes (split on first `-`, `–`, `—`, `|`; trim; no prefix → "Other"). Selecting a client filters visible rows client-side; "All clients" default. No schema change, no stored field, no layout redesign — additive only.
- **Done-rule:** on localhost with seeded rows across ≥2 prefixes: dropdown lists exactly the distinct prefixes, selecting one hides every other client's rows, "All clients" restores, en/em-dash and pipe prefixes all parse.

### Step 4 — Backfill implementation (build only, run in Step 6)
A one-time script in the worktree (not a permanent route): pull last-7-day core-four replies for campaigns assigned to enabled agents, bypass the `campaign_assigned_at` skip for this pass only, dedupe via `_existing_row`, run each through the normal pipeline so a draft is generated — mode/switch untouched, so every row lands held-for-review. Idempotent (safe to re-run; dedupe absorbs).
- **Done-rule:** dry-run against prod Supabase prints the exact candidate list (count matches Step 1's SQL count ± explained rows) and writes nothing; unit test proves the `campaign_assigned_at` bypass exists ONLY in the backfill path, not the live poll.

### Step 5 — Tests green + deploy
Extend `test_setter.py` for the gate + backfill guard; commit ONLY the setter.py/setter.html hunks (plus test file) in the detached worktree — nothing from the other session's files can be swept in (verify `git show --stat`); push to origin/main; wait for Render.
- **Done-rule:** (a) full suite exits 0, ≥415 + new tests, zero pre-existing skips; (b) commit on origin/main touches only setter.py, setter.html, test_setter.py; (c) `/api/version` returns the new SHA — DONE-RULE check (1) recorded.

### Step 6 — Run the backfill against prod
Execute Step 4's script live once. Then independent SQL: queue insert count vs the qualifying-replies count, duplicate check on (workspace, campaign, email, message-id).
- **Done-rule:** DONE-RULE check (3) passes with both numbers recorded; spot-read 5 backfilled rows — each has a draft, none sent, all held for review.

### Step 7 — Live verification: the remaining checks
Trigger a live "Check for new replies" run, then direct Supabase read for check (2). In Bjion's authenticated Chrome (claude-in-chrome): rendered setter page shows the dropdown, one-client filter spot-checked against SQL — check (4). SQL zero `auto_sent` since ship + `autopilot_enabled=false` + every agent `mode=review` — check (5). Manual Send: inject an `is_test` row addressed to a self-owned address, Bjion (or the session with his approval in chat) clicks Send, SQL confirms it sent AND that no real lead was emailed during the whole verification window — check (6). Clean up `is_test` rows.
- **Done-rule:** DONE-RULE checks (2), (4), (5), (6) each pass with evidence recorded (SQL outputs, Chrome screenshot). All 6 now green.

### Step 8 — Safety close-out
Re-read `__settings__` and all agent docs directly from Supabase: `autopilot_enabled=false`, every agent `mode=review`, docs match Step 1's snapshot except intentionally shipped fields; no `is_test` rows left in `setter_queue`; the deprecated iCloud copy untouched (`git status` there irrelevant — just confirm no edits were made); worktree removed or left clean.
- **Done-rule:** all checks pass, read directly from Supabase / filesystem.

## Final report (always, both modes)

One summary: per-step pass/skip/FAILED with retry counts; the real numbers — backfill candidate count vs inserted count, non-core-four rows since ship (must be 0), auto_sent since ship (must be 0), test count; artifacts — commit SHA, `/api/version` output, SQL outputs, Chrome screenshot, `is_test` row ids created + cleaned, snapshot path; the 6-check bar with each check's evidence; anything deferred or FAILED, stated plainly.

## Hard don'ts

- Never flip `autopilot_enabled`, never move an agent off `mode=review`, never add or trigger any auto-send path — the manual Send button is the only sender.
- Never email a real prospect during verification — `is_test` + self-owned address only.
- Never touch the Make categoriser or re-tag categorised replies; an uncategorised reply staying out forever is accepted by design.
- Never widen the category set beyond the exact core four — `Call Booked`, `Contact Forward`, `Contact In Future` and all negatives stay out (ruling Bjion 2026-07-14).
- Never edit the iCloud copy, never work outside the detached worktree, never commit another session's files (campaigns.html, server.py, notifications.html, unified.html).
- Never store a client field — the campaign-name prefix, derived live, is the only source.
- Never touch training pages, share links, or grading features.
- Never trust the app's own labels for verification — Supabase SQL and Bjion's authenticated Chrome are the evidence surfaces.
- Never exceed a retry cap or report done while any of the 6 checks fails.
