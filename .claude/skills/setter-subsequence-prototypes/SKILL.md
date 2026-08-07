---
name: setter-subsequence-prototypes
description: Static orchestration skill that designs and builds 5 clickable UI prototypes giving the Appointment Setter what Smartlead has and it doesn't — the ability to send a lead to a sub-sequence at send time, plus awareness of every reply where that step was forgotten. Goal is a system where a missing sub-sequence is impossible to overlook and opting out is one obvious click. Each prototype must score 8/10+ on ease of use AND on effectiveness at stopping the setter forgetting, judged by an independent panel, before it reaches Bjion for hands-on testing. One fixed step list, checkable done-rules, retry caps, and a Loop Training Mode toggle (ON by default). Use when the user says "run the setter sub-sequence prototypes", "build the sub-sequence UI options", "prototype sub-sequence sending", or "/setter-subsequence-prototypes".
---

# Setter: Sub-Sequence Send — 5 UI Prototypes

In Smartlead, when you reply to a lead you can push them into a **sub-sequence** (a follow-up track). The Appointment Setter can't — and worse, nothing tells you when you've forgotten. This loop produces **5 clickable UI prototypes** so Bjion can test which design best guarantees: every send that should carry a sub-sequence does, and opting out is one easy, deliberate click.

Static loop — fixed steps, each has a done-rule, Loop Training Mode controls the pauses.

## ⚙ Loop Training Mode: **OFF**   ← flip this line to ON to pause at every step

**ON (default):** pause at EVERY step boundary and wait for the user's explicit approval before continuing. Before starting a step, check its done-rule first — if it already passes, report "Step N already passes, skipping" and move on. Only re-run steps whose done-rule fails. Show what you're about to do before doing it.

**OFF:** run all steps end-to-end with no pauses. The done-rule checks, skip-if-passing behaviour, and retry caps stay exactly the same — only the pauses go.

**Retry cap (both modes):** each step retries **max 3** times against its done-rule. On cap-hit: record the step as FAILED with the reason, continue to the next step if it doesn't depend on the failed one, and surface every FAILED step in the final report. Never silently exceed the cap. Never declare the skill done on a cap-hit.

**Model routing:** judgment (concept selection, panel scoring, done-rule verdicts) runs on the orchestrating session. Execution (prototype HTML builds, mock data) runs on Sonnet 5 subagents (`model: sonnet`).

### Non-negotiable gates (both modes)

