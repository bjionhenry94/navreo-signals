---
name: strategy-companion-lab
description: Orchestration skill for redesigning and shipping the Lilly-strategy dashboard (app/strategy.html) as a simple, highly-visual "campaign strategy companion" — where a non-technical founder skims fresh campaign ideas down to the bare bones (how many people we can email → who → first line → the emails) and watches them progress to launch-readiness. Runs a fixed goal → steps → done-rule loop with a Loop Training Mode toggle (pause-for-approval vs autonomous). Use when asked to prototype, iterate, score, or ship the strategy board / strategy companion / strategy.html, or when someone says "run the strategy companion lab".
---

# Strategy Companion Lab

A static, pre-baked loop for taking the strategy dashboard from brief → 5 prototypes → scored → winner → live. Read it top to bottom once; it does not change between runs.

---

## ⚙️ LOOP TRAINING MODE  →  **ON**

Flip this one word to change how the whole loop runs. Default is **ON**.

**When ON (default — training):**
- **Pause at every step.** Do the step, show the result, then STOP and wait for my explicit approval before moving to the next step.
- **Skip any step that already passes its done-rule.** Don't redo finished work — check the done-rule first; if it's already green, say so and move on.
- **Only re-run steps that fail.** If a step's done-rule fails, fix and re-run that step only — not the whole loop.
- **Retry cap: 3.** Max 3 attempts on any one step. After 3 fails, STOP and surface the blocker in plain English. Never loop forever.

**When OFF (autonomous):**
- **No pauses.** Run every step start to finish without waiting for approval.
- **Keep the done-rule checks.** Every step is still gated on its done-rule; a failed done-rule still blocks progress.
- **Keep the retry cap (3).** Same 3-attempts-then-stop rule. Autonomous ≠ infinite.

> To change it later: edit the line above to `→ OFF` (or back to `→ ON`). Nothing else in this file needs touching.

---

## 🎯 Goal

Turn `app/strategy.html` into a **campaign strategy companion**: a calm, highly-visual page where a non-technical founder can, in one skim, see each fresh campaign idea's **bare bones** and watch ideas move toward launch-readiness — with language a 16-year-old understands and zero jargon.

Every idea shows, in this order and nothing more at strategy time:
1. **How many** — people we can actually email (the reach number; flag real vs estimated).
2. **Who** — the people we'd email.
3. **First line** — the opener.
4. **The emails** — the copy.
5. *(faded "up next")* turning it into a real list — the data-processing step, deferred, never in the way.

## 🔒 Design contract (keep / drop — never violate)

**KEEP:** the sidebar layout as an idea-navigator · the "chat updates the page + top-right toast of the most recent change" behavior · the page-by-page, open-one-idea-at-a-time model.

**DROP:** email-finding counters · data-processing / launch-readiness step machinery at strategy time · the 3D-box idea thumbnail · the gray sidebar background (go **warm cream**, not gray) · cramped thumbnails (go **roomy**).

**FEEL:** minimal. Less explanation, more intuitive design — *if it needs explaining, it's already too complicated.* Warm white page, ONE orange accent, generous space, big hero numbers. No gradients, glass, or emoji.

---

## 🪜 Steps (each has its own done-rule — that's what Loop Training Mode gates on)

**1 · Frame.** Confirm the client and which ideas are on the board; restate the KEEP/DROP contract for this run.
  - *Done-rule:* client + idea set named, and the KEEP/DROP contract acknowledged in writing.

**2 · Build.** Produce (or refresh) the prototypes as self-contained files in `app/prototypes/strategy-companion-p*.html`. Each = a distinct visual framework for the ideas HOME + one shared bare-bones idea page. 16-year-old English throughout.
  - *Done-rule:* every prototype renders a HOME and an idea page, shows the 4 bare-bones sections in order with the "up next" deferral, carries the warm sidebar + top-right change toast, and contains **none** of the DROP list. No console errors.

**3 · Score.** Run a panel of **5 simulated non-technical founders & sales leaders** (distinct personas — e.g. first-time founder, VP sales, agency operator, skeptical COO, brand-led founder). Each scores every prototype 1–10 on **actionable insights**, **easy to digest**, **beauty of the design**, plus one favourite and the single fix to reach 9.
  - *Done-rule:* all 5 reviewers have returned all 3 scores for all prototypes, recorded in the session file.

**4 · Polish.** Pick the front-runner (highest panel average, or my override). Apply the single highest-impact fix each reviewer named; re-score just the winner.
  - *Done-rule (THE BAR):* the chosen prototype scores **≥ 9/10 from every reviewer on all three** — actionable, digest, beauty. Below the bar → fix → re-score (retry cap 3).

**5 · Ship.** Merge the winner into `~/.claude/skills/lilly-strategy/wizard-template.html`, rebuild with `python3 ~/.claude/skills/wizard-launch-lab/wizard-lab/build_live.py ~/navreo-signals/app/strategy.html`, verify it hydrates from a real run and the top-right change toast fires on a chat update, then commit + push.
  - *Done-rule:* prod `strategy.html` renders the winning design, a chat-driven update reflects live with the toast, KEEP behaviors intact, DROP features gone, pushed.

**6 · Record.** Save the session record and update memory (winner, score, live commit).
  - *Done-rule:* session file + memory written.

---

## ✅ Overall done-rule

Done when the shipped strategy companion **scores 9/10 from 5 non-technical founders & sales leaders on all three — actionable insights, easy to digest, beauty of the design — AND is live on `strategy.html`** with the KEEP behaviors intact and every DROP feature gone. Anything less is not done; anything past 3 failed attempts on a step stops and reports the blocker.

## 🧭 Runbook quick-reference
- Prototypes: `~/navreo-signals/app/prototypes/strategy-companion-p{1..5}.html`
- Live page: `~/navreo-signals/app/strategy.html` (built from `lilly-strategy/wizard-template.html`)
- Idea data shape: `app/data/strategy_cache.json` (reach = `dms_total`; `estimated`/`approx` flags = real vs guessed)
- Chat mirror: page polls `GET /api/strategy/run`; chat POSTs the run — see memory `strategy-board-live-on-tool`.
