# Step 7 — 20 use-case verification (2026-07-09)
Every use-case a user can perform on https://navreo-signals.onrender.com/app/, traced to the Supabase table(s) that record it. LIVE = executed for real today and row confirmed.

| # | Use-case | Recorded in | Verdict |
|---|---|---|---|
| 1 | Create a new signal source in the wizard | `signal_sources` + `app_activity_log` (create/source) | RECORDED |
| 2 | Edit a source's targeting/keywords | `signal_sources` upsert + ledger (update/source) | RECORDED |
| 3 | Pause / reactivate a source | `signal_sources.active` + ledger | RECORDED |
| 4 | Duplicate a source | new `signal_sources` row + ledger | RECORDED |
| 5 | Delete a source | ledger row survives the delete (endpoint+payload); rows removed by sb_delete_source | RECORDED |
| 6 | Manual "Pull now" on a source | `signal_leads`, `signals` + ledger (pull/source) | RECORDED |
| 7 | 3-hourly autopilot batch pull | `signal_cron_runs` summary + `signal_leads` + ledger (actor=cron) — **LIVE** (pre-existing) | RECORDED |
| 8 | Lead auto-pushed to Smartlead | `signal_leads.status='pushed'`, `pushed_to='smartlead:<id>'` | RECORDED |
| 9 | Lead auto-pushed to HeyReach | `signal_leads.pushed_to='heyreach:<list>'` + member appears in `heyreach_leads` next sync | RECORDED |
| 10 | Reject a lead in the Leads tab | `signal_leads.status='rejected'` + ledger | RECORDED |
| 11 | Create a campaign draft | `campaign_drafts` + `campaign_versions` + ledger | RECORDED |
| 12 | Edit campaign goal/copy | `campaign_drafts` + `campaign_versions` + ledger | RECORDED |
| 13 | Restore a deleted campaign | ledger (restore) + `campaign_drafts.deleted_at` cleared | RECORDED |
| 14 | Purge a campaign permanently | ledger delete row survives after the row is gone | RECORDED |
| 15 | Save a client profile / ICP | `clients` + ledger — **LIVE** (client-prefill preview row id 31 on production) | RECORDED |
| 16 | Role suggestion thumbs up/down | `role_feedback` + ledger | RECORDED |
| 17 | Run a preview (hiring/companies/lookalike/people/TAM) | ledger preview row — previously completely invisible | RECORDED |
| 18 | Save a QA run | ledger (create/qa_run) — **LIVE** (row id 1) | RECORDED |
| 19 | Action/dismiss an optimiser notification | `optimiser_notifications` + ledger (execute / status) | RECORDED |
| 20 | HeyReach-side activity with NO app involvement (new inbox reply, campaign stat movement, lead added in HeyReach UI) | new hash-row in `heyreach_conversations` / `heyreach_campaign_stats` / `heyreach_leads` on next sync + sync summary in ledger — **LIVE** (2nd sync run: 3 changed conversations, 5,888 new leads, unchanged objects 0) | RECORDED |

Bonus, organically proven during the run: Lists-page actions (favourite/move/create-folder) from a parallel session landed ledger rows 25–30/32 in real time; manual HeyReach sync trigger landed rows 2/4/17.

**Result: 20/20 RECORDED, 4 verified live (≥3 required). Done-rule met.**
