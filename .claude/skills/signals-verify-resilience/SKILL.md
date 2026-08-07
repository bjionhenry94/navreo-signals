---
name: signals-verify-resilience
description: Static orchestration loop for the Navreo signals tool (app/server.py + app/deliverability-tab.js on Render, navreo-email-deliverability-audit.onrender.com). Diagnose what restarts kill list-verification jobs (Supabase boot ledger + interruption attribution), restore guarded auto-resume of interrupted verify jobs (production-only, one continuation per job, duplicate-storm-proof), surface "Last verified <date> · N checked · N removed" on each campaign row, and fix the "N to verify" count so it excludes already-verified leads across both cache tiers with instant cache invalidation. Use when the user says "run the verify resilience loop", "fix the verify job restarts", "make verify jobs survive redeploys", or "/signals-verify-resilience".
---

# signals-verify-resilience

One static loop. Read once, run steps in order, judge each against its done-rule, stop when the Final Done-Rule passes.

## Loop Training Mode

**`LOOP_TRAINING_MODE: ON`** (default; flip the word to OFF to change behaviour)

- **ON:** Pause at EVERY step. Show the user what the step will do and wait for explicit approval before executing. Before running any step, first evaluate its done-rule: if it already passes, report "already passing, skipping" and move on. Only re-run steps whose done-rule fails. Max **3 attempts per step**; after the 3rd failure, stop and report the blocker to the user instead of looping.
- **OFF:** Run all steps autonomously with no pauses. Keep every done-rule check and the same 3-attempt retry cap. Still stop and report if a step exhausts its retries.

In both modes: never mark a step done without its done-rule evidence in hand.

## Goal

Verification jobs survive redeploys by resuming themselves without wasting credits; every campaign shows when it was last verified; the to-do's "N to verify" counts only leads that actually still need verifying.

## Hard constraints (apply to every step)

- **Edit the repo that actually deploys to Render.** The iCloud working copy has silently reverted edits before. Find the deploy repo via `git remote -v` matching the Render service; after every deploy, verify the deployed commit hash (e.g. via a `/api/version` or commit endpoint, or the boot ledger row) equals the pushed hash before claiming the deploy landed.
- **Spend gate:** all restart-survival and resume tests run in mock mode (`_mock_verify_worker` / `DELIV_MOCK`). Exactly ONE real verification run is allowed, on the smallest flagged campaign, hard-capped at **200 email verifications total** across ListMint + MillionVerifier. Count provider calls as you go; abort the real run at 200.
- **Line numbers drift.** Every line number quoted below (3692, 4456, 4786, 9848) is a hint, not a fact. Step 1 re-verifies all of them by grep before any edit.
- Supabase project: `fnykldftbkrccihdjayl`. All verification reads are direct SQL against Supabase (or direct Smartlead API), never app logs or the app's own UI numbers.
- No em-dashes in any written verdict or doc.

## Steps

### Step 1 - Recon and line-number re-verification
Locate the deploy repo (not the iCloud copy). Grep server.py for: `_jobs_recover_orphans` (docstring documenting the 2026-07 duplicate-run storm, quoted ~3692), the `verify_campaign_state.last_verify_at` write (~4456), `api_verify_status` returning it (~4786), the email_verifications discount in the lead-count path (~9848), plus `_SERVER_INSTANCE`, `_ON_RENDER`, `_campaign_has_active_job`, `_JOB_CREATE_LOCK`, `_LEAD_COUNT_CACHE`, `_VERIFY_TTL_DAYS`, `_mock_verify_worker` / `DELIV_MOCK`. Record actual line numbers.
**Done-rule:** every symbol above located with its current line number, and the deploy repo confirmed as the one Render builds from (remote URL matches the Render service repo).

### Step 2 - Boot ledger (diagnosis instrumentation)
Create Supabase table `server_boot_ledger` (id, booted_at, server_instance, render_instance_id, git_commit, prev_uptime_seconds, created_at). In server.py startup, write one row per boot: boot time, `_SERVER_INSTANCE`, `RENDER_INSTANCE_ID` env, deployed git commit, and the previous incarnation's process uptime (persist a heartbeat timestamp somewhere durable so the next boot can compute it; Supabase itself is fine). Deploy; verify deployed commit hash.
**Done-rule:** SQL against `server_boot_ledger` returns at least one row from the live Render instance whose git_commit equals the just-pushed hash.

### Step 3 - Restart-cause verdict (Verification 1)
Over an observation window (use all history available since ledger install, plus retroactive attribution where app_jobs timestamps + git push timestamps allow), pull every `app_jobs` row with status 'interrupted' via SQL. Match each to the nearest ledger boot and to git-push timestamps. Attribute each interruption: **redeploy** (boot follows a push within minutes), **idle spin-down** (boot after a long idle gap, prev_uptime consistent with Render free/starter spin-down), or **crash** (boot mid-activity with no push). Write the verdict in plain English (no jargon): what causes the restarts, with counts per cause.
**Done-rule:** a written verdict exists in which every 'interrupted' app_jobs row in the window has an attributed cause, and every attribution is backed by SQL read from Supabase, not app logs.

