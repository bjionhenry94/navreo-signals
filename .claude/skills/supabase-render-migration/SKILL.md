---
name: supabase-render-migration
description: Static orchestration skill that migrates the Navreo signals tool off the local laptop and onto the proposed Supabase + Render setup — operational state into Postgres, secrets into env vars, the local `claude` CLI dependency removed, the Python app deployed as a Render Web Service, and the daily pull moved to a Render Cron Job — so the whole system runs remotely with no local files required. One fixed step list, each with a checkable done-rule, plus a Loop Training Mode toggle. Use when the user says "migrate the tool to Render", "run the Supabase/Render migration", "get the tool off my laptop", or "/supabase-render-migration".
---

# supabase-render-migration

Move the signals tool from "runs on Bjion's laptop via launchd" to "runs remotely on Render, state in Supabase". Static loop — the steps below are fixed, each has a done-rule, and Loop Training Mode controls whether you pause between them.

Files: `app/server.py` (HTTP server + `/api` + data layer), `app/run_daily.py` (the daily pull), `app/campaigns.html` (UI), `app/data/*.json` (local state to migrate). Secrets: `~/.navreo-keys.env`. Local scheduler: launchd jobs `com.navreo.signals-server`, `com.navreo.signals-daily`, `ai.navreo.dailysync`.

---

## ⚙️ LOOP TRAINING MODE  →  **OFF**

Flip it by editing this one line:

    LOOP_TRAINING_MODE = OFF       # ON = approve every step · OFF = run autonomous

**When ON**
- Pause at the end of **every** step and wait for my explicit approval before starting the next.
- Before running a step, check its done-rule first. **If it already passes, skip it** — say so and move on.
- Only (re-)run steps that fail their done-rule.
- Retry cap applies (see below). Never loop a step forever.

**When OFF**
- Run all steps autonomously, no pauses.
- Still check every step's done-rule and still honour the retry cap. Report at the end, not between steps.

**Retry cap (both modes):** any single step retries **max 3** times against its done-rule. On cap-hit, stop that step, record it as FAILED with the reason, keep going, and surface it in the final report. Never silently exceed.

---

## THE GOAL

The tool runs **entirely off the laptop**: served from Render, all operational state in Supabase Postgres, all secrets in Render environment variables, the daily pull on Render's Cron scheduler. **Done means: stop the local server, rename `app/data/*.json` and `~/.navreo-keys.env` aside, and the Render URL still works end-to-end** — no local file is required to run the system.

