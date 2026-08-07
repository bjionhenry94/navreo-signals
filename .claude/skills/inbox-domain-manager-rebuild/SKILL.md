---
name: inbox-domain-manager-rebuild
description: Static orchestration skill for the Navreo signals tool — rebuild the Fleet Health Audit's "Inbox & domain manager" so it is domain-level instead of inbox-level, replace the from/to date pickers with Last 7/14/30-day presets (min-sent + reply-rate floor stay but move to background defaults), and fix the section-wide loading problem where sub-tab clicks appear dead for ~5 minutes because every tab reloads from scratch. Four fast flows: one-click warm-up for below-floor domains, spot anything not warming, in-warmup list with due dates + Restore buttons + an Overview-tab flag when restores are due, and needs-reconnect. One fixed step list, checkable done-rules, retry caps, and a Loop Training Mode toggle (ON by default). Verified with dummy data in the rendered browser and a simulated panel of 5 GTMEs scoring >=8/10. Use when the user says "rebuild the inbox & domain manager", "run the domain manager rebuild", "fix the fleet health audit loading", or "/inbox-domain-manager-rebuild".
---

# Inbox & Domain Manager Rebuild

## ⚙ Loop Training Mode: **OFF**   ← flip this line to ON to pause at every step

**ON (default):** pause at EVERY step boundary and wait for the user's explicit approval
before continuing. Before starting a step, check its done-rule first. If it already
passes, report "Step N already passes, skipping" and move to the next pause. Only re-run
steps whose done-rule fails. Show what you're about to do before doing it.

**OFF:** run all steps end-to-end with no pauses. The done-rule checks, skip-if-passing
behaviour, and retry caps stay exactly the same. Only the pauses go.

**Retry cap (both modes):** each step retries **max 3** times against its done-rule.
On cap-hit: record the step as FAILED with the reason, continue to the next step if it
doesn't depend on the failed one, and surface every FAILED step in the final report.
Never silently exceed the cap. Never declare the skill done on a cap-hit.

**Model routing:** delegate mechanical build/execution work to `model: sonnet`
subagents; profiling conclusions, panel scoring, and go/no-go calls stay with the
orchestrator.

## Goal

The Fleet Health Audit's Inbox & domain manager, rebuilt simple and fast on
https://navreo-signals.onrender.com:

1. **Domain-level, not inbox-level.** Rows are domains; the mailboxes under each domain
   are grouped and expandable. Warm-up decisions are made per domain, acting on all its
   mailboxes at once.
2. **Simpler controls.** The from/to window pickers become one preset select:
   Last 7 days / Last 14 days / Last 30 days. Min-sent and the reply-rate flag floor
   keep working exactly as today but move to background defaults (a small "advanced"
   disclosure, not front-and-centre).
3. **Four fast flows**, each reachable in one click:
   - Below-floor domains, with one button that pushes ALL of a domain's mailboxes into
     warm-up rest (confirm before applying, as today).
   - Spot any domains or mailboxes currently not warming up.
   - All mailboxes in warm-up, with a clear due date, a Restore button, and reminders —
     flagged on the Overview tab whenever any restore is due.
   - Mailboxes that need reconnecting.
4. **No more dead clicks.** Today each sub-tab (Inbox & domain manager, Performance by
   batch, ...) loads as if from a fresh start and the click looks broken for ~5 minutes.
   The section loads its data ONCE and every sub-tab renders from that instantly.

**Score target:** a simulated panel of 5 GTMEs rates ease of use and speed to access
information and take action at **8/10 or higher**.

## Ground truth (verified 2026-07-11 — re-verify in Step 1, line numbers drift)

- Working copy: `~/navreo-signals/` (the git/Render repo). There is ALSO an iCloud copy
  under the project dir; iCloud can REVERT edits — after any merge, diff-check the two
  (memory `signals-deploy-repo`). Local dev: `python3 app/server.py` then
  `http://localhost:7901/app/deliverability.html`.
- Fleet Health Audit lives in `app/deliverability-tab.js` (~7,216 lines). Sub-tab shell
  at ~:1223-1232 (`blacklist`, `manager`, `batch`, `reminders`); the manager panel
  renders around ~:3550-3624 with the 8-view selector and shared search.
- Mutating actions (pause / reactivate / reconnect / warm-up) go through `liveAction()`
  which POSTs `/api/deliverability/<action>`; `app/server.py` (~8,600 lines) forwards
  those to the standalone audit service
  (navreo-email-deliverability-audit.onrender.com). Keep this plumbing — this rebuild
  changes how things are grouped and loaded, not how mutations execute.
- The page header shows "Last pull: 2h ago" — an audit dataset cache already exists
  somewhere in the chain. Step 1 must find where, and why sub-tabs still re-fetch or
  recompute from scratch.
- Colour-as-severity, no emoji (memory `deliverability-visual-pass`). Rendered browser
  pages are the only done-evidence for UI work — a grep of deployed JS only proves the
  deploy, never the UI.
