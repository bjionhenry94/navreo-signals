---
name: pull-more-uxlab
description: Orchestration loop that builds FIVE distinct prototypes improving the experience of pulling MORE leads from an existing source pool into a campaign (the shipped Sources-tab "Pull more" panel is the baseline). Prototypes are self-contained HTML in the signals design system, fed by REAL pool numbers but never wired to the live pull endpoint (no credit spend). Runs a 5-tester non-technical panel scoring Simplicity, Minimalist, and Ability-to-complete-the-task - does not finish until EVERY prototype scores 8/10+ on all three. Ends with an index page and the user's pick; ships nothing. Trigger: "run the pull-more uxlab", "prototype the pull-more experience", "/pull-more-uxlab".
---

# Pull-more UX lab

## ⚙ Loop Training Mode: **ON**   ← flip this line to OFF to run autonomously

**ON (default):** pause at EVERY step boundary and wait for the user's explicit approval
before continuing. Before starting a step, check its done-rule first - if it already
passes, report "Step N already passes, skipping" and move to the next pause. Only re-run
steps whose done-rule fails. Show what you're about to do before doing it.

**OFF:** run all steps end-to-end with no pauses. The done-rule checks, skip-if-passing
behaviour, and retry caps stay exactly the same - only the pauses go.

**Retry cap (both modes):** each step retries **max 3** times against its done-rule.
On cap-hit: record the step FAILED with the reason, continue only to steps that don't
depend on it, and surface every FAILED step in the final report. Never declare done on
a cap-hit.

## Goal

**Make adding more leads to a campaign from its existing pool feel effortless.** Five
genuinely different prototype directions, each judged by five non-technical testers on
Simplicity, Minimalist, and Ability-to-complete-the-task - every prototype must reach
**8/10 or higher on all three axes** before the lab can end. The deliverable is the
scored prototype set and the user's pick; this skill never ships or wires anything.

## Config (baked)

```yaml
BASELINE: the live Sources-tab panel (campaigns.html hydratePoolPull, shipped 25 Jul 2026)
PROTO_DIR: ~/navreo-signals/app/prototypes/pull-more/   # p1.html .. p5.html + index.html
PROTOTYPES:
  p1: "Preset chips - one tap on 500 / 1,000 / 2,000, no typing"
  p2: "Top up to target - pick the total you want, the tool computes the batch, progress bar to target"
  p3: "Keep it topped up - a standing weekly auto-pull rule with one on/off switch"
  p4: "List-row quick action - pull without opening the campaign page; mini progress chip on the row"
  p5: "One-sentence UI - 'Add [500] more verified people' + one button; everything else behind Details"
PANEL_TESTERS: 5              # non-technical personas; ALL must score >= PANEL_BAR
PANEL_AXES: [simplicity, minimalist, task_completion]
PANEL_BAR: 8                  # out of 10, per axis, per prototype
REDESIGN_CAP: 3               # fix-and-rescore rounds per prototype
RETRY_CAP: 3
```

## Ground truth

- Design system: `~/navreo-signals/app/navreo.css` (cream/ink, ONE orange per screen,
  DM Sans body / Acid Grotesk display, line-bordered 12px cards). No emoji in UI.
- Real numbers for mock data: `GET /api/pool-pulls` (authed via the minted-cookie
  recipe, memory [[live-tool-authed-curl-minted-cookie]]) - prototypes should show the
  five real pools (A 84,920-total etc.) so testers judge real scale, not lorem ipsum.
- **Prototypes NEVER call `/api/pool-pulls/pull`** - every pull in a prototype is
  simulated (setTimeout stages mirroring the real job: selecting → sweeping →
  verifying → uploading). A prototype must not be able to spend a ListMint credit.
- The gated pipeline is invariant: whatever UX wins, the pull underneath stays
  sweep + verify + audit + upload. Prototype copy must not promise instant adds.
- Repo pushes deploy the LIVE app - prototypes live under `app/prototypes/` which is
  static and unlinked; committing them is safe, wiring them is out of scope.

## Steps

### Step 1 - Baseline read
Load the live panel (minted-cookie Browser-pane or DOM read), capture its screenshot
and the exact current journey (find campaign → Sources → panel → button → narration →
result). Run the panel once against the BASELINE so every later score has a reference
row ("today's panel" scored on the same three axes by the same testers).
- **Done-rule:** baseline journey documented + baseline scores recorded per axis.

### Step 2 - Build the five prototypes
One self-contained HTML file per PROTOTYPES entry in `PROTO_DIR`, all on the design
system, all using the real pool numbers, all with a working simulated pull (stage
narration + honest result line). Each file header comments its direction and what it
deliberately removes compared to the baseline. Build an `index.html` linking all five
with one-line descriptions.
- **Done-rule:** 5 prototype files + index exist, each opens standalone (no server
  beyond static hosting), each demonstrates a complete simulated pull, zero calls to
  any live API endpoint that mutates.

### Step 3 - Panel loop
Five distinct non-technical personas (an account strategist who hates dashboards, a
new VA on day 3, a founder checking on his phone between calls, a numbers-averse
copywriter, a careful spender) walk each prototype: "your campaign is running low -
add about a thousand more people". Each scores each prototype 1-10 on each of
Simplicity / Minimalist / Ability-to-complete, with a one-line reason - recorded
verbatim, never invented, never rounded up. Any axis below 8 → apply the named fix to
that prototype → re-panel THAT prototype (max `REDESIGN_CAP` rounds each).
- **Done-rule:** a recorded final round where all 5 prototypes score >= 8 on all 3
  axes from all 5 testers; every redesign round's fix is listed.

### Step 4 - Present + record
Commit `PROTO_DIR` to the repo (static, unlinked - safe). Update `index.html` with
the final scores table. Hand the user: the index link, a one-line verdict per
prototype (what it's best at, what it trades away), and the panel's overall
favourite with the reason. Save a `project` memory (scores, favourite, location).
**Ask the user to pick; do not ship.** Wiring the winner into campaigns.html is a
separate ruling and a separate piece of work.
- **Done-rule:** prototypes committed + pushed; index shows final scores; memory
  written; the report ends with the pick question, not a ship.

## Hard don'ts
- Never let a prototype call the live pull endpoint or anything that spends credits
  or writes rows - simulated pulls only.
- Never ship, wire, or replace the live panel from this skill.
- Never fake, average, or round up a panel score - an axis at 7.9 is a fail.
- Never make the five prototypes cosmetic variants of one idea - each must remove or
  restructure something real.
- Never exceed a retry cap or report done while any done-rule fails.
