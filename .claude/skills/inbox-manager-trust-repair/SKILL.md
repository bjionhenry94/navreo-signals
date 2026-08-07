---
name: inbox-manager-trust-repair
description: Static orchestration skill for the Navreo signals tool — make the deliverability section's Inbox & domain manager TRUSTWORTHY: the data it shows matches live Smartlead (no ghost "sends paused" rows), and the three action buttons (Restore, Warm up domain, Re-enable) actually land and verifiably change Smartlead state. Root causes already verified live 2026-07-25: (1) a zombie pool_pull job stuck "running" starves the job queue so every Restore click sits "queued" forever, (2) the audit backend 502s on cold start and failures surface nowhere, (3) the "sends paused (N)" badges paint a frozen resting ledger that contradicts Smartlead (ledger says 14 paused boxes on navreoexpansion.info; Smartlead has 52 boxes at 2/day, none paused). One fixed step list, checkable done-rules, retry caps, Maildoso rows never touched, and a Loop Training Mode toggle (ON by default). Use when the user says "run the inbox manager trust repair", "fix the restore buttons", "the deliverability section is buggy", "audit the inbox & domain manager", or "/inbox-manager-trust-repair".
---

# Signals: Inbox & Domain Manager — Trust + Actions Repair

The deliverability page's **Inbox & domain manager** fails the user two ways: the
numbers lie, and the buttons don't work. Verified live on 2026-07-25 (minted-cookie
session, real Restore click on navreodemand.digital):

1. **The queue is starved.** `POST /api/warmup-job` returns 202, but the job sits
   `queued` forever — a zombie `pool_pull` job (`61f9e9643c`, "Pull 1000 more · pool B",
   no created_at = predates a restart) holds `running` and is never reaped, so the
   single worker never picks up new jobs. Historical `warmup_resume` jobs show 6
   `failed` with **HTTP 502 Bad Gateway** (audit-backend cold start on Render), plus
   `interrupted` ("server restart") and `cancelled` — days of the user's clicks, none
   of which changed anything, none of which told them why.
2. **The badges are fiction.** "sends paused (N)" comes from a resting ledger frozen at
   pause time. Ledger: 14/19/25/19/24/5/1 boxes on the seven navreo* domains. Smartlead
   ground truth (full pagination, 4,600 accounts): 52/51/52/52/52/22 OUTLOOK boxes, all
   `message_per_day: 2` except ONE at 0 (`bh_henryh@navreodemand.digital`, id 19953848).
   Six of seven "sends paused" domains are not paused at all — and even a successful
   Restore (resumed=0, nothing to do) never clears the ledger row, so the domain can
   never leave the tab. The audit backend's own `inwarmup` view knows only that 1 box.
3. **Re-enable can't be trusted.** Its suggested settings are not shown as "read live
   from Smartlead" vs invented defaults, so the user can't tell what the mailbox
   actually had before.

Static loop — fixed steps, each with a checkable done-rule, Training Mode controls pauses.

## ⚙ Loop Training Mode: **ON**   ← flip this line to OFF to run autonomously

**ON (default):** pause at EVERY step boundary and wait for the user's explicit approval
before continuing. Before starting a step, check its done-rule first — if it already
passes, report "Step N already passes, skipping" and move to the next pause. Only re-run
steps whose done-rule fails. Show what you're about to do before doing it.

**OFF:** run all steps end-to-end with no pauses. Done-rule checks, skip-if-passing, and
retry caps stay exactly the same — only the pauses go.

**Retry cap (both modes):** each step retries **max 3** times against its done-rule.
On cap-hit: record the step FAILED with reason, continue to steps that don't depend on
it, surface every FAILED step in the final report. Never declare done on a cap-hit.

**Maildoso gate (both modes, non-negotiable):** NEVER action a Maildoso-marked row.
No Restore, no Warm-up, and absolutely no warm-up **Re-enable** (Maildoso warms
externally BY DESIGN — warmup INACTIVE in Smartlead is intentional). The Maildoso
generics (growandlead.info, scaleandlift.info, … 19 domains) are DELIBERATELY parked at
cap 0 by owner ruling 2026-07-24 — they are not broken, do not "fix" them. Identify
Maildoso rows by the UI tag AND `smtp.maildoso.com` / `maildoso:true` in data — if the
two disagree, treat as Maildoso and skip.

## Goal

On https://navreo-signals.onrender.com/app/deliverability.html:
1. Every number in the Inbox & domain manager matches live Smartlead.
2. Clicking Restore / Warm up domain / Re-enable visibly works: job starts <60s,
   finishes with a truthful toast, the row updates, and Smartlead state actually changed.
3. Failures are loud: a failed action shows WHY and offers Retry — never a silent
   still-paused row.
4. Re-enable shows the mailbox's real current Smartlead warm-up values, labelled as
   live-read, before suggesting anything.

> **THE DONE-RULE (single source of truth):** all non-Maildoso rows in the three action
> tabs have been actioned (Restore / Warm up domain / Re-enable) with each action's
> Smartlead effect verified via the Smartlead API; the In-warm-up tab shows zero ghost
> rows (every "sends paused (N)" equals the live count of cap-0 boxes); a fresh Restore
> click reaches `running` <60s and terminal <5min; and a 5-tester panel scores the flow
> **8/10 or higher, all five testers**.

## Laws (bake into every step)

