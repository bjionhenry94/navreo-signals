---
name: warmup-dueback-fix
description: Static orchestration skill for the Navreo signals tool — close the "no due-back date" gap in the Inbox & domain manager so EVERY warming/resting domain always shows a real due-back date (never "—"), by stamping the resting ledger on warm-up ENTRY (not just on rest) and backfilling existing gaps; then diagnose every errored warm-up move in app_jobs and re-run only the transient failures (capped, gated, Maildoso-skipped). One fixed step list, each step with a checkable done-rule, retry caps, and a Loop Training Mode toggle (ON by default). Use when the user says "run the warm-up due-back fix", "fix the missing due-back dates", "every warm-up domain should have a due-back date", "check the errored warm-up jobs", or "/warmup-dueback-fix".
---

# Signals: Warm-up Due-Back Guarantee + Errored-Job Sweep

Two gaps in the deliverability section's **Inbox & domain manager**. (1) The "In warm-up"
tab unions two populations — *rested* domains (paused, ledger-tracked, carry a due-back
date) and *freshly-warming* domains (building reputation, never "rested", **no ledger row**)
— so the warming ones render "—" for Due back and you can't tell "just entered warm-up" from
"coming off a rest". (2) A batch of warm-up moves errored and their domains never entered
warm-up. This ships one date mechanic for the whole tab and diagnoses+retries the errors.

Static loop — fixed steps, each has a checkable done-rule, Training Mode controls the pauses.

## ⚙ Loop Training Mode: **ON**   ← flip this line to OFF to run autonomously

**ON (default):** pause at EVERY step boundary and wait for the user's explicit approval
before continuing. Before starting a step, check its done-rule first — if it already passes,
report "Step N already passes, skipping" and move to the next pause. Only re-run steps whose
done-rule fails. Show what you're about to do before doing it.

**OFF:** run all steps end-to-end with no pauses. The done-rule checks, skip-if-passing
behaviour, and retry caps stay exactly the same — only the pauses go.

**Retry cap (both modes):** each step retries **max 3** times against its done-rule. On
cap-hit: record the step as FAILED with the reason, continue to the next step if it doesn't
depend on the failed one, and surface every FAILED step in the final report. Never silently
exceed the cap. Never declare the skill done on a cap-hit.

**Destructive-action gate (both modes, non-negotiable):** the ONLY live action this loop
takes is **re-running a failed warm-up move (Step 7), which PAUSES live mailboxes**. The
only domains ever retried are those whose failure is classified **transient** (timeout /
HTTP 5xx / "server unreachable"), **capped at 50 domains per run**. Hard failures (bad
domain / auth) and **all Maildoso-fleet domains** are NEVER retried — they are reported.
Before the retry batch fires (in BOTH modes, because this is a live-sending change) show a
**self-contained decision packet** — the exact domain list, each domain's error text and
transient/hard classification, "pauses sending on N mailboxes", and the cap — and get
explicit approval. The eventual run has none of this chat's context, so the packet must
stand alone. Steps 2–4 (ledger + render) touch NO live sending and mutate only the
`deliverability_resting_ledger` display ledger.

## Goal

Four user-visible outcomes on https://navreo-signals.onrender.com (deliverability page):

1. **No blank due dates, anywhere.** Every domain shown warming or resting displays a real
   due-back date — on the In-warm-up tab, the Overview "resting in warm-up" cards, and the
   blacklist-rested rows. Zero "—".
2. **One clock for the whole tab.** Freshly-warming domains get due-back = warm-up start
   **+ 7 days**, same clock as a rest. No new state-marker/column — the date alone is the fix
   (user, 2026-07-15).
3. **Established rest clocks untouched.** Existing rested domains keep their current due
   dates — the fix never re-stamps them to "+7d from now".
4. **Errors resolved.** Every errored warm-up move is diagnosed; transient ones are re-run
   and have actually entered warm-up with a due-back date; hard/Maildoso ones are listed.

> **THE DONE-RULE (single source of truth):** every domain in the live inwarmup+rested union
> has a `first_rested_at` ledger row **and** renders a due-back date on all three surfaces,
> **and** a known previously-rested domain's due date is unchanged before→after, **and** the
> errored-job sweep reports retried/flagged/skipped counts read back from the DESTINATION
> (live view + ledger), not job success labels. Anything less than all of these = not done.
> On any retry/round cap-hit, stop and report the gap honestly — do not declare done.

## Ground truth (verified 2026-07-15 from source — re-verify in Step 1, line numbers drift)

