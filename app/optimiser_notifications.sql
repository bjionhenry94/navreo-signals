-- Lilly-Optimiser-style findings, one row per (campaign_id, finding_type, title).
-- Populated/kept in sync by app/build_notifications.py. Idempotent upsert target:
-- POST {SUPABASE_URL}/rest/v1/optimiser_notifications?on_conflict=campaign_id,finding_type,title
-- with header Prefer: resolution=merge-duplicates.
--
-- This file is a reference copy of the DDL. build_notifications.py creates the
-- table itself (via the Supabase Management API `database/query` endpoint,
-- using SUPABASE_ACCESS_TOKEN) the first time it runs against a project that
-- doesn't have it yet. If that path is ever unavailable, run this block by
-- hand once in the Supabase SQL editor before running the script.

CREATE TABLE IF NOT EXISTS optimiser_notifications (
  id uuid primary key default gen_random_uuid(),
  campaign_id text not null,
  campaign_name text,
  client text,
  finding_type text not null check (finding_type in ('needs_optimisation','variant_call','low_reply_flag','distribution_flag','recommended_action','all_clear')),
  priority text,
  title text not null,
  detail text,
  suggested_action text,
  sent int,
  positive int,
  sent_pos_ratio numeric,
  status text not null default 'new' check (status in ('new','acknowledged','actioned','dismissed')),
  created_at timestamptz not null default now(),
  actioned_at timestamptz,
  unique(campaign_id, finding_type, title)
);
