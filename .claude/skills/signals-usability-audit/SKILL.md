---
name: signals-usability-audit
description: Run a functional usability audit of the Navreo Signals campaigns page (https://navreo-signals.onrender.com/app/campaigns.html) to confirm the tool is beta-ready. Tests every button, form, filter, and feature on the page and reports each as BROKEN, ACTIVE, or NEEDS IMPROVEMENT. Use when the user says "run the campaigns audit", "usability audit", "test the signals app", or references beta-readiness for navreo-signals.
---

# Signals Usability Audit

## Loop Training Mode toggle

**Default: ON.**

Flip it by editing this line, or telling Claude "turn Loop Training Mode off/on" for this run:

```
LOOP_TRAINING_MODE: ON
```

- **ON** — pause after every step below and wait for explicit approval before moving to the next one. Skip any step whose done-rule already passes (report it as ACTIVE and move on without pausing). Only re-run a step that fails the done-rule.
- **OFF** — run all steps autonomously, no pauses. Still apply the done-rule check and the retry cap on every step.

**Retry cap (applies in both modes): 2 retries per step (3 attempts total).** If a step still fails the done-rule after 3 attempts, stop retrying, log it as BROKEN with the last error observed, and move to the next step.

## Goal

Test https://navreo-signals.onrender.com/app/campaigns.html from a functional standpoint and produce a report of any usability issues that should be fixed ahead of a beta launch.

## Scope

**The "Signals" tab only** — i.e. the campaigns page itself and every control that lives on it (client filter, New campaign wizard, Add-new-client wizard, campaign cards, Remove). Do NOT audit sibling nav destinations (Dashboard, Mailboxes, Notifications); only confirm their nav links load without error, then return. Findings about those other tabs are out of scope.

## Done-rule (applies to every step)

A step is DONE only when all three hold:
1. The action was actually performed in the browser (via preview/Chrome tools), not just visually assumed.
2. No console error, network error (4xx/5xx), or unhandled UI exception occurred during or immediately after the action.
3. The UI reflects the expected result (data loads, state changes, modal opens/closes, etc. — whatever that control is supposed to do).

If any of the three fail → step fails the done-rule → retry (up to cap) → then log as BROKEN.

## Steps

1. **Load the page.** Navigate to the URL, wait for full load, capture console + network logs. Done-rule: page renders with no console/network errors and the campaigns list (or empty state) is visible.
2. **Inventory every interactive element.** Snapshot the DOM and list every button, link, input, filter, dropdown, toggle, tab, and modal trigger on the page. Done-rule: a complete list exists before any clicking starts.
3. **Test each navigation/tab control** (page tabs, sidebar links, breadcrumbs). Done-rule: each destination loads without error and shows expected content.
4. **Test each list/table control** (sorting, search, filters, pagination). Done-rule: each control changes the visible data set as expected, no errors.
5. **Test each campaign-level action** (create, view detail, edit, pause/resume, delete, duplicate — whatever exists on this page). Done-rule: each action completes and the UI/state updates to match; destructive actions are tested on a disposable/test record only, never on real client data — if no test record exists, log as "needs improvement: cannot verify without a safe test record" instead of acting on live data.
   - **Destructive-action safety (hard rule):** trigger a delete/remove ONLY on the single record you created this session, targeted by its unique id or a ref you have re-verified points to that exact row. NEVER click a delete via a broad text/selector match (e.g. "first button whose text is Remove") — it can hit a neighbouring real record. If a native `confirm()` dialog blocks automation, do NOT script around it with page JS that re-dispatches clicks; pause and ask the user to click the dialog. Re-read the row's identity immediately before and after the click.
6. **Test each form and modal** (validation, required fields, save/cancel, error states). Done-rule: valid input submits cleanly; invalid input shows a real validation message, not a silent failure or crash.
7. **Test responsive/edge behavior** (resize to mobile width, empty states, slow/failed network via preview_network). Done-rule: layout doesn't break and errors surface as user-facing messages, not blank screens or console-only errors.
8. **Compile the report.** One row per inventoried element/feature from step 2, each tagged exactly one of: **BROKEN** (fails done-rule after cap), **ACTIVE** (passes done-rule), **NEEDS IMPROVEMENT** (passes but has a UX/edge-case gap worth flagging, e.g. no loading spinner, unclear error copy, missing confirmation on delete). Include the specific error/evidence for every BROKEN or NEEDS IMPROVEMENT row.

## Verification

The audit is complete only when every element inventoried in step 2 has a final verdict (BROKEN / ACTIVE / NEEDS IMPROVEMENT) in the step 8 report — no element left untested or unlabeled.
