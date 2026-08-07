---
name: action-card-simplify-lab
description: Static orchestration loop that prototypes a BRAND-NEW, radically simpler version of the "Act on it now" recommendation card in the campaign cockpit (campaigns.html action cards). Today one card stacks 5+ near-identical buttons (three "Draft the fix", two "Draft a challenger") plus "Copy prompt for Claude" and the status buttons, which reads as an overwhelming wall of choices. The lab builds 3 minimal self-contained prototypes in the Navreo design system under app/prototypes/, each collapsing that wall into ONE obvious next move (e.g. a single "Fix it with Claude" button with a small menu behind it), screenshots them with headless Chrome, and scores them with a 5-persona panel of non-technical founders and sales leaders until every prototype earns 9/10+ on actionable insights, easy to digest, AND beauty. Delivers a gallery + scorecard for Bjion to pick a winner; nothing ships to campaigns.html in this loop. Use when the user says "simplify the action card", "too many buttons on the card", "prototype the act-on-it card", "action card simplify lab", or "/action-card-simplify-lab".
---

# Action Card Simplify Lab

## Loop Training Mode: **OFF**

Flip it by editing this one line: `LOOP_TRAINING_MODE = OFF`  →  set to `ON` to pause at every step. (Default is ON; set OFF here for a hands-off run.)

**When ON (default)**
- Pause at the end of **every** step. Show the step's done-rule result, then wait for Bjion's approval before moving to the next step. Never chain two steps in one turn.
- **Skip** any step whose done-rule already passes. Say "Step N already passes, skipping" and move on.
- Only re-run steps that **fail**.
- Retry cap still applies (below).

**When OFF**
- Run every step back to back, no pauses, no approval requests.
- Done-rule checks still run on every step. Retry cap still applies.
- Report once at the end: which steps ran, which were skipped, which failed.

**Retry cap (both modes)**
- Max **3** attempts per step. On the 3rd failure: stop the loop, report the step, its done-rule, the last failure output, and the best guess at the blocker. Never attempt a 4th.
- Max **3** full panel rounds. After round 3, stop and report the best scores even if the 9/10 bar was not met everywhere.
- After a cap is hit, never widen scope to "fix it another way". Report and stop.

---

## The Goal

An action card a non-technical founder reads in one glance and knows the single next move to book more meetings, in language a 16-year-old understands. Today the card is right on CONTENT (the verdict, the why, the numbers) but wrong on CHOICE: it offers 5+ almost identical buttons ("Draft the fix" for Version ?, for Version B, for Version A; "Draft a challenger" for B, for A) sitting next to "Copy prompt for Claude" and the status buttons. The founder cannot tell them apart, so the card feels heavy and they do nothing.

Collapse that wall into ONE obvious next move. The user's own steer: all of those could have lived as a small menu behind "Copy prompt for Claude" — the point is to give paste-into-Claude options without showing them all at once. **If a prototype needs explaining, it is already too complicated.** Less explanation, more intuitive design.

## What must survive (settled, do not relitigate)

1. **The verdict + the number stay.** The founder still sees the headline ("Swap variant B's line"), the one big number (e.g. 4,839 per positive vs healthy under 1,500), and the two-bar receipt. This lab simplifies the CHOICES, not the diagnosis.
2. **Paste-into-Claude survives.** The whole reason the buttons exist is to hand the founder a prompt they paste into Claude. Every prototype must still deliver that — just without a wall of buttons. A single button, a dropdown, or a two-tap choice all qualify.
3. **The lifecycle controls stay on the card** (Bjion, this run): the status pill (In progress / you), Mark as completed, Assign, and Dismiss must all remain reachable. Simplifying the CHOICE of fix must not delete the card's housekeeping row. Keep them quiet in a footer, below a divider, so they never compete with the one primary move.
4. **Claude vs one-click split** (Bjion, this run): anything that needs ideation or a confirmation (rewrite the line, draft a challenger) is a Claude action — it hands over a prompt. Anything simple and reversible-enough (turn a losing version off) can be a one-click action done in place. Label the two kinds so the founder can tell them apart at a glance ("Claude" vs "1 click").
5. **ONE orange per card, ever** (Bjion, 02 Aug 2026): never two loud primaries competing. The FINAL mechanism (see the superseded-status note below): the card's single orange is either the 1-click fix (when the headline recommends a mechanical move) or Copy-prompt (ideation) — it REPLACES Copy-prompt outright, no ghost demote, and the wall's act buttons render quiet, never orange.
5. **One accent only.** Navreo orange (`--nav-orange`) is the single accent; red means "replace this". No second colour system.
6. Standing house rules: no em dashes; captions 5 words max; kid-simple wording everywhere; real numbers only.

**STATUS: this lab is HISTORY — P4 was shipped, then REVERTED for drift (Bjion: "all of this stuff has just gone really far off base"). Do NOT resurrect the P4 split-button-of-Claude-moves, the one-orange ghost demote, or the "Ways to fix it" list.** The prototypes remain at `app/prototypes/act-simplify-p*.html` as reference only.