- Simulated-panel testing pattern already exists in this repo (`app/ux_sim.py` et al.):
  personas of mixed ability drive the UI, score 1-10, findings feed the next iteration.
- Maildoso fleet warms EXTERNALLY; Smartlead warmup showing inactive is intentional
  (memory `maildoso-warmup-external`). Confirm in Step 1 what the existing "Warm up"
  button really does (rest/rotation vs a Smartlead warmup toggle) before rebuilding
  around it.

## Steps

### Step 1 — Re-verify ground truth + profile the slowness
Confirm every bullet above against current code. Reproduce the dead-click: load the
Fleet Health Audit locally, click between sub-tabs, capture timings and network calls.
Name the exact bottleneck (which fetch/recompute runs per sub-tab click, which endpoint,
how long) and the code path of the "Warm up" button (what API call actually fires).
- **Done-rule:** you can state "sub-tab X takes Ns because Y" with captured evidence,
  name where the existing audit cache lives, and name the warm-up button's real action.
  No code changed yet.

### Step 2 — One shared load, instant sub-tabs
Load the audit dataset ONCE per page visit (single fetch shared across all sub-tabs,
backed by the server-side cache found in Step 1); every sub-tab renders from that
in-memory dataset. First load gets a loading skeleton with progress; after that, no
sub-tab click is ever visually dead — every click gives an immediate response.
- **Done-rule:** measured in-browser on localhost: after first load, switching between
  all five sub-tabs takes under 1 second each, and the network log shows no duplicate
  audit fetches. Zero console errors.

### Step 3 — Domain-level manager UI
Rebuild the manager panel in `app/deliverability-tab.js`:
- Rows are DOMAINS. Sent / leads / reply rate / positive / bounce aggregate across the
  domain's mailboxes; a row expands to show its individual mailboxes.
- Replace the from/to date pickers with the preset select (Last 7 / 14 / 30 days,
  default 7). Min-sent and the reply-rate floor move behind a small "advanced"
  disclosure with today's values as the defaults — same flagging behaviour, set in the
  background.
- Replace the 8-view dropdown with the four flows as simple one-click views:
  **Below floor** (per-domain "Warm up domain" button = all its mailboxes into warm-up
  rest, confirm-before-apply), **Not warming**, **In warm-up** (due date per mailbox +
  Restore button), **Needs reconnect**. Keep search and the existing confirm pattern;
  drop everything else that doesn't serve the four flows.
- Overview tab: a flag/banner whenever any mailbox's restore is due, linking straight
  into the In warm-up view.
- **Done-rule:** with dummy data, each of the four flows completes in <=2 clicks from
  tab-open in the rendered browser; the domain "Warm up" button hits the same liveAction
  path per mailbox as today; the Overview flag appears when (and only when) a restore
  is due.

### Step 4 — Dummy-data verification (browser)
Seed dummy data covering at least: a below-floor domain with several mailboxes, a
healthy domain, a domain with mixed-state mailboxes, a mailbox in warm-up due today,
one due next week, and a failed connection. Walk every flow end-to-end in the rendered
browser, including the confirm-then-apply on the domain warm-up button (against a mock
or dry-run target, never a real mutation from dummy data).
- **Done-rule:** every seeded case appears in the right view with the right numbers,
  all four flows complete, the Overview flag matches the seeded due-dates, zero console
  errors, screenshots captured for the report.

### Step 5 — GTME panel
Run 5 simulated GTMEs of mixed ability through the main jobs on the dummy dataset:
find-and-warm-up a below-floor domain, spot what's not warming, find what's due for
restore and restore it, find what needs reconnecting. Each scores ease of use and speed
to access information and take action, 1-10, with specific friction notes. Fix the
friction, re-run the panel. Iterate within the retry cap.
- **Done-rule:** panel average >= 8/10 on a run with no fixes applied after it.

### Step 6 — Deploy
Commit in `~/navreo-signals`, push, wait for the Render deploy, then verify live with
REAL data: sub-tab switching is fast, domains group correctly, the four views populate.
Read-only walk only — no live mutations as part of verification. Diff-check the iCloud
copy against the repo and reconcile.
- **Done-rule:** production shows the domain-level manager with the preset window
  select; all five sub-tabs switch in under 1 second live; repo↔iCloud diff for the
  touched files is empty.

## Final report (always, both modes)
One summary: steps passed/skipped/FAILED; before/after sub-tab timings; the GTME panel
scores per persona with their friction notes; screenshots of the four views and the
Overview flag; anything deferred.

## Hard don'ts
- Never enable Smartlead warmup on Maildoso-fleet inboxes (external warmup is
  intentional). "Warm up" in this tool means rest from sending via the existing action
  path — whatever Step 1 proves that path to be.
- Never fire a real mutation from dummy data, and never mutate live data during
  verification walks.
- Never change the flagging maths (min-sent, reply-rate floor) — only where the
  controls live.
- Never bypass the existing confirm-before-apply pattern on destructive/bulk actions.
- Never declare UI work done from a grep or an API response — rendered browser only.
- Never exceed a retry cap or report done while any done-rule fails.
