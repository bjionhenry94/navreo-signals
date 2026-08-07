---
name: offer-angles-lab
description: Static orchestration skill that produces FOUR A/B-testable offer angles for Navreo's new offer (we run your outbound from inside Claude Code / ChatGPT, backed by the Navreo signals platform at navreo-signals.onrender.com), benchmarked against what is working for gojiberry.ai ($3.5M ARR in under a year) and against Navreo's own proven "you only pay after we've built it" template (188k sends, 367 positives, 1-in-182 on follower lists). Fixed A/B magnet across ALL angles: a free guide / training on finding high-intent leads and contacts from inside Claude/ChatGPT, where the system runs 24/7 and gets better every week. ICP: B2B sales leaders and CEOs at 5-200 employee companies. Every angle must survive a simulated panel of 5 ICP buyers at 8/10+ as a no-brainer they would reply to. Use when the user says "run the offer angles lab", "test the new offer angles", "adapt the offer to the Claude outreach positioning", or "/offer-angles-lab".
---

# Offer Angles Lab

One run = four paste-ready offer angles where ONLY the offer paragraph differs, ready to A/B test across niches and industries.

## Loop Training Mode (toggle)

**Current mode: OFF** (edit this line to ON to pause at every step)

- **ON:** pause at EVERY step and wait for Bjion's approval before continuing. Before running any step, check its done-rule first: if it already passes (artifacts exist from a prior run), SKIP the step and say so. Only re-run steps that fail. Retry caps below are hard limits.
- **OFF:** run all steps end to end with no pauses. Done-rule checks and retry caps still apply exactly as written. If any cap is hit, stop and report. Never loop forever.

## The job

Navreo's new offer: we build and run your outbound from inside Claude Code / ChatGPT (the Navreo signals platform: campaigns, signals, setter, all of it). Very similar play to Gojiberry, but our wedge is the AI-native workspace the buyer already uses.

We are A/B testing the OFFER first. So every angle is wrapped in the same test frame:

> The CTA always offers to send a **free guide / training** on how they would **find high-intent leads and contacts from inside Claude/ChatGPT, where the system runs 24/7 and gets better every week.**

Same email skeleton, same magnet, same CTA shape. The only thing that changes between variants is the offer paragraph. That is the whole experiment.

## Fixed constants (never re-decide these)

- **ICP:** B2B sales leaders and CEOs at companies with 5-200 employees. Niches rotate; the ICP does not.
- **Magnet:** the guide / free training above. Fixed by the brief. Do not swap it.
- **Angle 1 is pre-seeded:** Build-First risk reversal ("you only pay after we've built it, nothing upfront"). Proven house angle.
- **Angle 2 is pre-seeded:** Outcome guarantee ("30 qualified leads in 90 days", exact guarantee mechanics decided at draft time).
- **Angles 3 and 4** come out of the Gojiberry research. Bench candidates: cost collapse (replace the SDR/agency stack), compounding asset (own a system that gets better every week instead of renting an agency), speed-to-pipeline (live in days), already-in-your-stack (your team already lives in ChatGPT/Claude). Research evidence picks the two.
- **NEVER audit offers.** No "free audit" angle, ever. Standing rule.
- **Offer engine rules** (mirror the live engine at /app/offer.html, v2): research brief goes in, ONE mechanism per offer, a 40-word offer statement, then a template-email preview. Optionally POST the research brief to the live engine for raw drafts; final wording is composed here to the same rules.
- **Copy rules:** soft yes-CTA (ask permission to send the magnet, never push a meeting), keep openers minimal, no em-dashes, avoid "your size", company acronyms stay caps.
- **Proof on hand:** pay-after-build all-time: 188,356 sends, 367 positives (1 per 513 blended, 1 per 182 on follower lists, best 1 per 93). Warm affinity audiences beat cold 6x. Use as internal calibration and as proof lines where honest.
- **Models:** this skill orchestrates; research and panel subagents run on Sonnet.
- **Cost:** zero paid provider credits. Web research and Supabase reads only.

