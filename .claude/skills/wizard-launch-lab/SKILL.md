---
name: wizard-launch-lab
description: Static orchestration skill that builds 3 minimal prototypes of the lilly-strategy
  campaign-launch walkthrough (from a fresh copy of the maintained winner wizard-template.html),
  each fixing the five launch blockers Bjion documented on 2026-07-27 (stale cross-session board,
  invisible targeting, unsendable strategy-speak inside emails, missing back buttons, UI-only
  targeting edits) while keeping the split-view structure, journey and gates identical. Minimal
  design law - if it needs explaining, it is already too complicated; language a 16-year-old
  understands. Each prototype must pass a simulated panel of 5 non-technical founders and sales
  leaders at 9/10+ on actionable insights, easy to digest, and beauty of the design. Winner merges
  into wizard-template.html only on Bjion's pick. Use when the user says "run the launch lab",
  "prototype the launch walkthroughs", "rebuild the strategy walkthrough", or "/wizard-launch-lab".
---

# wizard-launch-lab

The walkthrough's journey is right, and it still loses people between "nice idea" and "launched".
Build **3 prototypes**, each the same structure, experience and main layout as today's split view,
each shipping all five fixes below, each a stricter exercise in minimal design: less explanation,
more intuitive. Static loop - fixed steps, checkable done-rules, Loop Training Mode controls pauses.

## ⚙️ LOOP TRAINING MODE  →  **OFF** (flipped by Bjion, 2026-07-27)

Flip it by editing this one line:

    LOOP_TRAINING_MODE = OFF       # ON = approve every step · OFF = run autonomous

**When ON**
- Pause at the end of **every** step and wait for my explicit approval before continuing.
- Before running a step, check its done-rule first. **If it already passes, skip it** - say so and move on.
- Only (re-)run steps that fail their done-rule.
- Retry cap applies (below). Never loop a step forever.

**When OFF**
- Run all steps autonomously, no pauses.
- Still check every step's done-rule and still honour the retry cap. Report at the end, not between steps.

**Retry cap (both modes):** any single step retries **max 3** times against its done-rule; the
panel (Step 4) runs **max 4 full rounds**. On cap-hit, record FAILED with the reason and honest
scores, keep going where possible, surface every FAILED item in the final report. Never declare
done on a cap-hit.

## THE GOAL

