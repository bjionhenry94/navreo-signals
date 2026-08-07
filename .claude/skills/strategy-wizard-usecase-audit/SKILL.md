---
name: strategy-wizard-usecase-audit
description: Static orchestration skill that audits the winning strategy-wizard artifact (split-view board, artifact 5d6e5fdd) against Navreo's real daily ideation use-cases — "ideate for [client]", "refresh a plateaued campaign", "new audience for [campaign]", optimiser-flagged pivots, greenfield onboarding — then closes the gaps so a CSM can mention a client or campaign and instantly get campaign ideas backed by real qualitative + quantitative campaign data (winners/losers, reply patterns, net reachable people). Pre-seeded with Bjion's four 2026-07-18 fixes (per-person real opener in previews, explicit Smartlead upload status, share button on the list, an in-artifact "Ask for new ideas" route to chat). Verified by THREE simulated panels of 5 (CSMs, customers, recipients) at a 9/10 bar. Free-data only: reads Supabase/session files for evidence; zero provider credits. Use when the user says "run the wizard use-case audit", "audit the ideation experience", "/strategy-wizard-usecase-audit".
---

# strategy-wizard-usecase-audit

Audit the winning wizard (r3, artifact 5d6e5fdd) against the ideation work CSMs actually do daily, close the gaps, and verify with three panels. Static loop — fixed steps, checkable done-rules, Loop Training Mode controls pauses.

**Data rule:** evidence comes from what we already own (Supabase scorecard/replies, session files, memory). ZERO provider credits; the artifact stays mock-driven but its *insight surfaces* must mirror real data shapes.

---

## ⚙️ LOOP TRAINING MODE  →  **ON** (default)

Flip it by editing this one line:

    LOOP_TRAINING_MODE = ON        # ON = approve every step · OFF = run autonomous

**When ON**
- Pause at the end of **every** step and wait for my explicit approval before continuing.
- Before running a step, check its done-rule first. **If it already passes, skip it** — say so and move on.
- Only (re-)run steps that fail their done-rule.
- Retry cap applies (see below). Never loop a step forever.

**When OFF**
- Run all steps autonomously, no pauses.
- Still check every step's done-rule and still honour the retry cap. Report at the end, not between steps.

**Retry cap (both modes):** any single step retries **max 3** times against its done-rule. On cap-hit, record FAILED with the reason, keep going where possible, surface it in the final report. Never silently exceed.

---

## THE GOAL

Customer success managers stop hitting creative blocks: they mention a client or campaign — in chat or from the artifact — and instantly receive campaign ideas backed by real insights and data (what worked, what died, who actually replies, how many people are reachable net of our own history), then push each idea to launch-ready through the wizard.

**Verification bar (three simulated panels of 5, all 9/10+):**
- **CSMs:** speeds up ideation · ideas are convincing because they cite real qualitative/quantitative campaign data · ideas reflect what prospects are and aren't responding to.
- **Customers:** the process understands their customers' problems and pain points · the copy carries strong offers likely to get replies.
- **Recipients:** the email identifies a relevant/timely problem · the offer is a no-brainer, easy to say yes to.
Bjion's REAL panels come after his sign-off; the simulated panels are the pre-filter.

---

## THE STEPS

### Step 1 — Use-case inventory (the daily reality)
- From memory + session files, write `wizard-lab/usecases.md`: the 5-7 ideation asks CSMs actually make (at minimum: "ideate for [client]" · "campaign plateaued / optimiser flags TAM-exhausted — new angles" · "new audience for [existing campaign], adapt its proven copy" · "strategy-call menu for a client" · "greenfield client onboarding, first 3 campaigns" · "client asked for something specific — validate it fast"). Per use-case: the trigger phrase, the evidence the ideas MUST cite (positives/1k winners+losers, reply patterns, net reachable people with free-vs-paid split, cooldown), and the expected artifact behaviour.
- Done-rule: file exists; every use-case names its evidence sources from data we own; no provider calls anywhere.

### Step 2 — Bjion's pre-seeded fixes (apply to r3 first)
1. **Previews show the ACTUAL opener each person gets** (post-generation truth): "Example people" carry a concrete generated opener line per person (mock-real: company-specific detail lines), and the assembled preview for a tapped person shows THEIR line, not the template.
2. **Explicit Smartlead upload status:** every campaign state shows where it physically is — "Not uploaded yet" → "Uploading to Smartlead…" → "In Smartlead — launch-ready (campaign #30021)" on sign-off, launch summary, and the left-list state line.
3. **Share button on the list:** next to "View the full list", a "Share" control (copies a mock share link, confirms "Link copied").
4. **"Ask for new ideas" route to chat:** a visible button on the board ("Want new ideas? Ask in chat") that opens a small panel with 2-3 copy-ready prompts ("Ideate 5 new campaigns for [client] using our reply data") and a "Copy" button — the artifact stays buttons-and-progress, chat stays the ideas engine.
- Done-rule: all four live-verified in r3 (?fast=1 walk), republished to artifact 5d6e5fdd, zero console errors.

### Step 3 — Audit walk (artifact + process vs each use-case)
- Walk every Step-1 use-case through the CURRENT experience (artifact + the lilly-strategy/lilly-idea-to-launch process behind it). Score each 1-5 on: reachable from a client/campaign mention · ideas visibly evidence-backed (does the idea card SHOW its "why now" data?) · speed to first idea · path to launch-ready. Write the gap register (`wizard-lab/audit.md`): every gap with severity (BLOCKER/MAJOR/MINOR) and owner (artifact-scope vs real-integration-scope).
- Done-rule: every use-case scored with named gaps; register separates artifact-scope fixes from real-build hand-offs.

### Step 4 — Close the artifact-scope gaps
- Fix every BLOCKER/MAJOR the audit assigns to artifact scope. Expected shape (audit may refine): idea cards carry a visible **"Why this idea"** evidence line (e.g. "Tool-follower campaigns: 3.8-9.4 replies per 1,000 — this is the biggest untouched source"); a **client/campaign context header** ("Ideas for: Navreo · based on 148 campaigns, 18,000 replies"); plateaued-campaign ideas cite the plateau ("this audience stopped replying: 0.2/1,000 last 30 days").
- Done-rule: all artifact-scope BLOCKER/MAJOR gaps closed and live-verified; republished same URL.

### Step 5 — Triple-panel verification
- Three simulated panels of 5 walk the artifact end-to-end (?fast=1): **CSM panel** (their 3 criteria), **customer panel** (their 2), **recipient panel** (reads the assembled emails cold, their 2). Every score /10 with a worst-moment quote. Any panel average below 9 → fix worst-moments and re-panel (consumes the retry cap; cap-hit = FAILED-BAR with honest scores).
- Done-rule: all three panels ≥9/10 average, scorecards recorded.

### Step 6 — Report + real-build hand-off
- Final report: per-step DONE/SKIPPED/FAILED, panel scores, and the real-integration hand-off list (chat-first entry wiring, live data feeds, Smartlead push, share links) appended to `lilly-strategy/sessions/wizard-lab-2026-07-17.md` + memory updated.
- Done-rule: report delivered in chat; session file + memory updated; artifact current at 5d6e5fdd.

---

## OVERALL DONE-RULE
- All four pre-seeded fixes live; audit register written; artifact-scope gaps closed; three panels at 9/10+; hand-off list recorded; zero provider credits spent; artifact URL unchanged throughout.
