---
name: hiring-signal-ship
description: "Orchestration skill that turns the Navreo signals-tool hiring signal from prototype into a fully working feature: DM-role field, negative keywords, prospect-first preview, leads-per-day pacing, exclusions + freshness + re-touch + verified emails, Supabase-backed paginated Leads tab, then an end-to-end next-day simulation that proves leads would push into Smartlead campaign 3591996 and HeyReach list 'Arna test'. Trigger on: 'ship the hiring signal', 'run the hiring signal shipper', 'turn the hiring signal into a real feature', '/hiring-signal-ship'."
---

# hiring-signal-ship

## LOOP TRAINING MODE

```
LOOP_TRAINING_MODE: ON        <- flip to OFF to run autonomously
```

- **ON**: pause at EVERY step gate and wait for the user's approval before continuing.
  Before starting a step, check its done-rule: if it already passes, say so and SKIP it.
  Only re-run steps that fail. Announce plan -> wait -> build -> check done-rule -> report -> wait.
- **OFF**: run all steps autonomously, no pauses. Keep every done-rule check and the retry cap.
- **Retry cap (both modes): 3 attempts per step.** On the 3rd failure, stop the step,
  write down what failed and why, and (ON) ask the user / (OFF) halt with a failure summary.
  Never loop past the cap.

## Goal

Once a hiring signal is set up, it delivers new leads every day and automatically pushes
them into outreach (when destinations are set) with zero user intervention.

## Orientation (read once)

- Model: client -> campaign draft -> source. A hiring source = one signal config.
- UI: `app/campaigns.html` — wizard `openSourceWizard('hiring', campaignId)`; campaign view
  `renderDraftCampaign` with Overview/Leads/Sources tabs (Leads = `dtab === "leads"` branch).
- Pipeline: `app/server.py` `pull_hiring_source()` — `cfg = {**config, **params}`; trigger roles
  from `cfg.job_titles` (or split `cfg.titles`); DM roles from the source's top-level `titles`;
  `theirstack_jobs()` (unblurred) -> `signals` + `companies` -> `dm_find_by_domain()` (Prospeo)
  -> `signal_leads`. Current caps: scan_limit 50, enrich_cap 50, max_dms 2.
- Preview: `preview_hiring()` (blurred, free) returns `total_companies` + `total_jobs`.
- Clients: `/api/clients` (`app/data/clients.json`); DM roles at `client.icp.titles`;
  resolve a source's client via `campaign_drafts.client_id`.
- Supabase via `server.sb()`: `signal_sources`, `signal_leads` (no email column yet),
  `signals`, `companies`, `contact_history`, `suppressions`,
  RPC `check_exclusions(client_id, emails[], domains[])` (suppressions + contact history).
- Push routing (standing user rule): email found -> ONLY Smartlead; no email -> ONLY HeyReach.
- Server runs at `python3 app/server.py 7901`. Restart after server.py edits.

## Pre-flight (verify before building, one pass)

1. TheirStack negative-keyword param: fetch `api.theirstack.com/openapi.json` and confirm the
   exact names (expected `job_title_pattern_not` / `job_description_pattern_not`, regex arrays).
   If unsupported -> client-side filter fallback (step 2).
2. Prospeo email finder: reuse `find_email()` in server.py (enrich-person,
   `only_verified_email: true` — same endpoint lilly-email-verification uses). Confirm it's intact.
3. `signal_leads.email`: check the column; if missing, migrate
   `alter table signal_leads add column if not exists email text;` (Supabase MCP `apply_migration`).

## Steps

### 1. Decision-maker roles: always ask, always include (UI)
Split the hiring wizard into two labelled fields:
- "Roles they're hiring for (the trigger)" -> `config.job_titles` (array).
- "Who we email at these companies" -> source top-level `titles` (array). REQUIRED —
  block Next/Save while empty. Prefill from `client.icp.titles` (client via campaign draft).
No backend change beyond confirming the wizard sends both.
**Done-rule:** cannot save a hiring source with an empty DM field; a saved source has BOTH
`config.job_titles` and `titles` (inspect `app/data/draft_sources.json`).

