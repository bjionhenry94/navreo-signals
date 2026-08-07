---
name: deliverability-page-filters
description: Orchestration loop that unifies deliverability.html onto two page-level filter dimensions — client and date range (7d/14d/30d, never all-time) — moves the date seg to the top of the page, makes every section adapt (inbox/domain manager filter by client only), ships it live, and validates with 5 simulated non-technical testers who must score the page 9/10+ on actionable insights and easy-to-digest. Trigger on "run the deliverability filter loop", "unify the deliverability filters", "/deliverability-page-filters".
---

# deliverability-page-filters — Orchestration Skill

## ⚙️ LOOP TRAINING MODE: **ON**

> **To flip it:** edit this line to `LOOP TRAINING MODE: OFF` (or say "training mode off" when invoking).
>
> - **ON** — pause at EVERY step and wait for Bjion's explicit approval before continuing.
>   Skip any step that already passes its done-rule. Only re-run steps that fail.
>   Retry cap still applies.
> - **OFF** — run all steps autonomously, no pauses. Done-rule checks and the retry
>   cap stay exactly the same.
>
> **Retry cap (both modes): 3 attempts per step.** On the 3rd failure, stop the loop
> and report what's blocking — never loop forever.

## Goal

Make https://navreo-signals.onrender.com/app/deliverability.html easy to filter by
**exactly two page-level dimensions**:

1. **Client** (chips, already at top — `#ah-chips`)
2. **Date range** — **7d / 14d / 30d only. All-time must not exist anywhere.**

The 7/14/30 seg moves to the **top of the page** beside the client chips so it reads as
a page dimension, and **every section re-slices** to the pair. Inbox manager and domain
manager sections respect the **client filter only** (date range doesn't apply to current
mailbox/domain state — that's fine, they must not show a dead date control).

Repo: `~/navreo-signals` · Page: `app/deliverability.html` (state object ~line 584 holds
`trend/week/bounce` as separate ranges — collapse to one `state.range`). Standing ruling:
≤3 date presets, 30-day cap, client filter is client-side re-slice ([[analytics-widget-controls-ruling]]).

## Steps

**Step 1 — Unify the filters in the code.**
Promote one 7/14/30 seg into the page header next to the client chips; delete the
per-widget segs (`data-seg="week"` ~line 403, `data-seg="bounce"` ~line 421); collapse
`state.trend/week/bounce` into a single `state.range` (default 30) that every widget
reads. Client chips stay page-level. Remove any all-time path.
*Done-rule:* exactly ONE date seg in the DOM, at page level; grep finds no other
`data-range` groups; every metric widget re-renders on both client and range change;
inbox/domain sections react to client only and show no date control.

**Step 2 — Data-truth check.**
For at least 3 combos (e.g. All×7d, one client×14d, one client×30d), recompute the
headline numbers straight from the hub JSON / API the page loads and compare to what the
page renders.
*Done-rule:* every checked number matches the source data exactly.

**Step 3 — Ship and verify live.**
Commit, push, then confirm the deploy per [[signals-live-verify-recipe]]: mint the
`navreo_session` cookie, poll `/api/version` until the new build is live, then load the
live page and confirm the Step 1 done-rule holds in production.
*Done-rule:* live URL serves the new build and passes the Step 1 checks.

**Step 4 — 5-tester validation.**
Spawn 5 parallel subagent testers, each a distinct non-technical persona (e.g. agency
founder, VP Sales, SaaS founder, sales ops lead, fractional CRO). Each loads the live
page (logged in), tries to answer "how is deliverability for [client] over the last
7/14/30 days?", and scores 1–10 on **(a) actionable insights** and **(b) easy to
digest**, with specific reasons for anything below 10.
*Done-rule:* all 5 testers score **≥9 on BOTH criteria**.

**Step 5 — Iterate on failures.**
If Step 4 fails, cluster the sub-9 feedback, apply the smallest fix that addresses it,
then re-run only Steps 2→4 (Step 1 skips if its done-rule still passes). Each full
iteration counts against the retry cap.

## Loop rules

- Before running any step, check its done-rule first — **skip steps that already pass**.
- Re-run only the steps that fail; never restart the whole loop from scratch.
- Training Mode ON: after finishing (or skipping) a step, report the result and **wait
  for approval** before the next step.
- Overall done: Step 1–4 done-rules all pass on the **live** page. Report the final
  tester scorecard when closing the loop.
