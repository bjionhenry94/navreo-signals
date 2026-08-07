---
name: analytics-accuracy-reconcile
description: Reconcile the Navreo tool's per-client analytics numbers (Sent / Replies / Interested / Meetings / Bounces / reply rate) against the source of truth in Smartlead, where a client's book = every campaign whose name contains the client's name. Use when the numbers in the tool's Analytics / Deliverability page don't match a Smartlead All-Campaigns filter, when onboarding a new client into analytics, or as a periodic accuracy check. Trigger phrases "the numbers are wrong", "tool doesn't match Smartlead", "reconcile analytics", "fix the client totals", "why is Navreo showing X but Smartlead shows Y", "/analytics-accuracy-reconcile".
---

# Analytics Accuracy Reconcile

## ⚙️ Loop Training Mode — TOGGLE HERE

```
LOOP_TRAINING_MODE = OFF
```

Flip to `OFF` for autonomous runs. Behaviour:

| Mode | Pauses | Done-rule checks | Retry cap |
|------|--------|------------------|-----------|
| **ON** (default) | Pause at every step, wait for the user's approval before continuing. Skip any step already passing its done-rule; only re-run failing steps. | Enforced | Enforced |
| **OFF** | None — run start to finish | Enforced | Enforced |

**Retry cap: max 3 attempts per step.** If a step still fails after 3 tries, STOP and report the failing step, the last error, and the tool-vs-Smartlead gap that remains. Never loop forever.

Rules that hold in BOTH modes:
- Never write to Smartlead (read-only there — it is the source of truth).
- A step that already passes its done-rule is not re-run.
- Every step ends with an explicit PASS/FAIL against its done-rule before moving on.

---

## Goal

Make the tool's per-client analytics **real** — i.e. for every client, the tool's window totals equal what you get in Smartlead by filtering "All Campaigns" to campaigns whose name contains the client's name, within tolerance. Fix the aggregation so this holds **across the board**, not just for one client.

**Definition of a client's book (the contract):** a client owns every Smartlead campaign whose **name contains the client name** (case-insensitive substring). This is exactly what the user does manually in Smartlead's campaign filter, and it is what the tool must replicate.

## Done-rule (whole skill)

For **each** client, over the **same date window** (default: last 30 days, matching the page's active range) and the **same campaign set**:

- `Sent`, `Replies`, `Interested/Positive`, `Meetings`, `Bounces` each match Smartlead within **±1%** (or exact where the tool claims "exact"), AND
- reply rate and bounce rate derive from those same numbers.

The skill is DONE when every active client passes, verified by a side-by-side table. If any client still fails after the retry cap, the skill reports the residual gap rather than declaring success.

---

## Steps

Each step: do the work → check the done-rule → (if Loop Training Mode ON) pause for approval.

### Step 1 — Establish the Smartlead ground truth
- Repo/data: `~/navreo-signals`. Analytics page is `app/deliverability.html`; the engine is `/api/client-windows` (client + 7/14/30 range). See memory [[deliverability-client-range-filters]] and [[analytics-hub-live-shipped]].
- For each client, pull from Smartlead the list of campaigns whose **name contains the client name**, and sum Sent/Replies/Interested/Meetings/Bounces over the active window. Record per-campaign and per-client totals.
- **Done-rule:** a saved ground-truth table (client → campaign list → totals) exists for every active client, matching what the Smartlead UI shows for the same filter+window.

### Step 2 — Capture what the tool currently reports
- Read the tool's current per-client totals from `/api/client-windows` (or the rendered page) for the same window.
- **Done-rule:** a tool-side table exists in the same shape as Step 1's, ready to diff.

### Step 3 — Diff and locate the divergence
- Compute per-client, per-metric gaps (tool − Smartlead). For every client that fails tolerance, drill into WHICH campaigns are the cause. Classify each into one of:
  - **Membership mismatch** — tool's client→campaign mapping ≠ the name-substring rule (missing campaigns, extra campaigns, hard-coded IDs, stale mapping).
  - **Window/timezone mismatch** — different date boundaries or TZ than Smartlead.
  - **Metric-definition mismatch** — e.g. "Interested" vs "Positive Reply", replies counting sub-sequences, bounce = total vs unique, estimated-split bars leaking into totals.
  - **Stale/partial sync** — cron hasn't ingested recent campaigns.
- **Done-rule:** every failing metric for every failing client is attributed to one of the four causes above, with the specific campaigns named. No unexplained gaps.

### Step 4 — Fix the aggregation
- Apply the minimal change that makes the tool derive each client's book from the **name-substring rule** and sum the source metrics correctly. Prefer fixing the mapping/aggregation at the engine (`/api/client-windows`) so it holds for ALL clients, not per-client patches.
- Re-run the cron/sync if the cause was staleness.
- **Done-rule:** code/data changed; the engine now computes client books by name-substring; a local re-query reproduces Step 1's Smartlead totals within tolerance for the previously-failing clients.

### Step 5 — Cross-compare verification (the whole done-rule)
- Regenerate the tool totals and lay them beside the Smartlead ground truth from Step 1 in one side-by-side table, all clients, all metrics.
- **Done-rule (final):** every active client passes tolerance on every metric. Produce the table as the deliverable. If anything fails after the retry cap, report the residual gaps explicitly instead of claiming success.

---

## Notes / gotchas
- Navreo shares the fleet, so its daily *bars* are an estimated split — but its **window totals must still be exact**. Don't let the estimated-split logic contaminate totals. (See the page's own footnote.)
- Never mimic client campaign copy; irrelevant here but note client roster lives in `workspaces.display_label` — one source ([[client-workspace-labels-one-source]]).
- Smartlead reply/positive definitions differ from the tool's "Interested"; pin the mapping in Step 3 before touching code.
- Read-only on Smartlead. Writes only to the tool's engine/data.
