---
name: launch-dashboard-uxlab
description: "Static orchestration skill that builds 5 minimal prototypes turning the lilly-strategy board (the /app/strategy.html 'strategy link') from an idea-picker into a LIVE, breathing campaign-launch dashboard — every campaign shows its real launch progress (targeting → copy → icebreaker → checks → live) as a visual you can skip straight to, no 'Start' button and no numbers pretending to be progress. Minimal design law: if it needs explaining it is already too complicated; language a 16-year-old understands. Each prototype must pass a simulated panel of 5 non-technical founders and sales leaders at 9/10+ on actionable insights, easy to digest, and beauty of the design. Winner merges into the live board only on Bjion's pick. Use when the user says 'run the launch dashboard lab', 'prototype the live launch dashboard', 'make the strategy board a live launch dashboard', or '/launch-dashboard-uxlab'."
---

# launch-dashboard-uxlab

Today the strategy board is an idea-picker: cards with a net number and a "Start" button that imply
ideation, not launch. Rebuild it as a **live, breathing dashboard of the actual campaign launch** — for
every campaign you see how far the launch has got, what is happening right now, and you can jump straight
into its targeting, its copy, or its icebreakers and SEE each one. Build **5 prototypes**, each a stricter
exercise in minimal design: less explanation, more intuitive. Static loop — fixed steps, checkable
done-rules, Loop Training Mode controls the pauses.

## ⚙️ LOOP TRAINING MODE  →  **OFF** (flipped by Bjion, 2026-07-27; default is ON)

Flip it by editing this one line:

    LOOP_TRAINING_MODE = OFF       # ON = approve every step · OFF = run autonomous

**When ON (default)**
- Pause at the end of **every** step and wait for Bjion's explicit approval before continuing.
- Before running a step, check its done-rule first. **If it already passes, skip it** — say so and move on.
- Only (re-)run the steps that fail their done-rule.
- Retry cap applies (below). Never loop a step forever.

**When OFF**
- Run all steps autonomously, no pauses.
- Still check every step's done-rule and still honour the retry cap. Report at the end, not between steps.

**Retry cap (both modes):** any single step retries **max 3** times against its done-rule; the panel
(Step 3) runs **max 4** full revise-and-rescore rounds. On cap-hit, record FAILED with the reason and the
honest scores, keep going where possible, surface every FAILED item in the final report. Never declare done
on a cap-hit.

## THE GOAL

The strategy link is a **live, breathing dashboard of the campaign launch**. A non-technical founder opens
it and, per campaign, sees at a glance how far the launch has got, what is happening right now, and can tap
straight into the targeting, the copy, or the icebreakers to watch them take shape. No "Start" button, no
numbers pretending to be progress — real launch state, shown visually.
**Verification bar: 5 simulated non-technical founders and sales leaders score EACH prototype 9/10+ on all
three axes — actionable insights, easy to digest, beauty of the design.** (Bjion's real panel follows his
pick; the simulated panel is the pre-filter, not the proof.)

## THE LAUNCH STAGES the dashboard visualises

Every campaign moves through the same five stages (the real skill chain underneath). Each must be a place
you can skip to and SEE, not just a tick:

| Stage | What it is | What "see it" means |
|---|---|---|
| Targeting | who we email (roles/signal + the list building) | the roles/tools as chips + the live count filling |
| Copy | the emails | the email frames, readable, sendable |
| Icebreaker | the per-lead opening lines | a few real sample openers |
| Checks | email verify + the safety/QA gate | pass/fail lights, "no one emailed twice" |
| Live | loaded to Smartlead, paused | the paused campaign, one switch from sending |

Progress is real where we have it, **mocked-but-labelled "preview" where we do not** — fixtures come from
the current live run's 5 Prospeo campaigns (real names + net numbers, invented launch state marked preview).

## HARD RULES

- **If it needs explaining, it is already too complicated.** No caption teaching the UI, no legend, no
  tooltip required to understand a state. A 16-year-old gets it in one look.
- **Live and breathing.** The in-progress stage shows motion (a pulse, a filling bar, a ticking count). The
  dashboard feels alive, not a static form — but motion is subtle, never a distraction.
