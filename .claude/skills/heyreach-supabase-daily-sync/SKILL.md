---
name: heyreach-supabase-daily-sync
description: Static orchestration skill that builds the daily HeyReach→Supabase snapshot sync, mirroring the existing smartlead-daily-sync (edge function + pg_cron tick, zero Claude credits). Snapshots all available HeyReach data — LinkedIn accounts, lists, campaigns, per-campaign stats, leads, and inbox conversations — into heyreach_* tables in project fnykldftbkrccihdjayl, with hash-deduped raw payloads so the database holds an ongoing record of all HeyReach activity. Fixed step list with done-rules, retry cap, and a Loop Training Mode toggle (ON by default). Ends with a mock scheduled run that proves data is actually being pulled. Use when the user says "set up the HeyReach Supabase sync", "run the HeyReach daily sync build", "document HeyReach changes in Supabase", or "/heyreach-supabase-daily-sync".
---

# heyreach-supabase-daily-sync

**Goal:** the Supabase database (project `fnykldftbkrccihdjayl`) keeps an ongoing record of all available HeyReach data, snapshotting activity daily — exactly like the existing Smartlead daily sync does. Fully external once built (pg_cron → pg_net → edge function; ZERO Claude credits per run).

Static loop — the steps below are fixed, each has a checkable done-rule, and Loop Training Mode controls whether you pause between them.

---

## ⚙️ LOOP TRAINING MODE  →  **ON** (default)

Flip it by editing this one line:

    LOOP_TRAINING_MODE = ON        # ON = approve every step · OFF = run autonomous

**When ON**
- Pause at the end of **every** step and wait for my explicit approval before starting the next.
- Before running a step, check its done-rule first. **If it already passes, skip it** — say so and move on.
- Only (re-)run steps that fail their done-rule.
- Retry cap applies (see below). Never loop a step forever.

**When OFF**
- Run all steps autonomously, no pauses.
- Still check every step's done-rule and still honour the retry cap. Report at the end, not between steps.

**Retry cap (both modes):** any single step retries **max 3** times against its done-rule. On cap-hit, stop that step, record it as FAILED with the reason, keep going where later steps don't depend on it, and surface it in the final report. Never silently exceed.

---

## FIXED FACTS (don't rediscover these)

- **Supabase project:** `fnykldftbkrccihdjayl`. Access via Supabase MCP tools or Management API with `SUPABASE_ACCESS_TOKEN` from `~/.navreo-keys.env`.
- **HeyReach API:** base `https://api.heyreach.io/api/public/`, header `X-API-KEY`, key = `HEYREACH_API_KEY` in `~/.navreo-keys.env`. Endpoints are POST with JSON bodies; paginated via `offset`/`limit`. (Full API notes: `lilly-heyreach-upload` skill.)
- **Pattern to mirror:** edge function `smartlead-daily-sync` — verify_jwt OFF, auth via `x-navreo-token` header, chunked + resumable via a `sync_progress` row per (source, sync_date) with a ~90s work budget per invocation, `pg_cron` tick every 5 min calling it through `pg_net`, URL + token pulled from Vault secrets. Read that function's source first and copy its skeleton.
- **What to snapshot** (everything the public API exposes):
  1. LinkedIn senders — `li_account/GetAll`
  2. Lists — `list/GetAll` (+ leads per list via `list/GetLeadsFromList`)
  3. Campaigns — `campaign/GetAll` (+ leads per campaign via `campaign/GetLeadsFromCampaign`)
  4. Per-campaign stats — `stats/GetOverallStats` (per campaign id, per day)
  5. Inbox — `inbox/GetConversationsV2` (conversations + messages = replies record)
- **Change tracking:** append-only snapshot tables with a SHA-256 `content_hash` per entity; only insert a new row when the hash changed (same dedupe idea as `campaign_versions`). That gives "document all changes" without storing identical payloads daily.
- **Secrets hygiene:** NEVER write the HeyReach key into this file, the repo, or Notion. It lives only in `~/.navreo-keys.env` and as a Supabase edge-function secret.

---

## THE STEPS

