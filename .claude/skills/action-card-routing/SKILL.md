---
name: action-card-routing
description: Static orchestration loop that fixes HOW each cockpit action card routes its primary button (campaigns.html). The rule, in Bjion's words - simple tasks such as moving traffic and disabling variants stay a ONE-BUTTON push; ideating new copy, new angles, or running a list audit is done INSIDE Claude via Copy prompt. The card must route by ITS OWN recommendation (the headline), not by which fix types happen to exist. Supersedes the routing logic shipped in 0ee1737; the card layout itself (primary + status pill + wall + dedupe) is settled and untouched. Verified by a 5-persona panel of GTM engineers and non-technical founders scoring 9/10+ on ease of use and understanding. Use when the user says "fix the card routing", "simple tasks one click", "the buttons are the wrong way around", or "/action-card-routing".
---

# Action Card Routing — simple = 1 click, ideation = Claude

## Loop Training Mode: **OFF**

Flip it by editing this one line: `LOOP_TRAINING_MODE = OFF`  →  set to `ON` to pause at every step. (Default was ON; Bjion switched it OFF 02 Aug 2026.)

**When ON (default)**
- Pause at the end of **every** step. Show the step's done-rule result, then wait for Bjion's approval before the next step. Never chain two steps in one turn.
- **Skip** any step whose done-rule already passes. Say "Step N already passes, skipping".
- Only re-run steps that **fail**.
- Retry cap applies (below).

**When OFF**
- Run every step back to back, no pauses. Done-rule checks still run. Retry cap still applies.
- Report once at the end: ran / skipped / failed.

**Retry cap (both modes)**
- Max **3** attempts per step; on the 3rd failure stop and report the step, done-rule, last output, best guess at the blocker.
- Max **3** panel rounds; then stop and report best scores.
- Never widen scope after a cap. Report and stop.

---

## The Goal

Make it simpler to do the simple tasks, and keep ideation inside Claude. Concretely, each action card's primary button routes by **what the card's own headline recommends**:

- **Simple / mechanical** (move or shift traffic, scale a winner, even a split, turn off or disable or pause a variant) → the primary IS that one-click button, wired through the existing confirm modals. No Claude round-trip for a traffic move.
- **Ideation** (rebuild or rewrite copy, write new angles or challengers or openers, run a list audit) → the primary is **Copy prompt for Claude**. That work happens in Claude.

One orange per card, and it matches the headline. Language a 16-year-old understands.

## The canonical miswired pair (campaign 3576107, 02 Aug 2026) — FIXED, keep as the regression test

- Card 1 "**Rebuild Email 2**, 5,976 sends with no positives" → got the 1-click equal-share button. WRONG: rebuild = new copy = Claude.
- Card 2 "**Move variant G's quarter of the traffic onto F**" → got Copy prompt. WRONG: moving traffic = one click.

The fix passes when this pair flips. (Shipped through 5c8dbd7; the 96-card audit found zero remaining mismatches. Re-run this pair after any classifier edit.)

## Settled, do not relitigate

1. Card layout is FINAL (commits 0ee1737 + 2ea297d): one primary slot (Copy-prompt or the swapped 1-click), status pill (blue in-progress dot, visible menu state), original Act-on-it-now wall inside Why?, swapped act deduped from the wall. Touch ONLY the classifier that decides which primary shows.
2. Never resurrect the P4 split-button / dropdown / "Ways to fix it" machinery.
3. One orange per card, ever.
4. When in doubt, ideation wins (Claude can do anything; a wrong one-click is worse than a prompt).
5. If the headline is simple but no matching one-click act exists on the card, keep Copy-prompt — the prompt tells Claude to make the move.

## The classifier contract (SHIPPED through 5c8dbd7 — this is the law as-built)

