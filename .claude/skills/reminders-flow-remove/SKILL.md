---
name: reminders-flow-remove
description: Static orchestration skill for the Navreo signals tool — remove the "Restore reminders" flow from the Inbox & domain manager on the deliverability page, editing ONLY app/deliverability-tab.js in the live ~/navreo-signals repo. Deletes the ["reminders","Restore reminders"] MGR_FLOWS chip, makes the reminders flow body unreachable (renderRemindersFlowBody / renderRestoreRow and code reachable ONLY from it), and drops the manual "+ Add 14-day reminder" bar — while KEEPING the shared restore modal, rst-restore actions and "Restore all due" (used by In warm-up) and the whole reminders data layer in server.py untouched. Repoints every entry path that landed on the reminders flow (legacy redirect, Overview "reminder(s) due" insight-card button, fifth-flow-chip comment path) at the In warm-up flow. Verifies the already-existing In warm-up due-date-ascending sort on live data. Deploys via the detached-worktree recipe so foreign uncommitted work (app/unified.html) stays untouched. One fixed step list, checkable done-rules, retry caps, and a Loop Training Mode toggle (ON by default). Use when the user says "remove the restore reminders flow", "run the reminders flow removal", "kill the reminders chip", or "/reminders-flow-remove".
---

# Remove "Restore reminders" from the Inbox & Domain Manager

## ⚙ Loop Training Mode: **OFF**   ← flip this line to ON to pause at every step

**ON (default):** pause at EVERY step boundary and wait for the user's explicit approval
before continuing. Before starting a step, check its done-rule first. If it already
passes, report "Step N already passes, skipping" and move to the next pause. Only re-run
steps whose done-rule fails. Show what you're about to do before doing it.

**OFF:** run all steps end-to-end with no pauses. The done-rule checks, skip-if-passing
behaviour, and retry caps stay exactly the same. Only the pauses go.

**Retry cap (both modes):** each step retries **max 3** times against its done-rule.
On cap-hit: record the step as FAILED with the reason, STOP (this is a linear removal —
every later step depends on the edit surviving), and surface the FAILED step in the final
report. Never silently exceed the cap. Never declare the skill done on a cap-hit.

**Model routing:** the edits are small and precise — the orchestrator does them directly.
No mechanical fan-out needed. Judgment calls (shared-vs-orphan analysis, live verdicts)
stay with the orchestrator.

## Goal

On https://navreo-signals.onrender.com, the Inbox & domain manager shows **four flow
chips** (no "Restore reminders"), and the **In warm-up view is the single restore
surface**, ranked closest-due-back first with no-due-date domains at the bottom. The
reminders data layer underneath (API endpoints, restore-plan ledger, and the red
"dormant mailboxes — warmup off, no reminder" Overview guard) keeps working, untouched.

This is a **UI-only removal**. Nothing in the backend changes.

## Ground truth (verified at brief time — RE-VERIFY in Step 1, line numbers drift)

- **Edit ONLY** `~/navreo-signals/app/deliverability-tab.js`. This is the live git/Render
  repo. Render auto-deploys on push to `main`.
- **NEVER touch, read-only at most:**
  - the iCloud copy under `…/Navreo/Claude/Navreo/app/` — deprecated; iCloud can REVERT
    edits (memory `signals-deploy-repo`). Do not edit it, do not diff-reconcile into it.
  - `app/deliverability-tab-proto.js`, `app/deliverability-proto.html` — prototype files.
  - `app/unified.html` — **foreign uncommitted work-in-progress**. Must stay untouched;
    this is WHY the deploy uses a detached worktree (Step 5), not a plain commit.
  - `app/server.py` — ruling: the reminders API endpoints, the restore-plan ledger, and
    the red "dormant mailboxes — warmup off, no reminder" Overview guard ALL stay working
    underneath. Do not remove or edit any of them.
- **What to remove (all inside `app/deliverability-tab.js`):**
  1. The `["reminders", "Restore reminders"]` entry in **`MGR_FLOWS`** (~line 3364).
  2. The reminders flow **body**: `renderRemindersFlowBody`, `renderRestoreRow`, and any
     code reachable ONLY from that flow — remove it or make it unreachable.
  3. The manual **"+ Add 14-day reminder" bar** — dropped entirely. Ruling: NOT moved
     into In warm-up. Existing manual reminders keep feeding due-back data until they
     expire; we just remove the UI to add new ones.
