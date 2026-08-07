# Coverage map — signals tool + HeyReach → Supabase (fnykldftbkrccihdjayl)
Audited 2026-07-09 against ~/navreo-signals/app/server.py (5405 lines).

## Re-audit 2026-07-09 evening (commit ca82dea) — gaps CLOSED
Endpoints shipped by other streams after the ledger landed, all returning before
the central log_activity call. All eight now log (prod-proven: login probes +
live fix-signatures rows in app_activity_log):
- POST /api/auth/login — attempt + outcome, email only, NEVER the password
- POST /api/jobs/{id}/cancel — cancel/job (logged on success only)
- POST /api/verify-campaign · /api/verify-remove (destructive) · /api/verify-dismiss
- POST /api/process-new-selected — Smartlead mailbox mutations
- POST /api/deliverability/_audit/refresh — audit_refresh
- POST /api/deliverability/* (proxy) — apply signatures, process-new, warmup changes, etc.
Deliberately NOT logged: /api/deliverability/_mock/* (DELIV_MOCK=1 test-only, 404 in prod);
unauthenticated gated calls (rejected before any handler; the login attempt itself IS logged).

## (a) App endpoints (server.py)

| Endpoint / action | What it changes | Verdict |
|---|---|---|
| POST /api/clients (save_client) | client profile | RECORDED → `clients` (entity) · GAP (no change audit) |
| POST /api/role-feedback | role thumbs | RECORDED → `role_feedback` |
| POST /api/sources (save_draft) | signal source create | RECORDED → `signal_sources` · GAP (audit) |
| POST /api/sources/update | source edit / pause / destination | RECORDED → `signal_sources` · GAP (audit) |
| POST /api/sources/duplicate | source copy | RECORDED → `signal_sources` · GAP (audit) |
| POST /api/sources/pull | manual pull + auto-push | RECORDED → `signal_leads` (status, pushed_to), `signals` · GAP (audit) |
| POST /api/sources/provision-engagement | Trigify wiring | RECORDED → `signal_sources` · GAP (audit) |
| POST /api/trigify-webhook | inbound engagement events | RECORDED → `engagement_events` |
| POST /api/qa-history (save_qa_run) | QA run log | **GAP** — local JSON only (`qa_history.json`) |
| POST /api/campaign-drafts (+ update/duplicate/restore/purge) | campaign lifecycle | RECORDED → `campaign_drafts`, `campaign_versions` · GAP (audit incl. purge/delete) |
| POST /api/notifications/{id}/execute · PATCH /api/notifications/{id} | optimiser actions / status | RECORDED → `optimiser_notifications` (RLS **off** — pre-existing) |
| POST /api/cron/pull-all | 3-hourly batch pull + autopush | RECORDED → `signal_cron_runs`, `signal_leads` |
| Push to Smartlead / HeyReach (inside pull/autopush) | outreach push | RECORDED → `signal_leads.pushed_to` · GAP (no per-push audit row) |
| POST previews (/api/preview/*, suggest-location, client-prefill, role-suggest, tam-map, strategy-map, outreach-destinations) | ephemeral user activity | **GAP** — nothing recorded anywhere |
| Deletes (sb_delete_source, sb_delete_doc) | destructive removals | **GAP** — rows vanish with no trace of who/when |

**Fix for every GAP-audit row:** append-only `app_activity_log`, written centrally in do_POST/do_PATCH dispatch (one choke point, covers every current and future endpoint).

## (b) HeyReach REST objects (api.heyreach.io/api/public)

| Object | Endpoint | Verdict |
|---|---|---|
| LinkedIn sender accounts | /li_account/GetAll | **GAP** → `heyreach_senders` |
| Lists | /list/GetAll | **GAP** → `heyreach_lists` |
| Leads per list | /list/GetLeadsFromList | **GAP** → `heyreach_leads` |
| Campaigns | /campaign/GetAll | **GAP** → `heyreach_campaigns` |
| Campaign stats | /stats/GetOverallStats | **GAP** → `heyreach_stats_daily` |
| Inbox conversations | /inbox/GetConversationsV2 | **GAP** → `heyreach_conversations` |

Snapshot-diff on each daily pull appends change rows to `app_activity_log` (actor = "heyreach_sync"), so HeyReach-side activity (replies, connects, stat movement) is documented, not just mirrored.
