---
name: deliverability-manager-restore
description: Static orchestration skill for the Navreo signals tool — on the new analytics page (app/deliverability.html, the "Are your emails landing?" lane) RETURN the Inbox & domain manager that was dropped/buried when the analytics hub shipped, and REMOVE the "Where your emails end up" inbox-vs-spam card because there is no real placement data behind it. One fixed, small step list with checkable done-rules, a retry cap, and a Loop Training Mode toggle (ON by default). Verified in the rendered browser only: every deliverability sub-tab navigates with no dead clicks and the Inbox & domain manager shows correct domain-level data. Use when the user says "return the inbox & domain manager", "restore the domain manager to the analytics page", "remove Where your emails end up", "fix the deliverability analytics page", or "/deliverability-manager-restore".
---

# Deliverability Analytics — Manager Restore

## ⚙ Loop Training Mode: **OFF**   ← flip this one line to ON to pause at every step

**ON (default):** pause at EVERY step boundary and wait for the user's explicit approval
before continuing. Before starting a step, check its done-rule FIRST — if it already
passes, report "Step N already passes — skipping" and move to the next pause. Only
re-run steps whose done-rule fails. Show what you're about to do before doing it.

**OFF:** run all steps end-to-end autonomously with no pauses. The done-rule checks, the
skip-if-already-passing behaviour, and the retry cap all stay exactly the same — only
the pauses go.

**Retry cap (both modes):** each step retries **max 3** times against its done-rule.
On cap-hit: record the step FAILED with the reason, stop retrying (never loop forever),
surface every FAILED step in the final report, and NEVER declare the skill done while any
done-rule still fails.

**Model routing:** delegate mechanical edits and verification walks to `model: sonnet`
subagents; the go/no-go done-rule calls stay with the orchestrator.

## Goal

On the live analytics page https://navreo-signals.onrender.com/app/deliverability.html,
inside the **"Are your emails landing?"** lane, two changes and nothing else:

1. **Return the Inbox & domain manager.** It was dropped/buried when the analytics hub
   shipped. Surface it inside this lane again — real domain-level rows with the
   warm-up · restore · reconnect flows, and its sub-tabs navigating cleanly.
2. **Remove "Where your emails end up."** That inbox-vs-spam landing-% card has no real
   placement data behind it — delete the card and all its now-dead wiring.

Nothing else on the page changes.

## Ground truth (verified 2026-07-27 — re-verify in Step 1; line numbers drift)

- Repo: `~/navreo-signals/` (git + Render). An iCloud copy also lives under the project
  dir and can REVERT edits — after editing, diff-check the two and reconcile
  (memory `signals-deploy-repo`). Local dev: `python3 app/server.py` →
  `http://localhost:7901/app/deliverability.html`.
- Page: `app/deliverability.html`. The "Are your emails landing?" lane is `#lane-sent`
  (h2 ~:374).
- **"Where your emails end up"** = the acard at ~:379-396 (`data-seg="landing"`, ids
  `land-big / land-lg / land-lr / land-sent / land-inbox / land-take`). Its JS is
  `renderLanding()` + the `land-*` writes (~:1052-1067) and the `landing` case in the
  seg handler (~:1265). Remove the card AND this JS — leave no orphan references.
- The deliverability engine mounts at `#dlv-embed-slot` (~:419): `deliverability.html`
  loads `deliverability-tab.js` (:516) and calls `window.renderDeliverability()` (:519).
  That function (deliverability-tab.js `window.renderDeliverability` ~:7954) mounts into
  `#dlv-embed-slot` (~:7962).
- The Inbox & domain manager itself is `renderManagerPanel(D)` inside a collapsible fold
  `#dlv-fold-manager-embed` (deliverability-tab.js ~:4882) — so today it most likely
  renders but COLLAPSED/buried (which is why it reads as "removed"), or the embed
  silently fails. Step 1 proves which.
- Mutations (warm-up / restore / reconnect / reactivate) go through `liveAction()` →
  `/api/deliverability/<action>`. Keep this plumbing untouched — this is a surface +
  remove job, not a manager rewrite.
- Colour-as-severity, no emoji (memory `deliverability-visual-pass`). The rendered
  browser is the ONLY done-evidence for UI — a grep of deployed JS proves the deploy,
  never the UI. Live verify needs the `navreo_session` cookie and `/api/version`
  (memory `signals-live-verify-recipe`).

## Steps

### Step 1 — Verify the current state (no code changes)
Load `deliverability.html` locally AND live. Establish, with rendered-browser evidence:
(a) exactly how the Inbox & domain manager behaves today in the "Are your emails
landing?" lane — absent, collapsed in `#dlv-fold-manager-embed`, or embed-failed — and
the real reason; (b) that the "Where your emails end up" card is present and has no real
data feeding `land-*` (placeholder / fabricated split). Re-anchor every line number above.
- **Done-rule:** you can state why the manager reads as "removed" and where it actually
  is in the DOM, and confirm the `land-*` card has no real placement feed. No file
  changed yet.

### Step 2 — Remove "Where your emails end up"
Delete the acard (html ~:379-396) and every piece of its now-dead JS: `renderLanding()`,
the `land-*` writes (~:1052-1067), and the `landing` case in the seg handler (~:1265).
Leave the lane header and the "Replies by the day we sent" card intact.
- **Done-rule:** in the rendered browser the card is gone and the rest of the lane still
  renders, the console is clean, and
  `grep -nE "land-|renderLanding|data-seg=\"landing\"" app/deliverability.html` returns
  no orphan references.

### Step 3 — Return the Inbox & domain manager to the lane
Make the Inbox & domain manager visible inside the "Are your emails landing?" lane again
— expanded and reachable, not buried in a collapsed fold or a silently-failed embed (fix
whatever Step 1 proved to be the cause). Domain-level rows with warm-up · restore ·
reconnect, fed by the real audit dataset through the untouched `liveAction()` path. Its
sub-tabs (Overview / blacklisted / manager / batch / reminders) navigate without dead
clicks.
- **Done-rule:** in the rendered browser (local), the manager shows real domain rows
  inside the "Are your emails landing?" lane; every sub-tab switches with an immediate
  response (no dead click); the numbers match the audit dataset; zero console errors;
  screenshot captured.

### Step 4 — Deploy + live verification
Commit in `~/navreo-signals`, push, wait for the Render deploy, then verify LIVE with
real data behind the `navreo_session` cookie (memory `signals-live-verify-recipe`):
navigate every deliverability tab, and spot-check that the Inbox & domain manager's
domains, mailbox counts, reply rates and warm-up states are correct against the audit
service. Diff-check the iCloud copy against the repo for the touched files and reconcile.
Read-only walk — no live mutations during verification.
- **Done-rule:** production `deliverability.html` shows the Inbox & domain manager inside
  "Are your emails landing?" with "Where your emails end up" gone; every tab navigates
  cleanly; the manager's numbers are correct against the audit service; the repo↔iCloud
  diff for the touched files is empty.

## Final report (always, both modes)
One summary: steps passed / skipped / FAILED (with reasons); before/after screenshots of
the "Are your emails landing?" lane; confirmation that the tabs navigate and the manager
data is correct; the repo↔iCloud diff result; anything deferred.

## Hard don'ts
- Don't touch the `liveAction()` / `/api/deliverability/*` mutation plumbing — this is
  surface + remove, not a manager rewrite.
- Don't fire a real warm-up / restore / reconnect during any verification walk.
- Don't leave orphaned `land-*` / `renderLanding` references after removing the card.
- Don't declare UI work done from a grep or an API response — rendered browser only.
- Don't exceed the retry cap or report done while any done-rule still fails.
