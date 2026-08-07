---
name: campaign-insight-skim-lab
description: Static orchestration skill that prototypes 5 visually-distinct treatments of the per-campaign "whole picture" insight section in the Navreo cockpit artifact (proto6 / artifact 1c7161d8) — each minimal on text, highly visual, skimmable in seconds — then user-tests them with a 5-person non-technical panel until one scores 9/10+ on "skim it and instantly know what's working and what's not", and merges the winner back into the live cockpit. Use when the user says "run the insight skim lab", "prototype the campaign insight section", "make the whole picture skimmable", or "/campaign-insight-skim-lab".
---

# Campaign insight skim lab — 5 section prototypes

## Loop Training Mode: OFF  ← flip to ON to pause at every step for approval

- **ON:** pause at every step and wait for Bjion's approval before continuing. Skip any step that already passes its done-rule. Only re-run steps that fail. Retry cap applies.
- **OFF:** run all steps autonomously, no pauses, but keep every done-rule check and the retry cap.
- **Retry cap:** max 3 attempts per step (Step 3 panel: max 4 revise-and-rescore rounds). On cap, stop and report the best result plus what's still failing.

## Goal

Make it effortless to understand what's moving the needle **within a campaign**: the whole-picture + action section must be skimmable — minimal text, highly visual, colour-graded — so what's working and what's not reads in seconds, not sentences.

## Hard rules

- Prototypes live in ONE comparison Artifact (the "lab") so variants sit side by side; the winning treatment then merges into the real cockpit artifact (proto6.html → artifact 1c7161d8-f83d-41ad-ae79-9d2771953c4d) — same URL, no new page in the tool.
- Real data only (the session's ground-truth snapshot); the Manufacturers overrule story and one healthy campaign (Amplifyy) render in every variant so treatments are compared on the same facts.
- Visible text budget per variant: the insight headline, chart labels, and one "→ act" line — no prose paragraphs; evidence/receipts/click-paths live behind expanders. The System-said→Verdict trust spine survives, but as a visual device (strike-through chip, before/after), not sentences.
- White-app colourway + dark mode, chart-series palette for marks, ONE accent moment, no emoji, charset-first file rules, Acid Grotesk data-URI. Jargon-free labels.

## Steps

**Step 1 — Build the lab.**
One Artifact page showing 5 genuinely different section treatments, each rendered twice (Manufacturers = "fix it" story, Amplifyy = "feed it" story), with a variant switcher and theme toggle. The 5 directions: (1) scorecard chips — needle movers graded green/amber/red with one number each; (2) leak funnel — sends → replies → real answers → positives with the leak labelled; (3) before/after split — "system saw" vs "the truth" panels; (4) traffic-light tile grid with micro-charts per needle mover; (5) one-number-one-chart-one-act ultra-minimal with a "why?" expander.
*Done-rule:* lab artifact live; 5 variants × 2 campaigns render in both themes at 375px and desktop with no horizontal scroll; each variant's visible text fits the budget.

**Step 2 — Skim test (user testing).**
5 fresh non-technical founder/sales-leader personas per round. Each gets a 10-second skim framing per variant, then answers: what's working, what's not, what would you do — and rates each variant 1-10 on "I could skim this and instantly understand what's working and what's not." Average per variant.
*Done-rule:* ≥1 variant averages ≥9.0 from a full 5-persona round, with the score table recorded. Revise and re-run (fresh personas) until true; cap 4 rounds.

**Step 3 — Merge the winner into the cockpit.**
Apply the winning treatment to all 6 campaign Overview sections in proto6.html (keeping routing, receipts, actions, counters reconciliation), browser-verify both themes at 6 widths, republish to the SAME artifact URL.
*Done-rule:* cockpit republished at 1c7161d8… with the winning treatment on all 6 campaigns; verification checklist passes; font blob untouched.

**Step 4 — Handover.**
Report: lab link, score table, winner and why, what changed in the cockpit.
*Done-rule:* handover delivered with links + scores + winner.

## Done

Steps 1-4 pass their done-rules. If the Step 2 cap is hit without a 9.0, merge the best-scoring variant anyway only with Bjion's explicit approval; otherwise deliver the lab, the scores, and the blockers.