- Deploy = edit `~/navreo-signals` repo + push main. The iCloud copy is NOT the live
  source and REVERTS edits.
- Live verify = rendered DOM on the live host via minted cookie (HMAC signs the RAW
  payload bytes, secret `sha256(SERVICE_ROLE_KEY + ":navreo-session-v1")`; confirm via
  `/api/auth/me` BODY, status is a false positive). Curls alone never close a step that
  has a UI surface.
- Smartlead pagination: `curl` (not urllib), 100/page, stop ONLY on an empty page —
  an error mid-page reads as end-of-list and silently truncates. ~0.8s pacing.
- Outlook cap policy: restored OUTLOOK boxes go to **2/day** (`max_email_per_day`),
  never a generic 20.
- New/changed POST handlers in `server.py` read `self._post_body`, never rfile.read.
- Supabase RPCs die at 8s statement_timeout — keep reconcile queries sargable.
- Additive, never replace — confirm before removing any existing behaviour.

## Steps

**1. Un-starve the job queue.**
Reap zombies: on server boot (and on a sweep now), any job `running` with no live
worker (or predating the boot ledger's current boot) → `interrupted` with the standing
resume message. Then make the worker actually drain `queued` (find why `c4643af22d`
never started; if the runner is single-slot, blocked-by-zombie is the whole bug).
Cancel-or-run the stale queued Restore from 2026-07-25.
*Done-rule:* POST a fresh `warmup_resume` job → status `running` within 60s, terminal
within 5min, and `/api/jobs` shows zero `running` jobs without a live worker.

**2. Truth audit (report only, no mutations).**
Pull the FULL Smartlead account list (pagination law) → per-domain truth: box count,
`message_per_day` distribution, warmup status, provider. Pull the audit bundle,
`inwarmup` view, and the resting ledger. Diff the three. Classify every In-warm-up row:
GENUINE (has cap-0 boxes) vs GHOST (ledger only). Expected ghosts include
navreoexpansion.info, navreorevenueengine.digital, navreodemandengine.info,
navreopipelineengine.info, navreopipelineflow.digital, strategizewithnavreo.org.
*Done-rule:* a written mismatch table covering all 151 In-warm-up rows, zero
unclassified.

**3. Make the data honest (self-healing, not one-off).**
"sends paused (N)" must be computed from the LIVE count of cap-0 boxes, not the frozen
ledger; a reconcile pass (on bundle refresh) clears ledger rows whose domains have no
cap-0 boxes left, so ghost rows drain automatically now and forever. Audit-backend
inventory must cover every Smartlead box (fix its sync if it only knows a subset —
it knew 1 of 22 navreodemand.digital boxes).
*Done-rule:* live In-warm-up tab (DOM read) lists only GENUINE rows from Step 2, every
badge count equals the Smartlead cap-0 count, and the tab count in the pill matches.

**4. Make actions resilient and loud.**
502 from the audit backend (cold start) → retry with backoff inside the job before
failing. A `failed`/`interrupted` job must surface ON THE ROW: reason text + a Retry
button (not just a vanishing toast). A job that finishes with `resumed: 0` is reported
as "nothing to restore — row reconciled", and reconciles the ledger rather than
pretending success.
*Done-rule:* simulate a backend failure → the row shows the error + Retry; a real
restore of the one genuine cap-0 box moves it to 2/day in Smartlead (verified via API).

**5. Action pass — the user's standing permission, non-Maildoso only.**
In this order, each verified in Smartlead before the next batch:
   a) **Restore** every non-Maildoso "ready now" row (post-Step-3 this is only genuine
      cap-0 boxes; OUTLOOK → 2/day).
   b) **Warm up domain** every non-Maildoso "Below reply floor" row (12-row tab;
      Maildoso floor is 0.5% not 0.8% — a Maildoso row above 0.5% real-volume is
      exempt and skipped).
   c) **Re-enable** warm-up for every non-Maildoso "Not warming" row.
Batch ≤25 actions between verifies; on any error stop the batch, fix (Step 4 machinery),
re-run only the failures.
*Done-rule:* every non-Maildoso row in the three tabs is actioned; for each, the
Smartlead API shows the expected new state (cap restored / cap 0 + resting ledger row
with due date / warmup ACTIVE); zero unexplained failures.

**6. Re-enable settings trust.**
Before suggesting warm-up settings, the Re-enable modal shows the mailbox's CURRENT
live Smartlead values (`warmup_details`: status, per-day, reply rate) labelled
"read live from Smartlead just now", and the suggestion separately, labelled as the
house default. No invented "was" values.
*Done-rule:* DOM read of the modal on a real mailbox shows both blocks, and the
live-read values match a direct Smartlead API read of that box.

**7. Full live walkthrough + 5-tester panel.**
Walk the WHOLE journey on the live host as the user would: load page → each tab →
click each action type → watch the row update → refresh → still true. Then run a panel
of 5 independent user-tester agents (fresh eyes, no build context) scoring "smooth,
instant, bugless" 1–10 with specific complaints.
*Done-rule:* 5/5 testers score ≥8. Below 8 → their complaints become a fix list →
apply → re-run panel (counts toward this step's retry cap of 3).

## Final report

Steps passed/failed, every action taken with its Smartlead verification, ghost rows
cleared, panel scores with quotes, and any FAILED-at-cap items with exact reasons.
Update memory: root causes fixed, new laws learned, and mark the 2026-07-25 stuck job
(`c4643af22d`) resolved.