A simple, highly visual strategy walkthrough that takes a non-technical founder from "here are
this session's campaign ideas" all the way to launch-ready, so they book more meetings. Nothing
on screen needs explaining; the words read like a 16-year-old wrote them for their mum.
**Verification bar: 5 simulated non-technical founders and sales leaders score EACH prototype
9/10+ on all three axes - actionable insights, easy to digest, beauty of the design.**
(Bjion's real panel follows his pick; the simulated panel is the pre-filter, not the proof.)

## THE FIVE FIXES (every prototype ships all five - source: Lilly-strategy.pdf, 2026-07-27)

| # | Problem observed | Required fix + its test |
|---|---|---|
| F1 | A brand-new brief showed ideas carried from previous sessions mixed into the menu | The board shows ONLY this session's ideas. Anything already running lives on a visually separate "Already running" shelf below, never mixed in. Test: fresh load - menu contains the fixture's 4 new ideas only; carried campaign appears solely on the shelf. |
| F2 | Clicking an idea did not show the exact roles | Targeting is first-class: the exact roles/tools render as chips in the FIRST screen of an opened idea, above the fold at 1280px, no scroll, no toggle. Test: open each idea - chips visible without scrolling. |
| F3 | The email preview contained strategy commentary that would never be sent ("the new-in-role trigger is the one signal that keeps working...") | Every line inside a mail frame must be sendable to the prospect. Lint: no sentence about signals, triggers, mechanisms, "this list", or why-we-picked-you-this-way inside any mail body; rationale lives outside the frame. Test: grep the rendered mail bodies for the banned-phrase list in the spec - zero hits. |
| F4 | No back button on many pages; hard to navigate | Every screen after the board has a visible Back control; Back never loses state (edits, approvals, build progress all survive). Test: walk to sign-off, go back to the board, return - everything as left. |
| F5 | Changing targeting did nothing - UI-only | Targeting edits visibly DO something: the chip editor mirrors the tool's "Who should they be hiring?" modal (page 3 of the PDF - removable chips, "add a role..." input, Generate more, two groups: trigger roles + who we email), and any change re-counts the headline number with a brief "re-checking..." state and updates downstream previews. Counts are mocked deltas labeled "estimate - re-checked free before launch". Test: remove a chip - number changes and label appears; add it back - number returns. |

## HARD GATES (all prototypes, non-negotiable)

- **Zero real credits.** All numbers replay `lilly-strategy/sessions/navreo-2026-07-27-run.json`
  (already paid for). Recounts on chip edits are mocked, honestly labeled. No provider calls anywhere.
- **Same structure, experience, main layout.** Split view: sticky campaign rail left, workspace
  right; same journey and gates (preview → targeting → build → copy pack → opener → sign-off →
  launch-ready); parallel builds and Needs-you states intact.
- **Template law.** Each prototype starts from a fresh COPY of
  `~/.claude/skills/lilly-strategy/wizard-template.html`. The template is never edited in place.
- **Standing-artifact gate.** The standing URL
  `https://claude.ai/code/artifact/5d6e5fdd-69d8-48f2-be8e-bec57da7b51f` is never republished or
  repointed by this lab. Each prototype gets its OWN artifact URL with a stable favicon.
- **Design system.** Navreo white app variant exactly: tokens, Acid Grotesk data-URI, one-orange
  law. Known token gotcha: `--card-toned` does not exist; toned surfaces use `--sunken`, raised
  chips use `--raised` + `--line-2`.
- **Language.** Jargon ban ("people we can reach", not TAM/DM/enrich; "opener"; "double-checked").
  No em-dashes in user-visible copy. Minimal-lab lesson stands: never hide the decision cue.
- **Nothing sends.** No Smartlead writes, no uploads, no activation - launch-ready is the end state.

## THE THREE PROTOTYPES (identical journey and fixes; only the interaction emphasis differs)

| # | Treatment | The discipline |
|---|---|---|
| L1 | **Chips do the work** | Targeting IS the front door: open an idea and the chip editor (F5 pattern) sits beside the live number; everything else collapses to one line each. You launch by shaping the audience, then approving words. |
| L2 | **One decision per screen** | The workspace shows exactly one decision at a time (who → words → opener → go) with progress dots, a big Next and an always-there Back. The rail still shows every campaign building in parallel. |
| L3 | **Launch runway** | Each card carries a 4-stop runway strip (who · words · opener · go) that fills as you progress; tapping a stop opens a minimal sheet for just that decision. The board always shows how far every campaign is from launch-ready. |

## THE STEPS

### Step 1 - Fix-spec + fixture
- Write `wizard-lab/launch-spec.md`: the five fixes as testable requirements (F1-F5 with their
  exact tests), the banned-phrase list for F3, the word budgets (card at rest ≤12 words, workspace
  screen ≤40 outside mail frames, every label ≤5 words), the 16-year-old language rule, and the
  chip-editor spec copied from the PDF's page-3 modal. Build `wizard-lab/launch-fixture.js` from
  the 2026-07-27 run file: 4 fresh ideas + 1 already-running campaign for the F1 shelf, per-idea
  targeting chips, mocked recount deltas.
- **Done-rule:** both files exist; every fix has a written test; banned-phrase list ≥8 entries;
  zero provider calls anywhere in the plan.

### Step 2 - Build L1-L3
- Copy the winner template 3× (`l1.html` `l2.html` `l3.html`), apply each treatment per spec, wire
  the fixture, publish each as its own artifact (3 separate URLs, stable distinct favicons).
- **Done-rule (per prototype):** full journey board → launch-ready completable by clicks alone;
  all five F-tests pass with rendered evidence (screenshots for F1/F2, grep output for F3, a
  walked back-and-return for F4, a recorded chip-edit recount for F5); word census within budget;
  desktop + 375px clean; zero console errors; artifact live.

### Step 3 - Panel: 5 non-technical founders and sales leaders
- Five fresh personas (no CSMs, no marketers-who-know-our-stack; impatient, allergic to reading).
  Each walks every prototype end-to-end and scores /10 on the three axes: **actionable insights ·
  easy to digest · beauty of the design**, plus a one-line worst-moment quote.
- **Done-rule:** 15 scorecards (5 testers × 3 prototypes), all three axes scored on each, every
  scorecard carries a worst-moment quote.

### Step 4 - Fix loop
- Any prototype under **9/10 average on ANY axis** gets its worst moments fixed (over-minimising
  that hides a decision cue counts as a defect) and is re-panelled. Max 4 rounds.
- **Done-rule:** all 3 prototypes at 9/10+ on all three axes; any miss after round 4 is a named
  FAILED-BAR line with honest scores, never rounded up.

### Step 5 - Hand-off (chat summary, no new artifact)
- One report: the 3 URLs, per-axis scores, one line on what each treatment does best, per-fix
  evidence links, and a recommendation for which treatment (or blend) merges into the real
  walkthrough. Append the session file `lilly-strategy/sessions/wizard-launch-lab-<date>.md`.
  **wizard-template.html and the standing artifact stay untouched until Bjion picks**; on his
  pick, a follow-up step merges the chosen treatment into `wizard-template.html` (backup first),
  republishes the standing URL, and notes the two real-build wirings the prototypes only mock:
  chip edits → free TheirStack re-probe via `engine.py probe`, and F1's session-fresh board →
  run.json carry rendered as the shelf, never as menu cards.
- **Done-rule:** report delivered with all five fixes evidenced per prototype; session file
  written; standing URL untouched (verify by listing, not memory).

## OVERALL DONE-RULE

3 prototype artifacts live, each journey-complete by clicks alone, each passing all five F-tests
with evidence, DS-intact, census-passing, zero real credits, zero console errors; 15 scorecards
with every prototype at 9/10+ on actionable insights, easy to digest, and beauty (or honest
FAILED-BAR lines); hand-off report + session file delivered; wizard-template.html and the
standing artifact untouched pending Bjion's pick.
