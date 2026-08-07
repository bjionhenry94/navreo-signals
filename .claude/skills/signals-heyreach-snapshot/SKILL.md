---
name: signals-heyreach-snapshot
description: Static orchestration skill that upgrades the daily Supabase pulls/checks so EVERY change made under the Navreo signals tool (https://navreo-signals.onrender.com/app/) is documented, and all available HeyReach data is snapshotted daily — giving Supabase an ongoing record of all activity. Fixed 7-step loop with done-rules, retry caps, and a Loop Training Mode toggle. Verified by ideating 20 random platform use-cases and proving each one lands in the database. Use when the user says "run the HeyReach snapshot build", "wire the signals activity ledger", "make Supabase record everything the tool does", or "/signals-heyreach-snapshot".
---

# Signals → Supabase Activity Ledger + HeyReach Daily Snapshot

# ⚙️ LOOP TRAINING MODE — flip this line to change behaviour
LOOP_TRAINING_MODE: OFF

- **ON:** Pause at EVERY step and wait for Bjion's explicit approval before continuing. Before running a step, check its done-rule first — if it already passes, report "SKIP (already done)" and move on without doing work. Only re-run steps whose done-rule FAILS. Max **3 attempts per step**; on the 3rd failure, stop and report the blocker instead of looping.
- **OFF (current):** Run all steps autonomously with no pauses. Keep the done-rule checks (skip passing steps) and keep the 3-attempt retry cap. Report a single summary at the end.

To flip it later: edit the `LOOP_TRAINING_MODE:` line above to `OFF` and re-run the skill.

---

## Goal (pre-baked, do not renegotiate)

The Supabase database (project `fnykldftbkrccihdjayl`) holds an **ongoing, daily-refreshed record of all available data from HeyReach** and an **audit trail of every change made under the signals tool** at https://navreo-signals.onrender.com/app/. Nothing a user does in the tool, and nothing that exists in HeyReach, should be invisible to the database.

## Fixed context

- Signals app source: iCloud working copy (this project) + `~/navreo-signals` git/Render deploy repo. Changes MUST land in the deploy repo and be diff-checked (see memory `reference_signals_deploy_repo`).
- HeyReach: REST API only, never MCP (`lilly-heyreach-upload` conventions; key in `~/.navreo-keys.env`).
- Scheduling: pg_cron → pg_net → Render endpoint pattern, same as `signals-autopull-repair`. NOT launchd, NOT a Claude cron.
- Existing daily sync: Smartlead→Supabase edge function + pg_cron (memory `project_smartlead_supabase_daily_sync`) — extend this pattern, don't duplicate it.
- All snapshot writes are **additive**: upserts + an append-only change log. Never blanket-DELETE a table (memory: `_pg_replace` data-loss incident).

## Steps (static — run in order)

### Step 1 — Coverage audit
Map what is already recorded vs missing. Enumerate (a) every mutating endpoint in `app/server.py` (create/edit/pause/delete signal, pull, push to Smartlead/HeyReach, autopilot actions, settings changes), and (b) every HeyReach data object reachable via its REST API (campaigns, lists, leads, conversations/inbox, stats, senders).
**Done-rule:** A coverage table exists at `notes/coverage-map.md` inside this skill folder, with one row per endpoint/object and a verdict of RECORDED (which table) or GAP.

### Step 2 — Schema
Create the missing Supabase tables. Minimum set: `app_activity_log` (append-only: ts, actor, endpoint, entity, payload jsonb) and `heyreach_*` snapshot tables (campaigns, lists, leads, conversations, stats) each with `snapshot_date` and natural-key upsert. RLS enabled on all new tables (Signals beta audit found RLS off before).
**Done-rule:** All tables from the coverage map's GAP rows exist in Supabase (verified by SQL against `information_schema`), with RLS on.

### Step 3 — App-side activity logging
Add a small write-through in `app/server.py` so every mutating endpoint appends one row to `app_activity_log`. No behaviour change to the endpoints themselves.
**Done-rule:** Hitting each class of mutating endpoint (locally or on Render) produces a matching `app_activity_log` row with the correct entity + payload.

### Step 4 — HeyReach daily pull
Build the pull job (Render endpoint on the signals service, same shape as auto-pull): fetch all HeyReach objects from Step 1(b), upsert into the snapshot tables, and diff against the previous snapshot to append change rows to `app_activity_log` (source = "heyreach_sync"). Respect HeyReach rate limits; bound the batch.
**Done-rule:** One manual invocation completes without error and every `heyreach_*` table has rows with today's `snapshot_date`.

### Step 5 — Schedule daily
Register a pg_cron job that pg_net-calls the Render pull endpoint once daily (pick a quiet hour, e.g. 05:00 UTC), alongside the existing Smartlead sync job.
**Done-rule:** The job appears in `cron.job`, and either its first scheduled run has succeeded (check `cron.job_run_details`) or a forced run through the exact cron path succeeds.

### Step 6 — Deploy + mirror
Commit and push to the `~/navreo-signals` deploy repo so Render redeploys; then diff-check the iCloud copy against the deploy repo so the two stay in sync.
**Done-rule:** `git status` clean in the deploy repo, Render deploy is live (endpoint responds), and iCloud↔deploy diff shows no drift on the touched files.

### Step 7 — Verification: 20 random use-cases
Ideate **20 random, varied use-cases** a user could perform on https://navreo-signals.onrender.com/app/ (mix of: creating/editing/pausing signals, pulling leads, pushing to Smartlead, pushing to HeyReach, autopilot behaviour, HeyReach-side activity like replies or campaign stat changes). For each, trace exactly which Supabase table+row would record it. Execute at least 3 of them for real (choose safe/reversible ones) and confirm the rows appear.
**Done-rule:** All 20 use-cases have a verdict of RECORDED with a named table; ≥3 verified live. Any FAIL sends you back to the earliest step that fixes it (schema → Step 2, logging → Step 3, pull → Step 4), counting against that step's retry cap.

## Done-rule for the whole skill

Steps 1–7 all pass their done-rules, and the Step 7 table shows 20/20 RECORDED. Report the final coverage table to the user.

## Retry policy

- Max **3 attempts per step** (a Step-7 bounce-back counts as an attempt on the target step).
- On the 3rd failure of any step: STOP, report what failed, what was tried, and the smallest decision needed from Bjion. Never loop past the cap in either mode.