- **What MUST STAY (shared with the In warm-up flow — do NOT delete):**
  - the **restore modal**
  - the **`rst-restore` actions**
  - **"Restore all due"**
  These three are the restore machinery the In warm-up view relies on. Before deleting
  anything in Step 2, prove each candidate for deletion is reachable ONLY from the
  reminders flow — if In warm-up also calls it, it stays.
- **Entry paths to repoint at the In warm-up flow** (they currently land on reminders):
  - legacy redirect at ~line 1069: `UI.mgr.flow = "reminders"` → point at the In warm-up
    flow key instead.
  - the Overview **"reminder(s) due" insight card's "Reminders ↓" button** (~lines
    2121 / 3193) → land on In warm-up, AND reword its action text to reference In warm-up
    (not "Reminders").
  - the **fifth-flow-chip comment path** (~line 7042) → point at In warm-up.
- **In warm-up default sort ALREADY EXISTS** at ~line 3691: `doms.sort` by due date
  ascending, with `|| Infinity` putting no-due-date domains last. **Verify it behaves on
  live data — do NOT reimplement it.** Fix only if Step 6 proves it broken.
- **Live app is behind a Supabase login gate.** Anonymous curl 302s to login; the in-app
  Browser pane carries no session. Live verification MUST go through the user's
  authenticated Chrome via `claude-in-chrome`. Entering the login password is prohibited —
  if Chrome isn't already authenticated, stop and ask the user to log in.
- Rendered browser is the ONLY done-evidence for the UI checks — a grep of deployed JS
  proves the deploy shipped, never that the UI renders right.

## Steps

### Step 1 — Re-verify ground truth (no code changed)
Open `~/navreo-signals/app/deliverability-tab.js`. Confirm against current code:
- the exact current line of the `["reminders", "Restore reminders"]` `MGR_FLOWS` entry
  and the other four entries (so you know what "four chips" should read as).
- the reminders flow body functions (`renderRemindersFlowBody`, `renderRestoreRow`) and
  the "+ Add 14-day reminder" bar location.
- **shared-vs-orphan map:** for the restore modal, `rst-restore`, and "Restore all due",
  find every caller. Confirm each is ALSO called by the In warm-up flow (⇒ keep). For
  every function reachable from the reminders body, confirm whether In warm-up (or
  anything else) also reaches it (⇒ keep) or only reminders does (⇒ safe to remove).
- the three entry paths (~1069, ~2121/3193, ~7042) and the In warm-up flow's exact key.
- the existing sort at ~3691.
- **Done-rule:** you can name the exact current line of every target above, and you have
  a written keep/remove list for each function reachable from the reminders body, each
  tagged with its callers. No file edited yet.

### Step 2 — Remove the chip, the flow body, and the Add-reminder bar
In `app/deliverability-tab.js` only:
- delete the `["reminders", "Restore reminders"]` entry from `MGR_FLOWS`.
- remove (or make unreachable) `renderRemindersFlowBody`, `renderRestoreRow`, and every
  function on the Step-1 "remove" list — and ONLY those. Leave the restore modal,
  `rst-restore`, and "Restore all due" intact.
- delete the "+ Add 14-day reminder" bar entirely.
- **Done-rule:** grep of the file shows no `"Restore reminders"` `MGR_FLOWS` entry and no
  "+ Add 14-day reminder" markup; every function on the "keep" list still present; no
  reference in the file still reaches the removed body (checked in Step 4). No other file
  touched.

### Step 3 — Repoint the three entry paths at In warm-up
In `app/deliverability-tab.js` only:
- ~1069: change `UI.mgr.flow = "reminders"` to the In warm-up flow key.
- ~2121/3193: point the "reminder(s) due" insight-card button at the In warm-up flow, and
  reword its action label to reference In warm-up instead of "Reminders".
- ~7042: repoint the fifth-flow-chip comment path at In warm-up.
- **Done-rule:** grep for `"reminders"` as a flow target returns zero live assignments;
  all three paths now resolve to the In warm-up flow key; the insight-card button text no
  longer says "Reminders".

