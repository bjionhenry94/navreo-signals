---
name: recontact-250k-agrade-batches
description: Build the first-batch audience for the five Recontact 250k drafted campaigns - select only A/A+ on-ICP titled leads from each pool list, sweep collisions/suppressions, ListMint-verify with a top-up loop until 3,500 verified per campaign (or the pool's honest maximum), stage the result as a tool list, and hand off to lilly-upload-gate. Never pushes to Smartlead itself. Trigger: "build the A-grade verified batches", "run the 250k A-grade batch builder", "/recontact-250k-agrade-batches".
---

# Recontact 250k - A-grade verified batches

## ⚙ Loop Training Mode: **ON**   ← flip this line to OFF to run autonomously

**ON (default):** pause at EVERY step boundary and wait for the user's explicit approval
before continuing. Before starting a step, check its done-rule first - if it already
passes, report "Step N already passes, skipping" and move to the next pause. Only re-run
steps whose done-rule fails. Show what you're about to do before doing it.

**OFF:** run all steps end-to-end with no pauses. The done-rule checks, skip-if-passing
behaviour, and retry caps stay exactly the same - only the pauses go.

**Retry cap (both modes):** each step retries **max 3** times against its done-rule.
On cap-hit: record the step FAILED with the reason, continue only to steps that don't
depend on it, and surface every FAILED step in the final report. Never declare done on
a cap-hit.

## Goal

**For each of the five Recontact 250k drafted campaigns: a staged prospect list of
on-ICP leads (title classifies A/A+ buckets) whose emails are ListMint-verified -
3,500 per campaign, or the pool's honest maximum where the pool is smaller, with any
deficit stated plainly.** The output is a staged list per campaign, mirrored to the
signals tool's Lists page, ready for `lilly-upload-gate`. This skill NEVER calls any
Smartlead lead-push - upload happens only through the gate.

## Config (baked)

```yaml
CAMPAIGNS:                    # segment -> pool list id, Smartlead campaign id
  A: {list: d84c4881-fe13-4375-8368-d897a380bca4, campaign: 3708724}   # SaaS & Tech Sales Leaders / CEOs
  B: {list: 3ad89fce-772c-46d5-9989-e86423806301, campaign: 3708725}   # Industry Verticals
  C: {list: a0eff7e1-6a5f-4187-9078-83ca27b9abe6, campaign: 3708726}   # SEO/GEO Agencies
  D: {list: 2f2311b6-0616-44c0-a2c2-eb68915d8486, campaign: 3708727}   # General B2B Sales Leaders
  E: {list: df1c4575-b312-4390-801b-58182ac8a6ac, campaign: 3708728}   # Warm Followers

TARGET_PER_CAMPAIGN: 3500
ON_ICP_BUCKETS: [OWNER/EXEC, SALES-LEADER, SALES-SUPPORT]   # lilly-list-audit classifier
VERIFY_KEEP: [valid, catch_all_valid]     # ListMint verdicts that count as verified (flag catch_all)
CACHE_TTL_DAYS: 90                        # people.email_verified_at inside TTL = skip, no credit
LM_TRANCHE: 500                           # emails per ListMint batch call
TOPUP_BUFFER_PCT: 15                      # over-select candidates so LM failures don't force a second loop
RETRY_CAP: 3
STAGING_TABLE: r250k_batch                # existing Supabase staging (reuse; do not recreate blindly)
```

**Known honest shortfalls (from the 2026-07-24 audit - a done-rule that cannot pass
is a bug, so these are pre-declared):**
- **B** has only 407 titled rows in the whole pool (~352 on-ICP). Max possible ≈ 350. The
  other 29,811 rows are campaign-inferred (no title) and can NEVER score A - they are out
  of scope for this skill by definition.
- **D** has 3,722 titled (~80% on-ICP). Max possible ≈ 2,990 before verification losses.
- **E** has zero titled rows (warm followers). Max possible = 0 A-grade rows. E is
  reported as "not gradeable on title - needs a separate ruling", never silently padded.
A/C can genuinely reach 3,500. Deficits are REPORTED, never backfilled with off-ICP or
untitled rows - that would defeat the goal.

## Ground truth

- Keys: `~/.navreo-keys.env` (`LISTMINT_API_KEY`, `SUPABASE_*`, `SMARTLEAD_API_KEY`).
  curl for all HTTPS (this Mac's python urllib has no SSL certs).
- Classifier: `~/.claude/skills/lilly-list-audit/scripts/audit_campaign.py::classify()` -
  word-boundary abbreviations, partner/VP rules. Use it verbatim, never a rewrite.
- ListMint: `POST https://api.listmint.io/api/verify-emails?return=true&api-key=<key>`,
  body `{"emails":[...]}` → `results[{email, result}]`. Auth is the QUERY param.
- Every real ListMint call logs to `provider_usage` (provider `listmint`, credits =
  batch size, source_id `recontact-250k-agrade-batches`); verdicts write back to
  `people` (`email_verification`, `email_verified_at`) via PostgREST upsert
  `on_conflict=email` with uniform keys.
- Collision rules are lilly-upload-gate Step 5's four checks (contact_history dossier,
  suppressions, Navreo positive-repliers w/ corrections overlay, cross-campaign
  collisions incl. live check on ACTIVE campaigns via leads-export intersect).
- PostgREST pages cap at 1,000 rows - paginate with Range headers.
- Supabase RPC/statement work must stay sargable; batch big UPDATEs by segment.

## Steps

### Step 1 - A-grade candidate selection
Per pool list: classify EVERY titled row with the lilly-list-audit classifier.
Candidates = rows whose bucket is in `ON_ICP_BUCKETS`. Untitled rows are excluded by
definition (they cannot score A). Record per-pool: titled, on-ICP, candidate count.
- **Done-rule:** a per-segment candidate table exists (titled / on-ICP / candidates);
  every candidate row carries its bucket; B/D/E shortfalls restated against
  `TARGET_PER_CAMPAIGN`.

### Step 2 - Collision + suppression sweep (free, before paid checks)
Run lilly-upload-gate Step 5's four checks over all candidates in set-based SQL
(never row-by-row): suppressions → hard drop; Navreo positive repliers (with
`reply_category_corrections` overlay) → drop to positive pipeline; active enrollment
in another campaign → drop; sends within 30 days → drop; cross-batch duplicate emails
→ keep first segment only. Then the live check: export leads of every ACTIVE Smartlead
campaign (one `leads-export` call each, ≤150/min) and intersect - Navreo↔Arnic hits are
dossier-only, other cross-client hits WARN, same-client hits drop.
- **Done-rule:** every candidate swept against all sources; per-segment counts
  (clean / dropped-per-reason) recorded with dossiers on every drop.

### Step 3 - ListMint verify with top-up loop
Per segment, work through clean candidates in selection order:
1. Cache skip: `people.email_verification` in (good, ok, valid) AND
   `email_verified_at` within `CACHE_TTL_DAYS` → verified, no credit.
2. Others: ListMint in `LM_TRANCHE` batches. Keep `VERIFY_KEEP` verdicts
   (catch_all_valid kept but flagged); everything else fails the lead, never the run.
3. After each tranche: verdicts → `people`, credits → `provider_usage`.
4. Top up: while verified < min(TARGET, pool max) and clean candidates remain,
   pull the next tranche of candidates through 1-3.
- **Done-rule:** per segment, verified count = `TARGET_PER_CAMPAIGN` OR every clean
  candidate has a verdict (pool exhausted - deficit stated); provider_usage credit
  rows sum exactly to real ListMint calls; zero verified leads lack a verdict source
  (`cache_ttl` / `listmint_valid` / `listmint_catch_all`).

### Step 4 - Stage + mirror to the tool
Stage each segment's verified batch (email, name, title, company, domain, country,
linkedin_url, icebreaker, bucket, verdict, verify source) in `STAGING_TABLE`, and
create/update ONE tool list per segment named
`Recontact 250k - <seg> first batch (A-grade, verified)` with exactly those rows
(list-autopush conventions: full fidelity, row_count stamped). Never touch the pool
lists themselves; never put a preview `prospects` array on any source doc (mirror-wipe
law, incident 2026-07-24).
- **Done-rule:** five batch lists exist in the tool, `row_count` = staged verified
  count per segment, verified via the tool's own `/api/lists` (authed curl).

### Step 5 - Report + hand-off (no upload)
One table: per segment - pool size → titled → A-grade candidates → survived sweep →
verified (with credit spend) → deficit vs 3,500 + why. State catch_all counts
separately. End with the literal hand-off: "Upload runs ONLY via /lilly-upload-gate
on these batch lists." Confirm zero Smartlead lead-push calls were made.
- **Done-rule:** report delivered; every FAILED/capped step surfaced; no
  add_leads/push call appears anywhere in the run.

## Hard don'ts
- Never pad a shortfall with off-ICP or untitled rows - the deficit is the honest answer.
- Never spend a ListMint credit on a cache-fresh email, and never make a call without
  its provider_usage row.
- Never write a `prospects` preview array onto a source doc (boot mirror-sync wipes
  the list - proven 2026-07-24).
- Never call any Smartlead lead-push from this skill - `lilly-upload-gate` is the only
  door, and it runs as its own gated flow.
- Never exceed a retry cap or report done while any done-rule fails.
