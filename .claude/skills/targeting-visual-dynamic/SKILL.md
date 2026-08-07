---
name: targeting-visual-dynamic
description: Orchestration skill for making the strategy board's "Targeting" section dynamic — so it visualises the targeting of ANY campaign use-case (niche list, hiring signal, engagement signal, followers, lookalike, news signal, recontact, events) instead of the frozen lookalike-example labels ("companies like these", "case studies we pull"). Runs a fixed goal → steps → done-rule loop with a Loop Training Mode toggle (pause-for-approval vs autonomous). Use when asked to make the targeting section dynamic/malleable, fix the hard-coded targeting headers, generalise the Targeting page across use-cases, or when someone says "run the targeting visual loop".
---

# Targeting Visual — Dynamic Loop

A static, pre-baked loop for turning the strategy board's Targeting section from a frozen, one-example layout into a data-driven visual that fits whatever the idea is. Read it top to bottom once; it does not change between runs.

---

## ⚙️ LOOP TRAINING MODE  →  **OFF**

Flip this one word to change how the whole loop runs. Default is **ON**.

**When ON (default — training):**
- **Pause at every step.** Do the step, show the result, then STOP and wait for my explicit approval before moving on.
- **Skip any step that already passes its done-rule.** Check the done-rule first; if it's already green, say so and move on. Don't redo finished work.
- **Only re-run steps that fail.** If a step's done-rule fails, fix and re-run that step only, not the whole loop.
- **Retry cap: 3.** Max 3 attempts on any one step. After 3 fails, STOP and surface the blocker in plain English. Never loop forever.

**When OFF (autonomous):**
- **No pauses.** Run every step start to finish without waiting for approval.
- **Keep the done-rule checks.** Every step is still gated on its done-rule; a failed done-rule still blocks progress.
- **Keep the retry cap (3).** Same 3-attempts-then-stop rule. Autonomous ≠ infinite.

> To change it later: edit the line above to `→ OFF` (or back to `→ ON`). Nothing else in this file needs touching.

---

## 🎯 Goal

Make the Targeting section **visualise the targeting of a wide range of common campaign use-cases**, malleable to whatever the idea is — not frozen to the one lookalike example it was built from.

Today `renderShowcase(idea)` in `wizard-template.html` hard-codes two headers that only fit a lookalike-of-agencies idea:
- `"Lookalike anchor — companies like these"` (reads `idea.anchors`)
- `"Case studies we pull"` (reads `idea.cases`)

On a hiring signal, a niche list, a news signal or a followers idea those headers are wrong or empty. Every label and every section must instead come from the idea's own data, so each use-case shows its own fitting framing.