**Convention (reuse, don't reinvent):** the Supabase call helper `sb(method, path, body)` already exists in `server.py` and already backs `signal_sources` / `signal_leads` / `engagement_events`. Route all new DB reads/writes through it — do not add a second Postgres client. The app is pure stdlib + `certifi`, so keep dependencies at exactly that.

---

## THE STEPS

### Step 1 — Inventory the local source-of-truth
- Enumerate every local file the running server reads or writes and tag each **OPERATIONAL** (authoritative state, must move to Postgres) or **CACHE** (regenerable, may stay ephemeral). The three OPERATIONAL ones are known: `campaign_drafts.json` (`CAMPAIGN_DRAFTS`), `draft_sources.json` (`DRAFTS`), `clients.json` (`CLIENTS`). Confirm whether `role_feedback.json` / `qa_history.json` are operational or log-only.
- Done-rule: a written OPERATIONAL/CACHE classification for every path emitted by `grep -nE 'APP_DIR / "data"' app/server.py`, plus the data-layer surface (`read_json_list`, `read_drafts`, `write_drafts`) named as the only functions that touch operational files.

### Step 2 — Create Postgres tables for the operational state
- In Supabase, create one table per operational document, keyed by id with a `jsonb` doc column so the exact JSON shapes the code already passes around survive unchanged: `campaign_drafts(id text primary key, doc jsonb not null, updated_at timestamptz default now())`, and the same for `sources` and `clients`. (`signal_leads` / `engagement_events` already exist — do not recreate.)
- Done-rule: `list_tables` (or a `select` via `sb`) shows `campaign_drafts`, `sources`, `clients` with an `id` + `jsonb doc` column each; existing signal tables untouched.

### Step 3 — Repoint the data layer at Postgres
- Rewrite `read_json_list`, `read_drafts`, `write_drafts` (and the client/role/qa readers) to `select`/`upsert` the `doc` column via `sb()` instead of reading/writing JSON files. Keep the in-memory return shapes identical so no caller changes. Replace the `fcntl` `drafts_lock` file lock with a DB upsert (Postgres handles concurrency) or a process-local lock.
- Done-rule: `grep -nE '\.json"|read_text\(\)|write_text\(|fcntl' app/server.py` shows no operational-state file I/O left (caches, if any kept, explicitly noted); app boots and `/api/campaign-drafts`, `/api/sources`, `/api/clients` return the same records, now from Postgres.

### Step 4 — Backfill existing local data into Postgres
- One-time, idempotent: load current `campaign_drafts.json`, `draft_sources.json`, `clients.json` and upsert every record into the new tables.
- Done-rule: Postgres row counts equal the live local files (expect ~5 campaigns, ~7 sources, N clients); the running app shows the same campaigns and lead counts as before the migration, served from Postgres.

### Step 5 — Move secrets to environment variables
- Change `load_keys()` to read from `os.environ` first and fall back to `~/.navreo-keys.env` only when it exists. No key literal committed anywhere.
- Done-rule: with `~/.navreo-keys.env` temporarily renamed aside and the keys exported as env vars, the app boots and a live TheirStack **and** Supabase call both succeed; `grep -n "navreo-keys" app/server.py` shows env-first, file-fallback logic.

### Step 6 — Remove the local `claude` CLI dependency
- The AI ideation path shells out to a local `claude` binary (`server.py` ~`shutil.which("claude")` / `claude_bin`). Replace it with a direct Anthropic API call (`ANTHROPIC_API_KEY` from env), or gate it behind a flag that degrades cleanly when neither CLI nor API is present.
- Done-rule: `grep -nE 'shutil.which\("claude"\)|claude_bin' app/server.py` returns nothing; ideation returns ideas via the API (or is cleanly disabled) on a box with no `claude` CLI installed.

### Step 7 — Add deploy scaffolding + a Git repo
- Add `requirements.txt` (just `certifi`), a `render.yaml` declaring a **Web Service** (`python app/server.py $PORT`) and a **Cron Job** (`python app/run_daily.py`, daily at the current pull time), and a `.gitignore` excluding `app/data/*.json`, `*.env`, `*.bak`. Make `server.py` bind `0.0.0.0` and read `PORT` from env (Render injects it).
- `git init`, commit, push to a new private GitHub repo Render can deploy from. Commit **no** secrets and **no** data JSON.
- Done-rule: `render.yaml` + `requirements.txt` exist; server binds `0.0.0.0:$PORT`; `git log` shows the pushed commit; `git ls-files | grep -E '\.env$|data/.*\.json$'` returns nothing.

### Step 8 — Provision Render and deploy
- Create the Render Web Service and Cron Job from the repo. Set every env var: all provider keys, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `ANTHROPIC_API_KEY`. Trigger a deploy.
- Done-rule: the Render public URL serves `/app/campaigns.html`, and `GET /api/lead-counts` on that URL returns JSON matching Supabase; a manual trigger of the Render Cron Job runs `run_daily.py` and writes leads to Supabase.

### Step 9 — Decommission the laptop
- Unload the launchd jobs: `com.navreo.signals-server`, `com.navreo.signals-daily`, `ai.navreo.dailysync`. Rename the local operational files aside: `app/data/{campaign_drafts,draft_sources,clients}.json` → `.bak`, and `~/.navreo-keys.env` → `.bak`.
- Done-rule (**the verification**): `launchctl list | grep navreo` is empty; with the local server stopped and those files renamed away, the Render URL still loads the UI, shows the data, and a pull still runs. **No local file is required to run the system.**

---

## HOW TO RUN

1. Read the mode line above. If **ON**, do one step at a time and stop for approval after each; skip any step whose done-rule already passes. If **OFF**, run all nine in order without pausing.
2. For each step: make the change, then check the done-rule — run the grep/`list_tables`/`curl` assertions, and for the two remote steps (8, 9) hit the actual Render URL, not localhost. Retry up to 3× on failure, then mark FAILED and continue.
3. Steps 7–9 are outward-facing (create a public repo, a hosted service, tear down local infra). In ON mode the pauses gate them; in OFF mode still confirm each done-rule passed before moving on.

## OVERALL DONE-RULE

- Render URL serves the app **and** its `/api`; the daily pull runs on Render's Cron; all state is in Supabase; all secrets are Render env vars.
- Proven by Step 9: local server stopped, `app/data/*.json` + `~/.navreo-keys.env` renamed aside, launchd empty — and the remote system is unaffected.
- Final report: one line per step — DONE / SKIPPED (already passed) / FAILED (with reason).
