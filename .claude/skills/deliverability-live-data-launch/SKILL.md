---
name: deliverability-live-data-launch
description: Static orchestration skill for the Navreo signals tool — confirm whether the Fleet Health Audit (app/deliverability.html) is showing mock or real data, verify the real numbers against Smartlead + Supabase, and push the confirmed-accurate live data to production so the "demo mode — mock data" banner disappears. One fixed step list, each step with a checkable done-rule, retry caps, and a Loop Training Mode toggle. Use when the user says "launch the real deliverability data", "is the fleet audit mock or real", "verify and ship the deliverability numbers", or "/deliverability-live-data-launch".
---

# Deliverability: Verify Real Data + Launch Live

## ⚙ Loop Training Mode: **OFF**   ← flip this line to ON to pause at every step

**ON (default):** pause at EVERY step boundary and wait for the user's explicit approval
before continuing. Before starting a step, check its done-rule first — if it already
passes, report "Step N already passes, skipping" and move to the next pause. Only re-run
steps whose done-rule fails. Show what you're about to do before doing it.

**OFF:** run all steps end-to-end with no pauses. The done-rule checks, skip-if-passing
behaviour, and retry caps stay exactly the same — only the pauses go.

**Retry cap (both modes):** each step retries **max 3** times against its done-rule.
On cap-hit: record the step as FAILED with the reason, continue to the next step only if
it doesn't depend on the failed one, and surface every FAILED step in the final report.
Never silently exceed the cap. Never declare the skill done on a cap-hit.

**Deploy gate (both modes, non-negotiable):** nothing is pushed to the deploy repo /
Render until Step 4's accuracy check has PASSED. In Training Mode ON, additionally show
the exact diff and the verified-numbers table and get approval before the push.

## Goal

The Fleet Health Audit at `app/deliverability.html` currently shows **mock data** (the
footer literally says "demo mode — mock data"). Three outcomes:

1. **Confirmed provenance.** A written verdict on exactly which numbers on screen were
   mock and why (the `DELIV_MOCK=1` gate).
2. **Verified real numbers.** A live audit run against real Smartlead, with the headline
   figures (mailbox counts, sent 7d, reply %, bounce % per batch) cross-checked against
   two independent sources: the Smartlead API directly, and the Supabase
   `smartlead_*` sync tables. Discrepancies beyond tolerance are investigated and fixed.
3. **Live in production.** https://navreo-signals.onrender.com serves the real audit,
   the demo banner is gone, and the on-screen numbers match the verified table.

## Ground truth (verified 2026-07-10 — re-verify in Step 1, don't trust blindly)

- **The screenshots ARE mock.** `DELIV_MOCK=1` is the single gate — `_deliv_mock_on()`
  at `app/server.py:7433-7438`; `import mock_deliv` at `server.py:34` serves an
  in-memory fake fleet (`server.py:4465, 7443, 7702`). Mock-only endpoints
  `/api/deliverability/_mock/state|scenario` 404 outside mock mode
  (`server.py:7976, 8164`). Mock mode was built local-only on 2026-07-09 (commit
  `2ba515f`) — see memory `project_deliverability_mock_mode`.
- **The banner** renders at `app/deliverability-tab.js:3428`. Separately, ":595 sample
  mode" = backend unconfigured/unreachable → mock data + banner. Both must be off in
  the final state.
- **Real data path:** cached audit blob via `GET /api/deliverability/_audit`, refresh
  via `POST /api/deliverability/_audit/refresh` (`server.py:7424-7426, 7980, 8181`);
  other `/api/deliverability/*` calls proxy to the standalone audit service
  `navreo-email-deliverability-audit.onrender.com` via `_DELIV_AUDIT_BASE`
  (`server.py:7693-7727`).
- **Verification sources:** Smartlead MCP (`get_email_accounts`,
  `get_mailbox_domain_wise_health_metrics`, `get_campaign_analytics_by_date`,
  `get_email_warmup_stats`) and Supabase project `fnykldftbkrccihdjayl`
  (`smartlead_*` daily-sync tables — note sync skips drafts and only covers
  campaigns with ≥500 sends, so expect it to be a subset).
