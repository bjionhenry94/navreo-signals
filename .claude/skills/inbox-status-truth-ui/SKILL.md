---
name: inbox-status-truth-ui
description: Static orchestration skill for the Navreo signals tool — fix the Inbox & domain manager's status column so it tells the TRUE story of every domain instead of three contradictory ones. Today a Maildoso row shows "warming" with no "sends paused" tag and no Restore button, while other rows show "warming (52) + sends paused (52)" with a Restore — the same underlying reality (warming up, sends held) rendered three different ways, so no CSM can tell what is actually happening or act on it. This skill defines ONE coherent status vocabulary, shows the send-hold state on EVERY warming row (including Maildoso, which warms externally), and makes Restore available wherever a hold exists. One fixed step list, checkable done-rules, retry caps, and a Loop Training Mode toggle (ON by default). Verified with dummy data in the rendered browser and a simulated panel of 5 non-technical CSMs scoring the truth-of-picture at >=9/10 average. Use when the user says "fix the warming/sends-paused confusion", "make the inbox status honest", "run the inbox status truth fix", or "/inbox-status-truth-ui".
---

# Inbox Status Truth UI

## ⚙ Loop Training Mode: **OFF**   ← flip this line to ON to pause at every step

**ON (default):** pause at EVERY step boundary and wait for the user's explicit approval
before continuing. Before starting a step, check its done-rule first. If it already
passes, report "Step N already passes, skipping" and move to the next pause. Only re-run
steps whose done-rule fails. Show what you're about to do before doing it.

**OFF:** run all steps end-to-end with no pauses. The done-rule checks, skip-if-passing
behaviour, and retry caps stay exactly the same. Only the pauses go.

**Retry cap (both modes):** each step retries **max 3** times against its done-rule.
On cap-hit: record the step as FAILED with the reason, continue to the next step only if
it doesn't depend on the failed one, and surface every FAILED step in the final report.
Never silently exceed the cap. Never declare the skill done on a cap-hit.

**Model routing:** delegate mechanical build/verification work to `model: sonnet`
subagents; the status-vocabulary design, panel scoring, and go/no-go calls stay with the
orchestrator.

## The problem in one sentence

The status column is inconsistent: some warming rows carry a **sends paused** tag and a
**Restore** button, some warming rows (Maildoso) carry neither — yet all of them are in
the same real situation (warming up, live sends held). A non-technical CSM reading the
screen cannot tell which inboxes are actually sending, which are held, or which they can
act on. The fix is honesty and continuity, not new plumbing.

## Goal

On https://navreo-signals.onrender.com, the Inbox & domain manager shows the TRUE state
of every domain in one consistent vocabulary:

1. **One status vocabulary, applied to every row.** Every domain row states, in the same
   words every time, (a) whether it is warming, (b) whether live sends are held or
   flowing, and (c) — where it matters — *why*. No row is allowed to show "warming" alone
   while another shows "warming + sends paused" for the same underlying reality.
2. **The send-hold state is always visible.** If a domain's sends are held, the row says
   so — including Maildoso domains, which warm EXTERNALLY and whose Smartlead sends being
   held is intentional (memory `maildoso-warmup-external`). The row must make clear this
   is a normal, deliberate state, not a broken one.
3. **Every row is actionable or explains why not.** Restore (or the correct action) is
   available wherever a hold exists. Where an action is intentionally unavailable, the row
   says why in plain words instead of just leaving a blank cell that reads as broken.
4. **Continuity.** Two rows in the same real state look identical. Tags, wording, colour,
   and available buttons are driven by the true state, never by which provider or code
   path happened to render the row.

**Score target:** a simulated panel of 5 non-technical CSMs rates *"the screen now shows
the true picture of what is actually going on"* at **9/10 or higher on average**, on a run
with no fixes applied after it.

## Ground truth (verified via `inbox-domain-manager-rebuild` 2026-07-11 — RE-VERIFY in Step 1, line numbers drift)

- Working copy: `~/navreo-signals/` (the git/Render repo). An iCloud copy also exists under
  the project dir and can REVERT edits — after any change, diff-check the two and reconcile
  (memory `signals-deploy-repo`). Local dev: `python3 app/server.py` then
  `http://localhost:7901/app/deliverability.html`.
- Manager UI lives in `app/deliverability-tab.js` (~7k lines); the manager panel renders
  around the sub-tab shell / view selector. The status tags in the screenshot
  ("warming (N)", "sends paused (N)") and the Restore button are rendered here.
- **This is a render-layer fix.** The true state already exists in the audit dataset — the
  bug is that the renderer derives tags/buttons inconsistently per row. Do NOT change how
  warm-up / restore mutations execute: those go through `liveAction()` → POST
  `/api/deliverability/<action>` → the standalone audit service. Keep that plumbing.
- Maildoso warms EXTERNALLY; Smartlead warmup showing inactive/paused for Maildoso is
  intentional and must be shown as a *deliberate* state, never re-enabled (memory
  `maildoso-warmup-external`, `maildoso-fleet`).
- Colour-as-severity, no emoji (memory `deliverability-visual-pass`). A held-but-healthy
  state is NOT a red/alarm state — pick a calm, neutral treatment so CSMs don't read a
  normal hold as a problem.
