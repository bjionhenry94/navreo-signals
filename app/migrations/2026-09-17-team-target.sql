-- Team Target page (owner ask 2026-09-17): the whole team's shared meetings
-- board — how many meetings we've booked this month vs the target of 4 ATTENDED
-- meetings per active sending client, who has said yes and is waiting, and what
-- happened to each meeting. "Said yes" and "booked" leads are pulled live from
-- the reply archive (Meeting Request / Call Booked, client campaigns only, never
-- Navreo's own). This table holds ONLY what the archive can't know: the human
-- outcome of a meeting (attended / no-show / cancelled / not a fit), meetings a
-- teammate adds by hand, and who did each edit + when — so the page reads as a
-- shared, editable board.
--
-- Two kinds of row:
--   * an OVERRIDE of an auto-pulled lead — id = 'ovr:<workspace>:<lead_email>',
--     so a re-edit of the same lead upserts in place; carries the human status.
--   * a HAND-ADD — id = 'man:<uuid>', lead_email may be null; always shown.
-- Counting rule (owner ruling 2026-09-17): only status='attended' counts toward
-- the target. 'booked' shows as still-to-happen; no_show/cancelled/not_fit stay
-- visible but never count. Deleting a row drops the human outcome (an auto lead
-- falls back to its archive status).
--
-- Apply against the navreo-signals Supabase project. Service-role access only,
-- same as every other operational table.
create table if not exists team_meetings (
  id            text        primary key,
  workspace     text        not null default 'navreo',
  lead_email    text,
  client_label  text        not null,
  person        text        not null default '',
  company       text        not null default '',
  status        text        not null,
  meeting_date  date,
  said_yes_on   date,
  source        text        not null default 'hand',
  created_by    text,
  created_at    timestamptz not null default now(),
  updated_by    text,
  updated_at    timestamptz not null default now()
);

-- overlay auto leads by (workspace, lead_email); newest-touched drives the feed
create index if not exists team_meetings_ws_email_idx on team_meetings (workspace, lead_email);
create index if not exists team_meetings_updated_idx  on team_meetings (updated_at desc);

alter table team_meetings enable row level security;