**The common use-cases to cover (the board's vectors):** `targeted_list` (niche), `prospeo_signal`, `hiring_signal`, `engagement_signal`, `followers`, `lookalike`, `news_intent`, `recontact`, `events`. The Targeting visual must read well for every one of these.

## 🔒 Design contract (keep / drop — never violate)

**KEEP:** the editable role chips · `targetingHtml(idea)`'s already-data-driven model (label/roles/excluded/meta/audience/note all come from data) · `esc()` on every value · theme-aware styling · the render-only-when-a-field-is-present gating (a missing field renders nothing, never an empty header or an error).

**DROP:** the two frozen literal headers above, and any label or section that assumes the lookalike/case-study example. No string that names one specific idea's framing may live in the renderer.

**THE RULE:** every section header, and *whether a section appears at all*, is a function of the idea's data (+ a per-kind default label map for sparse blocks), never a constant tied to one example. A niche list says "Companies we target"; a hiring signal "Roles they're hiring for"; an engagement idea "Posts they react to"; a followers idea "Pages whose followers we email"; a lookalike keeps "Companies like these" — but now scoped to that idea, not forced on all.

**GOTCHA (must design around):** the page does NOT see `idea.vector` — the engine strips `vector`/`probe`/`pull_spec`/`netting` before splicing the IDEAS array (engine.py `cmd_hydrate`, README contract). So the renderer cannot branch on the vector. Make it **data-driven**: the `targeting` block itself carries the labelled groups (recommended: a `groups: [{label, chips, muted?}]` array + the existing `roles`), so the page renders whatever labels the data supplies. Add an optional page-visible `targeting.kind` ONLY as the key into a default-label fallback map for when a block is sparse. Keep a back-compat shim so existing `anchors`/`cases` runs still render (map them into a lookalike group).

**FEEL:** the same calm, minimal, highly-visual language as the rest of the board — labelled chip groups, generous space, one accent, theme-aware, no gradients/emoji. A GTME should grasp and *remember* the targeting from one glance.

---

## 🪜 Steps (each has its own done-rule — that's what Loop Training Mode gates on)

**1 · Frame.** Read `renderShowcase` + `targetingHtml` in `~/.claude/skills/lilly-strategy/wizard-template.html`. List every frozen/example-specific string. Write the dynamic data model (the `targeting.groups` shape + optional `kind` + per-kind default-label map covering all vectors above) and the back-compat plan for `anchors`/`cases`.
  - *Done-rule:* the frozen strings are enumerated and the data model + default-label map (one entry per vector) + back-compat shim are written down and approved.

**2 · Fixtures.** Build a fixture run with ONE representative idea per vector (niche list, prospeo signal, hiring, engagement, followers, lookalike, news, recontact, events), each carrying a realistic `targeting` block in the new shape.
  - *Done-rule:* a fixture JSON exists with an idea for every vector, each with a populated targeting block; validates against the engine.

**3 · Build.** Rework `renderShowcase`/`targetingHtml` to render the Targeting section purely from the targeting data (+ default-label fallback + back-compat shim). Preview it across all fixtures in a self-contained harness at `~/navreo-signals/app/prototypes/targeting-dynamic-p*.html`.
  - *Done-rule:* every vector's fixture renders a correct, fitting Targeting visual — right labels, no empty headers, no leftover example strings, no console errors — and old `anchors`/`cases` runs still render via the shim.

**4 · Score.** Run a panel of **5 simulated GTMEs** (distinct: new GTME, senior GTME, ops-minded GTME, skeptical GTME, visual-first GTME). Each rates every vector's Targeting visual 1–10 on **visualises the targeting clearly** and **helps me remember what the targeting is**, plus one favourite and the single fix to reach 9.
  - *Done-rule:* all 5 reviewers returned both scores for all vectors, recorded in the session file.

**5 · Polish.** Apply the highest-impact fix the panel named; re-score just the changed visuals.
  - *Done-rule (THE BAR):* every vector's Targeting visual scores **≥ 9/10 from all 5 GTMEs on both axes** (clear visualisation + memorability). Below the bar → fix → re-score (retry cap 3).

**6 · Ship.** Merge into `~/.claude/skills/lilly-strategy/wizard-template.html`, rebuild with `python3 ~/.claude/skills/wizard-launch-lab/wizard-lab/build_live.py ~/navreo-signals/app/strategy.html`, update the engine README + `validate` for the new `targeting.groups`/`kind` shape, verify prod hydrates a multi-vector run with the right per-idea Targeting and no console errors, then commit + push (`~/navreo-signals`, Render auto-deploys).
  - *Done-rule:* prod `strategy.html` renders the dynamic Targeting correctly for every vector, back-compat holds, engine contract updated, pushed.

**7 · Record.** Save the session record and a one-line memory (what changed, the data shape, live commit).
  - *Done-rule:* session file + memory written.

---

## ✅ Overall done-rule

Done when the Targeting section **renders a fitting, correct visual for every common use-case with zero example-specific hard-coding, AND 5 GTMEs score it ≥ 9/10 on both visualising the targeting and remembering it**, live on `strategy.html`, with back-compat intact and the engine contract updated. Anything less is not done; anything past 3 failed attempts on a step stops and reports the blocker.

## 🧭 Runbook quick-reference
- Renderer: `~/.claude/skills/lilly-strategy/wizard-template.html` → `renderShowcase()` (~line 3049) + `targetingHtml()` (~line 3020)
- Engine + contract: `~/.claude/skills/lilly-strategy/engine/engine.py` + `engine/README.md` (targeting block, hydrate strips `vector`)
- Prototypes: `~/navreo-signals/app/prototypes/targeting-dynamic-p{1..N}.html`
- Live page: `~/navreo-signals/app/strategy.html` (built from wizard-template.html via `wizard-launch-lab/wizard-lab/build_live.py`)
- Verify live: mint a `navreo_session` cookie (memory `signals-live-verify-recipe`), POST a multi-vector run to `/api/strategy/run`, GET it back, open `https://navreo-signals.onrender.com/app/strategy.html`
- Sessions: `~/.claude/skills/targeting-visual-dynamic/sessions/<date>.md`
