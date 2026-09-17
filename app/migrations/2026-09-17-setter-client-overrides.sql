-- Click the client pill to re-file a conversation (owner ask 2026-09-17).
-- One row per lead a human has filed under a client by hand; it outranks the
-- campaign-derived label everywhere the setter shows a client (pill, client
-- filter, the About-the-client fold). Keyed by (workspace, lead_email), NOT a
-- setter_queue id: a queue row is deleted and re-inserted on every re-intake
-- and a re-reply is a brand-new row, so a per-row flag would silently vanish.
-- Written only via POST /api/setter/queue/client (owner-only); deleting the
-- row puts the lead back on the automatic label. A label for Navreo's own
-- inbox only - client share-link scope and Slack routing stay on the campaign.
create table if not exists setter_client_overrides (
  workspace    text        not null default 'navreo',
  lead_email   text        not null,
  client_label text        not null,
  set_at       timestamptz not null default now(),
  primary key (workspace, lead_email)
);
-- Service-role access only, same as every other setter table.
alter table setter_client_overrides enable row level security;
