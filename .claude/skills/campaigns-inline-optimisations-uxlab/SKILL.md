---
name: campaigns-inline-optimisations-uxlab
description: Orchestration loop that merges the separate Optimisations tab into the campaigns list on /app/campaigns.html — you click a campaign row and its recommended optimisations expand INLINE (lazy-loaded on click, one-second fetch, not on page load), reusing the optimisation-card layout and buttons without re-stating which campaign it is. Produces FIVE distinct prototypes of this expand-in-place experience. Runs a 5-tester non-technical scoring panel and does not finish until every prototype scores 8/10+ on simplicity, not-overwhelmed, and ease of use. Use when the user says "run the inline optimisations uxlab", "merge the optimisations tab into campaigns", "build the five inline-expand prototypes", or "/campaigns-inline-optimisations-uxlab".
---

# Campaigns Inline-Optimisations UX Lab 🧪

> ## ⚙️ LOOP TRAINING MODE  =  **ON**   (default)
> Flip this one line to `OFF` to run autonomously. Nothing else changes.
>
> | Mode | Behaviour |
> |------|-----------|
> | **ON**  | Pause at **every step** and wait for the user's approval before continuing. **Skip** any step that already passes its done-rule. Only **re-run** steps that fail. Respect the retry cap. |
> | **OFF** | Run **autonomously**, no pauses. Still enforce **every done-rule** and the **retry cap**. |
>
> **Retry cap:** each step may be attempted at most **3 times**. On the 3rd failure, STOP and report the blocker — never loop forever.

---

## The Goal
Kill the separate **Optimisations tab** by folding it into the **campaigns list** at
`https://navreo-signals.onrender.com/app/campaigns.html`. Clicking a campaign (without leaving the top-level campaign view) reveals the optimisations recommended **for that campaign only**, expanded in place. Deliver **five distinct prototypes** of this expand-in-place experience.

## Must-haves (bake into every prototype)
1. **No leaving the list.** The optimisations appear inline under (or beside) the clicked campaign row — the user stays on the campaigns view. No tab switch, no navigation away.
2. **Lazy-load on click, never on page load.** With ~80 campaigns, the page must NOT fetch every campaign's optimisations up front. Optimisations for a campaign are fetched only when that campaign is clicked/expanded. Expect a ~1-second fetch — show a clear loading state during it, then reveal.
3. **Reuse the optimisation-card layout + buttons** from the current Optimisations tab (headline, sub-line, "Why?", and the action buttons — Copy Claude prompt, Open in Smartlead, Acknowledge, Mark as completed, Dismiss). Same behaviour, same wording.
4. **Save space — don't restate the campaign.** Because the card lives under its own campaign row, it must NOT repeat the campaign name / CSM / sent / complete% that the row already shows. Drop the redundant context line.
5. **Empty + error states.** A campaign with no optimisations shows a calm "nothing recommended" state; a failed fetch shows a retry, not a spinner-forever.

Design rules: Navreo Design System (`~/.claude/skills/navreo-design-system/`) — cream/ink, ONE orange accent, Acid Grotesk, no emoji in the UI. Non-technical users are the judges — plain words, obvious controls.

## The Done-Rule (single source of truth)
**A panel of 5 non-technical user testers each score every prototype 8/10 or higher** on THREE axes: **(a) simplicity, (b) not feeling overwhelmed by the data, (c) ease of use.**
- 5 prototypes × 5 testers × 3 axes = 75 scores. The loop is DONE only when **all 75 ≥ 8**.
- Any prototype with any axis-score < 8 fails; revise only that prototype and re-score it.

---

## Steps (each has its own done-rule; skip if already passing)

**Step 1 — Capture the baseline (both surfaces).**
Read the live DOM (Browser pane, not screenshots) of `/app/campaigns.html`: (a) how a campaign row renders today, and (b) how the Optimisations tab renders an optimisation card — its headline, sub-lines, "Why?" disclosure, and every action button. Note the endpoint/data that already supplies optimisations and whether it can be fetched per-campaign.
_Done-rule:_ a written before-state exists naming the campaign-row anatomy, the optimisation-card anatomy (every button), and the per-campaign fetch path.

**Step 2 — Confirm lazy per-campaign fetch is possible.**
Verify optimisations can be requested for a SINGLE campaign id on demand (not only as one big bundle at page load). If today's data only arrives bundled, note the exact shape and how a prototype would slice one campaign's optimisations out of it client-side without fetching all up front.
_Done-rule:_ a documented mechanism for loading one campaign's optimisations on click, with the ~1s expectation confirmed.

**Step 3 — Build the five prototypes.**
Five genuinely distinct approaches to the same idea — click a campaign, see its optimisations inline. Vary the pattern, not just the paint, e.g.:
- accordion drawer that pushes rows down,
- inline expand with a slide-in detail band,
- right-side slide-over panel anchored to the row (still on the list),
- row-morph (the row grows to hold a compact optimisation stack),
- click-to-reveal count badge that expands to the card list.
Every prototype: lazy-loads on click with a visible ~1s loading state, reuses the card layout + all buttons, omits the redundant campaign restatement, and handles empty/error states. Navreo Design System. Deliver as standalone previewable HTML (mock the fetch with a ~1s delay + sample optimisation payload so the lazy behaviour is demonstrable).
_Done-rule:_ five prototypes render without console errors; each expands one campaign at a time, shows a loading state, then the reused cards + buttons, and never loads optimisations at page load.

**Step 4 — Run the 5-tester panel.**
Score each prototype with five non-technical personas on the three axes (simplicity / not-overwhelmed / ease of use), 1–10 each. Capture the number + one-line reason per axis per persona per prototype.
_Done-rule:_ 75 scores recorded with reasons.

**Step 5 — Revise the failures.**
For any prototype with any axis-score < 8, apply the testers' reasons and re-score (Step 4) — that prototype only. Respect the retry cap (3 attempts per prototype).
_Done-rule:_ all 75 scores ≥ 8.

**Step 6 — Hand over.**
One line + link per prototype, plus a one-line recommendation of the winner and why it best merges the two tabs. Live-verify anything claimed as shipped (DOM reads on the live host, not screenshots). Nothing is "done" until Step 5's done-rule holds.
_Done-rule:_ five prototype links delivered; winner named; all 75 scores ≥ 8 stated.

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
Global finish = **Step 6 done-rule holds AND all 75 panel scores ≥ 8.** Never declare done otherwise.
