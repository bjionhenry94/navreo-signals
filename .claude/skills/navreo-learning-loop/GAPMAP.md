# Learning Loop Gap Map (Step 1 output, 2026-07-11)

Preflight: 7/7 systems responded (Supabase, Smartlead, HeyReach, Notion, Fathom, Slack, local scheduler).
Slack scope finding: connector currently sees ONLY #general (C06JEBN56UE). No client channels visible (likely wrong workspace or limited scope). Roster starts at #general; re-auth flagged in handoff.

| Mech | Status | Evidence |
|---|---|---|
| M0 person_identities | MISSING | Seed sources ready: people 568k rows (id bigint, email citext, linkedin_slug), contact_history 1.11M (person_id, email) |
| M1 campaign_meta + variant_registry | MISSING | Sources: campaigns 778 rows; campaign_versions 1,005 rows WITH sequences jsonb (hashable copy history); heyreach_campaigns payload jsonb |
| M2 variant_stats_daily + lead_variant_assignments | MISSING | Bonus found: campaign_versions.variant_stats jsonb = historical per-variant stats already snapshotted; sent_messages.email_seq_number = per-lead step for replay |
| M3 decision_ledger + sequence_structure | PARTIAL | app_activity_log EXISTS (signals tool + HeyReach diffs, 1,173 rows); campaign_versions = settings snapshots; ledger + structure tables MISSING |
| M4 meeting_events + meetings | MISSING | Sources: replies.category, contact_history.lead_category (Call-booked tags), Fathom API live (10 meetings on page 1) |
| M5 inbound annotations + view | PARTIAL | replies 18.2k + sent_messages 6.1k + reply_category_corrections 213 EXIST; annotations table + inbound_handling_log view MISSING |
| M6 proposals + weekly_reviews | MISSING | pgcrypto installed (hashing), trigger support standard |
| M7 weekly review routine | MISSING | Scheduled-task infra proven (13 existing local tasks, 3 enabled); no review task exists; pg_cron 1.6.4 + pg_net installed for dead-man |
| M8 sync_runs + nightly checks | PARTIAL | sync_progress (smartlead sync) + signal_cron_runs (signals) exist per-pipeline; unified sync_runs MISSING; optimiser_notifications reused as the existing alert surface |
| M9 comms layer | MISSING | Fathom OK; Slack limited to #general pending re-auth; no comms tables exist |

Skip list (EXISTS, untouched): raw activity capture (contact_history, replies, sent_messages, heyreach_*, mailbox_stats_daily, provider_usage, suppressions, app_activity_log, qa gate tables).