- **Repo is the iCloud copy.** `app/deliverability-tab.js` + `app/server.py`. Edits here are
  NOT live until pushed/deployed; live host navreo-signals.onrender.com. Reconcile repo↔iCloud
  (memory `signals-deploy-repo` / INDEX_signals_app: iCloud REVERTS edits).
- **The "In warm-up" union** — `rowsForFlow('inwarmup')` (~deliverability-tab.js:3352-3366)
  concats backend views `inwarmup` (cap=0, warmup ON, `!r.rested`) + `rested`.
- **Due-back source** — `restDueFor` (~:3409) → `bundleRestDue()` = bundle `restDue` map;
  `domDue` (~:3650) returns null when ledger present but domain absent; row render at ~:3700
  emits `<span class="dlv-mb-dom">—</span>` when `due` is falsy. `blDueChip(due)` draws the chip.
- **Ledger** — Supabase table `deliverability_resting_ledger` (cols: `domain`,
  `first_rested_at`, `approx`, `last_seen_at`, `dismissed`). Written ONLY from the `rested`
  view by `_deliv_resting_ledger_sync` (~server.py:9290) and bundle builder (~:9390-9408).
  **This is the bug**: `inwarmup` domains are never passed in, so they get no row → "—".
- **Re-stamp gotcha (2026-07-11)** — the audit backend re-stamps `restedAt` every sweep, so
  the ledger's `first_rested_at` is the ONLY trustworthy due source. NEVER revert to backend
  `restedAt`. Backfill uses `on_conflict=domain` `resolution=ignore-duplicates` (no-op re-runs)
  so it never overwrites an existing `first_rested_at` (this is what protects rest clocks).
- **Other two surfaces** — Overview "resting in warm-up" cards (~deliverability-tab.js:2264-2288,
  gated on `D.restingDue[dom]`); blacklist-rested rows use `b.restedDue` (~:3259).
- **Errored jobs** — persisted to Supabase `app_jobs` (kind `warmup_pause`/`warmup_resume`,
  status `failed`, `error` string; worker `_warmup_job_worker` ~server.py:4994; success path
  logs `counts.failed` for partial per-mailbox failures). `_job_finished` persists BOTH done
  and failed. Re-run via POST `/api/warmup-job` `{op:"pause", domains:[…]}` (api_warmup_job
  ~server.py:5022) — one job, poll `/api/jobs/<id>`.
- **Maildoso** — warms externally (memory `maildoso-warmup-external`); a display-only ledger
  date is fine, but NEVER re-enable/retry Smartlead warmup on Maildoso rows (`r.maildoso`).
- **Unknowns for Step 1** — exact current line numbers; how many `app_jobs` warmup rows are
  `failed` and their error strings; how many union domains currently lack a ledger row.

## Steps

### Step 1 — Re-verify ground truth
Confirm every Ground-truth bullet against current code (grep the line refs; they drift).
Read back the two DB unknowns with read-only queries: `deliverability_resting_ledger`
row set, and `app_jobs` where kind in (`warmup_pause`,`warmup_resume`) and status=`failed`
(plus done-with-counts.failed>0). Record the count of union domains currently rendering "—".
- **Done-rule:** each Ground-truth location resolves to real current code; the failed-job
  list and the "—"-domain count are printed with real numbers (not assumed).

### Step 2 — Backend: stamp the ledger on warm-up ENTRY, not just on rest
In the bundle builder (~server.py:9390-9408), extend the domain set passed to
`_deliv_resting_ledger_sync` (or an entry-parallel path) to include the `inwarmup` view's
domains — every domain in the inwarmup+rested union gets a `first_rested_at` row; due-back =
`first_rested_at + _DELIV_REST_DAYS_MS` (7d) for ALL of them. New rows insert at now with
`approx=true`. Keep `on_conflict=domain ignore-duplicates` so existing rows (established rest
clocks) are never overwritten. Do NOT change the truncation-guard `allow_delete` logic that
protects against a flaky backend refusal wiping the ledger.
- **Done-rule:** (a) the sync input for a live bundle contains inwarmup domains, not just
  rested; (b) a fresh bundle's `restDue` map has a key for every union domain (read the
  bundle JSON back); (c) `first_rested_at` for a domain that already had a row is byte-identical
  before→after (grep the two ledger reads).

