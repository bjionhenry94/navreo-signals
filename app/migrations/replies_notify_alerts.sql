-- Ever-positive alert sweep (once-positive-always-notify, 2026-07-22).
-- Marker columns on the replies archive: notify_alerted_at is stamped only
-- after the alert hook accepted the Slack post (fail-closed; unmarked rows
-- retry on every 3-min reply-sync tick). notify_kind records WHY a row was
-- stamped: ever-positive-alerted | positive-covered (module 33 / routeB own
-- fresh positives + still-positive re-replies) | no-positive-history |
-- seeded-pre-launch (backlog stamped at ship time so history never floods
-- Slack; the one exception, replies id 19418, is the gabriel@silver.dev
-- Jul-20 miss this feature exists to catch — left unstamped so the first
-- live tick delivers the alert the original event never got).
alter table replies add column if not exists notify_alerted_at timestamptz;
alter table replies add column if not exists notify_kind text;
create index if not exists replies_notify_pending
    on replies (workspace, replied_at) where notify_alerted_at is null;
update replies
   set notify_alerted_at = now(), notify_kind = 'seeded-pre-launch'
 where notify_alerted_at is null and id <> 19418;
