---
name: tier1-daily-uxlab
description: Static orchestration skill that redesigns and PROVES the UX for Navreo's 7 tier-1 daily
  tasks (list-build, TAM-view, campaign top-up, campaign-shell, copy, recontact, variant-swap) as one
  cohesive frontend-only prototype in the app shell — each task placed on its best surface (tool page
  or Claude-Code chat), each page proven in a real browser with ZERO paid-API calls, then hammered by
  a 10-tester simulated panel. One fixed step list, each with a checkable done-rule, retry caps, and a
  Loop Training Mode toggle. Use when the user says "run the tier-1 UX lab", "redesign the daily tasks",
  "prototype the tier-1 workflow", or "/tier1-daily-uxlab".
---

# Tier-1 Daily UX Lab

The gap: Navreo's 7 most-common daily tasks are inconsistent, technical, and slow — each should be
graspable by a non-technical person and doable in **under 5 minutes of labour**. This loop audits how
each task is done today (tool + backing skills), decides where each SHOULD live, builds a cohesive
frontend-only redesign for the page-surface tasks, writes the improved chat workflow for the rest,
then proves the whole thing with a 10-tester simulated panel — **all without burning a single provider
credit or API token** (mock fixtures only). Static loop — fixed steps, each has a done-rule, Training
Mode controls the pauses.