## Artifacts

All outputs live in `~/.claude/skills/offer-angles-lab/runs/<YYYY-MM-DD>/`:
`research-brief.md`, `own-proof.md`, `angles-draft.md`, `panel-round-N.md`, `ANGLES-FINAL.md`.

## Steps

### Step 1: Gojiberry research
Study gojiberry.ai (home, product, pricing, case studies) plus the three founders on X: @pierreeliottlal, @romanbuildsaas, @Dylan_txa_. They routinely share lead magnets and GTM guides; mine those too. Use WebFetch/WebSearch; if x.com blocks direct fetch, go through search results and mirrors.
Classify every finding into four buckets: (a) pain points they lead with, (b) value props, (c) offer mechanics (pricing, trials, guarantees), (d) magnet formats the founders share.
**Done-rule:** `research-brief.md` exists with 8+ distinct findings, each with a source URL, and at least 2 findings in every bucket, ending with a "what this means for our angles" section.
**Retries:** 2.

### Step 2: Own-proof mining
Write `own-proof.md`: the pay-after-build template numbers above, the winning line itself ("You only pay after we've built it, so no upfront amount"), what the follower-list split teaches, and the platform capabilities worth claiming (signals watched daily, runs 24/7, learns weekly) pulled from the campaigns app. Mostly pre-known; this step just pins it to paper.
**Done-rule:** `own-proof.md` exists with the real numbers and 3+ claimable capability lines.
**Retries:** 1.

### Step 3: Draft the four angles
Run the offer engine rules over the research brief + own proof. Produce `angles-draft.md` with EXACTLY four angles. Per angle: name, one-line positioning, 40-word offer statement, ONE mechanism, the email-ready offer paragraph, one proof line, the fixed magnet CTA line. Angles 1-2 are the pre-seeded ones; 3-4 chosen from the bench by research evidence. Then check every angle against the constraint checklist (no audit, soft CTA, one mechanism, 40-word statement, magnet untouched, no em-dashes).
**Done-rule:** 4 angles, all constraint checks pass, offer paragraphs are drop-in swappable within one identical email skeleton.
**Retries:** 3.

### Step 4: ICP panel test
Spawn 5 FRESH simulated ICP buyers per round (Sonnet subagents): randomized role (CEO, founder, VP Sales, Head of Sales, CRO), size 5-200, mixed niches and geos. Each persona sees the full email (skeleton + one angle's offer paragraph), blind to the other panelists and to which angle is which. Each returns: score 0-10 for "no-brainer, I would reply", the exact sentence that earned or lost the score, their #1 objection, and what would make it a 10.
**Pass bar per angle:** mean score >= 8.0 AND at least 4 of 5 say they would reply.
Failing angles only: rewrite using the objections (Step 3 rules), then re-panel with a fresh 5. Passing angles are not re-tested.
**Retries:** 3 rewrite rounds per angle. If an angle still fails, swap in the next-best bench candidate (max 2 rounds for the replacement). If the bench fails too, stop and report honestly.
**Done-rule:** all four angles at 8/10+ with 4/5 would-reply, evidenced in `panel-round-N.md`.

### Step 5: Package and hand off
Write `ANGLES-FINAL.md`: the shared email skeleton once, then per angle: name, positioning line, 40-word offer, offer paragraph, proof line, panel score, top objection and its counter. End with the A/B wiring note (same subject, same opener, same magnet CTA, only the offer paragraph swaps) and the hand-off pointer: campaign build goes through lilly-bot, and nothing touches Smartlead without lilly-upload-gate.
**Done-rule:** `ANGLES-FINAL.md` exists, four angles at 8+, zero em-dashes, zero audit offers, and a summary of scores has been shown to Bjion in chat.
**Retries:** 1.

## Done (overall)

Four offer angles at 8/10+ no-brainer scores from the ICP panel, packaged in `ANGLES-FINAL.md`, only-the-offer-differs, ready to test across niches. Then STOP. Building the actual campaigns is a separate, explicitly approved next step.