### Step 3 — Backfill existing "—" domains
One-shot: for every union domain currently lacking a ledger row (from Step 1's count), insert
`first_rested_at=now, approx=true` via the same `on_conflict=domain ignore-duplicates` write.
Skip nothing on Maildoso (date is display-only) but do not touch their warmup state.
- **Done-rule:** re-query the ledger — the set of live union domains == the set with a
  `first_rested_at` row, **zero gaps**; and a second run of the backfill inserts 0 rows (no-op).

### Step 4 — Frontend: never render "—" for a warming/resting domain
Make `domDue`/`restDueFor` return a value for every in-warm-up domain (they will, once the
bundle carries the row) and remove the reachable "—" fallback in the In-warm-up render
(~:3700) — replace with the `blDueChip(due)` path. Apply the same guarantee to the Overview
resting cards (~:2264-2288) and blacklist-rested rows (~:3259). No new column, no state marker.
- **Done-rule:** grep the render — no reachable `—` branch for a union-domain row; for a
  sample of union domains `domDue` returns non-null. (Deferred to Step 6 for the visual proof.)

### Step 5 — Deploy + reconcile
Push to the deploy repo, wait for live, marker-grep the deployed `deliverability-tab.js` /
`server.py` for the new code, and reconcile the repo↔iCloud copies (iCloud reverts — memory
`signals-deploy-repo`). Push=deploy; iCloud≠live.
- **Done-rule:** the deployed artifact on navreo-signals.onrender.com contains the Step 2+4
  changes (grep the live JS/py or the version marker), and the iCloud copy matches.

### Step 6 — Live browser proof (Part 1)
On https://navreo-signals.onrender.com → deliverability → Inbox & domain manager → In warm-up:
every visible row shows a due-back date, **zero "—"**. Check the Overview resting cards and a
blacklist-rested row likewise. Screenshot each. Then the regression check: a known
previously-rested domain still shows its ORIGINAL due date (compare to Step 1's ledger read).
- **Done-rule:** (a) In-warm-up tab: 0 "—" cells, screenshot attached; (b) Overview cards +
  blacklist-rested rows carry dates; (c) the regression domain's due date is unchanged.

### Step 7 — Errored warm-up jobs: diagnose + gated transient retry (Part 2)
From Step 1's failed-job list, group by domain, extract the error, classify transient
(timeout / HTTP 5xx / "server unreachable") vs hard (bad domain / auth / Maildoso). Build the
**decision packet** (domain list, per-domain error + class, "pauses sending on N mailboxes",
cap=50) and — per the Destructive-action gate — get approval. Then POST `/api/warmup-job`
`{op:"pause", domains:[transient, ≤50, non-Maildoso]}`, poll `/api/jobs/<id>` to done. READ
BACK from the destination: each retried domain now appears in the live inwarmup/rested view
WITH a ledger due-back date — not the job's own success label. If >50 transient domains, retry
the first 50 and report the remainder as the gap.
- **Done-rule:** (a) every failed job is classified; (b) approval captured before any retry;
  (c) each retried domain is confirmed warming+dated in the live view/ledger; (d) hard +
  Maildoso-skipped domains listed with reasons; (e) a 50-cap hit is reported FAILED with the
  remaining count, never "done".

## Final report (always, both modes)
One summary: steps passed / skipped / FAILED; the real numbers — count of domains backfilled,
count of union domains now ledger-covered (must equal), the regression domain's before/after
due date, count of failed jobs found / classified transient / retried / confirmed-warming /
flagged hard / Maildoso-skipped, and any 50-cap remainder; artifacts — screenshots, deployed
version marker, `app_jobs` ids retried, ledger row counts. Name the numbers; "a summary" is
not a spec. Any FAILED done-rule is listed, not hidden.

## Hard don'ts
- **Never re-run a warm-up move that pauses live mailboxes without the approval gate** — and
  never retry a hard-failure or ANY Maildoso domain. Cap = 50 transient domains per run.
- **Never re-enable Smartlead warmup on a Maildoso-fleet domain** (they warm externally).
- **Never overwrite an existing `first_rested_at`** — backfill/entry-stamp is
  `on_conflict=domain ignore-duplicates` only. Resetting a rest clock to "+7d from now" is a bug.
- **Never trust the audit backend's re-stamped `restedAt`** as a due source — the ledger's
  `first_rested_at` is authoritative (2026-07-11 "due in 7d forever" bug).
- **Never verify from the app's own success label** — read the ledger and the live view back
  from the destination.
- **Never leave a reachable "—" fallback** for a union domain on any of the three surfaces.
- **Never weaken the ledger truncation/`allow_delete` guard** that stops a flaky refresh wiping
  the ledger.
- **Never exceed a retry cap or report done while any done-rule fails.**