**This is a UX/process job, NOT a TAM-accuracy job.** Do not try to improve list/TAM *finding* itself
(70%-on-brief is the real system's target, out of scope). The job is the experience wrapped around it
and where each task belongs.

## ⚙ Loop Training Mode: **OFF**   ← flip this line to ON to pause at every step

**ON:** pause at EVERY step boundary and wait for the user's explicit approval before continuing.
Before starting a step, check its done-rule first — if it already passes, report "Step N already
passes, skipping" and move on. Only re-run steps whose done-rule fails. Show what you're about to do
before doing it.

**OFF:** run all steps end-to-end with no pauses. The done-rule checks, skip-if-passing behaviour, and
retry caps stay exactly the same — only the pauses go.

**Retry cap (both modes):** each step retries **max 3** times against its done-rule. The panel (Step 6)
retries **max 4 full tester-rounds**. On cap-hit: record the step as FAILED with the reason, continue
to the next step if it doesn't depend on the failed one, and surface every FAILED step in the final
report. Never silently exceed the cap. Never declare done on a cap-hit.

## 🔒 Spend gate (both modes, non-negotiable)

The whole point of a frontend-only build is that the panel can hammer it for hours with zero cost.
**No prototype page, and nothing the loop runs to test one, may EVER make a live call to a paid
provider or model endpoint** — AI-ARK, Prospeo, Smartlead API, HeyReach API, or any LLM/completion
endpoint. Every prototype runs on **local mock fixtures only**; `loadData()`/`fetch()` are stubbed to
return fixtures, never network. This is proven from the actual browser **network log** (Step 2 + Step
7), never from a "no API" claim in the code. The only permitted spend in this loop is the model tokens
for the simulated panel's own reasoning — bounded by the round cap. If any live paid call is observed,
that step is FAILED.

## Goal

1. All 7 tier-1 tasks + the 2 smart-suggestion screens have a chosen surface (tool page vs chat) with
   a written justification — nothing silently dropped.
2. Every page-surface task is a cohesive redesign inside the app shell, rendered and proven in a real
   browser, making zero paid-API calls.
3. A 10-tester mixed-ability panel completes every in-scope task in **<5 min** each.
4. Bjion receives the full-picture UX walkthrough + live-view screenshots + the panel scorecard.

**THE DONE-RULE (single source of truth):**
> Every in-scope task has a surface + justification; every page prototype renders live with a working
> load-bearing control and a **clean network log (zero paid calls)**; the panel's average simplicity is
> **≥8/10 with no task below 7/10** AND **every tester completes every task in <5 min**; every walkthrough
> step maps to a real control; fixtures reset between testers. Anything less than ALL of these = not done.
> On the round cap, stop and report the gap honestly — do not declare done.

## Ground truth (verified 2026-07-13 — re-verify in Step 1, line numbers/sizes drift)

- **App source** (working dir `…/Navreo/Claude/Navreo/`): `app/index.html` (7.5KB command-centre home,
  the page Bjion linked), `app/campaigns.html` (~305KB, the big campaigns tool), `app/lists.html`
  (~112KB), `app/server.py` (~634KB backend), nav rail via `app/shell.js` (~35KB). Styling: `app/navreo.css`.
  Live at navreo-signals.onrender.com/app/.
- **`shell.js` makes live calls**: it exposes `renderRail(page)`, `loadData(...)`, `freshnessBlock()`,
  chart/format helpers. `loadData()` fetches from the server — so a prototype that imports the real
  `shell.js` and calls `loadData()` WILL hit the network. The prototype MUST use a mock shell that
  stubs `loadData()` to return local fixtures (this is the spend-gate mechanism). Re-verify in Step 1.
- **Prototype convention already in repo** (frontend-only, standalone): `mailboxes-prototype.html`,
  `notifications-prototype.html`, and the dir `notifications-essentialism-proto/` (baseline.html +
  notifications.html). Follow this: put this loop's prototypes in a NEW dir `tier1-uxlab-proto/` —
  never touch or redeploy `app/campaigns.html` / `app/index.html` / `app/server.py`.
- **Deploy-repo gotcha** (memory `signals-deploy-repo`): iCloud reverts edits on the deploy repo. This
  loop is local-only and touches no production file, so it sidesteps this — keep it that way.
- **Simulated-panel precedent**: `signal-push-uxlab` ran 10 mixed-ability testers at ≥8/10; artifacts
  `SIGNAL-PUSH-UXLAB-2026-07-05.md`, `app/campaigns_unified_tester_panel.md`, reset helper
  `app/uxlab_reset.py`. Reuse the panel shape.
- **Hard UI rule** (memory `browser-verify-before-done`): a rendered page in a real browser is the ONLY
  done-evidence for UI work; a grep of deployed JS is a deploy check, not proof.
- **Backing skills to audit** (Step 1): `lilly-tam` / `-v2`, `lilly-tam`,
  `lilly-strategy`, `lilly-optimiser`, `lilly-bot`, plus the recontact flow. **Ocean is dead** — drop it
  from any SOP framing (memory: AI-ARK primary, Prospeo second).
- **Per-task design constraints** (load-bearing, do not rediscover): see Step 3.
- **Unknown → resolve in Step 1**: current in-tool state of each task (does `campaigns.html` already
  have a Sources tab / top-up button? confirm the liked "upload the rest" control exists and is NOT
  rebuilt); the browser tool available for live proof (in-app Browser pane vs chrome MCP).

## Budget

No provider-credit budget — the spend gate forbids all paid calls. The only cost is model tokens for
the panel's reasoning, bounded by **max 4 tester-rounds** (Step 6). At round 3 with the bar still
unmet, pause (ON) / stop-and-report (OFF) rather than burning the 4th silently.

## Steps

### Step 1 — Re-verify ground truth + audit the 7 tasks, pick each surface
Confirm every Ground-truth bullet against current code (open the files, confirm sizes/exports, confirm
`shell.js` `loadData` fetches network, confirm the top-up "upload the rest" control already exists).
Resolve the recorded unknowns. Audit how each of the 7 tasks + the 2 smart screens is done today across
tool + backing skills, then decide each one's **best surface**: a live tool-page prototype ONLY where a
page genuinely beats doing it in Claude-Code chat; otherwise an improved chat workflow. Write this to
`tier1-uxlab-proto/SURFACE-MATRIX.md`.
- **Done-rule:** `SURFACE-MATRIX.md` exists and contains a row for each of the 7 tasks + both smart
  screens, each with (a) how it's done today, (b) chosen surface (page/chat), (c) one-line
  justification, (d) the load-bearing control or chat-step that fixes it. No task blank. The top-up
  "upload the rest" control is confirmed present and flagged **do-not-rebuild**.

### Step 2 — Scaffold the cohesive prototype shell (mock, zero-API)
Create `tier1-uxlab-proto/` reusing `navreo.css` and a **mock shell** (`mock-shell.js`) that renders the
rail and stubs `loadData()`/`fetch()` to return local `fixtures.js` data — never the network. Build the
shared home/redesign frame so page prototypes read as the real next version of the tool.
- **Done-rule:** the scaffold page loads in a real browser with no console errors, the rail renders,
  AND `read_network_requests` shows **zero** requests to any host other than the local prototype files
  (specifically zero to ai-ark / prospeo / smartlead / heyreach / any LLM endpoint). Screenshot taken.

### Step 3 — Build the page-surface prototypes, each with its load-bearing control
For every task the matrix assigns to a page, build the screen inside the scaffold, honouring these
baked constraints:
- **(1) List-build:** a big **scrollable review TABLE** — company + who-they-are per row — to eyeball
  on-brief vs off-brief fast. Ocean absent; AI-ARK primary, Prospeo second in any framing.
- **(2) TAM→ideas:** a screen that takes a mapped TAM and hands back **suggested new campaign ideas**.
- **(3) Top-up:** do NOT rebuild the liked "upload the rest" button — add an **auto-suggested Sources
  expansion** (reads where positives come from) + a **one-click "find new, suppress everyone already
  contacted in this campaign, add them"**, plus **in-campaign tracking** of that added segment's
  positives / reply-rate / meetings WITHOUT splitting to a new campaign.
- **(4) Campaign-shell:** a wizard that spins up a Smartlead **+** HeyReach shell with **sequences
  pre-wired** and lets you finish copy later. Reflect the real blockers in the UX: Smartlead
  sub-sequences don't carry on duplicate/webhook (built from a God-template via API); HeyReach God-
  template duplicated, multi-branch copy filled via API (in-mail = 1 msg, no follow-up unless accepted
  → if not accepted, normal LinkedIn connect + 3 msgs; if no email/in-mail, just 3 msgs; 3–4 touchpoints).
- **(5) Recontact:** a view that makes **"recontact everyone who's finished, minus anyone live in this
  OR any other campaign"** a one-look decision (in-progress exclusion + cross-campaign dedup).
- **(6) Variant-swap:** in the optimiser surface, a **next-untried-problem-statement suggester** that
  reads what's been tried and proposes the next, holding icebreaker/offer/CTA constant.
- **(7) Smart Sources-expansion + segment tracking:** the second smart screen (may merge with top-up).
- **Done-rule:** for each page assigned in the matrix, the screen renders in a real browser with **no
  console errors**, its named load-bearing control is **present and interactive** (clickable/scrollable
  with fixture data), and a **screenshot** is captured. Lettered per task (a)–(g); partial passes visible.

### Step 4 — Write the chat-surface workflows
For each task the matrix assigns to chat (e.g. copy-writing via `lilly-copywriter`, TAM-mapping itself),
write the improved end-to-end chat workflow — concrete steps naming the real skills — into
`tier1-uxlab-proto/CHAT-WORKFLOWS.md`.
- **Done-rule:** every chat-assigned task has a numbered workflow whose steps reference real, existing
  skills/controls; no step invents a capability that doesn't exist.

### Step 5 — Full-picture walkthrough + narrative-matches-build check
Write `tier1-uxlab-proto/UX-WALKTHROUGH.md`: plain-English "how each task now works end-to-end" for all
9 items. Then walk each narrative step against the rendered page (or the real chat step) and confirm it
exists.
- **Done-rule:** every walkthrough step maps to a real control on a rendered prototype page or a real
  chat step — zero vaporware steps. Any mismatch is logged and the offending screen/narrative fixed.

### Step 6 — Run the 10-tester simulated panel (reset between testers)
Define 10 testers of mixed ability (non-technical → power-user). Each attempts every in-scope task on
its chosen surface. Reset fixtures between testers so one tester's clicks can't false-pass the next.
Record per (tester × task): completed? estimated labour minutes, step count, simplicity 1–10. Iterate
the prototypes on failures, **max 4 rounds**.
- **Done-rule:** the scorecard (`tier1-uxlab-proto/PANEL-SCORECARD.md`) shows (a) **every** tester
  completes **every** task, (b) each in an estimated **<5 min** of labour, (c) **average simplicity ≥8/10**,
  (d) **no single task below 7/10**, (e) fixtures were reset between testers (reset invocations logged).
  Any tester/task below bar is recorded as FAILED with the specific tester, task, and score — never
  rounded up. Cap-hit at round 4 = FAILED with the gap named.

### Step 7 — Final zero-spend audit
Reload every prototype page in a real browser and read the aggregated network log.
- **Done-rule:** across all prototype pages, `read_network_requests` shows **zero** requests to ai-ark,
  prospeo, smartlead, heyreach, or any LLM/completion endpoint. One clean log per page, screenshot or
  quoted.

### Step 8 — Deliver to Bjion
Assemble the deliverable: the full-picture UX walkthrough, the live-view screenshots of every prototype
screen, the surface matrix, the chat workflows, and the panel scorecard.
- **Done-rule:** a single hand-off message/section links or embeds all five artifacts and states the
  final numbers (tasks covered, page vs chat split, panel average, per-task lows, any FAILED items).

## Final report (always, both modes)

One summary listing: steps passed / skipped / FAILED; the surface split (how many tasks → page vs chat);
the panel numbers (average simplicity, per-task low, slowest task's minutes, any tester×task failures
by name); the zero-spend audit result per page; artifacts with paths (`tier1-uxlab-proto/…`, screenshot
files); and anything deferred. Name the specific numbers — "a summary" is not a spec.

## Hard don'ts

- **Never** make a live call to AI-ARK, Prospeo, Smartlead, HeyReach, or any LLM endpoint from a
  prototype or its test — mock fixtures only; a page's clean network log is the proof.
- **Never** edit, overwrite, or redeploy production `app/campaigns.html`, `app/index.html`,
  `app/server.py`, or any deployed file — prototypes are standalone in `tier1-uxlab-proto/` only.
- **Never** rebuild the existing liked "upload the rest of the pool" top-up button — extend around it.
- **Never** try to improve TAM/list *finding* accuracy — this loop is UX/process only (70%-on-brief is
  the real system's job, out of scope).
- **Never** reintroduce Ocean into any SOP framing — it's dead; AI-ARK primary, Prospeo second.
- **Never** declare a page done on a grep of the file — a real browser render with no console errors is
  the only UI done-evidence.
- **Never** round the panel up: any tester×task under <5 min / ≥7 is a FAILED line item, and a round-cap
  hit is reported as the gap, not as done.
- **Never** exceed a retry cap (3/step, 4 panel rounds) or report done while any done-rule fails.