**The FINAL shipped design lives in the `action-card-routing` skill (read that, not this, before touching the card):** original card layout + status pill (blue in-progress dot) + ONE adaptive primary — a real 1-click action (e.g. `shift_share`, direction read from the data) when the headline recommends a mechanical move, Copy-prompt for ideation — with the two curated Claude moves behind the primary's caret and the wall folded away on swapped cards. Any future card-simplification loop starts from `action-card-routing`'s "Proven learnings" section and the memory `action-card-simplify-p4-picked`.

## The design defect being attacked

The card presents 5+ actions that a non-technical reader cannot rank or tell apart, so choice paralysis sets in and the card is skipped. Each of the 3 prototypes must give a DIFFERENT structural answer to "one obvious move instead of a wall":
- e.g. **one button + hidden menu** (the dropdown-behind-Copy-prompt idea),
- e.g. **2-3 big outcome tiles** you tap (Rewrite it / Try something new / Stop it),
- e.g. **one recommended default** shown, with "other options" quietly tucked away (progressive disclosure).

No two prototypes may share the same layout skeleton. Minimal is the bar: every element earns its place, or it goes.

---

## Steps

### Step 0 — Preflight
Read the live card code in `~/navreo-signals/app/campaigns.html` (search `vawWhyActionsHTML`, `vaw-acts`, `copy-prompt`, `data-prompt`) and confirm the real action kinds (p1 turn-off, p3 draft-the-fix, p5 scale winner, p6 equal-share, p7 challenger) and the copy-prompt payload. Copy the design tokens from the `:root` block (colours, fonts, radii). Confirm `~/navreo-signals` is on latest main.

**Done-rule:** card code + tokens read, the real action kinds and the copy-prompt payload captured to the scratchpad, repo current.

### Step 1 — Build 3 prototypes
Three self-contained pages `app/prototypes/act-simplify-p1.html` … `p3.html` in the live Navreo design system (tokens from Step 0). Each renders the SAME real card (the Var A / Var B swap case from the screenshot: 1 pos / 1,744 vs 0 pos / 1,762, 4,839 per positive, healthy under 1,500, 16,489 still to run) in that prototype's simplified treatment, so panelists compare like for like. Each page carries a one-line label of its structural idea. Three different layout skeletons, per the defect section. Real numbers only, no lorem, no fake stats. Each prototype must still deliver a paste-into-Claude prompt somewhere.

**Done-rule:** 3 files exist, open locally without console errors, render the same real card, no two share a layout skeleton, each still surfaces a copyable Claude prompt, zero em dashes.

### Step 2 — Screenshot the gallery
Headless Chrome (`chrome --headless --screenshot`) each prototype at 1280x800, light mode. Assemble `app/prototypes/act-simplify-gallery.html` linking all 3 with their screenshots and idea labels.

**Done-rule:** 3 non-blank PNGs exist and the gallery page opens with all 3 visible.

### Step 3 — Founder panel (the 9/10 gate)
Spawn 5 independent subagents: 3 non-technical founders, 2 sales leaders, each with a distinct one-line persona (time-poor, numbers-averse, skim-reader, meetings-obsessed, design-picky). Give each the 3 screenshots (or the DOM-read text plus layout description where a screenshot is unreadable). Each scores each prototype 1-10 on three axes: **actionable insights** (do I know the one next move), **easy to digest** (did I get it in one glance, no explaining needed), **beauty** (would I be proud to show a client). Capture every objection verbatim.

**Done-rule:** every prototype scores 9+ from every panelist on all three axes. Any miss: fold the objections into that prototype (or replace it with a new skeleton if it scores under 6), re-run Steps 1-3 for the changed prototypes only. Panel-round cap applies (3 rounds).

### Step 4 — Deliver the pick sheet
Present to Bjion in chat: the gallery link, a scorecard table (prototype x axis x panelist), each prototype's one-line idea, and the panel's strongest praise + strongest objection per prototype. Recommend one winner with a one-sentence reason. Do NOT touch `campaigns.html` — wiring the winner into the cockpit is a separate brief once Bjion picks.

**Done-rule:** pick sheet delivered in chat with gallery + scorecard; no cockpit files modified anywhere in this loop.

---

## Guardrails

- Prototypes only. `app/campaigns.html` and everything outside `app/prototypes/` stays untouched. Do not commit or push unless Bjion asks.
- Real numbers only, from the screenshot card. A prototype judged on fake numbers is a void round.
- Standing fonts ("Acid Grotesk" / "DM Sans") will not load standalone; fall back to system sans but keep the exact colour tokens and card chrome so it reads native.
- If a panelist's objection is about the DIAGNOSIS (the metric, the verdict), record it for a separate backlog and judge the prototype on the CHOICE simplification only — this lab fixes the wall of buttons, not the upstream numbers.
- If a step is blocked (host down, no Chrome, repo moved), say so plainly, finish every step that does not depend on it, and name what was skipped.
