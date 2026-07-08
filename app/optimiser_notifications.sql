-- Lilly-Optimiser Priority Report findings (v2), one row per
-- (campaign_id, finding_type, title). Populated/kept in sync by
-- app/build_notifications.py. Idempotent upsert target:
-- POST {SUPABASE_URL}/rest/v1/optimiser_notifications?on_conflict=campaign_id,finding_type,title
-- with header Prefer: resolution=merge-duplicates.
--
-- v2 (2026-07-08): rows now mirror the 7-section Priority Report from
-- ~/.claude/skills/lilly-optimiser/SKILL.md exactly. New columns: section,
-- block_number, action_type, api_safe, smartlead_url, claude_prompt,
-- completion_pct, reply_rate. finding_type gained 'performing' and
-- 'lifecycle'. build_notifications.py applies the idempotent ALTER TABLE
-- migration itself (Supabase Management API `database/query` endpoint,
-- SUPABASE_ACCESS_TOKEN, browser User-Agent required). If that path is ever
-- unavailable, run this block by hand once in the Supabase SQL editor.

CREATE TABLE IF NOT EXISTS optimiser_notifications (
  id uuid primary key default gen_random_uuid(),
  campaign_id text not null,
  campaign_name text,
  client text,
  client_id text,
  finding_type text not null check (finding_type in ('needs_optimisation','performing','lifecycle','variant_call','low_reply_flag','distribution_flag','recommended_action','all_clear')),
  -- Report section this finding belongs to: 1-7 per the skill's Priority
  -- Report structure, 0 for all_clear (active campaign under the 1,500-send
  -- reporting threshold).
  section smallint,
  -- Section 7 only: sequential block number across the whole section
  -- (High tier first, then Medium, then Low; within tier by sent desc).
  block_number int,
  priority text,
  title text not null,
  detail text,
  suggested_action text,
  -- pause_campaign | replace_variants | scale_winner | disable_loser |
  -- fix_distribution | run_list_audit | upload_leads | nearing_completion |
  -- kill_threshold_pivot | none
  action_type text,
  -- true ONLY when the executable act is pausing the campaign (the single
  -- Smartlead action safe to run via API per the optimiser guardrails:
  -- pause_campaign, and kill_threshold_pivot where the executable part is
  -- the pause). Everything touching sequences/variants/copy is UI-only.
  api_safe boolean default false,
  smartlead_url text,
  -- Pre-made Claude Code prompt (Section 7 rows of type replace_variants /
  -- scale_winner / disable_loser / kill_threshold_pivot / run_list_audit).
  -- Static string assembly, begins with the skill's mandatory
  -- "SCOPE - DATA AND DRAFTING ONLY, DO NOT BUILD:" block.
  claude_prompt text,
  sent int,
  positive int,
  replied int,
  sent_pos_ratio numeric,
  completion_pct numeric,
  reply_rate numeric,
  -- 'resolved' (v3, 2026-07-08): auto-set by build_notifications.py's
  -- retirement pass when a 'new' finding's key is no longer emitted by the
  -- latest run (never applied to acknowledged/actioned/dismissed rows, which
  -- are CSM-owned state). Flipped back to 'new' if the same key reappears in
  -- a later run.
  status text not null default 'new' check (status in ('new','acknowledged','actioned','dismissed','resolved')),
  created_at timestamptz not null default now(),
  actioned_at timestamptz,
  unique(campaign_id, finding_type, title)
);

CREATE INDEX IF NOT EXISTS idx_optimiser_notifications_client_id
  ON optimiser_notifications (client_id);

-- Idempotent v1 -> v2 migration (safe to re-run; build_notifications.py runs
-- this on every start):
ALTER TABLE optimiser_notifications ADD COLUMN IF NOT EXISTS client_id text;
ALTER TABLE optimiser_notifications ADD COLUMN IF NOT EXISTS section smallint;
ALTER TABLE optimiser_notifications ADD COLUMN IF NOT EXISTS block_number int;
ALTER TABLE optimiser_notifications ADD COLUMN IF NOT EXISTS action_type text;
ALTER TABLE optimiser_notifications ADD COLUMN IF NOT EXISTS api_safe boolean default false;
ALTER TABLE optimiser_notifications ADD COLUMN IF NOT EXISTS smartlead_url text;
ALTER TABLE optimiser_notifications ADD COLUMN IF NOT EXISTS claude_prompt text;
ALTER TABLE optimiser_notifications ADD COLUMN IF NOT EXISTS completion_pct numeric;
ALTER TABLE optimiser_notifications ADD COLUMN IF NOT EXISTS reply_rate numeric;
ALTER TABLE optimiser_notifications ADD COLUMN IF NOT EXISTS replied int;
ALTER TABLE optimiser_notifications DROP CONSTRAINT IF EXISTS optimiser_notifications_finding_type_check;
ALTER TABLE optimiser_notifications ADD CONSTRAINT optimiser_notifications_finding_type_check
  CHECK (finding_type in ('needs_optimisation','performing','lifecycle','variant_call','low_reply_flag','distribution_flag','recommended_action','all_clear'));
ALTER TABLE optimiser_notifications DROP CONSTRAINT IF EXISTS optimiser_notifications_action_type_check;
ALTER TABLE optimiser_notifications ADD CONSTRAINT optimiser_notifications_action_type_check
  CHECK (action_type is null or action_type in ('pause_campaign','replace_variants','scale_winner','disable_loser','fix_distribution','run_list_audit','upload_leads','nearing_completion','kill_threshold_pivot','none'));
ALTER TABLE optimiser_notifications DROP CONSTRAINT IF EXISTS optimiser_notifications_section_check;
ALTER TABLE optimiser_notifications ADD CONSTRAINT optimiser_notifications_section_check
  CHECK (section is null or section between 0 and 7);

-- v3 (2026-07-08): widen the status check constraint to add 'resolved' (see
-- the retirement-pass note on the `status` column above). ALTER TABLE can't
-- modify a CHECK in place, so find whichever constraint is actually on
-- `status` (by definition text, not by an assumed name - a hand-run SQL
-- editor session could have named it differently than the DDL above) and
-- drop + re-add it. Wrapped in a DO block so the DROP is a no-op if no such
-- constraint exists; safe to re-run.
DO $$
DECLARE
  con_name text;
BEGIN
  SELECT con.conname INTO con_name
  FROM pg_constraint con
  JOIN pg_class rel ON rel.oid = con.conrelid
  WHERE rel.relname = 'optimiser_notifications'
    AND con.contype = 'c'
    AND pg_get_constraintdef(con.oid) LIKE '%status%';
  IF con_name IS NOT NULL THEN
    EXECUTE format('ALTER TABLE optimiser_notifications DROP CONSTRAINT %I', con_name);
  END IF;
END $$;
ALTER TABLE optimiser_notifications ADD CONSTRAINT optimiser_notifications_status_check
  CHECK (status in ('new','acknowledged','actioned','dismissed','resolved'));
