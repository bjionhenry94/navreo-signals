---
name: sources-pull-more-ship
description: Ship the "Pull more" experience for campaign source pools in the signals tool - a standing pull record per pool (total / pulled / remaining) and a one-button gated pull on the sources surface, so an account strategist who tested a pool can return and pull the rest without chat. The pull always routes through the gated pipeline (A-grade-first selection, collision sweep, ListMint verify, audit row) as a polled background job - NEVER a raw push. Finishes only when a 5-strategist panel scores the journey 9/10+ for ease of use. Trigger: "ship the pull-more button", "make pulling the remaining pool easy", "/sources-pull-more-ship".
---

# Sources "Pull more" - ship

## ⚙ Loop Training Mode: **ON**   ← flip this line to OFF to run autonomously

**ON (default):** pause at EVERY step boundary and wait for the user's explicit approval
before continuing. Before starting a step, check its done-rule first - if it already
passes, report "Step N already passes, skipping" and move to the next pause. Only re-run
steps whose done-rule fails. Show what you're about to do before doing it.

**OFF:** run all steps end-to-end with no pauses. The done-rule checks, skip-if-passing
behaviour, and retry caps stay exactly the same - only the pauses go.

**Retry cap (both modes):** each step retries **max 3** times against its done-rule.
On cap-hit: record the step FAILED with the reason, continue only to steps that don't
depend on it, and surface every FAILED step in the final report. Never declare done on
a cap-hit.

## Goal

**An account strategist who has tested a pool can return to the sources surface, see
exactly how much pool remains, and pull the next batch with one button - and that pull
runs the SAME gated pipeline as chat (selection ruling, collision sweep, ListMint
verify, audit row), as a background job with visible progress.** A standing pull
record per pool makes "return and pull more" a first-class object, not a chat memory.
Done means a 5-account-strategist panel scores the journey **9/10 or higher** for
ease of use.

## Config (baked)

```yaml
POOLS:                       # the five Recontact 250k pools; seed records for all
  A: {list: d84c4881-fe13-4375-8368-d897a380bca4, campaign: 3708724, ruling: a-grade-titled}
  B: {list: 3ad89fce-772c-46d5-9989-e86423806301, campaign: 3708725, ruling: titled-then-inferred}
  C: {list: a0eff7e1-6a5f-4187-9078-83ca27b9abe6, campaign: 3708726, ruling: a-grade-titled}
  D: {list: 2f2311b6-0616-44c0-a2c2-eb68915d8486, campaign: 3708727, ruling: titled-then-inferred}
  E: {list: df1c4575-b312-4390-801b-58182ac8a6ac, campaign: 3708728, ruling: inferred-ok}

DEFAULT_BATCH: 500
PANEL_PERSONAS: 5            # account strategists; ALL must score >= PANEL_BAR
PANEL_BAR: 9                 # out of 10, ease of use
PANEL_ITERATION_CAP: 3       # UI redesign loops before surfacing failure
RETRY_CAP: 3
LM_CHUNK_START: 100          # adaptive: halve on HTML-error down to 10 (proven 2026-07-24/25)
```

## Ground truth

- Repo `~/navreo-signals` (LIVE deploy source - NOT any iCloud copy); push main →
  Render auto-deploy (~2 min). Design system: `app/navreo.css`, one orange per screen.
- The RAW Saved Pull path (`/api/list_pulls/pull`, provider `sample`) pushes without
  verification - this skill must NEVER route through it for gated pools.
- Gated pipeline pieces already exist from the 2026-07-24/25 run: staging table
  `r250k_agrade` (selection+sweep+verdicts+pushed_at), sweep SQL (suppressions /
  Navreo positive-repliers w/ corrections overlay / active-other / 30-day /
  live-intersect), ListMint adaptive chunking, `provider_usage` ledger,
  `list_upload_qa_runs` audit rows, Smartlead push with test-lead-first.
- Collision law: same-client only ([[collision-same-client-only]]); client = campaign
  NAME prefix. Cross-client = dossier note, not a drop.
- Jobs >60s are POLLED jobs with UI progress (full-live-UI law). Server POST handlers
  read `self._post_body`, never rfile.read.
- Mirror-wipe law: never write a preview `prospects` array on any source doc.
- Live verify: minted `navreo_session` HMAC cookie (see memory
  [[live-tool-authed-curl-minted-cookie]]) for API + Browser-pane DOM verify.

