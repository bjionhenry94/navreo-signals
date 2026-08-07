---
name: fable-meetings-ideation
description: Static orchestration skill that produces the panel-verified "10 ways to use Fable 5" plan — 10 concrete ideas for using Fable 5 to book more qualified meetings or drastically cut delivery costs, grounded in Navreo's live campaign data (Supabase data layer, Smartlead/HeyReach analytics, credit ledgers), then scored by a 5-expert lead-generation panel until the list collectively scores ≥8/10. One fixed step list with checkable done-rules, retry caps, and a Loop Training Mode toggle. Use when the user says "run the meetings ideation", "10 Fable ideas", "ideate ways to book more meetings", "how can Fable lower our costs", or "/fable-meetings-ideation".
---

# Fable 5 Meetings & Cost Ideation — Panel-Verified 10

## ⚙ Loop Training Mode: **OFF**   ← flip this line to ON to pause at every step

**ON (default):** pause at EVERY step boundary and wait for the user's explicit approval
before continuing. Before starting a step, check its done-rule first — if it already
passes, report "Step N already passes, skipping" and move to the next pause. Only re-run
steps whose done-rule fails. Show what you're about to do before doing it.

**OFF:** run all steps end-to-end with no pauses. The done-rule checks, skip-if-passing
behaviour, and retry caps stay exactly the same — only the pauses go.

**Retry cap (both modes):** each step retries **max 3** times against its done-rule.
On cap-hit: record the step as FAILED with the reason, continue if the next step doesn't
depend on it, and surface every FAILED step in the final report. Never silently exceed
the cap. Never declare the skill done on a cap-hit.

**Model routing:** execution work (data pulls, drafting) may go to subagents on
`model: sonnet`. Panel judging and the final synthesis are judgment — keep them on the
session model (Fable). Panel judges must be independent subagents so they can't see each
other's scores.

## Goal

A ranked list of exactly **10 ideas** for using Fable 5 to either (a) book more
qualified meetings or (b) drastically lower Navreo's delivery costs — every idea
grounded in a real number from the live data, and collectively scored **≥8/10** by an
independent panel of lead-generation experts.

## Steps

### Step 1 — Evidence sweep (subagents OK, `model: sonnet`)
Pull real numbers, not impressions. Sources, in order of preference:
- `lilly-data` / Supabase (`fnykldftbkrccihdjayl`): reply + positive-reply rates by
  campaign/mechanism/icebreaker angle, contact_history volume, suppression counts.
- Smartlead MCP analytics: sends, bounce rates, per-variant stats, mailbox fleet health.
- Cost ledger facts already in memory: TheirStack credits (1/job returned, 166/day cap),
  Prospeo credits (1/page), MillionVerifier balance, HeyReach seats, Maildoso fleet
  (304 inboxes, 2,500-mailbox cap), Make scenario ops.
**Done-rule:** a written evidence brief with **≥8 quantified facts**, each with its
source named. No LLM-estimated numbers.

### Step 2 — Over-generate candidates
Draft **15 candidate ideas** (a bench of 5 beyond the 10 needed). Each candidate must
state: name · lever (**meetings** or **cost**) · the Step-1 fact it exploits · what
Fable 5 specifically does (orchestration, judgment, multi-agent, autonomy — not "AI
magic") · the existing skill/asset it builds on · effort (S/M/L) · expected impact ·
concrete first step.
**Done-rule:** ≥15 candidates; every one cites a Step-1 fact AND names an existing
Navreo skill, pipeline, or data asset. Reject any idea that requires buying a new tool
before it requires using what's already built.

### Step 3 — Shortlist (main loop, no subagents)
Pick the 10 that maximise portfolio value: mix of meetings-drivers and cost-cutters,
mix of quick wins and compounding plays, no two ideas exploiting the same fact the same
way.
**Done-rule:** exactly 10 ideas, ≥3 on each lever, no duplicated mechanism.

### Step 4 — Expert panel
Spawn **5 independent subagents**, each a lead-generation expert with a distinct lens:
1. deliverability & sending infrastructure, 2. offer/copy & reply conversion,
3. data & ops efficiency, 4. unit economics & cost per meeting, 5. pipeline math &
qualification. Each receives the shortlist + evidence brief only (no other judge's
output), scores the **list as a whole 1–10**, and names the single weakest idea with
a reason.
**Done-rule:** collective average **≥8.0/10** AND no individual judge below 6.

### Step 5 — Revise only what failed (retry loop with Step 4)
If the panel done-rule fails: fix or swap ONLY the ideas judges flagged, pulling
replacements from the Step-2 bench, then re-run Step 4. This Step-4↔5 loop counts
against Step 4's retry cap of 3. On cap-hit, deliver the best-scoring list and report
the score honestly — never inflate it to 8.

### Step 6 — Deliver
Final report in one message: the panel score, then the 10 ideas ranked, as a table
(Idea · Lever · Grounding fact · Fable 5's role · Effort · First step), followed by a
one-paragraph "start here" recommendation naming the top 1–2 ideas and the exact skill
or command to fire first. Plain English throughout — no jargon (per house rule).

## Done

The skill is done when Step 6's report is delivered AND Step 4's done-rule passed
(or its retry cap was hit and the shortfall is stated plainly in the report).
