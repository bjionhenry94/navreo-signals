---
name: notifications-impact-priority
description: Static orchestration skill that reworks the notifications digest's prioritisation (app/build_notifications.py + app/notifications.html) around a single Impact Score — meetings first, positives second, both scaled by remaining runway (net leads left ÷ the 1,500–2,500-sends-per-positive yield) — so account strategists see "work on these first" instead of a wall of equal-looking recommendations. Fixed step list, checkable done-rules, retry caps, Loop Training Mode toggle. Trigger on "run the impact priority skill", "fix the notifications prioritisation", "re-rank the digest", or "/notifications-impact-priority".
---

# Notifications Impact Priority

## ⚙️ Loop Training Mode — **OFF** (flip here)

```
LOOP_TRAINING_MODE: OFF
```

- **ON** (default): pause at EVERY step and wait for the user's approval before
  continuing. Before running a step, check its done-rule — if it already
  passes, announce "Step N already passes, skipping" and move on. Only re-run
  steps that fail their done-rule. Max **3 retries per step**; on the 3rd
  failure, stop and report instead of looping.
- **OFF**: run all steps autonomously with no pauses. Done-rule checks and the
  3-retry cap still apply exactly as above.

To flip: edit the `LOOP_TRAINING_MODE` line above and save.

## Goal

Account strategists have limited time and the digest overwhelms them. Re-rank
every recommendation block by **expected remaining impact**, so the top of the
page is always "the campaigns where action today buys the most future leads."

**Done when an account strategist scores the prioritisation 8/10 or higher.**

## The Impact Score (the whole idea)

Benchmark: **1 positive per ~2,000 sends** (range 1,500–2,500).

Per campaign:

```
remaining_sends     = net_leads_remaining × emails_per_lead_in_sequence
expected_positives  = remaining_sends ÷ 2000
    # if the campaign's own observed positive rate BEATS 1/2000, use its own
    # rate instead — a ripping campaign earns its own forecast
performance_mult    = 1 + (2 × meetings_booked) + (0.5 × positives_so_far)
    # meetings outrank positives, always
impact_score        = expected_positives × performance_mult
```

Sanity anchors from the brief — the score MUST reproduce these:
- Ripping campaign at 25% complete → **top** (big runway × big multiplier).
- Hot campaign with only ~1,000 net leads left → **low** (runway ≈ 0.5
  expected positives; nothing left to win).
- 90%-complete campaign with 15,000 contacts left → **high** (~7+ expected
  positives still on the table).
- Campaigns nearly out of leads never outrank younger campaigns with runway,
  no matter how good their history reads.

Severity tiers (High/Medium/Low) survive as a *badge on the card*, not the
sort key. Sort key = impact_score, descending, everywhere.

## Steps

### Step 1 — Gather the inputs
Confirm `build_notifications.py` can compute, per campaign: positives,
meetings booked, leads contacted, **net leads remaining** (total leads −
contacted − bounced/unsubscribed), and emails-per-lead from the sequence
length. Pull from the existing Supabase data layer / Smartlead fetch it
already uses — no new providers.
**Done-rule:** a dry run prints all five inputs for every active campaign
with zero nulls (unknown meetings → 0, stated in output).

### Step 2 — Implement the score
Add `impact_score(campaign)` to `build_notifications.py` implementing the
formula above, plus a one-line plain-English reason string, e.g.
*"~7 more leads likely here — 15,000 contacts left on a proven campaign"* or
*"Only ~0.4 leads left in the tank — park it."* No jargon in reasons.
**Done-rule:** unit check reproduces all four sanity anchors in the correct
relative order.

### Step 3 — Re-rank the digest
Replace the `(tier, -sent)` sort (currently ~line 1233) with
impact_score-descending across all sections that list campaign
recommendations. Tier stays visible as a badge.
**Done-rule:** rebuilt digest JSON is ordered by impact_score everywhere;
diff against a hand-computed ranking of the same data matches exactly.

### Step 4 — Simplify the page
In `notifications.html`: a **"Work on these first"** section with the top 5
cards (score + reason shown), then everything else collapsed under a
one-line-per-campaign summary list ("18 lower-impact campaigns — expand").
Follow the existing no-emoji / colour-as-severity conventions.
**Done-rule:** page loads with exactly 5 expanded cards, each showing score +
plain-English reason; the rest collapsed; no console errors.

### Step 5 — Verify on real data
Rebuild against live data. Hand-check the top 5: does each genuinely have
the most expected positives remaining? Hand-check the bottom: are the
nearly-drained campaigns down there even if historically strong?
**Done-rule:** all spot-checks pass; any surprise is explained by the data,
not a code bug.

### Step 6 — Strategist score
Convene a simulated account-strategist panel (subagent, `model: sonnet`,
persona: time-poor Navreo account strategist mid-morning triage). Show the
real rebuilt page; ask them to score **the prioritisation** 1–10 and name the
single worst-ranked item.
**Done-rule:** score ≥ 8/10. On failure: fix the named issue, re-run Steps
3–6. Counts against the 3-retry cap.

### Step 7 — Ship
Commit with a clear message. If any touched file has a deploy-repo copy
(~/navreo-signals), diff-check and sync it per the signals-deploy-repo rule.
**Done-rule:** clean `git status`; deploy copy identical where applicable;
final summary states the strategist score.

## Guardrails

- Static skill: do not add steps, providers, or scope mid-run.
- Never let the multiplier rescue a campaign with no runway — runway is the
  base, performance only multiplies it.
- Beware the PGRST102 mixed-key gotcha from the original digest build when
  touching Supabase queries.
- Reasons are plain English, always — the strategist should never need to
  understand the formula to trust the ranking.