### Step 0 — Preflight: keys + API alive
- `source ~/.navreo-keys.env`; confirm `HEYREACH_API_KEY` is set. If the user pasted a key in chat, compare against the env file: if different, ask which wins before continuing (never assume; the env key is the default).
- Prove the key works: POST `list/GetAll` with `{"offset":0,"limit":1}` → expect HTTP 200.
- Confirm Supabase is reachable (list tables on `fnykldftbkrccihdjayl`).
- **Done-rule:** HeyReach returns 200 with a JSON body AND Supabase responds. No writes yet.

### Step 1 — Schema: heyreach_* tables
Create (idempotent `create table if not exists`, via migration named `heyreach_daily_sync_schema`):
- `heyreach_accounts`, `heyreach_lists`, `heyreach_campaigns`, `heyreach_campaign_stats`, `heyreach_leads`, `heyreach_conversations` — each: `id bigserial pk`, natural id column(s) (`heyreach_id` / composite), `snapshot_date date`, `content_hash text`, `payload jsonb`, `fetched_at timestamptz default now()`; unique index on (natural id, `content_hash`) so unchanged payloads upsert-noop.
- Reuse the existing `sync_progress` table with a `source` discriminator if it has one; otherwise a `heyreach_sync_progress` table matching the Smartlead one (pending/done arrays, `finished_at`).
- RLS **enabled with no policies** (service-role only), matching the rest of the data layer.
- **Done-rule:** all 6 snapshot tables + progress tracking exist (`list_tables` shows them) and RLS is on for each.

### Step 2 — Edge function `heyreach-daily-sync`
- Port the `smartlead-daily-sync` skeleton: verify_jwt OFF; reject unless `x-navreo-token` matches secret `HEYREACH_SYNC_TOKEN`; one invocation works the pending queue for ≤90s then returns `{status:"partial"}`; fresh UTC day auto-creates a new progress row; empty queue → `finished_at` set and `already_complete` on further ticks.
- Work order per day: accounts → lists → campaigns → per-campaign stats → leads (per list + per campaign, paginated) → conversations. Hash-dedupe every payload before insert.
- Set secrets on the function's project: `HEYREACH_API_KEY` (value from env file) and a fresh random `HEYREACH_SYNC_TOKEN`.
- **Done-rule:** function deployed and listed; `curl` with wrong token → 401; with right token → 200 JSON containing a status field. Source mirrored into the project `db/` area like the Smartlead one.

### Step 3 — Schedule: pg_cron tick
- Vault: add `navreo_heyreach_sync_token` (reuse existing `navreo_project_url`).
- `cron.schedule('heyreach-daily-sync-tick', '*/5 * * * *', …)` calling the function via `pg_net` with URL + token from Vault — copy the `smartlead-daily-sync-tick` job's SQL verbatim, swapping names.
- **Done-rule:** `select jobname from cron.job` includes `heyreach-daily-sync-tick`, schedule `*/5 * * * *`, active.

### Step 4 — Mock scheduled run (THE verification)
- Force a run now instead of waiting for the tick: invoke the function directly with the sync token, repeatedly (respecting `partial`) until it returns `already_complete` or 10 invocations, whichever first.
- Then check the data landed: `select count(*), max(fetched_at) from <each heyreach_* table> where snapshot_date = current_date`.
- Also confirm the cron path works end-to-end: check `cron.job_run_details` (or `net._http_response`) for at least one successful tick after the job was created.
- **Done-rule:** every snapshot table that HeyReach has data for shows ≥1 row dated today; row counts are plausible vs live API totals (campaign count in `heyreach_campaigns` == `campaign/GetAll` total); one cron-initiated invocation shows a 2xx. If HeyReach genuinely has zero of an entity (e.g. no conversations), record that as verified-empty, not a failure.

### Step 5 — Prove change-tracking (dedupe works)
- Invoke the function once more after completion: expect `already_complete` and **zero new rows** (nothing changed).
- **Done-rule:** second full pass inserts 0 duplicate rows; unique (natural id, content_hash) index confirmed doing its job.

---

## OVERALL DONE-RULE

- All 6 `heyreach_*` tables exist with today's snapshot in them (Step 4 counts).
- `heyreach-daily-sync` edge function deployed, secret-authed, chunk-resumable.
- `heyreach-daily-sync-tick` cron job active at */5 and has ≥1 successful run.
- Re-run inserts no duplicates (Step 5).
- Final report: one line per step — DONE / SKIPPED (already passed) / FAILED (with reason) — plus today's per-table row counts.
