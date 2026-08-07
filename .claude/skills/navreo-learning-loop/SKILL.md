---
name: navreo-learning-loop
description: Phase-1 orchestrator that installs Navreo's self-learning recording layer (M0-M9; identity spine, campaign/variant metadata, reset-proof per-lead stats, decision ledger, meetings spine, inbound corpus, proposals flywheel, pipeline health, comms context layer capturing Fathom transcripts + Slack channels into structured context events) plus the Monday Weekly Learning Review that publishes insights and awaiting-approval proposals to Notion. RECORD-ONLY; it never changes campaigns, copy, lists or settings, and every proposed improvement waits for human approval. Use when the user says "run the learning loop install", "install the recording mechanisms", "set up the weekly learning review", "run the learning loop", or "/navreo-learning-loop".
---

# Navreo Learning Loop (Phase 1: record, review, propose. Never apply.)

## LOOP TRAINING MODE (the toggle: edit the line below to flip it)

LOOP_TRAINING_MODE: OFF

Rules when ON (default):
- Pause at EVERY step and wait for Bjion's approval before continuing.
- Skip any step that already passes its done-rule.
- Only re-run steps that fail.
- Max 3 attempts per step, then halt and report. Never loop forever.

Rules when OFF:
- Run autonomously, no pauses.
- Keep every done-rule check and the 3-attempt retry cap.

Human-gated in BOTH modes (never autonomous): campaign_meta backfill confirmation, proposal approvals, enabling RLS on the 3 existing exposed tables, and anything that would mutate a campaign, sequence, list or setting (which this skill must never do anyway).

## Goal

Install the recording mechanisms that let the platform learn what drives meetings (lists, offers, copy, optimisation decisions, inbound handling), cross-platform (Smartlead + HeyReach) and cross-user (Bjion, Asad, Yasir, skills), PLUS the comms context that explains the numbers (Fathom transcripts incl. Google Meet calls, Slack across every team/client channel, distilled into structured context events: provider deaths, deliverability incidents, client decisions). Then stand up a weekly review that publishes insights and actionable proposed changes to Notion, citing context before theories. Full specification: PLAN.md in this folder (panel-approved 8.0/10, 3 rounds, 15 expert reviews, plus a comms-layer delta review).

## Hard rules (any mode)

1. RECORD-ONLY. Writes are limited to: new Supabase tables/views/roles listed below, wrapped extensions of the existing sync scripts, one Notion parent page ("Weekly Learning Reviews"), two scheduled jobs. Nothing else, ever.
2. The weekly review PROPOSES; it never applies. Proposals move to approved only via the human-held approver role in the Supabase dashboard (DB trigger enforces approved_by + approval_evidence; credential never in agent-readable files).
3. Additive and reversible: new tables only, append-only sync extensions, failure-isolated from existing sync stages, each scheduled job deletable in one command.
4. Suppression consulted at write time in every stage; purged PII can never be resurrected by re-runs.
5. Notion pages carry aggregates and internal IDs only; never lead emails, names or reply text.
6. Guardrails baked into all analysis: reply categories never compared one-category-across-periods; corrections applied before positive counts; manual triage tags authoritative; opens never evidential; deliverability confounder rule before any copy/mechanism claim; anomalies must cite matching HUMAN-CONFIRMED context events (+/-14 days) before any copy/list/mechanism theory (unconfirmed candidates can never redirect or suppress a proposal); Benjamini-Hochberg correction + minimum-sample gates (200 sends / 5 positives); concurrent-exposure within-campaign contrasts outrank pooled observational cuts.
7. Comms governance: raw transcripts and Slack text leave Supabase ONLY to the extraction endpoint (Anthropic API, zero-data-retention no-training terms); Notion gets one-line CONFIRMED event summaries + source links only, never candidates; Slack DMs and private channels excluded by default; in-Slack deletions honoured via tombstones that propagate to citing events; the comms corpus is never training data without its own separate recorded approval; purge paths client-keyed AND team-member-keyed, verified nightly; 24-month rolling retention on raw comms text.

## The mechanisms (what "installed" means)

