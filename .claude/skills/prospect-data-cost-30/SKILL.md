---
name: prospect-data-cost-30
description: Static orchestration skill that produces and proves a plan to cut Navreo's prospect-data spend (email finding, list-building, enrichment, verification) by 30%, using the Supabase data layer as the cache that stops us buying the same data twice. Audits current spend and cache leaks, writes a lever-by-lever savings plan, then verifies the projected savings by replaying the two most common use-cases (list-building and email verification) against the cache in dry-run — no paid API calls, no production skill edits. Use when the user says "run the data cost cutter", "cut prospect data costs", "prove the 30% savings", or "/prospect-data-cost-30".
---

# Prospect-Data Cost Cutter (−30%)

## ⚙ Loop Training Mode: **OFF**   ← flip this line to ON to pause at every step

**ON (default):** pause at EVERY step boundary and wait for the user's explicit approval
before continuing. Before starting a step, check its done-rule first — if it already
passes, report "Step N already passes, skipping" and move to the next pause. Only re-run
steps whose done-rule fails. Show what you're about to do before doing it.

**OFF:** run all steps end-to-end with no pauses. The done-rule checks, skip-if-passing
behaviour, and retry caps stay exactly the same — only the pauses go.

**Retry cap (both modes):** each step retries **max 3** times against its done-rule.
On cap-hit: record the step as FAILED with the reason, continue to the next step if it
doesn't depend on the failed one, and surface every FAILED step in the final report.
Never silently exceed the cap. Never declare the skill done on a cap-hit.

**Zero-spend gate (both modes, non-negotiable):** this skill NEVER makes a paid provider
call (Prospeo, AI Ark, Ocean, TheirStack, MillionVerifier, ListMint) and NEVER edits a
production skill or the live database. It reads Supabase, reads skill files, and writes
reports. It is a plan + proof, not a rollout.

## Goal

A written, evidence-backed plan that cuts prospect-data spend by **≥30%**, with the
savings **measured** (not estimated) on the two most common use-cases:
(A) list-building / DM enrichment, (B) email verification — by replaying recent real
runs and counting which paid calls the Supabase data layer would have made unnecessary.

## Ground truth (verified 2026-07-10 — re-verify in Step 1, don't trust blindly)

- **Cache helper:** `db/navreo_db.py` (project root). Key functions:
  `get_enrichment(entity_type, key, provider, max_age_days=30)`,
  `put_enrichment(...)`, `check_exclusions(client_id, emails, domains)`,
  `log_contact(...)`, `upsert_person(...)`, `canonical_domain(raw)`.
  Supabase project `fnykldftbkrccihdjayl`; keys auto-load from `~/.navreo-keys.env`.