## Steps

### Step 1 - Standing pull records
Create table `pool_pulls` (id, list_id, campaign_id, seg, ruling, total_pool,
pulled_ok, dropped, remaining, last_pull_at, last_batch jsonb, status). Seed the five
POOLS rows with TRUE numbers reconstructed from `r250k_agrade` + `r250k_batch`
(pulled_ok = pushed_at rows per campaign; remaining = pool rows not yet selected or
selected-but-unverified). A pool a strategist tested always has its record - that is
the "existing record" the task names.
- **Done-rule:** five rows exist; their pulled_ok matches Smartlead lead counts ±
  Smartlead's own dupe-blocks; remaining is derived, not guessed.

### Step 2 - Server: gated pull endpoint + job
`POST /api/pool-pulls/<id>/pull {size}` starts a background job (job id returned,
`GET /api/pool-pulls/<id>/status` polls): select next `size` candidates per the
pool's `ruling` (A-grade titled first; inferred fill only where the ruling allows),
run the full sweep, ListMint-verify (adaptive chunks, cache-TTL skip, ledger rows,
verdicts to `people`), write the `list_upload_qa_runs` audit row, push verified
keeps to the campaign (test-lead-first, 100s, mark pushed), update the pool_pulls
record. Concurrency-locked per pool (409 while running). Failure leaves the record
consistent (every sub-step is written-back, resumable).
- **Done-rule:** a real end-to-end API pull of a SMALL batch (size 25) on one pool
  completes: verified keeps land in the campaign, audit row written, ledger rows
  match calls, record updated, second concurrent call 409s.

### Step 3 - UI: the "Pull more" panel
On the campaign page's **Sources tab** (app/campaigns.html, drafted-sources card) and
the pool list's page: show the record plainly - "X pulled · Y remaining of Z" - a
batch-size input (default `DEFAULT_BATCH`), and ONE orange **Pull more** button.
While a job runs: progress line (selecting → sweeping → verifying n/m → uploading)
polled from the status endpoint; on completion an honest result line ("487 verified
added · 13 failed verification · 2 dropped as collisions"). No raw-push controls
anywhere on gated pools.
- **Done-rule:** panel renders from the record (no fetch on page load beyond the
  existing detail fetch + one pool_pulls read); button fires Step 2's endpoint;
  progress and result lines show real job states; design-system compliant.

### Step 4 - Live wire + seed verify
Deploy; on the LIVE host with the minted cookie, browser-verify the WHOLE journey
DOM-first on one pool: open campaign → Sources → see remaining → Pull more (size 25)
→ watch progress → result line → Smartlead count grew by the kept count → record
updated. Interruptions/redeploys mid-job must resume, not duplicate (pushed_at
markers are the guard).
- **Done-rule:** the full journey passes on live with a real 25-row pull; a
  mid-job page reload shows the job still progressing (poll re-attaches); no
  double-pushed lead (Smartlead count delta == kept).

### Step 5 - Strategist panel (the bar the task sets)
Run `PANEL_PERSONAS` distinct account-strategist personas (cold-email strategist
day-to-day: tests pools, returns weekly, hates chat-only ops) through the live
journey. Each scores ease-of-use 1-10 with a written reason. ALL must score
>= `PANEL_BAR`. Below-bar feedback → fix the UI → re-panel (max
`PANEL_ITERATION_CAP` loops). Scores + reasons are recorded in the run log
verbatim - never invented, never averaged past a fail.
- **Done-rule:** a recorded panel round where every one of the five scores >= 9/10;
  every prior round's fixes listed.

### Step 6 - Ship + record
Commit+push (deploy repo), update memory (`project` note: pull-more shipped, record
schema, endpoint, the raw-pull ban on gated pools), publish the skill per convention.
- **Done-rule:** live host serves the shipped commit; memory updated; final report
  lists per-step status, panel scores, and any FAILED steps.

## Hard don'ts
- Never route a gated pool through the raw sample pull, and never add a control that
  could - the gate is the only door to Smartlead.
- Never fake, average, or round up a panel score - a 8.9 is a fail.
- Never write a preview `prospects` array on a source doc (mirror-wipe law).
- Never leave a job un-resumable: every sub-step writes back before proceeding.
- Never exceed a retry cap or report done while any done-rule fails.