Classify the card's HEADLINE (`p.act`), not the bag of available acts:
- IDEATION match: rebuild / rewrite / write / draft / new copy / new angle / challenger / opener / subject line / problem statement / audit / scrap / retire / pivot → Copy-prompt, always. Ideation outranks simple on a double match ("swap variant B's line" is copy work, not a traffic move). An UNMATCHED headline also defaults to Claude.
- REDISTRIBUTION match (move / shift / weight / lean / push / back / favour / prioritise): route to the `shift_share` one-click — and **read the direction from the DATA, never from word order**. `whyHarvestVariants` gives the card's named variants; worst per-positive = loser = `from`, best = winner = `to`. ("Weight Email 1 toward variant A against B" and "Move G onto F" put the winner in opposite word positions — word-order parsing shipped a wrong-direction bug once.) Requires ≥2 named variants with sends; otherwise fall through (that guard is what keeps "Bring the SIS list back" — a list re-import — on Claude).
- Other SIMPLE matches (scale / send 100% / even split / equal share / turn off / disable / pause) → the matching act if the card carries one (p5 > p6 > p1). No matching act → Copy-prompt stays (the prompt tells Claude to make the move).

## Proven learnings baked into the shipped build (do not regress)

1. **One-click labels + bars + modal all speak "Email N: Variant X"** — never bare "Version G".
2. **Bars encode conversion** (positives/sends), not raw sends — an even split shows two full send-bars that tell no story. Winner bar is green (`.is-good`). And `.why-bar-fill` MUST keep `display:block` — it is a span; without it the fill renders 0×0 (the bars-invisible bug).
3. **Swapped cards fold the wall away**; the two curated Claude moves (rewrite the LOSER's line / try a fresh angle) live behind the primary's caret as clipboard prompts. Never a challenger for the losing variant, never a doubled Draft-the-fix, no hint text beside the primary.
4. **Equal-split campaigns** (Smartlead "split equally" checkbox) store no percentages — every variant reads 0%. `shift_share` computes effective even shares when stored pcts sum to 0; `scale_winner` still has the latent guard bug. See variant-action-wire's field learnings.
5. **The done bar for wiring is a live-UI execution on prod** (click → type token → confirm → receipt), not a rendered button. The equal-split bug rendered perfectly and failed on confirm.
6. **Audit method that works:** CDP-sweep every campaign's cards (headline + button), classify with the regexes above, flag ideation-shown-as-1-click (dangerous) and mechanical-shown-as-Claude (missed). 96 cards / 60 campaigns took ~6 min; 2026-08-02 audit = zero mismatches, 4 legitimate one-clicks (3576107, 3642625, 3642647, 3723450).

---

## Steps

### Step 0 — Preflight
Locate the adaptive-primary block in `~/navreo-signals/app/campaigns.html` (search `Adaptive primary`, `action-swap-btn`, `actHideSwapDupe`). Reproduce the miswired pair live on campaign 3576107 (dev server + mock login per memory `signals-live-verify-recipe`). Confirm repo state and note any parallel-session churn (this repo gets clobbered from stale buffers — commit fast, stage scoped hunks only).

**Done-rule:** classifier code located; both miswired cards reproduced live with evidence.

### Step 1 — Reroute
Replace the act-kind ranking with the headline classifier (contract above). Keep everything else: the swap render, vawWireWhy wiring, the dedupe, the pill.

**Done-rule:** on 3576107, card 1 shows Copy prompt for Claude and card 2 shows a one-click traffic button; `node --check` passes on the file's inline JS; no card shows two oranges; dedupe still holds.

### Step 2 — Live sweep
Headless-verify at least 4 real cards across both buckets (more campaigns than the canonical pair). Screenshot each.

**Done-rule:** every checked card's primary matches its headline bucket; zero doubled buttons; screenshots captured.

### Step 3 — Panel (the 9/10 gate)
5 independent subagents: 3 GTM engineers, 2 non-technical founders, distinct one-line personas. Each scores the screenshots 1-10 on **ease of use** (is the next move obvious and one tap when it should be) and **understanding** (do I know why this button and not the other). Objections verbatim.

**Done-rule:** every persona scores 9+ on both axes. Misses: fold objections, re-run only failed steps. 3-round cap.

### Step 4 — Deliver
Scoped commit (filtered-patch staging, never `git add` the whole file blind), report to Bjion with before/after screenshots and a browser link verified loading first. Do NOT push unless Bjion says push; after any push, live-verify the deployed page and send that link (standing rule).

**Done-rule:** commit contains only routing hunks; verified link delivered; memory updated.

---

## Guardrails

- Only the classifier block changes. Everything else on the card is settled.
- Real cards, real data; no judging on mocks.
- A parallel session edits this file: re-check markers after any pause, commit quickly, stage scoped hunks via filtered patch + `git apply --cached`.
- If blocked (server down, repo churn mid-edit), say so plainly and stop rather than race.
