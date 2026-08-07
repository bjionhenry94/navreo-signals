---
name: campaigns-filter-sort-uxlab
description: Orchestration loop that redesigns the filter/sort bar on /app/campaigns.html into a simpler, more intuitive experience — produces FIVE prototypes and adds six new sort options (Meetings, Positives, Leads, Total Emails Sent, Emails Sent Per Positive, Emails Sent Per Meeting). Runs a 5-tester non-technical scoring panel and does not finish until every prototype scores 8/10+. Use when the user says "run the filter/sort uxlab", "redesign the campaigns filter bar", "build the five filter prototypes", or "/campaigns-filter-sort-uxlab".
---

# Campaigns Filter/Sort UX Lab 🧪

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
Make it **simpler to filter and sort** the campaigns list at
`https://navreo-signals.onrender.com/app/campaigns.html`, and deliver **five distinct prototypes** of the improved filter/sort bar.

## Must-haves (bake into every prototype)
The sort control must offer these options, in addition to what exists today:
1. Meetings
2. Positives
3. Leads
4. Total Emails Sent
5. Emails Sent Per Positive
6. Emails Sent Per Meeting

Design rules: Navreo Design System (`~/.claude/skills/navreo-design-system/`) — cream/ink, ONE orange accent, Acid Grotesk, no emoji in the UI. Simpler and more intuitive than the current three-row bar (segmented "Needs a decision / Watch / Fine" + "LIVE STATUS" row + "Sort by completion"). Non-technical users are the judges — plain words, obvious controls.

## The Done-Rule (single source of truth)
**A panel of 5 non-technical user testers each score every prototype 8/10 or higher.**
- 5 prototypes × 5 testers = 25 scores. The loop is DONE only when **all 25 ≥ 8**.
- Any prototype with a score < 8 fails; revise only that prototype and re-score it.

---

## Steps (each has its own done-rule; skip if already passing)

**Step 1 — Capture the baseline.**
Read the current filter/sort bar (live DOM via Browser pane, not screenshots). List exactly today's controls and today's sort options.
_Done-rule:_ a written before-state exists naming every current control + sort option.

**Step 2 — Confirm the six new sorts are computable.**
Verify each of the six required metrics is derivable from data the page already loads (Meetings, Positives, Leads, Total Emails Sent, and the two ratios). Note any that need a new field.
_Done-rule:_ each of the six sorts is mapped to a real data field (or flagged as needing one).

**Step 3 — Build the five prototypes.**
Five genuinely distinct approaches to the same bar (e.g. single-dropdown, chips + sort menu, search-led, preset-views, sort-first). Each includes all six new sorts + existing filters. Navreo Design System. Deliver as standalone previewable HTML.
_Done-rule:_ five prototypes render without console errors and each exposes all six sorts.

**Step 4 — Run the 5-tester panel.**
Score each prototype with five non-technical personas on "how easy is it to filter and sort?" (1–10). Capture the number + one-line reason per persona per prototype.
_Done-rule:_ 25 scores recorded with reasons.

**Step 5 — Revise the failures.**
For any prototype with a score < 8, apply the testers' reasons and re-score (Step 4) — that prototype only. Respect the retry cap (3 attempts per prototype).
_Done-rule:_ all 25 scores ≥ 8.

**Step 6 — Hand over.**
One line + link per prototype, plus a one-line recommendation of the winner. Live-verify anything claimed as shipped. Nothing is "done" until Step 5's done-rule holds.
_Done-rule:_ five prototype links delivered; winner named; all scores ≥ 8 stated.

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
Global finish = **Step 6 done-rule holds AND all 25 panel scores ≥ 8.** Never declare done otherwise.
