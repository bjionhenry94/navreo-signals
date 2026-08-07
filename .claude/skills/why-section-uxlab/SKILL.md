---
name: why-section-uxlab
description: Static orchestration loop that prototypes a BRAND-NEW "Why?" section for the campaign cockpit's recommendation cards (campaigns.html action cards). Keeps the adaptive behaviour (the Why shows what the card is talking about) but fixes the flat visual hierarchy - today the headline, sub-line, verdict and prose all read as the same block of text, so it feels like reading twice. Builds 5 minimal self-contained prototypes in the Navreo design system under app/prototypes/, screenshots them with headless Chrome, and scores them with a 5-persona panel of non-technical founders and sales leaders until every prototype earns 9/10+ on actionable insights, easy to digest, AND beauty. Delivers a gallery + scorecard for Bjion to pick a winner; nothing ships to campaigns.html in this loop. Use when the user says "prototype the Why section", "redesign the Why", "why section lab", "the Why has no hierarchy", or "/why-section-uxlab".
---

# Why? Section UX Lab

## Loop Training Mode: **OFF**

Flip it by editing this line: `LOOP_TRAINING_MODE = OFF`

**When ON**
- Pause at the end of **every** step. Show the step's done-rule result, then wait for Bjion's approval before moving on. Never chain two steps in one turn.
- **Skip** any step whose done-rule already passes. Say "Step N already passes, skipping" and move to the next.
- Only re-run steps that **fail**.
- Retry cap applies (below).

**When OFF**
- Run every step back to back, no pauses, no approval requests.
- Done-rule checks still run on every step. Retry cap still applies.
- Report once at the end: which steps ran, which were skipped, which failed.

**Retry cap (both modes)**
- Max **3** attempts per step. On the 3rd failure, stop the loop, report the step, the done-rule, the last failure output, and the best guess at the blocker. Never attempt a 4th.
- Max **3** full panel rounds. After round 3, stop and report the best scores even if the 9/10 bar is not met on every prototype.
- Never widen scope to "fix it another way" after a cap is hit. Report and stop.

---

## The Goal

A Why? section a non-technical founder reads in one glance and knows whether to act, using language a 16-year-old understands. The current digest (shipped 26 Jul 2026, see memory `why-digest-contract`) got the CONTENT right - one verdict, chips, one prose line, adaptive bars - but the PRESENTATION is flat: headline, sub-line, bold verdict and prose are four rows of similar text, so the eye reads the same fact twice and nothing signals "this is the claim, this is the proof". Keep the adaptive behaviour. Fix the hierarchy. Less explanation, more intuitive design: **if a prototype needs explaining, it is already too complicated.**

## What must survive from the current design (settled, do not relitigate)

1. **Adaptivity**: the Why shows receipts for what THAT card talks about - list cards show list progress, variant cards show variant bars, deliverability cards show reply numbers. This is liked. Keep it.
2. **One source of truth**: everything textual comes from the card's own payload (`p.act`, `p.bold`, `p.note`, `p.stats`); bars come from the optimiser variants data. Receipts must never contradict the headline (panel killed this at 3/10 last time).
3. Winners-first bars with "N pos / N sent · 1 per N", red-struck = replace, greyed = switched off, aggregate contrast bars for email-step claims.
4. Standing rules: no em dashes; captions 5 words max; kid-simple wording everywhere.

## The design defect being attacked

Bjion, 27 Jul 2026: the hierarchy between *the recommendation* (headline), *the reason* (verdict/prose) and *the proof* (chips/bars) is invisible - "it feels like you're either reading twice, or it's just inefficiently presented... it also feels like all the same thing, so it feels a bit overwhelming." The 5 prototypes must each try a DIFFERENT structural answer to that - e.g. claim-vs-proof split panes, numbers-first with one caption, a single annotated bar chart that IS the why, progressive reveal, comparison-anchored ("this vs healthy"). No two prototypes may share the same layout skeleton. Minimal is the bar: every element must earn its place.

---

## Steps

### Step 0 - Preflight
Read the live digest code in `~/navreo-signals/app/campaigns.html` (search `whyDigestHTML`, `why-verdict`, `whyBarsHTML`) and the memory `why-digest-contract`. Pull real card payloads from 3 live campaigns via `/api/cockpit/insights` (cookie recipe: memory `signals-live-verify-recipe`) - at least one variant card with bars, one lifecycle card, one deliverability card, including a zero-positive case like the CRE card ("Drop the CRE vertical or rewrite all three openers"). Confirm `~/navreo-signals` is on latest main.

**Done-rule:** code + memory read, real payloads for 3+ card kinds saved to the scratchpad, repo current.

### Step 1 - Build 5 prototypes
Five self-contained pages `app/prototypes/why-p1.html` … `why-p5.html` in the live Navreo design system (copy the cockpit's fonts, colours, card chrome). Each page renders the SAME 3 real cards (from Step 0) in that prototype's Why? treatment, so panelists compare like for like. Each page carries a one-line label of its structural idea. Five different layout skeletons, per the defect section. Real numbers only - no lorem, no fake stats.

**Done-rule:** 5 files exist, open locally without console errors, all render the same 3 real cards, no two share a layout skeleton, zero em dashes.

### Step 2 - Screenshot the gallery
Headless Chrome (`chrome --headless --screenshot`) each prototype at 1280x800, light mode. Assemble `app/prototypes/why-gallery.html` linking all 5 with their screenshots and idea labels.

**Done-rule:** 5 non-blank PNGs exist and the gallery page opens with all 5 visible.

### Step 3 - Founder panel (the 9/10 gate)
Spawn 5 independent subagents: 3 non-technical founders, 2 sales leaders, each with a distinct one-line persona (time-poor, numbers-averse, skim-reader, meetings-obsessed, design-picky). Give each the 5 screenshots (or the DOM-read text plus layout description where a screenshot is unreadable). Each scores each prototype 1-10 on three axes: **actionable insights** (do I know what to do next), **easy to digest** (did I get it in one glance, no explaining needed), **beauty** (would I be proud to show this to a client). Capture every objection verbatim.

**Done-rule:** every prototype scores 9+ from every panelist on all three axes. Any miss: fold the objections into that prototype (or replace it with a new skeleton if it scores under 6), re-run Steps 1-3 for the changed prototypes only. Panel-round cap applies (3 rounds).

### Step 4 - Deliver the pick sheet
Present to Bjion in chat: the gallery link, a scorecard table (prototype x axis x panelist), each prototype's one-line idea, and the panel's strongest praise + strongest objection per prototype. Recommend one winner with a one-sentence reason. Do NOT touch `campaigns.html` - wiring the winner into the cockpit is a separate brief once Bjion picks.

**Done-rule:** pick sheet delivered in chat with gallery + scorecard; no cockpit files modified anywhere in this loop.

---

## Guardrails

- Prototypes only. `app/campaigns.html` and everything else outside `app/prototypes/` stays untouched. Do not commit or push unless Bjion asks.
- Real payload data only, from the Step 0 pull. A prototype judged on fake numbers is a void round.
- Concurrent-session gotcha (memory `why-digest-contract`): other sessions commit `campaigns.html` from stale buffers. This loop never edits that file, so stay out of the blast radius - but re-pull payloads if the repo moves under you.
- If a panelist's objection is about the DATA (confusing metric semantics, rounding drift), record it for the generator backlog and judge the prototype on presentation - this loop fixes layout, not upstream data.
- If a step is blocked (host down, no keys, Chrome missing), say so plainly, finish every step that does not depend on it, and name what was skipped.
