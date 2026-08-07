---
name: workspace-mailbox-parity
description: Bring every integrated Smartlead client workspace to full parity with Navreo's own mailbox handling in the signals tool — daily stat recording, inbox/domain manager visibility, and reply-rate-driven sending-cap changes. Use when the user says client workspace mailboxes are missing from deliverability, that caps only move for Navreo, that a workspace "isn't being treated the same", or asks to finish/verify workspace mailbox parity. Trigger phrases "workspace mailbox parity", "client workspaces aren't in the domain manager", "caps aren't adjusting for client workspaces", "/workspace-mailbox-parity".
---

# Workspace Mailbox Parity

## Loop Training Mode — TOGGLE HERE

```
LOOP_TRAINING_MODE = ON      # ← flip to OFF for autonomous runs
```

**ON (default).** Stop after every step and wait for Bjion's approval before
continuing. Before running a step, evaluate its done-rule: if it already
passes, say so and skip it — do not re-run passing steps. Only failing steps
execute. Retry cap: **3 attempts per step**. On the 3rd failure, stop the whole
loop, report what failed and the last error, and ask what to do. Never loop
past the cap.

**OFF.** Run all steps end to end with no pauses. Done-rule checks and the
3-attempt retry cap still apply exactly as above; a step that blows its cap
still halts the loop and reports.

Announce the mode in the first line of the run.

---

## Goal

Every workspace registered in the `workspaces` table is treated identically to
`navreo` across the three daily mailbox processes:

1. **Stats recorded daily** — its mailboxes land in `mailboxes` and
   `mailbox_stats_daily` on every cron sweep, workspace-stamped.
2. **Visible in the UI** — its mailboxes and domains appear in the inbox /
   domain manager on `app/deliverability.html`, with the same columns, states
   and actions Navreo mailboxes get.
3. **Caps managed** — reply-rate-driven raising/lowering of `message_per_day`
   runs for its mailboxes too, writing back via **that workspace's** API key.

Repo: `~/navreo-signals`. Live: `https://navreo-signals.onrender.com`.

Federation primitives already exist — use them, don't invent new ones:
`server.ws_all()`, `ws_enabled()`, `ws_key(ws)`, `ws_for_campaign(id)`,
`ws_key_for_campaign(id)`, and `smartlead(..., workspace=)`.
`app/sync_mailboxes.py` is already federated and stamps `workspace` on both
tables — step 1 is mostly verification. The real gaps are reader-side:
unfiltered `mailboxes?select=...` queries and account-scoped Smartlead writes
that fall back to the env `SMARTLEAD_API_KEY`.

Non-goals: client *lists*, HeyReach (`heyreach` is a ledger name, never a
workspace), and any change to Navreo's own behaviour.

---

## Steps

Each step has a done-rule. A step is finished only when its done-rule passes.

### Step 0 — Build the parity harness
Write `app/test_workspace_parity.py`. It reads `server.ws_enabled()` and, for
**each** workspace, asserts the same battery it asserts for `navreo`:

- `mailboxes` has ≥1 row for the workspace with `last_synced_at` inside 36h
- `mailbox_stats_daily` has rows for the workspace for the last 2 stat dates
- the non-null rate of `message_per_day`, `warmup_enabled`, `reply_rate_pct`
  for the workspace is within 10pp of Navreo's
- every domain in that workspace's mailboxes appears in the domain-manager
  payload the UI consumes
- `ws_key(<workspace>)` resolves to a non-empty key distinct from the env key
  (except for `navreo`)

It prints one PASS/FAIL line per workspace per check and exits non-zero on any
FAIL. Read-only — never writes to Supabase or Smartlead.

**Done-rule:** the file exists, runs, and prints a full per-workspace matrix
(FAILs at this point are expected and fine — the harness itself is the artifact).

### Step 1 — Ingestion parity
Run the sweep against every enabled workspace and confirm rows land stamped.
Fix only what the harness flags.

**Done-rule:** harness ingestion checks (rows present, fresh, null-rates in
band) PASS for every enabled workspace.

### Step 2 — Reader / UI parity
Find every Supabase read of `mailboxes`, `mailbox_stats_daily` and the
domain/resting ledgers that has no workspace dimension — start at
`app/server.py:13513` and sweep with
`grep -n '"mailboxes?\|mailbox_stats_daily?\|deliverability_resting_ledger?' app/server.py`.
Make each one either workspace-filtered or workspace-grouped, so the inbox /
domain manager renders client mailboxes exactly as it renders Navreo's. Keep
the existing default view intact; add the workspace dimension, don't replace it.

**Done-rule:** harness domain-coverage check PASSES for every workspace, AND a
live load of `/app/deliverability.html` shows at least one client-workspace
domain in the inbox/domain manager with the same columns and actions as a
Navreo domain (verify live per the recipe in `[[signals-live-verify-recipe]]`:
mint the `navreo_session` cookie, hit the page, confirm in the rendered DOM).

### Step 3 — Cap-management parity
Make the reply-rate cap logic iterate workspaces. Every Smartlead write that
sets `message_per_day` (or warmup state) for an account must use
`ws_key(workspace)` for the row's own workspace — never the bare env key. The
thresholds, the OUTLOOK-vs-other cap split, and the resting-ledger behaviour
stay exactly as they are for Navreo; only the key and the row scope change.

**Done-rule:** no remaining account-scoped Smartlead cap/warmup write falls
back to `os.environ["SMARTLEAD_API_KEY"]` when the row's workspace is not
`navreo` (prove with grep), AND a dry-run of the cap pass reports proposed
changes for at least one non-Navreo mailbox.

### Step 4 — Green harness + ship
Re-run the harness; then commit and push.

**Done-rule:** `python3 app/test_workspace_parity.py` exits 0 with every check
PASS for every enabled workspace, the change is committed and pushed, and
Render reports the new version (poll `/api/version` per
`[[signals-live-verify-recipe]]`).

---

## Verification (the answer to "how do we verify this")

Parity is verified by **running the identical assertion battery against every
workspace, including Navreo, and requiring identical outcomes**. Navreo is the
control: any check Navreo passes that a client workspace fails is the bug.
That is `app/test_workspace_parity.py`, and it is re-runnable — it becomes the
standing regression test for every workspace added later.

Two layers on top of it:
- **Live UI proof** — a client-workspace domain visibly rendered in the
  deliverability inbox/domain manager, not just present in the database.
- **Write-path proof** — a dry-run cap pass naming a non-Navreo mailbox and
  the workspace key it would use.

## Done-rule for the whole loop

All five step done-rules pass in one run, with the harness exiting 0 and the
live page and dry-run proofs captured in the final report. Report each
workspace by name with its PASS/FAIL line — never a bare "done".
