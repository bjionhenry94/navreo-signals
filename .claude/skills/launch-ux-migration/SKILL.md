---
name: launch-ux-migration
description: Static orchestration skill that migrates Navreo's campaign-launch UX to the new
  consolidated system — builds the single-view Lilly-strategy walkthrough (no idea-tabbing),
  wires all 7 tier-1 use cases (list-build, TAM-map, top-up, campaign-shell, copy, recontact,
  variant-swap) to their ruled surfaces, retires the old routes that interfere, and proves the
  whole experience with a 5-tester GTME/Account-Strategist panel at 9/10+ simplicity. One fixed
  step list, each step with a checkable done-rule, retry caps, and a Loop Training Mode toggle.
  Use when the user says "run the launch UX migration", "consolidate the tier-1 launch flows",
  "migrate the campaign launch experience", or "/launch-ux-migration".
---

# Launch UX Migration

Weeks of new-workflow building now converge: one consolidated launch experience for the team,
with the 7 tier-1 daily use cases each routed to its ruled surface, a new **single-view
Lilly-strategy walkthrough** for the single-campaign cases, and every old route that would
interfere retired. Static loop — fixed steps, each has a done-rule, Training Mode controls
the pauses.

## ⚙ Loop Training Mode: **OFF**   ← flip this line to ON to pause at every step

**ON:** pause at EVERY step boundary and wait for the user's explicit approval before
continuing. Before starting a step, check its done-rule first — if it already passes, report
"Step N already passes, skipping" and move on. Only re-run steps whose done-rule fails. Show
what you're about to do before doing it.

**OFF:** run all steps end-to-end with no pauses. The done-rule checks, skip-if-passing
behaviour, and retry caps stay exactly the same — only the pauses go.

**Retry cap (both modes):** each step retries **max 3** times against its done-rule. The tester
panel (Step 7) retries **max 4 full rounds**. On cap-hit: record the step as FAILED with the
reason, continue to the next step if it doesn't depend on the failed one, and surface every
FAILED step in the final report. Never silently exceed the cap. Never declare done on a cap-hit.

## 🔒 Hard gates (both modes, non-negotiable)

- **Spend gate:** dummy-chat scenarios and panel rounds run on fixtures/dry-runs — **zero paid
  provider calls** (AI-ARK, Prospeo, Smartlead writes, ListMint, MillionVerifier). Live probes
  only where a done-rule demands one, **≤10 provider credits total** for the whole loop.
- **No-send gate:** nothing this loop does may activate a campaign or send anything. All
  campaign creation stays DRAFT; all uploads stay behind lilly-upload-gate.
- **Standing-artifact gate:** the multi-idea wizard's standing URL
  (`https://claude.ai/code/artifact/5d6e5fdd-69d8-48f2-be8e-bec57da7b51f`)
  is never repointed or overwritten by the single-view variant — the single view is a NEW
  sibling template + its own artifact flow. `wizard-template.html` is never edited in place.
- **Repo gate:** any tool-side edit happens in the deploy repo `~/navreo-signals` only — never
  the iCloud copy (memory `signals-deploy-repo`: iCloud REVERTS edits). This loop expects
  **zero tool-side edits** (Step 1 verifies the tool surfaces already exist); a gap found live
  is reported and only built after explicit approval.
- **Skill-retirement gate:** old routes are retired by moving trigger coverage (descriptions/
  trigger phrases), never by deleting skill folders. Anything retired is listed in the report.

## Goal

The team launches campaigns one way. Concretely:

1. **Single-view Lilly-strategy exists**: same walkthrough as the wizard, minus the idea-list/
   tab-switching — used whenever exactly ONE campaign idea is in play. Multi-idea requests still
   get the existing multi-campaign wizard.
2. **All 7 tier-1 use cases route per the rulings** (matrix below) with the old interfering
   routes retired.
3. **A 5-tester panel (GTMEs + Account Strategists) scores the experience ≥9/10 for simplicity**
   across dummy-chat scenarios covering all 7 use cases.

**THE DONE-RULE (single source of truth):**
> The single-view walkthrough renders and walks end-to-end in a real browser; every one of the
> 7 use cases demonstrably routes to its ruled surface in a dummy chat; the old routes no longer
> trigger; the panel averages **≥9/10 simplicity with no tester below 8 and no scenario below 8**;
> zero paid calls made by any simulation. All of it, or it isn't done. On the round cap, stop
> and report the gap honestly.

## The use-case routing matrix (the rulings — user, 2026-07-26)