### Step 4 — Static checks (grep + parse)
- grep the whole file: the `"Restore reminders"` `MGR_FLOWS` entry is gone, and there are
  **no dangling reachable references** to the removed flow body (a leftover call to a
  deleted function = FAIL — go back to Step 2/3).
- `node --check ~/navreo-signals/app/deliverability-tab.js` (or equivalent parse check).
- **Done-rule:** grep is clean of the entry and of dangling refs; `node --check` passes
  with no syntax error.

### Step 5 — Deploy via the detached-worktree recipe
So the foreign uncommitted `app/unified.html` stays untouched:
```
cd ~/navreo-signals
git worktree add --detach /tmp/navreo-deploy-<stamp>
cd /tmp/navreo-deploy-<stamp>
# copy the edited file in, OR checkout+re-apply — but the commit must contain ONLY
# app/deliverability-tab.js
git add app/deliverability-tab.js
git commit -m "Remove Restore reminders flow from inbox & domain manager (UI-only)"
git push origin HEAD:main
cd ~/navreo-signals && git worktree remove /tmp/navreo-deploy-<stamp>
```
(Use whatever stamp source is available; avoid `Date.now()` in scripts.) Then wait for
the Render deploy to finish.
- **Done-rule:** `git show --stat` for the deploy commit touches **exactly one file** —
  `app/deliverability-tab.js` — and nothing else (no `unified.html`, no server.py, no
  proto files); the push succeeded; the worktree is removed; Render reports the deploy
  live.

### Step 6 — Live verification through authenticated Chrome (the 4-check gate)
Drive `navreo-signals.onrender.com` in the user's authenticated Chrome via
`claude-in-chrome` (if not logged in, STOP and ask the user to log in — never enter the
password). Open the deliverability page → Inbox & domain manager. All four must hold:
1. **grep + diff** (from Steps 4–5): `"Restore reminders"` entry gone, no dangling
   reachable refs, deploy commit touched ONLY `app/deliverability-tab.js`.
2. **parse:** `node --check` passed (from Step 4).
3. **live proof (read the actual rendered DOM, not the app's own labels):**
   - the manager renders **exactly four flow chips**, none reading "Restore reminders".
   - the **In warm-up** view's **Due back column reads ascending top-to-bottom**, any
     no-due-date rows LAST — read the real cell values from the DOM and confirm the order.
   - the legacy reminders **deep-link / insight-card button lands on In warm-up**, not a
     blank panel.
   - the browser **console shows zero errors**.
4. **data layer survived:** the **Overview still renders the red "dormant mailboxes —
   warmup off, no reminder" guard** (in either its flagged or resolved state), proving the
   reminders/restore-plan backend is intact.
- **Done-rule:** ALL FOUR pass, with DOM reads / screenshots captured as evidence. Any one
  failing = not done.

## Final report (always, both modes)
One summary: steps passed / skipped / FAILED; the Step-1 keep/remove list as shipped;
`git show --stat` proving the single-file commit; the four live checks with the DOM Due-back
values you read (in order), the four-chip screenshot, the insight-card-lands-on-In-warm-up
screenshot, the zero-console-errors capture, and the Overview dormant-guard screenshot;
whether the existing sort needed a fix (it shouldn't); anything deferred.

## Hard don'ts
- Never edit any file other than `app/deliverability-tab.js`. Not server.py, not
  unified.html, not the proto files, not the iCloud copy.
- Never remove or alter the reminders API endpoints, the restore-plan ledger, or the
  Overview dormant-mailboxes guard — this is UI-only.
- Never delete the restore modal, `rst-restore` actions, or "Restore all due" — they are
  shared with In warm-up.
- Never move the "+ Add 14-day reminder" bar into In warm-up — it's dropped, full stop.
- Never reimplement the In warm-up sort — verify the existing one; fix only if proven
  broken.
- Never deploy with a plain `git add -A` / `git commit` that could sweep in the foreign
  uncommitted `unified.html` — use the detached-worktree recipe and commit the one file.
- Never enter the Supabase login password. If Chrome isn't authenticated, stop and ask.
- Never declare UI work done from a grep or an API response — authenticated rendered
  browser only.
- Never exceed a retry cap or report done while any done-rule fails.
