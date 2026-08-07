---
name: trigify-engagement-autopull
description: Static orchestration skill that makes the Navreo signals tool's Trigify engagement signal pull in automatically every day, like the hiring campaigns. The Trigify SEARCHES reliably collect posts, but the WORKFLOWS meant to turn posts into engagers + push them to Supabase almost never fire (≈6 executions across 47 workflows). Fix = the tool pulls engagers itself on the daily run (recent posts → /post/comments → /profile/enrich → stage engagement_events → qualify), plus reclaim events orphaned to dead source ids and kill stale workflows, then backfill the last N days and prove the Render cron feeds it unattended. One fixed step list, each with a checkable done-rule, plus a Loop Training Mode toggle. Use when the user says "fix the Trigify engagement pull", "engagement data isn't coming into the tool", "there should be more engagements", or "/trigify-engagement-autopull".
---

# trigify-engagement-autopull

Make the engagement (Trigify) signal flow into the tool automatically every day, like hiring. Static loop — steps are fixed, each has a done-rule, Loop Training Mode controls pausing.

## How it works now (grounding)
The old design relied on Trigify **workflows** to push engagers into Supabase — but those workflows barely fire (≈6 runs across 47). The **searches**, however, reliably collect each monitored profile's posts. So the tool now **pulls** engagers itself, in `app/server.py`:
`stage_trigify_engagers(src, cfg)` (called at the top of `pull_engagement_source`) reads each saved search's recent posts (`GET /searches/{id}/results`, last `ENG_BACKFILL_DAYS`=15), fetches commenters (`POST /post/comments`), enriches each (`POST /profile/enrich`), and stages them as `engagement_events (status=NEW)` — deduped by `(source_id, engager_linkedin_url, post_url)`. The existing qualify loop then gpt-5-mini-gates them and writes QUALIFIED to `signal_leads`. This runs on the Render **cron** (`python app/run_daily.py`, background job, no HTTP timeout) every 3h. Live engagement sources: `draft-f383570e` (46 competitor profiles → campaign `cdraft-1a9ba7ce`), `draft-068b0856` (bjionhenry → `cdraft-ca4cc4e3`).

**Credit + timeout notes:** enrichment is 1 credit/engager, so bound it — `ENG_STAGE_PER_RUN` (40) per source per run, `ENG_COMMENTS_PER_POST` (30). Never backfill through the HTTP `/api/sources/pull` endpoint (Render kills web requests >~100s); backfill by running the code directly / the cron.

---

## ⚙️ LOOP TRAINING MODE  →  **OFF**

Flip it by editing this one line:

    LOOP_TRAINING_MODE = OFF       # ON = approve every step · OFF = run autonomous

**When ON**
- Pause at the end of **every** step and wait for my explicit approval before starting the next.
- Before running a step, check its done-rule first. **If it already passes, skip it** — say so and move on.
- Only (re-)run steps that fail their done-rule.
- Retry cap applies (see below). Never loop a step forever.

**When OFF**
- Run all steps autonomously, no pauses.
- Still check every step's done-rule and still honour the retry cap. Report at the end, not between steps.

**Retry cap (both modes):** any single step retries **max 3** times against its done-rule. On cap-hit, stop that step, record it as FAILED with the reason, keep going, surface it in the final report. Never silently exceed.

---

## THE GOAL

Engagement pulls into the tool **automatically every day, no user intervention** — like hiring. **Done means:** the tool-driven pull is wired into the daily run, no `engagement_events` orphaned to a dead source, no stale workflow, both engagement campaigns are filled with leads from the last `ENG_BACKFILL_DAYS`, and the Render cron provably feeds new engagement data unattended.

**Convention (reuse, don't reinvent):** use `sb()`, `trigify_api()`, `stage_trigify_engagers()`, `pull_engagement_source()`, `_trigify_deprovision()`. Keep dependencies at pure-stdlib + `certifi`.

---

## THE STEPS

### Step 1 — Confirm the diagnosis
- Per live engagement source: searches healthy (`GET /searches/{id}` → `total_results` > 0, recent `last_result_at`) but workflows near-dead (`GET /workflows/{id}/executions` ≈ 0). Dump `engagement_events` by `(source_id, status)`; name any stale source ids.
- Done-rule: written evidence that searches collect posts but workflows don't fire, plus the stale-source-id set.

### Step 2 — Reclaim orphans + kill stale workflows
- Delete/repoint `engagement_events` rows tied to a dead source id (repoint NEW to the live successor by matching monitored profile; delete exact duplicates already under the live source). Deprovision any Trigify workflow whose embedded source id isn't live (`_trigify_deprovision`; keep shared searches).
- Done-rule: zero `engagement_events` under a non-live source; no enabled workflow targets a dead source id.

### Step 3 — Verify the tool-driven pull is wired
- `stage_trigify_engagers` exists and is called inside `pull_engagement_source`; a small live test (`per_run` low) stages real enriched engagers as NEW events via `/post/comments` + `/profile/enrich`. Code is deployed to Render (new deploy live).
- Done-rule: a test run stages ≥1 enriched engager (name + title + company) into `engagement_events`; `git log` on the deploy repo shows the pull commit and the Render web deploy is `live`.

### Step 4 — Backfill the last N days
- Run `pull_source({id})` for each live engagement source directly (not via HTTP) enough passes to drain the recent-post backlog into qualified leads. Bound by the per-run caps.
- Done-rule: **both** engagement campaigns show > 0 (target: a healthy batch each) leads in `signal_leads` / `/api/lead-counts`.

### Step 5 — Prove the daily automation
- Confirm the Render cron runs `python app/run_daily.py` on schedule, and that its per-source path (`pull_source` → `pull_engagement_source` → `stage_trigify_engagers` + qualify) processes new engagement data unattended. Seed one fresh post-engager (or rely on the next real post) and confirm it flows NEW → QUALIFIED/OFF_BRIEF → lead with no manual step.
- Done-rule: cron command == `python app/run_daily.py`, schedule set; a freshly-staged engager is auto-qualified into a lead by the daily path.

---

## HOW TO RUN

1. Read the mode line. If **ON**, one step at a time, stop for approval, skip already-passing steps. If **OFF**, run all five, report at end.
2. Check each done-rule with a real `sb`/Trigify/`curl` query. Retry ≤3×, then mark FAILED and continue.
3. Steps 2 (mutates data + external workflows) and 4 (spends enrichment credits) are the sensitive ones — honour the caps; never delete a saved search another live workflow uses.

## OVERALL DONE-RULE

- Tool-driven pull wired into the daily run and deployed to Render; no orphaned events; no stale workflow.
- Both engagement campaigns filled with leads from the last `ENG_BACKFILL_DAYS`.
- A fresh engager is auto-processed by the Render cron — future engagement data is pulled in with certainty, no intervention.
- Final report: one line per step — DONE / SKIPPED / FAILED (with reason).