| # | Use case | Surface ruling |
|---|---|---|
| 1 | Build a prospect list for a niche ("build me a list of freight forwarders") | Launch **single-view Lilly-strategy** (no tabbing) → campaign-launch walkthrough. Multi-idea view ONLY if the user asks for multiple ideas. |
| 2 | Map a TAM for a segment | **No UI at map time.** ALWAYS offer to draft the campaign; on yes → campaign added to the tool with pool/targeting saved via the **pull-more** feature in Sources → then the single-view walkthrough. |
| 3 | Top up a campaign running dry | **Upload gate opens within the chat.** After upload: link to the tool's **Leads** page + say a record of the upload was added there (if only part of the pool was uploaded, explain that too). |
| 4 | Build a campaign shell (Smartlead/Instantly/Lemlist) | **Single-view walkthrough** (no other campaigns to show). On successful upload → open the campaign in the tool on its **Overview** page. |
| 5 | Write cold email copy | **Chat only** (lilly-copywriter). No UI. |
| 6 | Recontact campaign (combine + dedup old) | **No own UI**, but on build → open the campaign inside the tool from the chat so the user sees it ready. |
| 7 | Replace/swap failing email variants | **Chat only** (lilly-optimiser). No UI. |

## Ground truth (verified 2026-07-26 — re-verify in Step 1, line numbers/sizes drift)

- **Multi-idea wizard:** `~/.claude/skills/lilly-strategy/wizard-template.html` (242KB,
  2026-07-19) with idea-list/`selectIdea` switching (grep-confirmed). Hydration is
  engine-only: `lilly-strategy/engine/engine.py` `validate` → `hydrate` (never hand-splice;
  template never edited in place — copy to scratchpad first). Standing artifact URL above;
  "chat carries no results" ruling (Bjion, 2026-07-19) applies to strategy runs.
- **Deploy repo** `~/navreo-signals`: clean vs origin/main (only untracked protos), push =
  Render deploy of navreo-signals.onrender.com. `app/campaigns.html` already has the Leads tab
  (24 `leads-tab` markers) and pull-more markers (4) live. Login wall on app pages — user
  supplies session cookie at live-proof time (memory `setter-live-verify-auth`).
- **Upload gate:** `lilly-upload-gate` is the forced pre-upload QA (ListMint/MV verify,
  collision sweep, HTML report, Supabase audit rows). Ruling #3 above means the gate's
  report/approve moment must surface **in the chat flow**, not as a detour the user hunts for.
- **Recontact:** `lilly-recontact` inline route proven 2026-07-23 (3274582 → draft 3709470);
  endpoints `/api/recontact/scan|buckets|create`; replaces-predecessor rule; draft only.
- **Chat-only skills:** `lilly-copywriter` (copy), `lilly-optimiser` (variant swaps).
- **Overlapping/interfering routes to audit in Step 1:** `lilly-idea-to-launch` (rival
  walkthrough chain), `lilly-strategy`'s always-launch-the-wizard rule (conflicts with ruling
  #2's "no UI at map time"), `lilly-tam` hand-off wording, `tier1-*` skills' leftover framing.
- **Panel precedent:** `sources-pull-more-ship` ran a 5-account-strategist panel at 9/10+ —
  reuse that shape.
- **Unknowns → resolve in Step 1:** does the wizard template hydrate cleanly with ONE idea
  (or does the idea-list rail break)? Exact trigger-phrase collisions between lilly-strategy /
  lilly-idea-to-launch / lilly-tam. Whether "pull-more" as shipped saves pool/targeting the
  way ruling #2 needs, and whether the Leads page shows upload records.

## Steps

