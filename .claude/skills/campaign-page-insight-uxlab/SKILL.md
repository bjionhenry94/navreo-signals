---
name: campaign-page-insight-uxlab
description: Build and score 5 UX prototypes for the dedicated campaign page (/app/campaigns.html#/c/<id>), optimising how fast a strategist gets from campaign to insight to a targeting or copy fix. Keeps the tabbed design, tab labels, header name/progress, and the sequence showcase. Runs a 5-persona account-strategist panel and does not finish until a prototype scores 9/10+. Use when the user says "run the campaign page uxlab", "prototype the campaign page", "make the campaign insights faster to act on", or "/campaign-page-insight-uxlab".
---

# Campaign page - insight UX lab

## Loop Training Mode: OFF  <- flip to ON to run step-by-step with approvals

- **OFF (default):** run all steps autonomously, no pauses. Every done-rule check and the retry cap still apply.
- **ON:** pause at every step and wait for Bjion's approval before continuing. Skip any step that already passes its done-rule. Only re-run steps that fail.
- **Retry cap:** max 3 attempts per step (Step 3 panel: max 4 revise-and-rescore rounds). On cap, stop and report the best result plus what is still failing.

## Goal

A strategist opens a campaign page and should know, in seconds, what is wrong and which of the two levers fixes it:

1. **Targeting** (wrong audience: list audit, split/distribution bug, dead segment)
2. **Copy** (wrong message: rewrite brief, variant fix, kill threshold)

Today the insight sits in a card, and the fix lives somewhere else (another tab, another tool, another skill). Close that gap. Produce **5 prototypes** of the campaign page that make insight-to-action faster, then let a panel pick the winner.

**Reference page:** `https://navreo-signals.onrender.com/app/campaigns.html#/c/3507283`
("Navreo | Distributors [June]", verdict-only: *9,560 sends, zero positives. The offer is not landing. -> Approve a rewrite brief. Different core angle.*)

## Hard rules

**Do NOT change:**
- The tabbed design (tabs stay tabs)
- Tab labels: Overview, Messaging, Leads, Sources. **One permitted experiment:** drop Sources and merge it into Leads. At least one prototype should try this so the panel can judge it.
- The campaign name and progress in the header
- The sequence showcase (Messaging keeps showing the real sequence)

**Must hold:**
- **The verdict-only case is the common case.** 37 of 44 live campaigns have only a verdict and render "No open flags beyond the verdict." A prototype that only looks good on a rich campaign fails. Design the empty state as a first-class screen, not a fallback.
- **Every insight names its lever.** Each card, row, or badge makes clear whether it is a targeting problem or a copy problem, and offers the next step inline.
- **Real data only.** Use the live `/api/cockpit/insights` payload and campaign scorecard numbers. No invented metrics.
- **Certified insight-card grammar still applies** where cards are used: hero number, its own chart, one caption line, one `->` act line, why? expander, owner chip.
- **Navreo Design System only:** cream/ink, one orange accent moment per card, Acid Grotesk, no emoji, chart-series palette, light and dark both correct (`~/.claude/skills/navreo-design-system/`).
- Responsive: no horizontal page scroll at 375px or desktop, both themes.
- Prototypes are artifacts. Nothing ships to the live app in this skill.

## Steps

**Step 0 - Capture the baseline.**
Pull the live page for `3507283` plus one rich campaign (`3550324`, Arnic, 2 cards) and one mid case. Record: what is on each tab, how many clicks and how many seconds from page load to starting a targeting fix, and to starting a copy fix. This click count is the number every prototype must beat.
*Done-rule:* baseline click/seconds counts for both levers recorded in the session record, for verdict-only and rich campaigns.

**Step 1 - Build the 5 prototypes.**
One artifact, five genuinely different takes on the same real campaign data. They must differ in structure, not styling. Suggested directions (swap freely, keep them distinct):
- (a) **Verdict-first**: the verdict owns the top of Overview, with the lever's action inline and everything else demoted
- (b) **Lever split**: insights grouped under two standing headings, Targeting and Copy, each with its own act button
- (c) **Sources merged into Leads**: the permitted tab experiment, freeing Overview for insight depth
- (d) **Inline fix drawer**: clicking an insight opens the fix in place (rewrite brief, list audit) without leaving the tab
- (e) **Evidence-on-demand**: one-line insights by default, receipts and charts expand only when challenged
Each renders verdict-only and rich states, both themes, 375px and desktop.
*Done-rule:* artifact live; 5 prototypes render both campaign states in both themes at both widths, no horizontal scroll, tab rules respected.

**Step 2 - Measure the gap.**
For each prototype, count clicks and estimate seconds from page load to starting a targeting fix and to starting a copy fix, same method as Step 0.
*Done-rule:* every prototype beats the Step 0 baseline on both levers, or is cut and replaced. Table recorded.

**Step 3 - Account-strategist panel.**
5 fresh account-strategist personas (people who run client campaigns daily, not designers). Each gets a short look at each prototype, then answers: what is wrong with this campaign, which lever fixes it, what would you click first, and a 1-10 score on "this gets me from opening the page to fixing the campaign fast."
*Done-rule:* at least one prototype averages **9.0+** across a full 5-persona round, with the score table recorded. Revise and re-run with fresh personas until true; cap 4 rounds.

**Step 4 - Handover.**
One line plus link, auto-launch per the handover convention. Report: artifact link, click-count table, score table, the winner and why, and the ruling on whether Sources should merge into Leads.
*Done-rule:* handover delivered with link, click counts, scores, winner, and the Sources ruling.

## Done

Steps 0-4 pass their done-rules: 5 prototypes exist on real data, every one beats the baseline click count on both levers, and a full 5-persona strategist panel scored at least one of them 9.0+. If the Step 3 cap is hit without a 9.0, deliver the artifact, the scores, and the blockers, and ship nothing without Bjion's explicit approval.
