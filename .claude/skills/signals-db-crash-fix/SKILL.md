---
name: signals-db-crash-fix
description: Find why the Navreo signals tool / database keeps crashing, fix the trigger, and prove the fix by re-firing the trigger. One static orchestration skill with a Loop Training Mode toggle (pause-per-step vs autonomous). Trigger on "/signals-db-crash-fix", "the tool keeps crashing", "the database keeps crashing", "signals is down again", "fix the db crash".
---

# Signals DB Crash Fix

## LOOP TRAINING MODE  ·  toggle here  ·  DEFAULT: ON
```
LOOP_TRAINING_MODE = ON        # flip to OFF for autonomous runs
RETRY_CAP = 3                  # max attempts per step, then STOP (never loop forever)
```
- **ON:** pause at every step and wait for Bjion's approval before continuing. Before running a step, check its DONE-RULE first: if it already passes, skip the step. Only re-run steps that fail. Never exceed RETRY_CAP attempts on a step.
- **OFF:** run autonomously, no pauses. STILL run every DONE-RULE check and STILL obey RETRY_CAP.
- Exception (both modes): any step that mutates infrastructure (restart, scale, delete, deploy) always pauses for one yes before it acts.

## GOAL
Stop the database (and the tool) from crashing. Find the exact trigger, fix it, and prove it by recreating the trigger without a crash.

## STANDING RULES
- Diagnose read-only first. Do not restart, scale, or wipe anything to "see if it helps".
- One trigger at a time: name it, fix it, prove it, before touching the next.
- If a step hits RETRY_CAP, STOP and report what you know. Do not keep looping.
- Context: repo `~/navreo-signals` (push main → Render auto-deploys). Live: navreo-signals.onrender.com. DB: Supabase project `fnykldftbkrccihdjayl`, service-role key in `~/.navreo-keys.env`. Web dyno is a 512MB Render starter.

## STEPS  (each has a DONE-RULE; in ON mode, pause after each)

**1. Define the crash + grab evidence.**
Pull `server_boot_ledger` (look at `prev_uptime_seconds`), Render logs, and Supabase health/metrics.
DONE-RULE: you can say, with a log line as proof, whether the WEB instance dies (Render OOM) or the DATABASE dies (Supabase), and roughly how often.

**2. Read the signature.**
OOM signature: repeated boots with `prev_uptime_seconds` ≈ 120s and memory near 512MB. DB signature: Supabase logs show connection-limit / pooler exhausted / compute exhausted / statement timeout.
DONE-RULE: one named signature backed by the exact line that proves it.

**3. Find the trigger.**
Prime suspects from history: a heavy in-process sweep run inside the web process (collision census / `_collision_live_loop`), an unpaginated query pulling everything (`sb_get_all`), a leaked DB connection (client never closed), or a burst endpoint (hydrate-burst). Correlate each crash time with what ran just before.
DONE-RULE: a single reproducible action or job that precedes the crash every time.

**4. Reproduce it safely.**
Fire the suspected trigger on demand (against a safe target, never a real send).
DONE-RULE: firing it crashes the instance / DB or clearly spikes it toward the limit. If it will not reproduce, return to step 3 (within RETRY_CAP).

**5. Fix the smallest thing that removes the trigger.**
Patterns: move the heavy sweep out of the web process into a cron/worker; paginate or bound the query; close connections / route through the pooler; add a guard or cap. Smallest change that kills the trigger, nothing else.
DONE-RULE: fix committed and deployed (note the commit sha); the offending work no longer runs in the web request path, or the query is now bounded.

**6. Prove it (the verification).**
Re-run the exact trigger from step 4.
DONE-RULE: it runs to completion with NO crash; `server_boot_ledger` then shows a stable long uptime; Supabase stays healthy.

**7. Report.**
DONE-RULE: one short plain-English note: what was crashing, the trigger, the fix (commit sha), and the proof from step 6.

## OVERALL DONE-RULE
The identified trigger can be fired repeatedly and the tool plus database stay up (stable uptime in `server_boot_ledger`, healthy Supabase). A different trigger surfacing later is a fresh run of this skill, not a failure of this one.