- **Credit models (why re-buying hurts):** Prospeo list-builder = 1 credit/page and
  per-DM enrich credits; AI Ark bills per row returned; TheirStack = 1 credit per JOB
  RETURNED and re-charges on re-fetch (cursor fix already shipped 2026-07-08 — that
  saving is baseline, don't double-count it); MillionVerifier bills per verification.
- **Existing cost defences (baseline, not new savings):** AI-Ark emails arrive
  pre-verified and `upsert_person(provider="ai_ark")` stamps `email_verified_at`, so
  MV already skips them; tam-mapper sends cumulative exclusion lists across providers;
  list-builders hard-abort below 50% fit; TheirStack BUY/ENRICH daily budgets.
- **The suspected leaks (what the plan targets):**
  1. Skills that call a provider without a `get_enrichment` cache check first, or that
     get paid results back and never `put_enrichment` them (bought → thrown away).
  2. Enriching people/domains we've already contacted or suppressed
     (`check_exclusions` + `contact_history` should gate BEFORE enrichment, not after).
  3. Re-verifying emails MV already verified recently — no TTL skip on
     `email_verified_at` for MV-source emails (only AI-Ark ones are skipped today).
  4. Cross-client re-buying: the same DM bought separately for two clients because
     lookups are per-run CSVs, not the shared `persons`/`companies` tables.

## Steps

### Step 1 — Re-verify ground truth + measure the baseline
Confirm every bullet above against current code and data. Then quantify current spend:
list the Supabase tables that record enrichment/verification activity
(`enrichments`, `persons`, `companies`, `contact_history`, `app_activity_log` — confirm
real names via `list_tables`), and pull the last 60 days of paid-provider activity per
provider. Where Supabase can't show credit counts, state the gap explicitly instead of
guessing. Identify the 2 highest-volume recent runs of each target use-case
(A: a `lilly-tam(-v2)` run; B: a `lilly-email-verification` run)
to use as replay material in Steps 4-5.
- **Done-rule:** a baseline table exists (provider × 60-day volume × credit model ×
  est. monthly cost, gaps marked "unknown"), and the chosen replay runs for use-cases
  A and B are named with their input files/campaigns and row counts.

### Step 2 — Cache-leak audit across the skill fleet
Grep every skill in `~/.claude/skills/` that calls Prospeo / AI Ark / Ocean /
TheirStack / MillionVerifier / ListMint and score each against three questions:
(a) cache check (`get_enrichment` or equivalent) before the paid call?
(b) write-back (`put_enrichment` / `upsert_person`) after the paid call?
(c) suppression/dedupe gate (`check_exclusions` + contact history) BEFORE enrichment?
- **Done-rule:** a matrix exists — skill × provider × {cache-first?, write-back?,
  suppression-gate?} — covering at minimum: lilly-tam,
  lilly-tam, lilly-email-verification, lilly-tam,
  lilly-tam, lilly-ocean-tam-builder, lilly-tam,
  lilly-icebreaker, lilly-theirstack-data-processing. Every "no" cell cites the file
  and the line/section that proves it.

### Step 3 — Write the savings plan
Turn Steps 1-2 into ONE plan document at the project root:
`PROSPECT-DATA-COST-PLAN-<date>.md`. For each lever: what changes (which skill/file,
which process step), the mechanism (cache-first / write-back / suppression gate /
verification TTL / cross-client shared lookup), the projected % of current spend saved
with the arithmetic shown, implementation effort (S/M/L), and risk. Include a proposed
**verification TTL policy** (e.g. skip re-verification when `email_verified_at` ≤ 90
days — pick the number from bounce data if Step 1 surfaced any) and a **standard gate
order** for every list-building run: suppression → cache lookup → paid call → write-back.
Levers must sum to ≥30% of baseline; if they don't, say so and list what else it would
take rather than inflating numbers.
- **Done-rule:** the plan file exists, every lever's % traces to Step 1/2 numbers,
  the total is stated, and a "not included / double-count avoided" section lists the
  already-shipped defences (TheirStack cursor, AI-Ark pre-verified skip, tam-mapper
  exclusions).

### Step 4 — Verify use-case A: list-building replay (dry-run, zero spend)
Take Step 1's chosen list-building run. For each input row, replay the NEW gate order
against Supabase only: would `check_exclusions`/contact history have dropped it? would
`get_enrichment`/`persons` have answered it from cache (at the plan's TTL)? Count rows
into: suppressed-skip / cache-hit / would-still-pay. Convert to credits using the
provider's credit model and compare against what the original run actually spent.
- **Done-rule:** a replay report exists with the three counts, the credit arithmetic,
  and a measured % saving for use-case A. No provider API was called (assert this in
  the report).

### Step 5 — Verify use-case B: email-verification replay (dry-run, zero spend)
Same method on Step 1's chosen verification run: for each email, would the TTL rule
(`email_verified_at` fresh enough) or AI-Ark pre-verified stamp have skipped MV? Count
skip vs would-still-verify, convert to MV credits, compare to actual.
- **Done-rule:** a replay report exists with counts, credit arithmetic, and a measured
  % saving for use-case B. No verifier API was called (assert this in the report).

### Step 6 — Final report + next actions
Append to the plan file: measured savings from Steps 4-5 vs the plan's projections,
whether the ≥30% goal is met on the tested use-cases (state plainly if not), any FAILED
steps with reasons, and a short ordered implementation backlog (per-skill edits from
Step 3, smallest-effort-per-% first) explicitly marked **NOT YET ACTIONED — needs
separate sign-off**. Do not implement anything.
- **Done-rule:** the plan file contains the measured-vs-projected table and the
  backlog; the user has been shown the headline numbers.

## Done-rule for the whole skill

`PROSPECT-DATA-COST-PLAN-<date>.md` exists with (1) a baseline, (2) the cache-leak
matrix, (3) levers summing to ≥30% with traceable arithmetic, (4) **measured** replay
savings for both use-cases, and (5) an un-actioned implementation backlog — and zero
paid provider calls were made and zero production files were edited along the way.
