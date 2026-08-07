---
name: inbox-manager-all-workspaces
description: Get every mailbox from every client workspace under Navreo's management showing in the Inbox & domain manager table on app/deliverability.html — one monitoring surface for all workspaces. Use when client-workspace mailboxes are missing from the deliverability manager, when the manager only shows Navreo boxes, or on "run the inbox manager workspace loop", "/inbox-manager-all-workspaces".
---

# Inbox Manager — All Workspaces

## Loop Training Mode — TOGGLE HERE

```
LOOP_TRAINING_MODE = OFF     # ← flip to ON to pause at every step
```

**ON (default).** Pause after every step and wait for Bjion's approval before
continuing. Before running a step, evaluate its done-rule first: if it already
passes, say so and SKIP the step — never re-run passing steps. Only failing
steps execute. Retry cap: **3 attempts per step**. On the 3rd failure, halt
the whole loop, report what failed with the last error, and ask what to do.
Never loop past the cap.

**OFF.** Run all steps end to end with no pauses. The done-rule checks and the
3-attempt retry cap still apply exactly as above; a step that blows its cap
still halts the loop and reports.

Announce the mode in the first line of every run.

---

## Goal

All clients, irrespective of Smartlead workspace, monitored from one place:
every mailbox belonging to a workspace under this tool's management appears in
the **Inbox & domain manager** table on
`https://navreo-signals.onrender.com/app/deliverability.html`, in the right
tab (Below reply floor / Not warming / In warm-up / Needs reconnect), with the
same columns Navreo boxes get.

