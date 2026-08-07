---
name: setter-regen-speed-fix
description: Fix the Appointment Setter's Regenerate button - stop it erroring with "Couldn't regenerate the draft: The read operation timed out" and get a regenerate finishing inside 3 seconds. Static loop with a pre-baked goal, five steps, and a measured done-rule. Use when the user says regenerate is bugging out, timing out, erroring, slow, taking 40 seconds, or "make regenerate faster"; or invokes /setter-regen-speed-fix.
---

# Setter Regenerate: stop the timeouts, get under 3 seconds

## LOOP TRAINING MODE: **ON**

Flip that word to **OFF** on the line above to change behaviour. Nothing else to edit.

- **ON** - pause at the end of every step and wait for Bjion's approval before
  continuing. Before running a step, check its done-rule first: if it already
  passes, say so and skip it. Only re-run steps that fail. Retry cap still applies.
- **OFF** - run every step autonomously with no pauses. The done-rule checks and
  the retry cap still apply exactly the same; only the pauses go away.

**Retry cap, both modes: 2 attempts per step.** A step that fails twice stops the
whole loop. Report what failed, what was tried, and what the numbers were. Never
attempt a third time, never widen the goal to make a step pass.

---

## Goal

A regenerate on a real Needs-review row completes in **under 3 seconds**, and never
surfaces "Couldn't regenerate the draft: The read operation timed out".

## Done-rule (the whole loop is finished when this passes on production)

Five timed regenerates against `navreo-signals.onrender.com`, measured client-side
from the POST to the status response that returns `done`:

1. **p50 <= 3.0s**
2. **max <= 5.0s**
3. **0 errors across the 5**

Anything less is not done. If steps 1-4 all land and p50 is still above 3.0s, STOP
and report the per-stage numbers - the remaining lever is the model itself, and
that is Bjion's call, not a reason to relax the bar.

## What is already known (do not re-derive this)

- Error text: `http_json` in `app/server.py:213` calls `urlopen(..., timeout=60)`.
  A socket read timeout stringifies to exactly "The read operation timed out",
  which the redraft job returns as its `error` and `setter.html` prefixes with
  "Couldn't regenerate the draft: ". **Nothing on this path retries.**
- Slowness: `_redraft_sync` in `app/setter.py` runs three serial gpt-5-mini calls -
  classify (`~1237`), draft (`~1103`), proofread (`~1313`) - each strict JSON schema,
  none setting `reasoning_effort` or a completion-token cap. The code's own comment
  measures the chain at 25-42s.
- Polling floor: `runRedraftJob` in `app/setter.html:~3475` does `await sleep(2000)`
  BEFORE its first status check, so no job can read faster than ~2s however fast the
  server is.

Repo: `~/navreo-signals`. Live verify needs a minted `navreo_session` cookie and a
`/api/version` poll to confirm the deploy landed (see the signals live-verify recipe).

---

## Step 0 - Baseline (always runs, never skipped)

Write `app/test_redraft_speed.py`: mint the session cookie, take 3 fixed
Needs-review row ids, POST `/api/setter/queue/redraft` with `async: true`, poll
`/api/setter/queue/redraft/status` every 250ms, record wall-clock ms and any error
per run. Print p50 / max / error count.

Run it against production. Save the numbers as BEFORE. This is the only step with no
pass/fail - it produces the "before" half of the verification.

**Side-effect to state out loud once:** a regenerate rewrites that row's draft. That
is exactly what the button does, the agent is draft_only, and nothing sends. Use
rows Bjion has not part-edited.

## Step 1 - Kill the crash

Give the OpenAI calls their own timeout and a single retry on timeout only (not on
4xx). Keep the 60s ceiling as the outer bound; the retry is what removes the visible
error.

**Done-rule:** with a forced-timeout stub, a regenerate still returns a draft, and
`test_redraft_speed.py` reports 0 errors across 5 runs on production.

## Step 2 - Make each call fast

Add `reasoning_effort: "low"` and a `max_completion_tokens` cap to all three
gpt-5-mini calls. This is the single biggest wall-clock lever.

**Done-rule:** server-side stage timings (step 3 adds them) show every individual
model call under 1.5s, and no draft comes back truncated or schema-invalid.

## Step 3 - Stop making calls that do not need to happen

Instrument `_redraft_sync` to record per-stage ms into the job body, then cut what
the timings show is dead weight: reuse the row's stored classification instead of
re-classifying (the persist path already exists), and fold or drop the separate
proofread call.

**Done-rule:** a regenerate on an already-classified row makes exactly **one** model
call, and the job body reports its per-stage breakdown.

## Step 4 - Remove the UI's 2-second floor

In `runRedraftJob`, poll immediately, then back off (0ms, 250ms, 500ms, 1s, 2s...).
Leave the 240s deadline, the `unknown` re-read recovery, and the "still working"
button text alone.

**Done-rule:** perceived end-to-end in the browser matches the measured server time
within ~300ms.

## Step 5 - Deploy, verify, report

Commit, push, poll `/api/version` until the deploy is live, re-run
`test_redraft_speed.py` against production. Then regenerate one row by hand in the
UI and confirm a clean draft appears with no error banner.

**Done-rule:** the full done-rule above passes on production, and the closing report
is a BEFORE / AFTER table: p50, max, error count, per-stage breakdown, and which
steps changed which number.

---

## Stop rules

- Any step failing twice ends the loop with a report. No third attempt.
- Never set the agent to autopilot, never touch `autopilot_enabled`, never send.
- Never relax the 3s bar or swap the measurement to a friendlier one to make it pass.
- If a change would alter what the drafter WRITES (tone, rules, slot picking) rather
  than how fast it writes it, stop and ask - this loop is about speed, not copy.
