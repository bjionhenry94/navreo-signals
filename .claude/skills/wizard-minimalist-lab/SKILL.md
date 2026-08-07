---
name: wizard-minimalist-lab
description: Static orchestration skill that builds 5 prototypes of the campaign-launch wizard (from the maintained winner r3 / artifact 5d6e5fdd), each applying a progressively more aggressive minimalist treatment — less copy on screen at any moment, insights made visual instead of verbal — in the stance of Dieter Rams, Steve Jobs and Jony Ive, WITHOUT changing the design system (Navreo white app variant), the flows, the journey, the gates, the parallel engine, or the Navreo-voice email copy itself. Only the chrome, insight surfaces and information density change. Each prototype must pass a simulated panel of 5 non-technical founders at 9/10+ for simplicity and ease of use. Winner's treatment merges back into r3 (the one maintained artifact) on Bjion's pick. Use when the user says "run the minimalist lab", "reduce the wizard copy", "make the wizard calmer", or "/wizard-minimalist-lab".
---

# wizard-minimalist-lab

The wizard's UX, flows and layout are right — it just says too much at once. Build **5 prototypes**, each a stricter exercise in "as little design as possible": fewer words on screen, insights carried visually, detail available on demand, never ambient. Static loop — fixed steps, checkable done-rules, Loop Training Mode controls pauses.

**Hard invariants (all five):** Navreo white app variant DS exactly (tokens, type, one-orange law) · identical journey and gates (preview → targeting → build → two-page copy pack → sign-off → launch-ready) · parallel engine + Needs-you states · the email copy itself is UNTOUCHED (it's the product; the chrome slims, not the letters) · jargon ban · zero real credits · artifacts only.

---

## ⚙️ LOOP TRAINING MODE  →  **ON** (default)

Flip it by editing this one line:

    LOOP_TRAINING_MODE = ON        # ON = approve every step · OFF = run autonomous

**When ON**
- Pause at the end of **every** step and wait for my explicit approval before continuing.
- Before running a step, check its done-rule first. **If it already passes, skip it** — say so and move on.
- Only (re-)run steps that fail their done-rule.
- Retry cap applies (see below). Never loop a step forever.

**When OFF**
- Run all steps autonomously, no pauses.
- Still check every step's done-rule and still honour the retry cap. Report at the end, not between steps.

**Retry cap (both modes):** any single step retries **max 3** times against its done-rule. On cap-hit, record FAILED with the reason, keep going where possible, surface it in the final report. Never silently exceed.

---

## THE GOAL

The insights become easier to digest and more visual: a non-technical founder opens the wizard and never feels read-at. Numbers, bars, dots and states carry the meaning; sentences appear only when summoned. **Verification bar: a simulated panel of 5 non-technical founders rates each prototype 9/10+ for simplicity AND ease of use** (Bjion's real panel follows his pick).

---

## THE FIVE TREATMENTS (each starts from a fresh copy of the maintained winner)

| # | Treatment | The discipline |
|---|---|---|
| M1 | **Progressive disclosure** | Every card/section collapses to ONE line at rest; evidence, splits, "why" open on tap and close behind you. Nothing scrolls that isn't summoned. |
| M2 | **Numbers first** | Cards = hero number + name, nothing else. Why-lines become a 3-4 word caption under the number; splits become pure bars with mono labels; sentences exist only inside previews. |
| M3 | **One thing per screen** | The workspace shows a single focused element at a time with generous whitespace; everything secondary sits behind one quiet "More" affordance per screen. |
| M4 | **Visual language** | A tiny consistent visual system replaces labels: state dots, split bars, spark-ticks, count-up numbers; microcopy ≤5 words everywhere outside emails. Legend once, then trusted. |
| M5 | **Calm board (Rams-strict)** | The composite: ~80% of at-rest text removed, one accent moment per screen, evidence as an on-demand layer, empty space as the primary material. As little design as possible. |

---

## THE STEPS

### Step 1 — Reduction spec
- Write `wizard-lab/minimal-spec.md`: the at-rest word budget per surface (card ≤12 words, workspace screen ≤40, sign-off ≤60 outside the email frames), the on-demand pattern (what opens, how it closes), the visual encodings (state dot vocabulary, split bar, progress language), and the invariants list above. Include a text-census script command (count rendered words per screen) used by every done-rule.
- Done-rule: spec exists with numeric budgets + census method; invariants restated verbatim.

### Step 2 — Build M1-M5
- Copy the winner file 5× (`m1.html`…`m5.html`), apply each treatment per spec (builders read the spec + the winner file; DS untouched; email copy strings byte-identical). Publish each as its own artifact.
- Done-rule (per prototype): full journey completable; text census meets its budget at rest on menu, workspace, and sign-off; email copy strings byte-identical to the winner (diff check); zero console errors; 375px clean; artifact live.

### Step 3 — Founder panel
- Simulated panel of 5 NON-TECHNICAL founders (fresh cast, not the CSM/customer panels; impatient, allergic to reading) walks each prototype end-to-end (?fast=1, two campaigns in parallel) and scores /10: simplicity, ease of use, "did the visuals tell me enough without reading?", plus a worst-moment quote each.
- Done-rule: 5 scorecards per prototype; flag any place a founder needed information that the reduction hid too deep (over-minimisation is a defect too).

### Step 4 — Fix loop
- Prototypes under **9/10 average** get their worst-moments fixed (including restoring anything hidden too aggressively) and re-panelled. Retry cap applies; cap-hit = FAILED-BAR with honest scores.
- Done-rule: ≥3 prototypes at 9/10+.

### Step 5 — Comparison + hand-off
- One summary chat report (no new artifact): the 5 URLs, scores, per-treatment word-census vs the winner's, and a recommendation for which treatment (or blend) merges into r3. **r3 itself is untouched until Bjion picks** (maintenance ruling: only r3 is maintained; the m-files are lab pieces).
- Done-rule: report delivered; session file appended; on Bjion's pick, a follow-up merge step applies the chosen treatment to r3 + wizard-template.html and republishes the standing URL.

---

## OVERALL DONE-RULE
- 5 minimalist prototype artifacts live, each journey-complete, DS-intact, email-copy-identical, census-passing; ≥3 at the founder-panel 9/10 bar; comparison + recommendation delivered; r3 unchanged pending Bjion's pick; zero real credits.