Repo: `~/navreo-signals`. Managed workspaces = `server.ws_enabled()`
(currently navreo, asteri, krg — read it live, don't hardcode).

## Why it isn't showing (root cause — verified 2026-07-28)

Ingestion IS federated: `app/sync_mailboxes.py` stamps `workspace` on
`mailboxes` + `mailbox_stats_daily` for every enabled workspace. But the
manager table's ROWS do not come from that mirror. They come from
`_deliv_bundle_run_bg_inner()` (`app/server.py:13050`), which pulls the five
views `("warmupoff","inwarmup","rested","reconnect","blocked")` and the
domain-health windows (7/14/30d) from the **external audit backend**
`navreo-email-deliverability-audit.onrender.com` — and that service only sees
Navreo's Smartlead. The mirror only feeds the `domainBoxes` census, which is
why the 2026-07-28 harness run found client DOMAINS present in the bundle
payload (22/22 asteri, 22/22 krg) yet **unattributable** — the payload carries
no workspace field and the view rows themselves are Navreo-only. Fix
direction: **merge client-workspace rows out of the Supabase mirror into the
bundle server-side** — do not touch the audit service (its repo is not local,
see `[[deliverability-audit-separate-service]]`, and its engine is retired).

## Guardrails (read before any step)

- **Never modify or depend on changes to the external audit service.** Its
  cap engine is RETIRED (see `[[workspace-mailbox-parity-status]]`): the
  Manager apply button 410s at the proxy — keep that retirement intact.
- **Cap tiering already runs in-tool and workspace-aware**
  (`provider_reply_caps()` in server.py, commit 2476ba0). **Asteri is
  excluded from the AUTOMATIC tiering** (`CAP_EXCLUDED_WORKSPACES` — they
  hand-set their own caps). MANUAL manager clicks on client rows are allowed
  (owner go-ahead 2026-07-28, commit 21e4464): the server intercepts
  `ws-<workspace>-<id>` row ids and runs the Smartlead write in-tool with the
  owning workspace's key; restores use the box's own last recorded cap, never
  Navreo's house 15/2.
- **Navreo rows stay exactly as they are** — merged client rows are additive.
- The rest-clock ledger guards in `_deliv_bundle_run_bg_inner` exist because a
  flaky pull once mass-reset every domain's rest clock. Merged client rows
  must never enter the ghost-drain / ledger-delete paths keyed on the
  Navreo-only census. Note the resting ledger has NO workspace column (rest
  state is domain-keyed, global) — don't let client domains collide with it.
- No manager action (caps, warm-up, reconnect) may fire a Smartlead write for
  a client row using the env `SMARTLEAD_API_KEY`. Route via
  `ws_key(workspace)` (warmup writes in `_warmup_job_worker` already do) or
  disable the action on client rows with a visible reason.
- Reuse the standing harness: `python3 app/test_workspace_parity.py [--live]`
  (committed 7cdce87 — last run 26 pass / 6 fail; the fails map to this loop).

---

## Steps

Each step is finished only when its done-rule passes.

### Step 1 — Confirm the gap, both ends
Run the harness ingestion checks (mirror has fresh, workspace-stamped rows for
every enabled workspace), then mint the `navreo_session` cookie per
`[[signals-live-verify-recipe]]` and pull the live `/api/deliverability/_bundle`.
Count rows per workspace in each view.

**Done-rule:** a per-workspace matrix showing mirror-rows PRESENT and
bundle-rows counted per view. (Zero client rows in the bundle is the expected
finding, not a failure — the matrix itself is the artifact.)

### Step 2 — Federate the five manager views
In `_deliv_bundle_run_bg_inner()`, after the backend pulls, read the mirror
(`mailboxes` filtered `workspace=neq.navreo`, joined with the latest
`mailbox_stats_daily`) and classify each client box into the same view
vocabulary using mirror fields (`warmup_enabled`, `message_per_day`,
`reply_rate_pct`, smtp/imap status). Append rows in the exact row shape the
views already use, stamped with `workspace`. A mirror read failure records an
error and leaves Navreo views intact — never voids the bundle.

**Done-rule:** a local bundle run returns ≥1 client-workspace row in the views
JSON, workspace-stamped, and all pre-existing Navreo rows unchanged
(same counts as a control run).

### Step 3 — Federate the reply-floor / domain-health windows
First CHECK what's already there: the `dh` windows come from the backend
(Navreo-only), but the 2026-07-28 harness saw client domains somewhere in the
bundle — establish exactly where before writing code. Then aggregate
per-domain sent/replies for 7/14/30d from `mailbox_stats_daily` for client
workspaces and merge into the `dh` windows, honouring the same `minSent` (500)
and `cutoff` (0.8%) already in the blob. Client domains below the floor must
surface exactly like Navreo domains.

**Done-rule:** with the same thresholds, every client domain that qualifies on
mirror data appears in the dh payload; a domain that doesn't qualify doesn't.

### Step 4 — Render + protect the write path
`app/deliverability.html` already carries `clientOfName(name, workspace)`
(`:600`, `:1050`) — make sure merged rows render with their client label, and
every row action either routes through `ws_key(workspace)` or is disabled for
client rows with a visible reason. Cap-touching actions must be inert for
`CAP_EXCLUDED_WORKSPACES` rows (asteri).

**Done-rule:** grep proves no action handler can reach a Smartlead write with
the env key for a `workspace != navreo` row, cap actions are inert for
excluded workspaces, AND a local page load shows a client-workspace domain row
with the same columns as a Navreo row.

### Step 5 — Ship and live-verify
Commit, push, poll `/api/version` until Render serves the new build, then
re-run Step 1's live pull plus `python3 app/test_workspace_parity.py --live`.

**Done-rule:** live `/api/deliverability/_bundle` contains rows for **every**
enabled workspace, the rendered live manager table shows client-workspace
mailboxes/domains, and the harness's domain-coverage check passes per
workspace.

---

## Done-rule for the whole loop

The brief's verification, verbatim: analytics from the various workspaces show
on `https://navreo-signals.onrender.com/app/deliverability.html`. Concretely:
all five step done-rules pass in one run, with the live bundle JSON and a
rendered-DOM (or screenshot) proof captured in the final report, reported
per workspace by name — never a bare "done".