- **UI-first means UI-only.** No setter.py changes, no Supabase migrations, no live queue rows touched, zero real sends. Prototypes are standalone HTML with mock reply data.
- **Smartlead API reality check:** the public API has **no sub-sequence endpoint** ([[project_idea_to_launch_first_run]]). Prototypes may assume the capability exists (that's the point of prototyping), but the final report MUST state the backend feasibility gap honestly so a winning design isn't picked on a false promise.
- **Prototypes wear the setter's skin**, not a generic mockup — clone the real setter.html review pane's look (fonts, colours, layout) so testing feels like the real app. Standalone docs follow the Navreo Design System ([[feedback_artifacts_navreo_design_system]]).
- **Verified in a rendered browser, not by grep** ([[feedback_browser_verify_before_done]]): every prototype is opened and clicked through in the browser pane before it counts as built.

## Goal

Whenever a sub-sequence hasn't been applied, the setter (or the human reviewing) is made aware and it gets applied; whenever it *shouldn't* be applied, opting out is one easy, explicit action. Five genuinely different UX answers to that, ready for hands-on testing.

### THE DONE-RULE (single source of truth)

> (1) **5 prototypes exist**, each a self-contained clickable HTML file under `prototypes/setter-subsequence/`, each embodying a *distinct* forget-prevention mechanism (no two are variants of the same idea).
> (2) Each prototype demonstrates **both halves** of the goal interactively: applying/choosing a sub-sequence on a send, AND surfacing sends where it was forgotten (with a working opt-out path).
> (3) Each prototype scores **≥8/10 on ease of use** and **≥8/10 on forget-prevention effectiveness** from a 3-judge independent panel (scores averaged per axis; both axes must clear 8).
> (4) Every prototype browser-verified: opened, clicked through the apply path, the forget-surface path, and the opt-out path, with a screenshot each.
> (5) Final report delivered to Bjion: the 5 prototypes with one-line pitches, panel scores, how to open them, and the honest Smartlead API feasibility note.
>
> **All 5, or it isn't done.** On any cap-hit, report the gap honestly — never declare done.

## Ground truth (re-verify in Step 1 — line numbers drift)

- **Files:** `app/setter.html` (the review pane UI to clone), `app/setter.py` (send flow: `route_queue_action` handles Approve/send). Working copy = iCloud dir; nothing here deploys.
- **What "sub-sequence" means operationally:** in Smartlead, after a reply you can move the lead into a follow-up sequence (e.g. "sent-calendar-link nudge track"). The setter's Approve currently sends the reply and stops — no follow-up track, no reminder that one was skipped.
- **Smartlead public API has no sub-sequence endpoint** — moving a lead to a sub-sequence is dashboard-only today ([[project_idea_to_launch_first_run]]). The eventual backend will need a workaround (Smartlead UI automation, a native setter-side follow-up scheduler, or a Smartlead feature request). Out of scope for this loop, in scope for the report.
- **Where the UI hooks in:** the review pane's Approve/send area (draft box + action buttons) and the queue list — both are candidate surfaces for "choose a sub-sequence" and "you forgot one".
- **Panel precedent:** the 8/10 panel bar and 3-judge averaging follow the house pattern used in [[project_offer_maker_v2_chord]] and setter panel tests.

## Steps

### Step 1 — Re-verify ground truth + capture the decision points
Sonnet subagent: confirm the setter review pane structure (where Approve lives, what the queue list shows), extract the real CSS/fonts/colours to reuse, and confirm the Smartlead sub-sequence API status hasn't changed (quick docs check). Write a short "decision map": at what moments could a sub-sequence be chosen, forgotten, or opted out of?
- **Done-rule:** ground-truth bullets confirmed or corrected in writing; a copyable style snippet from setter.html exists; the decision map lists at least the send-moment, the post-send moment, and the review-queue moment.

### Step 2 — Ideate and lock 5 distinct concepts
Generate 8–10 candidate UX concepts, then select the 5 most distinct. Each concept must name its **forget-prevention mechanism** — the thing that makes forgetting hard. Seed directions (replace freely if better ideas emerge, but the final 5 must each use a different mechanism):
1. **Default-on picker** — every Approve pre-selects a recommended sub-sequence; sending without one requires an explicit "No follow-up" click (opt-out is the deliberate act, not opt-in).
2. **Send gate** — Approve is disabled until a sub-sequence choice (including "None") is made; one-tap chips keep it fast.
3. **Forgotten-queue badge** — sends can go out bare, but a persistent "3 sent without follow-up" tray surfaces them for one-click retro-assignment.
4. **Smart suggestion + nudge** — the agent proposes a sub-sequence from reply context ("asked for pricing → pricing nudge track"); an inline banner nags only when it's confident one is needed.
5. **Checklist confirm** — a lightweight pre-send confirm strip showing "Reply ✓ · Follow-up track: —" that turns the missing item amber and clickable.
- **Done-rule:** 5 concepts locked, each with a one-line pitch, its named mechanism, and its opt-out story; no two share a mechanism. (Training Mode ON: Bjion approves the 5 before any building.)

### Step 3 — Build the 5 prototypes
One Sonnet subagent per prototype, in parallel. Each builds a self-contained HTML file in `prototypes/setter-subsequence/` (e.g. `p1-default-on.html`), using the Step-1 style snippet so it looks like the real setter, with 5–6 mock replies covering: an obvious sub-sequence case, a should-opt-out case, and an already-forgotten case. All interactions work client-side (no server): picking, sending, opting out, and the forgot-surface updating live.
- **Done-rule:** all 5 files exist, open in the browser pane without console errors, and each demonstrates apply + forget-surface + opt-out interactively (clicked through, screenshot each).

### Step 4 — Panel scoring
For each prototype, 3 independent judge subagents (given the prototype source + screenshots + the goal statement) score two axes 1–10: **ease of use** (clicks, clarity, speed — would a busy setter fight it?) and **forget-prevention effectiveness** (can a send realistically slip through unassigned? is opting out easy but deliberate?). Average per axis. Judges also return the single biggest weakness.
- **Done-rule:** every prototype has both averaged scores recorded with the judges' top weaknesses; any prototype under 8 on either axis is flagged for Step 5.

### Step 5 — Rework failures
For each flagged prototype: fix the judges' named weaknesses (don't redesign from scratch — the concept was already approved), re-verify in browser, re-run the same 3-judge panel. Max 3 rework rounds per prototype (the step's retry cap). If a concept can't clear 8/8 in 3 rounds, mark it FAILED with the panel's reasoning and — only if Training Mode is ON — offer Bjion a swap-in concept from the Step-2 leftovers.
- **Done-rule:** every non-FAILED prototype scores ≥8 on both axes; FAILED ones carry the panel's written reasoning.

### Step 6 — Hand over for testing
Final report to Bjion: table of the 5 prototypes (pitch, mechanism, ease score, effectiveness score, file path + how to open), the honest Smartlead API feasibility note, and a recommendation of which 1–2 designs to take to build. Open the top-scoring prototype in the browser pane so testing starts immediately.
- **Done-rule:** report delivered in chat; all prototype files listed with working paths; top prototype open in the browser pane; the API feasibility gap stated plainly.

## Final report format

```
SETTER SUB-SEQUENCE PROTOTYPES — RESULT
Prototypes built: N/5   Panel-passed: N/5   FAILED: [list or none]
| # | Concept | Mechanism | Ease | Effectiveness | File |
Feasibility note: Smartlead public API has no sub-sequence endpoint — backend will need [options].
Recommendation: [1–2 designs + why]
Steps skipped (already passing): [...]   Cap-hits: [...]
```
