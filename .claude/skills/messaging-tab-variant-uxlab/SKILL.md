---
name: messaging-tab-variant-uxlab
description: Orchestration loop that redesigns the Messaging tab of a campaign detail page on /app/campaigns.html (e.g. #/c/3507283/messaging) so an account strategist can instantly spot which variant is NOT working, decide what new variant to try next, and double down on what IS working. Produces FIVE distinct prototypes. Per-variant comparison (reply rate, positives, meetings) and variant-to-variant navigation are LOCKED — they must survive every prototype unchanged in capability. Runs a 5-strategist scoring panel and does not finish until every prototype scores 9/10+ on spot-the-loser, ideate-the-next, and double-down. Use when the user says "run the messaging tab uxlab", "optimise the messaging tab", "build the five messaging prototypes", or "/messaging-tab-variant-uxlab".
---

# Messaging Tab Variant UX Lab 🧪

> ## ⚙️ LOOP TRAINING MODE  =  **OFF**   (default)
> Flip this one line to `ON` to run step-by-step with approvals. Nothing else changes.
>
> | Mode | Behaviour |
> |------|-----------|
> | **ON**  | Pause at **every step** and wait for the user's approval before continuing. **Skip** any step that already passes its done-rule. Only **re-run** steps that fail. Respect the retry cap. |
> | **OFF** | Run **autonomously**, no pauses. Still enforce **every done-rule** and the **retry cap**. |
>
> **Retry cap:** each step may be attempted at most **3 times**. On the 3rd failure, STOP and report the blocker — never loop forever.

---

## The Goal
Rebuild the **Messaging tab** — `https://navreo-signals.onrender.com/app/campaigns.html#/c/3507283/messaging` — so that an account strategist opening it can, within seconds, do three things:

1. **Spot what isn't working.** Which variant / email / step is dragging, stated plainly.
2. **Ideate a new variant to try.** The page hands them the next thing to test, not just numbers.
3. **Double down on what is working.** The winner is obvious and the "do more of this" move is one click away.

Deliver **five distinct prototypes** of that experience.

## LOCKED — do not change (every prototype keeps these)
- **Per-variant comparison stays.** Reply rate, positives, meetings (and any other per-variant metric already shown) remain comparable variant-against-variant. You may re-present them; you may not remove them or make comparison harder.
- **Variant navigation stays.** The strategist can still move between variants. You may change the control; you may not lose the ability.

Anything else on the tab is fair game.

## Must-haves (bake into every prototype)
1. **A verdict before the numbers.** Every prototype leads with a plain-English read ("Variant B is losing — 0.4% reply vs 1.9%"), not a raw table the user has to interpret.
2. **The three jobs are visible, not buried.** Spot-the-loser, ideate-the-next, double-down each have an obvious home on the page.
3. **One recommended action per verdict.** Not a menu of five — the single next move (pause it, clone the winner, try this angle).
4. **Insight-card grammar** where a card is used: hero number + a chart + one caption + one action + a "why?" disclosure.
5. **Honest small-sample handling.** A variant with too little volume says so instead of showing a fake winner.
6. **Empty + error states.** No spinner-forever; a variant with no data reads calmly, a failed fetch offers retry.

Design rules: Navreo Design System (`~/.claude/skills/navreo-design-system/`) — cream/ink, ONE orange accent, Acid Grotesk, no emoji in the UI. Plain simple English throughout. Account strategists are the judges.

## The Done-Rule (single source of truth)
**A panel of 5 account strategists each score every prototype 9/10 or higher** on THREE axes:
**(a) I can spot what isn't working, (b) I know what new variant to try, (c) I know how to double down on the winner.**
- 5 prototypes × 5 strategists × 3 axes = **75 scores. The loop is DONE only when all 75 ≥ 9.**
- Any prototype with any axis-score < 9 fails; revise only that prototype and re-score it.
- **Auto-fail, no scoring:** any prototype that loses per-variant comparison or variant navigation. Fix and re-submit.

---

## Steps (each has its own done-rule; skip if already passing)

**Step 1 — Capture the baseline.**
Read the live DOM (Browser pane, authed — mint the HMAC `navreo_session` cookie; DOM reads, not screenshots) of `#/c/3507283/messaging`. Write down: every metric shown per variant, how variants are navigated today, where the data comes from, and what a strategist currently has to do in their head to reach a verdict.
_Done-rule:_ a written before-state naming every per-variant metric, the navigation control, the data source, and the specific mental work the page offloads onto the user.

**Step 2 — Name the three jobs against real data.**
Using this campaign's actual variant numbers, write the answer a strategist should get for each job: which variant is losing and why, what the next variant to test would be, and what doubling down on the winner means concretely. Note the volume floor below which a verdict is not honest.
_Done-rule:_ the three answers exist in plain English for the real campaign, plus a stated small-sample floor.

**Step 3 — Build the five prototypes.**
Five genuinely distinct approaches to the same tab — vary the pattern, not the paint. For example:
- **verdict-first** — a headline ruling on top, variants underneath as evidence,
- **head-to-head** — two variants side by side, winner/loser called, swap either side,
- **leaderboard** — variants ranked by one chosen metric, worst pinned at the bottom with its fix,
- **funnel-by-variant** — sent → reply → positive → meeting per variant, showing where each one leaks,
- **next-test board** — the page is a queue of proposed variants, with current performance as the reason for each.

Every prototype keeps the LOCKED items, honours the must-haves, and handles empty/error/small-sample. Deliver as standalone previewable HTML hydrated with this campaign's real variant numbers (mock any fetch with a visible loading state).
_Done-rule:_ five prototypes render with no console errors; each keeps per-variant comparison and variant navigation; each answers all three jobs on screen.

**Step 4 — Run the 5-strategist panel.**
Score each prototype with five account-strategist personas on the three axes, 1–10 each. Capture the number + a one-line reason per axis per persona per prototype.
_Done-rule:_ 75 scores recorded with reasons.

**Step 5 — Revise the failures.**
For any prototype with any axis-score < 9, apply the panel's reasons and re-score (Step 4) — that prototype only. Respect the retry cap (3 attempts per prototype).
_Done-rule:_ all 75 scores ≥ 9.

**Step 6 — Hand over.**
One line + link per prototype, plus a one-line recommendation of the winner and why it best serves the three jobs. Live-verify anything claimed as shipped (DOM reads on the live host, not screenshots). Nothing is "done" until Step 5's done-rule holds.
_Done-rule:_ five prototype links delivered; winner named; all 75 scores ≥ 9 stated; LOCKED items confirmed intact in all five.

---

## Loop control (how the modes actually run)
```
for step in 1..6:
    if step already passes its done-rule:  SKIP
    else:
        attempt = 0
        while not done-rule and attempt < 3:
            attempt += 1
            do the step
            if TRAINING MODE == ON:  pause → wait for approval
        if still not passing after 3 attempts:  STOP + report blocker
```
Global finish = **Step 6 done-rule holds AND all 75 panel scores ≥ 9 AND per-variant comparison + variant navigation survive in all five prototypes.** Never declare done otherwise.