- **Skip-to-stage is first-class.** From a campaign's row/tile you jump straight to Targeting, Copy or
  Icebreaker, see that stage, and get back with one obvious control. No deep menus, no scroll hunt.
- **Chat-first, board-mirrors (standing law).** The board is never where you TYPE instructions — it shows
  what the chat is doing. No forms that duplicate the conversation. (memory: chat-mirror.)
- **Real campaign identities.** Use the current live run's 5 campaigns (stack, new-exec, growth, MSP,
  freight) — real names + net numbers; any progress not truly known is labelled "preview".
- **Navreo Design System only** — cream/ink, one orange accent moment, Acid Grotesk data-URI, chart-series
  palette, no emoji, light + dark both correct, no horizontal scroll at 375px or desktop.
  (`~/.claude/skills/navreo-design-system/`.)
- **Prototype, do not ship.** The winner merges into the live board (`wizard-template.html` → wizard-lab
  `build_live.py`) ONLY on Bjion's explicit pick.

## FIVE DIRECTIONS (starting palette — the panel picks the winner)

Five genuinely different visual grammars for the same live dashboard; keep each minimal:
1. **Pipeline stepper** — each campaign a row; the five stages fill left→right; the live stage pulses.
2. **Progress ring** — each campaign a radial that fills; tap a segment to jump to that stage.
3. **Live stream** — a breathing activity feed per campaign ("icebreakers 60%…", updating in place).
4. **Launch lanes** — kanban columns Targeting→Copy→Icebreaker→Checks→Live; campaigns as cards moving right.
5. **Mission control** — one big tile per campaign: hero state + a sparkline of launch progress.

## STEPS

**Step 0 — Capture the surface + the real stages.**
Read today's board (`wizard-template.html` / `strategy.html`) and the live-run fixtures (the 5 Prospeo
campaigns + net numbers). Write `app/prototypes/launch-dashboard-fixture.js` holding the 5 campaigns and a
per-stage state for each (real where known, else "preview").
*Done-rule:* fixture exists with 5 campaigns × 5 stages; the surface file + insertion point are recorded.

**Step 1 — Build the 5 prototypes.**
`app/prototypes/launch-dashboard-p1..p5.html` (one per direction) + `launch-dashboard-index.html` linking
them side by side. Each renders the 5 campaigns as a live launch dashboard; skip-to-stage works; the
in-progress stage breathes; Navreo DS; theme toggle; 375px + desktop.
*Done-rule:* all 5 render from the fixture in both themes at both widths, no horizontal scroll, skip-to-stage
works on every one, zero console errors — browser-verified on the local server (7901).

**Step 2 — Self-critique against the minimal law.**
For each prototype list anything that needs explaining (caption, legend, tooltip, instruction). Remove or
redesign until that list is empty.
*Done-rule:* no prototype relies on words to be understood; the "needs-explaining" list is empty for all 5.

**Step 3 — Founder panel.**
5 fresh non-technical founder / sales-leader personas. Each gets a ~10-second look at each prototype, then
scores 1-10 on **actionable insights**, **easy to digest**, **beauty of the design**, plus one line of
"what is this telling me / what would I do". Average per prototype per axis.
*Done-rule:* at least one prototype averages **≥9.0 on all three axes** across a full 5-persona round; the
score table is recorded. Revise the top contenders and re-run with fresh personas until true; cap 4 rounds.

**Step 4 — Handover.**
One line + the index link, per the handover convention. Report: index link, the score table, the winner and
why, and what would change in the live board if merged. Do NOT merge — wait for Bjion's pick.
*Done-rule:* handover delivered with link + scores + a named winner; nothing merged into the live board.

## DONE

Steps 0-4 pass their done-rules: 5 minimal live-launch-dashboard prototypes render from real campaign
fixtures, none needs explaining, and a full 5-persona panel scored at least one prototype ≥9.0 on all three
axes. On a Step 3 cap-hit without a 9.0, deliver the lab, the honest scores and the blockers — never claim
the bar was met. The winner ships into the live board only when Bjion picks it.
