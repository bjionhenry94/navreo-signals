---
name: pull-more-wizard
description: Chat wizard behind the "+ Add people" button on a campaign's Sources tab. The tool generates a prompt naming a source pool (pp-A..pp-E) and campaign; pasting it into Claude runs this wizard - show the pool's live numbers, offer 500 / 1,000 / 2,000 (or a custom amount), state the estimated email-verification credit spend BEFORE anything runs, get an explicit yes, fire the gated pull endpoint, watch the job, and report added / failed verification / collision drops. Trigger: "/pull-more-wizard", any pasted prompt containing "Run the pull-more wizard for source pool", or "add more people to campaign X through the wizard".
---

# Pull-more wizard (chat side of "+ Add people")

## What this is

The Sources-tab button hands the strategist a prompt; this skill is what the prompt
runs. The conversation IS the wizard - three beats, no more:

1. **Show + ask.** Read the live record, restate it in one line ("3,517 pulled ·
   81,034 not yet pulled of 84,920"), offer **500 / 1,000 / 2,000** or their own
   number (cap 2,000 per run - the server clamps there anyway).
2. **Price + confirm.** Before ANY spend: estimate the verification cost - up to
   the chosen amount in ListMint credits, minus whatever is cache-verified (state
   the real cache count if cheap to read, otherwise say "up to N"). Wait for an
   explicit yes. Silence or "hmm" is not a yes.
3. **Run + report.** Fire the pull, poll until the job finishes, then report the
   honest triple: added / failed verification / dropped as collisions - plus the
   pool's new pulled / remaining line. If the job dies (server restart, ListMint
   outage), say exactly where it stopped and that a re-run cache-skips everything
   already verified - then offer the re-run.

## Mechanics

- Record: `GET https://navreo-signals.onrender.com/api/pool-pulls` (authed via the
  minted-cookie recipe - memory [[live-tool-authed-curl-minted-cookie]]). Match the
  pool id / campaign id named in the pasted prompt.
- Fire: `POST /api/pool-pulls/pull` body `{"seg":"<A..E>","size":<n>}` - 202 +
  job_id on start; 409 means one is already running (report its progress instead
  of double-firing).
- Watch: poll `GET /api/pool-pulls` (~every 60-120s, background-safe) until the
  pool's `active_job` clears; `last_batch` then carries pushed / verify_failed /
  live_dropped for the report.
- Cache-verified count (for the price line, optional): Supabase
  `r250k_agrade` where seg, flag null, pushed_at null, lm_result in the good set.
- The endpoint runs the FULL gated pipeline server-side (sweep, live collision
  check, ListMint, audit row, test-lead-first push). This wizard adds no checks
  and skips none - it only converses, fires, and reports.

## Hard rules

- **Never fire without the explicit size choice AND the yes after the price line.**
  The pasted prompt alone is intent to START the wizard, not consent to spend.
- Never exceed the asked size, never chain a second pull unprompted.
- One pull per pool at a time - a 409 is reported, not retried around.
- Report deficits plainly ("asked 1,000, added 924") - never round up, never pad.
- The campaign stays drafted throughout; say so when reporting if the user seems
  to expect sending.
