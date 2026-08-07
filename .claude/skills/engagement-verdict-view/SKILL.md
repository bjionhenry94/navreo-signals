---
name: engagement-verdict-view
description: Orchestration skill that adds a qualified/unqualified verdict view to the engagement Source wrapper in the Navreo signals tool (srcDetail in app/campaigns.html + app/server.py). Qualified is the default view; a segmented toggle reveals who was rejected and why, in plain English, straight from Supabase engagement_events. Ships only when a panel of 3 simulated user testers (local technical ability) scores the sort-qualified-from-unqualified experience 8/10 or above. Static plan with pre-baked done-rules, retry caps, and a Loop Training Mode toggle. Trigger on: 'build the verdict view', 'show unqualified engagers in the source', 'run engagement-verdict-view', '/engagement-verdict-view'.
---

# Engagement Verdict View

## ⚙️ Loop Training Mode — TOGGLE HERE

```
LOOP_TRAINING_MODE: OFF
```

Flip the value above (`ON` / `OFF`). Read it at the start of every run.

**When ON (default):**
- PAUSE at every step boundary. Show the step's plan + done-rule, wait for
  explicit approval ("go" / "approve") before executing.
- Before executing any step, TEST its done-rule first. If it already passes,
  SKIP it (report "Step N already passes — skipped").
- Only re-run steps whose done-rule FAILS. Never re-run a passing step.
- Retry cap: max 2 re-runs per step (3 attempts total). On exhaustion, HALT
  and report the failing done-rule verbatim with evidence.

**When OFF:** run autonomously, no pauses, but KEEP the done-rule checks,
skip-if-passing, and the retry cap.

Either mode: a done-rule passes only with observed evidence (API responses,
DOM snapshots, screenshots, recorded scores) — never on faith.

---

## Goal

Inside an engagement source's expanded row (the Source wrapper, `srcDetail`
in app/campaigns.html), the user can see at a glance who was QUALIFIED and
who was NOT, with qualified as the default view, and understand each
rejection without decoding jargon.

**Overall done-rule:** the verdict view is live on localhost:7901; qualified
renders by default; the toggle reveals unqualified engagers with plain-English
reasons; a 3-tester panel (local technical ability) averages ≥8/10 on ease of
sorting qualified from unqualified, with every tester completing the task.

## Context (verified 2026-07-05, this repo)

- Qualified engagers already render: `src.prospects` in `srcDetail`
  (campaigns.html ~line 990) — keep that as the default view, do not rebuild.
- Unqualified engagers exist ONLY in Supabase `engagement_events`
  (status OFF_BRIEF / BORDERLINE, verdict + reason in the `qualification`
  jsonb) — the tool has no API or UI for them yet.
- Live data to build against: source `draft-f383570e` (46-profile Navreo
  campaign, cdraft-1a9ba7ce) already holds OFF_BRIEF rows with string-gate
  reasons like `loc=India` and `co=size 1, outside 11-200`.
- Server helpers: `sb()` for PostgREST reads, ROUTES dict at the bottom of
  app/server.py, GET routes in `Handler.do_GET`.
- UX-sim precedent: app/ux_sim.py methodology. HARD RULE from memory: never
  use preview_click to simulate testers — testers are simulated as fresh-eyes
  LLM evaluations of real snapshots/screenshots, not scripted clicks.

---

## Steps

### Step 1 — Verdict API

Add GET `/api/engagement-verdicts?source_id=<id>&verdict=<qualified|
unqualified>` to server.py's `do_GET`: reads `engagement_events` via `sb()`,
returns `{count, rows:[{name, title, company, country, post_author, status,
reason, method, received_at}]}`. `unqualified` = OFF_BRIEF + BORDERLINE
(BORDERLINE labelled as "needs review"). Order newest first, limit 200.
Reasons are translated server-side to plain English:
`loc=India` → "Outside target countries (India)";
`co=size 1, outside 11-200` → "Company too small (1 person)";
LLM reasons pass through as-is (already sentences).

**Done-rule:** curl for `draft-f383570e` returns the live OFF_BRIEF rows with
translated reasons and a correct count; unknown source returns
`{count: 0, rows: []}` not an error.

### Step 2 — Verdict toggle in the Source wrapper

In `srcDetail` for engagement sources only: a segmented control above the
people list — `✓ Qualified (n)` | `✕ Not qualified (n)` — qualified
selected by default (the existing prospects list, untouched). Selecting
"Not qualified" lazy-fetches Step 1's API and renders compact rows: name,
title @ company, country, whose post they engaged, and a reason pill in
plain English (BORDERLINE rows get an amber "needs review" pill instead of
red). Counts load with the panel; empty states say what they mean ("Nobody
rejected yet - rejections appear here with the reason"). No layout shift for
non-engagement sources.

**Done-rule:** in the browser on `#cdraft-1a9ba7ce`: the source opens showing
qualified by default; clicking the toggle shows the live rejected engagers
with readable reasons and correct counts; hiring sources render exactly as
before; zero console errors.

### Step 3 — Tester panel (3 simulated users, local technical ability)

Run the ux_sim methodology (NOT preview_click): capture the real rendered
state (snapshot + screenshot of both views), then 3 independent fresh-eyes
tester personas — e.g. a CSM who lives in spreadsheets, a founder who skims,
a VA following instructions — each given the cold task: "Open the source.
Who qualified? Who didn't, and why was [specific person] rejected?" Each
tester answers from the captured UI alone and scores ease-of-sorting /10
with a one-line gripe. Record scores + gripes to
`~/.claude/skills/engagement-verdict-view/state/panel.json`.

**Done-rule:** all 3 testers complete the task correctly (right names, right
reason) AND the average score is ≥8/10. If not: fix the top gripe, re-run
the panel (this consumes the step's retries).

### Step 4 — Ship check

Restart the launchd server so 7901 serves the final code, re-verify Step 2's
done-rule once on the live port, and surface the panel scores + a screenshot
in the final report.

**Done-rule:** live 7901 passes the Step 2 checks and the recorded panel
average is ≥8/10. This passing = overall done-rule met.

---

## Retry + halt protocol

- 1 initial attempt + 2 retries per step; every retry must change something
  (a fix, not a re-roll). Panel re-runs after a UI fix are legitimate
  retries; re-rolling the panel on unchanged UI to fish for scores is NOT.
- On halt: report the step, failing clause, evidence (scores + gripes
  verbatim for Step 3), and the single most likely fix.

## Guardrails

- Qualified stays the default view — never open on rejections.
- Never simulate testers with preview_click; fresh-eyes evaluation of real
  captures only.
- Plain English everywhere the user reads (no `loc=`, `co=`, `OFF_BRIEF`).
- Don't touch the existing prospects rendering or push/verdict buttons.
- No em-dashes in any user-facing copy.