### 2. Negative keywords (UI + pipeline)
UI: optional "Exclude posts containing" (comma-separated) -> `config.negative_keywords` (array).
Pipeline: pass to TheirStack as the verified negative params from pre-flight; if unsupported,
drop any fetched job whose title or description contains a negative keyword (case-insensitive)
BEFORE dedupe in `theirstack_jobs()`/`pull_hiring_source()`.
**Done-rule:** a live pull with a negative keyword matching a known post title produces no
signal and no lead containing that word (assert against the pull result + `signals`).

### 3. Preview headline = prospects, not companies (UI + pipeline)
`preview_hiring()` accepts the DM-role count and returns
`total_prospects = total_companies * min(dm_role_count, 5)`. UI leads with "~X prospects";
companies become the secondary line. One source of truth: the UI reads `total_prospects`.
**Done-rule:** the wizard preview reads "~X prospects" with companies secondary, X computed
by the server formula.

### 4. Pace control (UI + pipeline)
UI: ONE numeric field "New leads per day" (default 20) -> `config.leads_per_day`.
Never expose scan_limit / enrich_cap / max_dms. Pipeline: fix `max_dms = 5`; enrich loop
accumulates DMs and STOPS once `len(prospects) >= leads_per_day` (or pool exhausted);
`scan_limit = min(leads_per_day * 4, 100)`.
**Done-rule:** a source set to 10 leads/day returns <=~10 leads per run, <=5 per company,
and stops enriching early once 10 are reached (assert from the pull result).

### 5. Exclusions, freshness, re-touch, verified email (pipeline)
In `pull_hiring_source()`:
- Resolve and store `client_id` on `signal_sources` (from the campaign draft).
- Freshness: cap `posted_at_max_age_days` at 30 AND drop older jobs in code.
- Re-touch: per-source company skip only if scanned within the LAST 90 DAYS (query the
  source's `signals` with a 90-day window instead of all-time) — a company re-posting after
  3 months is re-engaged.
- Per lead before keeping: (a) verified email via `find_email()`; (b)
  `check_exclusions(client_id, [email], [domain])`. Drop if excluded or no deliverable email.
  ⚠ DECISION GATE: dropping no-email leads means hiring sources never feed HeyReach, which
  conflicts with the standing no-email->HeyReach routing. At this step's gate confirm with the
  user: drop entirely (brief as written) OR keep no-email leads and route them to HeyReach.
  In OFF mode default to the brief as written (drop).
- Schema: `email` column on `signal_leads` + prospect objects; store the verified email.
**Done-rule:** a lead present in the client's suppressions/contact history is dropped; a job
posted 31+ days ago is ignored; a company scanned 10 days ago is skipped while one scanned
100 days ago is re-scanned; every kept lead has a stored Prospeo-verified email.

### 6. Leads view: newest first, paginate 10 (UI + read endpoint)
Add `GET /api/leads?campaign_id=...` proxying `signal_leads` for the campaign's source ids,
ordered `pulled_at.desc`. Leads tab reads it (accumulates across pulls, unlike the
last-pull-only local view) and paginates 10 per page with next/prev.
**Done-rule:** Leads tab shows every pulled lead for the campaign, newest first, 10/page.

### 7. End-to-end proof: the next-day simulation
Build the verification mechanism — do NOT wait 24 hours:
- Create a real test hiring campaign + source (client Navreo is fine), destinations set to
  Smartlead campaign **3591996** and HeyReach list **"Arna test"**.
- Add `app/simulate_daily.py --source <id>`: runs EXACTLY what the daily run would —
  rewind the source's per-source scan window state so "tomorrow's" pull has fresh companies
  (e.g. treat last_pull as >24h ago), call `pull_source`, then auto-push every new lead
  through `push_prospect()` (email -> Smartlead, no email -> HeyReach per routing) without
  any manual ✓.
- Verify via APIs that the leads actually landed: Smartlead campaign 3591996 leads list
  contains the pushed emails; HeyReach "Arna test" list contains the pushed profiles.
- Clean up: `unpush_prospect()` the test leads and remove the test campaign.
**Done-rule:** the simulation run reports N new leads, and BOTH live tools show those exact
leads (then cleaned up). This is the skill's overall done-rule.

## Reporting

After every step: one short line — step, attempt count, done-rule PASS/FAIL, what changed.
At the end: table of all 7 steps with status + the simulation evidence (lead names/emails
seen in Smartlead + HeyReach).
