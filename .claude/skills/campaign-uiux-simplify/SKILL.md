---
name: campaign-uiux-simplify
description: Static orchestration skill that performs the UI/UX simplification pass on the Navreo signals tool (app/campaigns.html + app/server.py) from the "Changes" brief — simplify the goal page, fix the Sources tab, add Add/Generate-more buttons across the wizards, trim the Hiring + Content-monitoring wizards, gate campaign creation on wizard completion, hide Preview tabs — and remove the now-orphaned backend for anything the UI drops. One fixed step list, each with a checkable done-rule, plus a Loop Training Mode toggle. Use when the user says "run the campaign UI/UX updates", "do the Changes brief", "simplify the campaign UX", or "/campaign-uiux-simplify".
---

# campaign-uiux-simplify

Perform the "Changes" UI/UX pass on the signals tool. Goal: **improve the simplicity and continuity of the user experience.** Static loop — the steps below are fixed, each has a done-rule, and Loop Training Mode controls whether you pause between them.

Files: `app/campaigns.html` (all UI) and `app/server.py` (backend to prune). Verify visuals against the running app at `http://localhost:7901/app/campaigns.html`.

---

## ⚙️ LOOP TRAINING MODE  →  **OFF** (default)

Flip it by editing this one line:

    LOOP_TRAINING_MODE = OFF       # ON = approve every step · OFF = run autonomous

**When ON**
- Pause at the end of **every** step and wait for my explicit approval before starting the next.
- Before running a step, check its done-rule first. **If it already passes, skip it** — say so and move on.
- Only (re-)run steps that fail their done-rule.
- Retry cap applies (see below). Never loop a step forever.

**When OFF**
- Run all steps autonomously, no pauses.
- Still check every step's done-rule and still honour the retry cap. Report at the end, not between steps.

**Retry cap (both modes):** any single step retries **max 3** times against its done-rule. On cap-hit, stop that step, record it as FAILED with the reason, keep going, and surface it in the final report. Never silently exceed.

---

## THE GOAL

The signals tool should feel simple and continuous: fewer decisions per screen, every list field ideatable with **Add** + **Generate more**, no dead-end options, and no half-built campaigns left behind. Done means **every UI change below is in place AND the backend for anything removed is gone too** — no orphaned handlers, params, or dead branches.

