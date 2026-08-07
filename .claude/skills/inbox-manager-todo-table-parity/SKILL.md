---
name: inbox-manager-todo-table-parity
description: Make the Inbox & domain manager TABLE reflect the same mailboxes the to-do list already knows about — every workspace's boxes (VeriSmile and any newly-integrated workspace) show in the right tab with Navreo's columns. Verify by running the audit and confirming flagged boxes actually land in the tabs. Use when the to-do count is ahead of the table, when newly-integrated workspace boxes are missing from the manager tabs, or on "run the inbox manager table parity loop", "/inbox-manager-todo-table-parity".
---

# Inbox Manager — To-do ⇄ Table Parity

## Loop Training Mode — TOGGLE HERE

```
LOOP_TRAINING_MODE = OFF     # ← flip to ON to pause at every step
```

**ON (default).** Pause after every step and wait for Bjion's approval before
continuing. Before running a step, evaluate its done-rule FIRST: if it already
passes, say so and SKIP the step — never re-run a passing step. Only failing
steps execute, and only the failing steps re-run. Retry cap: **3 attempts per
step**. On the 3rd failure, halt the whole loop, report what failed with the
last error, and ask what to do. Never loop past the cap.

**OFF.** Run all steps end to end with no pauses. The done-rule checks and the
3-attempt retry cap still apply exactly as above; a step that blows its cap
still halts the loop and reports.

Announce the mode in the first line of every run.

---

## Goal

The **table** on the Inbox & domain manager tells the same story the **to-do
list** already tells: every mailbox from every integrated Smartlead workspace
(VeriSmile and any newly-added one) appears in the manager TABLE, in the right
tab (Below reply floor / Not warming / In warm-up / Needs reconnect), with the
same columns and actions Navreo/Arnic boxes get. No workspace is
to-do-visible-but-table-invisible.

Repo: `~/navreo-signals`. Live: `https://navreo-signals.onrender.com/app/deliverability.html`.
Managed workspaces = read live from `server.ws_enabled()` — never hardcode.

## Why this happens (root cause — already diagnosed)

Ingestion is federated (`app/sync_mailboxes.py` stamps `workspace` on
`mailboxes` + `mailbox_stats_daily`), and the **to-do generator reads the
Supabase mirror**, so it sees every workspace. The **table tabs** do NOT — the
five view rows (`warmupoff / inwarmup / rested / reconnect / blocked`) come
from `_deliv_bundle_run_bg_inner()` (`app/server.py`), which historically only
carried Navreo-attributed rows. That split is exactly why the to-do count runs
ahead of the table. Fix direction: **merge the client-workspace rows out of
the Supabase mirror into the bundle server-side** — see
`[[inbox-manager-all-workspaces]]` and `[[workspace-mailbox-parity]]`.

## Guardrails (read before any step)

- **Never modify or depend on the external audit service.** Its cap engine is
  RETIRED (`[[deliverability-audit-separate-service]]`,
  `[[workspace-mailbox-parity-status]]`). Merge from the mirror, not the audit
  backend.
- **Navreo/Arnic rows stay exactly as they are** — merged workspace rows are
  additive, never replacing or renumbering existing rows.
- **No Smartlead write for a client row via the env `SMARTLEAD_API_KEY`.**
  Route every manager action through `ws_key(workspace)` / row ids of the form
  `ws-<workspace>-<id>`. See the tiering/exclusion rules in
  `[[inbox-manager-all-workspaces]]`.
- **Rest-clock ledger is domain-keyed and global (no workspace column).** Keep
  merged workspace domains out of the ghost-drain / ledger-delete paths keyed
  on the Navreo-only census.
- **NEVER send to real prospects** (`[[never-send-to-real-prospects]]`). This
  loop reads and re-renders; the only writes are cap/warmup actions the user
  explicitly approves, routed per-workspace.

---

## Steps

Each step is finished ONLY when its done-rule passes. In ON mode, check the
done-rule before running; skip if already green.

### Step 1 — Confirm the gap is real
Read `server.ws_enabled()` for the live workspace list. For each enabled
workspace, count its mailboxes in the Supabase mirror (`mailboxes` filtered by
`workspace`) and count how many of those appear in the current table bundle.
- **Done-rule:** you can name, per workspace, mirror-count vs table-count, and
  have identified which workspace(s) are table-invisible (expected: VeriSmile
  and any freshly-integrated one).

### Step 2 — Merge mirror rows into the bundle
In `_deliv_bundle_run_bg_inner()`, add the missing workspaces' mailbox/domain
rows from the Supabase mirror into the five tab views and the domain-health
windows, workspace-stamped, using existing federation primitives
(`ws_all/ws_enabled/ws_key`). Additive only; respect every guardrail above.
- **Done-rule:** bundle payload carries a workspace field per row, and each
  previously-invisible workspace's rows now appear in the correct tab
  server-side (verify in the payload, not just the UI).

### Step 3 — Verify in the live table
Open `app/deliverability.html`, refresh the bundle, and confirm the tab counts
(Below reply floor / Not warming / In warm-up / Needs reconnect) now include
the merged workspace boxes with full columns. Cross-check the table total
against the to-do count from the same window.
- **Done-rule:** table reflects the to-do list — no workspace is
  to-do-visible-but-table-invisible; the numbers reconcile.

### Step 4 — Run the audit and confirm flagging lands in the table
Run the audit (`email-deliverability-audit`) over the integrated workspaces.
Confirm it can **flag VeriSmile boxes** into the appropriate tabs and that
those flagged boxes then actually show in the table tabs — not just in the
audit output.
- **Done-rule:** VeriSmile boxes flagged by the audit are present in the live
  table tab they were flagged into; a spot-check of ≥3 flagged boxes matches
  between audit result and table.

### Step 5 — Ship + record
Commit with a clear message, deploy, and poll `/api/version`
(`[[signals-live-verify-recipe]]`) until the new build is live. Update the
parity memory with the commit and what shipped.
- **Done-rule:** new commit is live on Render and the memory note is updated.

---

## Done (whole loop)

All five step done-rules pass: every integrated workspace's mailboxes are in
the manager table in the right tab with Navreo's columns, the table reconciles
with the to-do list, the audit's VeriSmile flagging lands in the table, and the
change is shipped and recorded. State this explicitly on the final line.
