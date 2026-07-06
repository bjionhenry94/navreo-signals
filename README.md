# Navreo Signals

Signal-campaign tool (hiring + engagement signals → verified decision-maker leads → Smartlead/HeyReach). Runs remotely on Render with all state in Supabase Postgres.

## Architecture
- **Web service** (`app/server.py`) — serves the UI (`/app/campaigns.html`) and the `/api`. Binds `0.0.0.0:$PORT`.
- **Cron job** (`app/run_daily.py`) — the daily pull. Scheduled in `render.yaml` (UTC).
- **State** — Supabase Postgres: `campaign_drafts`, `sources`, `clients`, `role_feedback` (id + `jsonb doc`), plus `signal_leads` / `engagement_events`. No local files are the source of truth.
- **Secrets** — environment variables (see `render.yaml` → `navreo-secrets` group). Locally, `~/.navreo-keys.env` still works as a fallback.

## Deploy
1. Create the services from `render.yaml` (Render Blueprint).
2. Fill the `navreo-secrets` env group in the Render dashboard with the real key values.
3. Deploy. The web URL serves `/app/campaigns.html`; the cron runs `run_daily.py` daily.

## Local run
`python app/server.py 7901` → http://localhost:7901/app/campaigns.html