**Convention (reuse, don't reinvent):** "Generate more" and "Add" already exist on some fields (`campaigns.html` ~lines 2128 / 2304, and the `hiring-roles-autogen` skill shipped the pattern). Copy that exact component + its `/api/*` call for every new field rather than writing a new one. "Suggest more" is the *same* control with different label text.

---

## THE STEPS

### Step 1 — Simplify the "What's the goal of this campaign?" page
- Collapse to **two sections only**:
  1. **Suggested ideas** — the existing "Suggest ideas" output, but shown immediately **without** the user first defining a goal. Ideas must exclude any that duplicate — or are close relatives of — an already-active signal idea.
  2. **A single launch button** row for the **Hiring** and **Engagement** wizards.
- Remove the goal-input step that used to gate the suggestions.
- Done-rule: the page renders both sections with no goal field; suggestions load on open; a suggested idea already live as an active signal does not appear. Anchor: `campaigns.html:1620` (`goal of this campaign`), `:1632` (`Suggest ideas`).

### Step 2 — Fix the "Sources" tab on Campaign pages
- Clicking the **Hiring** or **Engagement** signal always opens the relevant wizard, but the resulting sources/ideas are added to the **incumbent** campaign (not a new one).
- Remove **"Find me more high-intent leads"** from the "Add Source" section entirely.
- Done-rule: `grep "Find me more high-intent" campaigns.html` returns nothing; opening Hiring/Engagement from an existing campaign's Sources tab writes back to that same campaign id. Anchor: `campaigns.html:401`.

### Step 3 — New Campaigns: remove "Reuse last setup"
- Delete the **"Reuse last setup"** button(s).
- Done-rule: `grep "Reuse last setup" campaigns.html` returns nothing; the new-campaign entry still works without it. Anchor: `campaigns.html:1610`.

### Step 4 — "Generate new ideas" wizard: complete the Add / Generate-more set
- **"Who do we email at these companies?"** — add the **Generate more** button.
- **"What kind of companies are you targeting"** → Industry section — add **Suggest more** (same control as Generate more, different label).
- **Company types** — add **Add** + **Generate more**.
- **Location** — add **Add** + **Generate more**.
- Done-rule: all four fields render both controls, wired to the existing generate/suggest endpoint; clicking each widens the field's list. Anchors: `campaigns.html:1641` (`Who do we email`), Industry / Company types / Location sections in the same wizard.

### Step 5 — Hiring wizard: trim + relabel
- Replace **"Exclude posts containing"** free-text field with **Add** + **Generate more** buttons.
- **Countries** — add **Add** + **Generate more**.
- Remove **"Posted within"** entirely. Instead: the pull runs **daily looking back 1 day**, and the shown estimate is computed from the **last-30-day pool**. Update the estimate logic accordingly.
- Rename **"New leads per day"** → **"Max leads per day"** (both occurrences).
- **Back** button now **closes the dialog**.
- Move **"Save for later"** to a footer button next to **Cancel**, and **remove it from the form body**.
- Done-rule: `grep "Posted within" campaigns.html` returns nothing; `grep "New leads per day" campaigns.html` returns nothing (replaced by "Max leads per day"); Exclude-posts + Countries show Add/Generate-more; Back closes; Save-for-later lives only in the footer. Anchors: `:2260` `:2262` `:2266`.

### Step 6 — Content monitoring wizard: trim + complete
- Remove the **"Don't have the links yet? Use 💾 Save what I've got…"** helper text.
- In **"Post topics that count"**: remove the **"Anything else"** free-text field but **keep** the Add + Generate-more buttons.
- **Countries** — add **Add more** + **Generate more**.
- **Companies to avoid** — add **suggestions** plus **Add** + **Generate more** buttons.
- Move **"Save for later"** to a footer button next to **Cancel**, and **remove it from the form body**.
- Done-rule: `grep "Anything else" campaigns.html` returns nothing in this wizard; the "Save what I've got" helper text is gone; Countries + Companies-to-avoid show Add/Generate-more with live suggestions; Save-for-later only in footer. Anchors: `:2300` `:2305`.

### Step 7 — General: gate creation + hide Preview tabs
- A new campaign is **only created once the wizard is fully completed** (no persisted campaign on cancel/close/back-out mid-wizard).
- **Hide all "Preview" tabs** on the Campaign pages for now (hide, don't delete the code).
- Done-rule: cancelling or backing out of the wizard leaves **no** new campaign row (check `server.py` create path + local JSON); no "Preview" tab is visible on any Campaign page. Anchors: `campaigns.html` Preview tabs at `:247 :413 :730 :740 :1578`.

### Step 8 — Backend cleanup (remove what the UI dropped)
For every element removed above, delete its now-orphaned backend so nothing dangles:
- `server.py` handler/route + params for **"Find me more high-intent leads"** (Step 2).
- **"Reuse last setup"** persistence/restore logic (Step 3).
- **"Posted within"** param + its old estimate query; replace with daily-1-day pull + 30-day-pool estimate (Step 5).
- Any **"Save what I've got" / save-for-later** form-field plumbing that's now footer-only (Steps 5–6) — keep the save endpoint, drop the removed field wiring.
- The mid-wizard **campaign pre-create** write, now that creation is gated on completion (Step 7).
- Done-rule: `grep -rn "high-intent\|reuse_last\|posted_within\|reuse last setup" app/server.py` returns nothing relevant; no route references a removed UI element; server still boots and the app loads clean.

---

## HOW TO RUN

1. Read the mode line above. If **ON**, work one step at a time and stop for approval after each; skip any step whose done-rule already passes. If **OFF**, run all eight in order without pausing.
2. For each step: make the edits in `campaigns.html` (and `server.py` for Step 8), then check the done-rule — grep for the string assertions and, for visual steps, take a `preview_snapshot` against `http://localhost:7901/app/campaigns.html`. Retry up to 3× on failure, then mark FAILED and continue.
3. After a `campaigns.html`/`server.py` change that's browser-observable, reload the preview and check console + snapshot before calling the step done.

## OVERALL DONE-RULE

- **All UI changes** (Steps 1–7) are in place and verified in the running app.
- **All orphaned backend** (Step 8) for removed UI is gone; server boots, app loads with no console errors.
- Final report: one line per step — DONE / SKIPPED (already passed) / FAILED (with reason).