### Step 4 - Guarded auto-resume
Restore auto-resume of interrupted verify jobs inside the existing grace-window sweep. Guards, all mandatory:
- Production instance only: `_ON_RENDER` true AND job owner == `_SERVER_INSTANCE`.
- At most ONE automatic continuation per job ever (persist a `auto_resumed` flag or resume_count on the job row; check before resuming).
- Must pass `_campaign_has_active_job` and acquire `_JOB_CREATE_LOCK` before creating the continuation, so the 2026-07 duplicate-run storm (see `_jobs_recover_orphans` docstring) cannot recur.
- Credit safety needs no extra code: the 60-day verdict cache means a resume only pays for not-yet-checked emails. Confirm the resume path actually goes through the cache lookup.
**Done-rule:** code review of the diff shows all four guards present, and the deployed commit hash matches the push.

### Step 5 - Mock-mode resume proof (Verification 2)
In mock mode (`DELIV_MOCK` / `_mock_verify_worker`): start a mock verify job, restart the server mid-job (redeploy or process restart on Render), and watch. Then SQL against app_jobs: confirm exactly one automatic continuation row/flag, no duplicate concurrent worker rows for the campaign, and the job reached 'finished'.
**Done-rule:** app_jobs SQL shows interrupted → exactly one auto-continuation → finished, zero duplicates. If duplicates appear, fix and re-run (counts against Step 5's retry cap).

### Step 6 - "Last verified" line in the UI
In deliverability-tab.js, on each campaign row in the verify to-do, render "Last verified <date> · N checked · N removed" from `api_verify_status` (which returns `verify_campaign_state.last_verify_at` and counts). Date in browser-local time with named timezone style. Deploy; verify commit hash.
**Done-rule:** the line renders on flagged campaign rows in the RENDERED deployed page in a browser (screenshot taken), and its date matches `verify_campaign_state.last_verify_at` read independently by Supabase SQL. Grep of deployed JS alone does NOT count as done.

### Step 7 - Fix "N to verify" count
The shown count must equal Smartlead `total_leads` minus DISTINCT leads verified within `_VERIFY_TTL_DAYS` across BOTH tiers: (a) Smartlead lead columns `email_verification` / `email_verified_at`, and (b) the `email_verifications` table. Replace the ~9848 overflow-only discount with this union. Also: invalidate that campaign's `_LEAD_COUNT_CACHE` entry the moment its verify job finishes, so no hour-old number survives a completed verify. Deploy; verify commit hash.
**Done-rule:** code implements the two-tier distinct union and the on-finish cache invalidation; deployed hash matches.

### Step 8 - Count equality proof on two campaigns (Verification 5)
For TWO campaigns, immediately after a verify completes (mock verifies are fine for one of them if they write the same state), compare: rendered page's "N to verify" vs (Smartlead API `total_leads` fetched directly) minus (distinct verified-within-60-days computed by direct Supabase SQL across both tiers).
**Done-rule:** exact equality for both campaigns, read from the rendered deployed page, with no cached hour-old number involved.

### Step 9 - The one real run + credit proof (Verification 3)
Pick the SMALLEST flagged campaign. Run one real verification, hard-capped at 200 provider calls total (ListMint + MillionVerifier combined); if the campaign's unverified count exceeds 200, verify only up to the cap and stop. Ideally structure it to exercise resume: start, restart, let auto-resume finish it. Then read the provider-call ledger back by SQL and cross-check: every email the resumed portion sent to a provider was absent from both cache tiers at call time.
**Done-rule:** provider ledger SQL shows ≤200 total calls, and zero calls for emails that were already present in either cache tier.

### Step 10 - Wrap-up
Assemble the five verification proofs (verdict text, mock-resume SQL, credit-proof SQL, UI screenshot + matching SQL date, two-campaign equality numbers) into one plain-English summary for the user. Note anything left open.
**Done-rule:** summary delivered containing all five proofs.

## Final Done-Rule

All five verifications pass:
1. Written restart-cause verdict; every 'interrupted' app_jobs row in the window attributed (redeploy / spin-down / crash), backed by Supabase SQL.
2. Mock-mode proof: exactly one automatic continuation, no duplicate workers, job finished (app_jobs SQL).
3. Real-run credit proof (≤200 emails): resumed portion called providers only for emails absent from both cache tiers.
4. "Last verified …" line visible on flagged campaign rows in the rendered deployed page (screenshot), date matching Supabase.
5. Two campaigns: rendered "N to verify" == Smartlead total_leads minus distinct verified-within-60-days (both tiers, direct SQL), exact, uncached.

All 5, or it isn't done.