- Rendered browser pages are the ONLY done-evidence for UI work — a grep of deployed JS
  proves the deploy, never the UI (memory `browser-verify-before-done`).
- Times shown to users are browser-local with a named tz, never bare UTC (memory
  `times-browser-local-with-tz`) — relevant if due-back dates appear in a row.

## Steps

### Step 1 — Re-verify ground truth + map every status a row can show
Confirm the bullets above against current code. In the running app (local), enumerate every
distinct status combination the manager can render today — for each, capture: the true
underlying state, the exact tags shown, whether Restore appears, and the code branch that
produced it. Explicitly capture the Maildoso "warming, no sends-paused tag, no Restore" case
and the "warming (52) + sends paused (52) + Restore" case, and prove they are the same real
state rendered differently.
- **Done-rule:** you can list, with captured evidence, every status combination the row
  renderer produces, mapped to its true state, and you can name the exact code branch
  responsible for the Maildoso inconsistency. No code changed yet.

### Step 2 — Design the ONE status vocabulary
Define the fixed, small set of true states a domain can be in (e.g. *Sending*, *Warming —
sends held*, *Warming externally — Smartlead sends held (normal)*, *Needs reconnect*, …
finalise the real set from Step 1). For each state define: the exact plain-English label,
the calm/severity colour, whether a hold tag shows, which action button appears, and — where
no action is offered — the one-line plain reason shown instead. This vocabulary is the single
source the renderer reads; no row may fall outside it.
- **Done-rule:** a written table of {true state → label, colour, hold-tag, button, reason-if-none}
  that covers 100% of the combinations found in Step 1, with the Maildoso case and the
  paused-52 case landing on states that read as the same reality. Approved before any build.

### Step 3 — Rebuild the row renderer to the vocabulary
In `app/deliverability-tab.js`, drive every row's tags, colour, wording and buttons from the
Step-2 vocabulary keyed off the row's true state — not off provider or render path. Show the
send-hold state on EVERY held row including Maildoso; show Restore (or the correct action)
wherever a hold exists; show the plain-language reason wherever an action is deliberately
withheld. Do not touch `liveAction()` or the mutation endpoints.
- **Done-rule:** in the rendered browser on localhost, two rows in the same true state are
  visually identical; every held row shows its hold state; every held row exposes the correct
  action; no row shows a bare/blank status or a dead button; zero console errors; mutation
  calls still route through the unchanged `liveAction()` path.

### Step 4 — Dummy-data verification (browser)
Seed dummy data covering at least: a freely-sending domain, a Smartlead domain warming with
sends paused + Restore, a Maildoso domain warming externally with Smartlead sends held, a
domain needing reconnect, and a mixed-state domain. Walk the manager in the rendered browser
and confirm each lands on the right vocabulary state with the right label/colour/tag/button.
Test Restore against a mock or dry-run target — never a real mutation from dummy data.
- **Done-rule:** every seeded case renders in its correct Step-2 state; the two "warming"
  variants now read as the same reality with only the honest difference (external vs internal)
  spelled out; Restore works on every held row it should; zero console errors; screenshots
  captured.

### Step 5 — CSM panel (5 non-technical testers)
Run 5 simulated non-technical CSM personas of mixed confidence through the screen on the dummy
dataset. Each answers, in their own words, "what is going on with these domains, and what can
I do?", then scores *"the screen shows the true picture of what is actually going on"* 1-10
with specific confusion notes. Fix the confusion, re-run the panel. Iterate within the retry
cap. Watch specifically for anyone reading a normal hold as broken, or being unsure whether an
inbox is sending.
- **Done-rule:** panel average **>= 9/10** on a run with no fixes applied after it, AND no
  single persona misreads the send/hold state of any domain.

### Step 6 — Deploy
Commit in `~/navreo-signals`, push, wait for the Render deploy, verify live with REAL data:
the status vocabulary is consistent across providers, Maildoso rows show the held state and an
explanation, held rows expose Restore. Read-only walk only — no live mutations during
verification. Diff-check the iCloud copy against the repo and reconcile.
- **Done-rule:** production shows one consistent status vocabulary; no "warming"-alone row
  exists beside a "warming + sends paused" row for the same reality; held rows are actionable;
  repo↔iCloud diff for the touched files is empty.

## Final report (always, both modes)
One summary: steps passed/skipped/FAILED; the Step-2 vocabulary table; before/after screenshots
of the manager showing the Maildoso and paused-52 rows now consistent; the 5 CSM scores with
their verbatim "what's going on here?" answers and confusion notes; anything deferred.

## Hard don'ts
- Never re-enable Smartlead warmup on Maildoso-fleet inboxes — external warmup is intentional;
  the fix is to SHOW that state honestly, not to change it.
- Never change `liveAction()` or the mutation endpoints — this is a render-layer truth fix.
- Never let a normal hold render as a red/alarm state; never leave a blank status or a dead
  button that reads as broken.
- Never declare UI work done from a grep or an API response — rendered browser only.
- Never exceed a retry cap or report done while any done-rule fails (panel < 9/10 = not done).