- **Deploy repo caution:** working copy is `~/navreo-signals/` (git/Render); an iCloud
  copy also exists — diff-check after any merge (memory `signals-deploy-repo`).
  As of 2026-07-09 some mock-mode `server.py` hooks were **uncommitted and mixed with
  concurrent verify work** — Step 5 must untangle before committing.
- Smartlead API cap: 200 req/min. Local dev: `python3 app/server.py` →
  `http://localhost:7901/app/deliverability.html`.

## Steps

### Step 1 — Confirm provenance of what's on screen
Re-verify the ground truth: confirm the running instance (local and/or prod) has
`DELIV_MOCK=1` or is in ":595 sample mode", and record which. Check whether prod
(Render env vars for navreo-signals) has `DELIV_MOCK` set at all.
**Done-rule:** a one-paragraph verdict naming the exact gate responsible for the mock
banner in each environment (local, prod), backed by the env var value or a mock-only
endpoint probe (`/_mock/state` → 200 means mock is on).

### Step 2 — Run a real audit locally
Start the app locally with `DELIV_MOCK` unset, trigger
`POST /api/deliverability/_audit/refresh`, and wait for a fresh real blob. If the
standalone audit service is unreachable, fix that first (it's a dependency, not a
skip).
**Done-rule:** `GET /api/deliverability/_audit` returns a fresh (today-stamped)
non-mock blob, and the page renders WITHOUT the "demo mode — mock data" footer and
WITHOUT the sample-mode banner.

### Step 3 — Build the verified-numbers table
From the real audit blob, extract the headline figures: total mailboxes, per-batch
mailbox/sending/warmup counts, sent (7d), reply %, bounce %. Independently pull the
same figures from (a) Smartlead MCP and (b) Supabase `smartlead_*` tables. Respect the
200 req/min cap — aggregate endpoints, not per-mailbox loops.
**Done-rule:** a three-column comparison table (audit vs Smartlead API vs Supabase)
exists for every headline figure, with each cell filled or explicitly marked
not-covered-by-source (e.g. Supabase's ≥500-sends subset).

### Step 4 — Accuracy check + fix discrepancies
Tolerance: counts (mailboxes, sent) within **2%** of the Smartlead API figure;
rates (reply %, bounce %) within **0.15 percentage points**. Anything outside
tolerance: diagnose (stale cache, window mismatch, batch-tag drift, sync lag), fix
the cause, re-run Step 2's refresh, re-compare. Supabase mismatches explained by its
known subset rules count as PASS with a note.
**Done-rule:** every audit figure is within tolerance of the Smartlead API figure, or
carries a written, source-verified explanation. This step PASSING unlocks the deploy
gate.

### Step 5 — Ship to production
In `~/navreo-signals/`: review the uncommitted `server.py` state, separate mock-mode
hooks from anything else, commit cleanly, diff-check against the iCloud copy, push,
and confirm Render deploys. Ensure prod env has NO `DELIV_MOCK` (or `=0`).
**Done-rule:** `git status` clean in `~/navreo-signals/`, Render deploy live, and
prod `/_mock/state` returns 404 (mock gate off in production).

### Step 6 — Prove it live + final report
Load https://navreo-signals.onrender.com deliverability page, refresh the audit, and
spot-check 3 headline figures against Step 3's verified table. Write the final report:
provenance verdict, verified-numbers table, fixes applied, any FAILED steps.
**Done-rule:** prod page shows no demo/sample banner, the 3 spot-checked figures match
the verified table within Step 4's tolerances, and the final report is delivered to
the user.

## Done

The skill is done when Steps 1-6 all pass their done-rules (or a cap-hit FAILED step
is explicitly reported and accepted by the user). The single sentence that must be
true at the end: **production shows real, source-verified deliverability numbers with
no mock banner.**