### Step 1 — Re-verify ground truth + route audit
Confirm every Ground-truth bullet against current files/repo. Resolve the unknowns. Build the
**route audit**: for each of the 7 use cases, (a) what triggers today and where it lands,
(b) the ruled surface from the matrix, (c) the exact edits needed (skill file + section), and
(d) every old route that would interfere, with its retirement action. Write to
`launch-ux-migration/ROUTE-AUDIT.md` (this skill's folder).
- **Done-rule:** ROUTE-AUDIT.md has all 7 rows complete with (a)–(d), the single-idea-hydration
  question answered with evidence (a test hydrate or grep), and the pull-more/Leads-page
  capability verdicts stated (EXISTS / GAP — a GAP is reported, not silently built).

### Step 2 — Build the single-view Lilly-strategy walkthrough
Create `lilly-strategy/wizard-single-template.html` from a COPY of the multi-idea template:
same walkthrough stages, styling, and Navreo voice — idea-list/tab-switching removed, one
campaign front and centre. Wire engine hydration for it (reuse `hydrate` with a
single-idea run.json or add a `--single` path). Publish a hydrated sample to a NEW artifact
(never the standing multi-idea URL).
- **Done-rule:** the hydrated single-view renders in a real browser: zero console errors, NO
  idea-list/tab controls present (grep + visual), all walkthrough stages reachable by click,
  engine round-trip works on a single-idea run.json. Screenshot captured.

### Step 3 — Wire the routing (skills consolidated to the matrix)
Edit the skill files per ROUTE-AUDIT.md so each use case lands on its ruled surface:
lilly-strategy gains the single-vs-multi fork (single idea → single view; "multiple ideas"
asked → existing wizard) and drops always-wizard for TAM-map requests; TAM-map flow gains the
always-offer-to-draft step (ruling #2); top-up flow opens the upload gate in-chat and ends with
the Leads-page link + partial-pool explanation (ruling #3); campaign-shell ends by opening the
campaign Overview in the tool (ruling #4); recontact ends by opening the campaign in the tool
(ruling #6); copy and variant-swap confirmed chat-only (rulings #5, #7). Retire interfering
routes per the retirement gate.
- **Done-rule:** every (c) edit from ROUTE-AUDIT.md is applied and grep-verifiable in the named
  skill file; every (d) retirement applied; no deleted skill folders; a dry re-read of each
  edited description routes the matrix's trigger phrases to the right skill with no collision.

### Step 4 — Dummy-chat scenario pack
Write `launch-ux-migration/SCENARIOS.md`: at least one realistic dummy chat per use case (7+),
including the Asad-style "build me a list of freight forwarders / MSPs / commercial roofers",
a multi-idea ask (to prove the fork), a partial-pool top-up, and a TAM-map where the user
declines the draft offer (to prove no UI launches). Each scenario names its expected route,
expected surfaces opened, and expected closing message shape.
- **Done-rule:** SCENARIOS.md covers all 7 use cases + the 3 named edge scenarios, each with
  expected route/surface/closing-message — no scenario blank.

### Step 5 — Walk every scenario (zero-spend)
Execute each scenario as a dry-run against the edited skills: follow the routed skill's steps
on fixtures, render the surfaces it would open (single-view artifact, upload-gate report, tool
pages via staging/screenshots), and capture the actual closing messages.
- **Done-rule:** per scenario: routed skill matches expected, surfaces opened match expected
  (rendered evidence for each UI surface), closing message captured verbatim, and **zero paid
  provider calls** made (state the checks used). Lettered per scenario; partial passes visible.

### Step 6 — Fix the misses
For every Step-5 miss, fix the skill wiring or messaging and re-walk just the failed scenarios.
- **Done-rule:** all scenarios pass Step 5's rule; the fix list is recorded (what changed, where).

### Step 7 — 5-tester panel (GTMEs + Account Strategists), iterate to 9/10+
Define 5 testers: 2 GTM Engineers, 3 Account Strategists, mixed seniority. Each tester runs
every scenario from the pack and scores simplicity 1–10 with a one-line reason. Iterate the
messaging/flow on the low scores and re-run — **max 4 rounds**. Record everything in
`launch-ux-migration/PANEL-SCORECARD.md`.
- **Done-rule:** scorecard shows (a) every tester ran every scenario, (b) **average ≥9/10**,
  (c) **no tester below 8 and no scenario below 8**, (d) per-round deltas recorded (what
  changed between rounds). Any miss is a named FAILED line, never rounded up. Cap-hit at
  round 4 = FAILED with the gap named.

### Step 8 — Hand-off report to Bjion
Assemble: the routing matrix as shipped, the single-view artifact link + screenshots, the
retired-routes list, the scenario evidence, and the panel scorecard — the launch-to-team pack.
- **Done-rule:** one hand-off message links all five artifacts and states the final numbers
  (routes migrated, routes retired, panel average, lowest tester/scenario, credits spent vs
  the ≤10 cap, any FAILED items).

## Final report (always, both modes)

One summary: steps passed / skipped / FAILED; the 7 routes with before → after; retired routes;
the single-view artifact URL; panel numbers (average, per-tester lows, rounds used); total
provider credits spent (must be ≤10); artifact paths (ROUTE-AUDIT.md, SCENARIOS.md,
PANEL-SCORECARD.md, screenshots); anything deferred (e.g. a tool-side GAP awaiting approval).

## Hard don'ts

- Never edit `wizard-template.html` in place, repoint the standing multi-idea artifact URL, or
  publish the single-view to it — the single view is a sibling template with its own artifact.
- Never launch the multi-idea wizard for a single-campaign request, and never skip the
  offer-to-draft on a TAM map — the matrix rulings are law.
- Never let a simulation or panel round make a paid provider call; never exceed 10 credits total.
- Never activate a campaign, send anything, or bypass lilly-upload-gate on any upload path.
- Never edit the iCloud app copy; never make an unapproved tool-side change — GAPs are reported.
- Never retire a route by deleting a skill folder — trigger coverage moves, files stay.
- Never round the panel up: any tester or scenario under bar is a FAILED line item, and a
  round-cap hit is reported as the gap, not as done.
- Never exceed a retry cap (3/step, 4 panel rounds) or report done while any done-rule fails.
