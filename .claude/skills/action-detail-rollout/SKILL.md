---
name: action-detail-rollout
description: Static orchestration skill that ports the mailboxes.html "Details & who's affected" formatting (If you approve / If you skip, exact before-after preview, affected-inboxes table, Show-technical-detail fold) into the existing action blocks on notifications.html and deliverability.html — only where the pattern is genuinely relevant. Verified two ways — a 5-GTME simulated panel must average 8/10+ on simplicity/usability, and a 20-use-case Supabase data-capture audit. One fixed step list with checkable done-rules, retry cap, and a Loop Training Mode toggle (ON by default). Use when the user says "run the action detail rollout", "format the notification/deliverability actions", or "/action-detail-rollout".
---

# action-detail-rollout

Port the **"Details & who's affected"** pattern from `mailboxes.html` into the action rows of **notifications.html** and **deliverability.html**. Goal: **every action is easy to rationalise — its impact, and exactly what problem exists — in a simple, intuitive way.** Static loop: fixed steps, each with a done-rule, Loop Training Mode controls pausing.

Files (deploy repo, serves the live Render URLs): `~/navreo-signals/app/notifications.html`, `~/navreo-signals/app/deliverability.html` + `deliverability-tab.js`. Reference design: `~/navreo-signals/app/mailboxes.html` (det-block pattern, lines ~544–562, CSS ~134).

---

## ⚙️ LOOP TRAINING MODE  →  **OFF**

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

An action row anywhere in the app should answer, at a glance: **what happens if I approve, what happens if I skip, exactly who/what is affected, and (folded away) the raw technical signal.** The mailboxes page already nails this. Port it — **only where absolutely relevant**: an action with no affected-entity list or no meaningful approve/skip fork keeps its current compact row. Don't force the pattern onto informational rows.

**The reference pattern (copy, don't reinvent) — from `mailboxes.html`:**
1. Two-column **"If you approve" / "If you skip"** consequence blocks (`det-block`, line ~557–558).
2. Optional **exact preview** — before/after diff or the exact email draft (line ~544–546).
3. **"Your affected [inboxes/campaigns/domains] — all N shown"** table, with search when >6 rows (~561–562, search wiring ~616).
4. **`<details>` "Show technical detail (exact action & raw signal)"** fold with What-Lilly-will-do + Why-this-fired-raw (~552–554).

Reuse the `det-block` / `disclose` / `tbl` CSS and glossaryize() approach; put shared CSS where both pages can use it (navreo.css or copied blocks with the page's prefix convention — `deliverability-tab.js` prefixes with `.dlv-`).

---

## THE STEPS

### Step 1 — Map which actions get the pattern
- List every action row on both pages: `actionBlockHTML(n)` (notifications.html:938) renders Section-7 optimiser actions; deliverability renders blacklist/advice actions (deliverability-tab.js, e.g. "PAUSE + FIX" rows ~419–424, ~621).
- For each, decide **pattern / keep-compact**, with a one-line reason (relevant = has an approve/skip fork AND/OR an affected-entity list).
- Done-rule: a written mapping table exists in the step output covering every action type on both pages; no action type is unclassified.

### Step 2 — Notifications: apply the pattern
- Extend `actionBlockHTML(n)` so each pattern-classified action expands (existing expander conventions — `tier-expander` / `sectionExpandState`) to show: If-approve / If-skip columns, the affected-entities table (campaigns/mailboxes/leads with search >6 rows), and the technical-detail fold with the raw optimiser signal.
- Plain-English consequence copy, glossary tooltips on jargon (reuse the page's existing tooltip/glossary approach). No em-dashes in copy.
- Keep-compact actions unchanged.
- Done-rule: every pattern-classified notification action renders all applicable blocks in the live page; `preview_snapshot` shows "If you approve" / "If you skip" and an affected table on at least one real action; no console errors; keep-compact rows visually unchanged.

### Step 3 — Deliverability: apply the pattern
- Same treatment in `deliverability-tab.js` for pattern-classified actions (blacklist PAUSE+FIX / REPLACE advice, rest-batch actions, delisting): If-approve / If-skip, affected mailboxes/domains table, technical fold showing the raw signal (blocklist name, bounce data).
- Respect the `.dlv-` CSS prefix convention (deliverability-tab.js ~897–899).
- Done-rule: every pattern-classified deliverability action renders the applicable blocks live; snapshot proof as in Step 2; no console errors.

### Step 4 — GTME panel verification (≥8/10 average)
- Spawn **5 parallel simulated GTME testers** (Agent tool, `model: sonnet`). Each gets a distinct persona (new hire, power user, skim-reader, sceptic, mobile-width user) and the rendered page content via `preview_snapshot` text (**never** preview_click UX sims — read-based evaluation only).
- Each rates 1–10 on: "Can I tell what each action does, what happens if I skip it, and who's affected — without thinking hard?" plus top-3 friction points.
- Done-rule: average across 5 testers **≥ 8.0/10** for BOTH pages. If below: fix the top friction points, re-run the panel (counts as a retry, cap 3).

### Step 5 — Supabase data-capture audit (20 use-cases)
- Ideate **20 random, realistic use-cases** on the platform (spread across notifications, deliverability, mailboxes actions: approve a fix, skip, flag, undo, send a draft, pause a campaign, re-enable warmup, delist a domain, etc.).
- For each, check against the live Supabase schema (project `fnykldftbkrccihdjayl`: `list_tables` + relevant table columns, e.g. `optimiser_notifications`) whether the action **would be recorded** in the database — YES (table.column), or NO (gap).
- Done-rule: a 20-row table exists — use-case · would-be-recorded YES/NO · evidence (table.column or "no table"). Gaps are **reported, not fixed** (surface them as recommended follow-ups; wiring writes is out of scope).

### Step 6 — Ship
- Commit + push `~/navreo-signals` so Render deploys; confirm both live URLs render the new formatting.
- Diff-check against the iCloud copy (`app/notifications.html` exists in both) and note any drift in the final report — don't silently overwrite the iCloud side.
- Done-rule: `git log` shows the pushed commit; a WebFetch/preview of both live URLs shows the new blocks; drift note written.

---

## HOW TO RUN

1. Read the mode line above. If **ON**, one step at a time, stop for approval after each; skip steps whose done-rule already passes. If **OFF**, run all six in order.
2. For each step: edit → check the done-rule (greps + `preview_snapshot` against the locally served page) → retry up to 3× on failure → mark FAILED and continue.
3. Judgment (pattern mapping, copy, panel scoring synthesis) stays with the orchestrator; execution subagents run on `model: sonnet`.

## OVERALL DONE-RULE

- Pattern applied to every relevant action on both pages, nothing forced onto irrelevant rows (Steps 1–3).
- GTME panel average **≥ 8/10** on both pages (Step 4).
- 20-use-case Supabase audit table delivered with gaps flagged (Step 5).
- Live on Render, iCloud drift noted (Step 6).
- Final report: one line per step — DONE / SKIPPED (already passed) / FAILED (with reason) — plus the panel scores and the audit table.