| ID | Install | Key |
|---|---|---|
| M0 | person_identities resolution table, seeded from existing people + contact_history | person_id |
| M1 | campaign_meta + variant_registry (offer_type per variant, template_hash, validity intervals, lineage) + human-confirmed backfill + build-skill instrumentation | variant_uid = platform+campaign+step+template_hash+rev |
| M2 | variant_stats_daily (cumulative + delta, day-0 baseline rule, reset apportionment) + lead_variant_assignments (temporal resolution; HeyReach descoped to campaign+step) + bounded historical replay | (date, platform, campaign, variant_uid) |
| M3 | decision_ledger (skill helper + daily settings/sequence snapshot-diff + app_activity_log view) + sequence_structure per campaign version | deterministic idempotency hash |
| M4 | meeting_events staging (calendar/booking feed first-class; tags corroborate; Fathom = held) -> deterministic merge into meetings (tri-state held_status, qualified flag, versioned attribution, reconciliation alerts) + historical seed | (source_platform, source_event_id) |
| M5 | inbound_handling_log view + annotations (latency, responder, draft-vs-final diffs, categoriser_version) + stratified rubric sampling + monthly categoriser accuracy audit | reply_id |
| M6 | proposals (pre-registered measurement plan mandatory; DB-trigger approval gate; add-variant-not-edit framing; 3-week stale expiry) + weekly_reviews | proposal_id |
| M7 | Weekly review routine: local schedule Mon 07:00 Europe/London + freshness preflight (fail-closed: DEGRADED page, no proposals) + transactional writes + pg_cron dead-man check Mon 12:00 + read-only review role + scoped Notion token | review period |
| M8 | sync_runs ledger + nightly checks (staleness, orphans, coverage, reconciliation, purge verification, trigger/grant integrity, comms staleness + channel coverage + extraction backlog) + numeric Phase-2 readiness gates | stage |
| M9 | comms context layer: comms_transcripts (daily Fathom poll, shared with M4) + slack_messages (watermark + trailing 7-day re-scan, 30-day open-threads reply pass, guarded self-healing tombstones, roster-add acknowledge line; public + client channels; DMs/private excluded by default) + context_events (daily bounded LLM extraction via Anthropic API under ZDR terms, content-hash extraction ledger, entity resolution at write time, span-merging dedupe algorithm, review_status pending/confirmed/dismissed, ONLY confirmed events citable, source excerpt at confirm time, Friday candidate digest, pending-context flag on affected proposals, private confirm queue capped 15/week) + anomaly-explanation rule + grant-layer raw-text block on the review role + backfill (full Fathom history, 12mo Slack burn-down on pg_cron->Render, batch-review mode) | (channel_id, ts) / recording_id / event span |

## Steps (static; each step max 3 attempts, then halt and report)

Step 0. Preflight.
Do: one read call each to Supabase, Smartlead, HeyReach, Notion, Fathom, Slack, and the local scheduler.
Done-rule: 7/7 respond.

Step 1. Gap inventory.
Do: verify M0-M9 against the live schema and running jobs; mark each EXISTS / PARTIAL / MISSING; write the gap map to this folder as GAPMAP.md.
Done-rule: gap map covers all ten mechanisms with evidence (table names, row counts, job names, channel roster). Mechanisms marked EXISTS are skipped in later steps.

Step 2. Schema install.
Do: additive migrations for missing tables (PKs, upserts, validity intervals, staging tables per PLAN.md), RLS policies, the read-only review role, the approver role, the proposals trigger. Present the RLS-enable SQL for the 3 existing exposed tables for approval; apply only if approved.
Done-rule: all tables present in list_tables; smoke insert/select/delete succeeds on each; the review role provably cannot write outside proposals/weekly_reviews; the trigger provably rejects an approval transition without approved_by + approval_evidence.

Step 3. Recorder wiring + backfill.
Do: sync-stage extensions (M2 both layers, temporal resolution), snapshot-diff feeds (M3 + sequence_structure), meeting_events feeds + merge job (M4), inbound view + annotations + draft capture (M5), comms ingest: Fathom transcript capture off the shared M4 poll, per-channel Slack watermark pull, daily context-event extraction pass (M9), person_identities resolution in each stage (M0), skill instrumentation helper (M1/M3), sync_runs + nightly checks + orphan detector + purge verification (M8). Run backfills: person_identities seed, campaign_versions -> variant_registry hashing, bounded sent_messages replay, meeting_events historical seed, full Fathom history + 12 months of Slack per rostered channel, human-confirmed campaign_meta backfill.
Done-rule: at least one real row from live data in every new table/view (including comms_transcripts, slack_messages, and at least one extracted context_event), AND a deliberately-injected sync failure appears in sync_runs and raises an alert, AND backfill coverage is reported (campaigns tagged, variants hashed, assignments replayed, meetings seeded, channels ingested vs roster, transcripts captured).

Step 4. Weekly review routine.
Do: create the local weekly schedule (Mon 07:00 Europe/London), the pg_cron dead-man check (Mon 12:00), the scoped Notion integration + "Weekly Learning Reviews" parent page; run one dry-run.
Done-rule: a complete Notion review page exists with all 11 sections (PLAN.md section 4, including "Context this week") populated from real data, zero applied changes, ending with "Proposed changes (awaiting approval)"; AND the freshness preflight demonstrably blocks proposals when a source is made artificially stale.

Step 5. Handoff.
Do: write the install summary (what was installed, where, the off-switch for each piece), restate the record-only standing rule, the toggle documentation, the 30-minute weekly human budget and its triage order (cut approvals-nagging first, then meeting corrections, then rubric ratings; event confirmations last), and the Phase-2 readiness gates.
Done-rule: summary delivered in chat; in Training Mode, Bjion acknowledges.

## Overall done-rule

The install is DONE when: all six step done-rules pass; the recording layer is watching itself (M8 alerts proven by injected failure); the first review page is live in Notion with zero applied changes; and no campaign, sequence, lead list or platform setting was modified by anything in this skill.

Phase 2 (auto-apply) may not even be PROPOSED until the readiness gates hold: campaign_meta coverage >= 95%, Smartlead variant-assignment coverage >= 90%, high-confidence meeting joins >= 80%, booked-feed coverage >= 85%, attribution precision 90% CI lower bound >= 85%, 4 consecutive non-degraded reviews.

## Rollback / off-switches

- Weekly review: delete the local scheduled task (one command).
- Dead-man check: drop the pg_cron job (one command).
- Sync extensions: each new stage has an enabled flag; existing sync stages are untouched and unaffected.
- Tables: all new; can be dropped without touching any pre-existing data.
