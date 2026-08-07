---
name: campaign-insight-cockpit
description: Static orchestration skill that prototypes 5 daily "campaign cockpit" Artifacts — one-place dashboards that fuse live campaign numbers, the queued optimisations, and Claude's own daily synthesis (e.g. "67% of replies are OOO, so ignore the variant recommendation") so Bjion stops bouncing between campaigns.html, notifications.html, and deep analysis to make decisions. Needle movers baked in - time to lead, deliverability, copy/offer performance. Verified by a 5-person panel of non-technical founders and sales leaders that must score 9/10 on simplicity AND insight quality before the loop stops. Artifacts only - never a new page in the signals tool. Use when the user says "run the campaign cockpit loop", "prototype the insight dashboards", "build the daily campaign dashboard artefacts", or "/campaign-insight-cockpit".
---

# Campaign Insight Cockpit — 5 Artefact Prototypes

## Loop Training Mode: OFF  ← flip to ON to pause at every step for approval

- **ON:** pause at every step and wait for Bjion's approval before continuing. Skip any step that already passes its done-rule. Only re-run steps that fail. Retry cap applies.
- **OFF:** run all steps autonomously, no pauses, but keep every done-rule check and the retry cap.
- **Retry cap:** max 3 attempts per step (Step 3 panel: max 4 revise-and-rescore rounds). On cap, stop and report the best result plus what's still failing.

## Goal

Improve the quality of insights so Bjion can make better data-driven decisions about campaign performance. The failure being fixed: campaigns view, optimisations view, and deep analysis each being individually correct but never seen together — e.g. the manufacturer campaign looked underperforming, the optimiser said "change variants", and only deep analysis revealed 67% of replies were OOO, which changed the whole picture. One place, whole picture, refreshed daily.

## Hard rules

- Deliverables are **Artifacts only** (Artifact tool, private). Never add or modify a page in the signals tool.
- Every artefact follows the **navreo-design-system** skill (cream/ink/ONE-orange, Acid Grotesk data-URI, no emoji).
- Prototypes must be grounded in **real live data** (signals app APIs, Smartlead, Supabase) — no invented numbers. The manufacturer/OOO story must be representable in each design.
- The three needle movers — **time to lead, deliverability, copy/offer performance** — must be answerable at a glance in every prototype (not necessarily as separate sections).
- Each prototype must fuse, in one view: live campaign numbers + the queued optimisations for that campaign + a synthesised "whole picture" verdict (the Claude daily crunch) that can veto or reframe a raw recommendation.
- Designed as a **daily routine**: each artefact reads as "today's briefing", not a live app.

## Steps

**Step 1 — Ground truth pull.**
Pull live data: campaign list + stats from the signals app / Smartlead (reply rates, bounce rates, sending health, lead flow), the current optimisation recommendations from notifications, and reply-category splits (OOO vs genuine positive/negative) from Supabase. Capture the manufacturer-campaign OOO case as the canonical test story.
*Done-rule:* a written data snapshot exists covering ≥3 live campaigns with, for each: core stats, any queued optimisation, and reply-category split — enough to populate all 5 prototypes with real numbers.

**Step 2 — Build 5 distinct prototypes.**
Five genuinely different design concepts (e.g. verdict-first briefing, per-campaign decision cards, exception-only "what changed" feed, needle-mover scoreboard, narrative daily memo with drill-downs). Each published as its own private Artifact using the design system, populated from the Step 1 snapshot, each passing the fusion rule and the manufacturer test story ("does this design stop the bad variant decision?").
*Done-rule:* 5 Artifact URLs live, each visually distinct, real-data-populated, design-system compliant, and each surfaces the OOO context alongside the variant recommendation.

**Step 3 — Panel verification loop.**
Spawn a panel of 5 personas — non-technical founders and sales leaders who run cold outbound but don't code. Each scores every prototype 1-10 on (a) simplicity and ease of use, (b) quality of insights for making changes that actually improve performance and drive revenue, with specific complaints. Average per prototype per criterion. Revise prototypes on the feedback and re-panel until **at least one prototype scores ≥9/10 on BOTH criteria**. Max 4 rounds; fresh persona instances each round so scores aren't anchored.
*Done-rule:* ≥1 prototype at ≥9.0 average on both criteria from a full 5-persona round, with the score table recorded.

**Step 4 — Handover.**
Report: all 5 Artifact links, the score table, the winning prototype and why it won, and a short spec for the daily routine (what gets crunched each morning, from where, and how the artefact is refreshed) — proposed, not built.
*Done-rule:* handover message delivered with links, scores, winner, and daily-routine spec.

## Done

The loop is complete when Steps 1-4 all pass their done-rules. If the Step 3 cap is hit without a 9/10, deliver the best-scoring prototype, the score history, and the specific blockers the panel kept raising.
