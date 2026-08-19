-- Lead notes (owner ask 2026-08-19): a free-text scratchpad the rep keeps on a
-- lead, shown in the setter sidebar just below the Timezone row and auto-saved
-- as they type. Lives on the SAME per-lead row as the warm-call enrichment /
-- call disposition (setter_lead_enrichment, keyed by lead_email) so a lead
-- carries ONE private record; written via POST /api/setter/lead-note, which
-- upserts (a note can be jotted before the one-time enrichment row exists).
alter table setter_lead_enrichment
  add column if not exists notes text,
  add column if not exists notes_at timestamptz;
