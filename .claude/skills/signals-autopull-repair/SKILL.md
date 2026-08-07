---
name: signals-autopull-repair
description: >
  Fix and verify the signal-campaign auto-pull so every active signal source pulls
  fresh leads on its own roughly every 3 hours, with zero human intervention, and
  the pulled leads land in signal_leads / the Leads tab. Use when the user says the
  signal campaigns "stopped pulling", "aren't pulling leads", "the auto-pull is
  broken", "leads aren't coming in", "wire the 3-hourly pull", or "/signals-autopull-repair".
  Static orchestration skill: fixed goal, fixed steps, a checkable done-rule per step,
  a hard retry cap, and a Loop Training Mode toggle.
---

# Signals Auto-Pull Repair

> ## ⚙️ LOOP TRAINING MODE — toggle here
>
> **`LOOP_TRAINING_MODE = OFF`**  ← flip to `ON` to supervise a run, `OFF` to let it run itself.
>
> **When ON:**
> - Pause at **every step** and wait for the user's explicit approval before continuing.
> - **Skip** any step that already passes its done-rule (report "already green, skipping").
> - Only **re-run** steps that fail their done-rule.
> - Obey the retry cap (below) — never loop a failing step forever.
>
> **When OFF (default):**
> - Run all steps autonomously, **no pauses**.
> - Still run every done-rule check, and still obey the retry cap.
>
> **Retry cap (both modes): max 3 attempts per step.** If a step still fails its
> done-rule after 3 attempts, **STOP the whole run**, report which step failed with the
> evidence, and do not proceed to later steps.

---

## Goal

Every **active** signal source pulls fresh leads **unaided, on a ~3-hour cadence**, and
the pulled leads are actually retrievable (present in Supabase `signal_leads` and rendered
in the tool's Leads tab). No laptop needs to be awake; no human clicks "pull".

## Where things live (fixed facts)

- **Pull code path:** `app/server.py` → `pull_source({"id": <source_id>})` — the exact code the
  in-tool pull button and both runners call. Full-batch orchestration: `app/run_daily.py`
  (pull every active source **+ autopilot push**) and `db/pull_signals.py` (pull active sources
  read from Supabase `signal_sources`).
- **Deployed server:** Render, `https://navreo-signals.onrender.com` (auto-deploys on push to
  `main` of `~/navreo-signals`). Working copy is the iCloud path; **deploy = surgical copy →
  commit → push** per the deploy-repo memory (fetch + `merge --ff-only` first; never blind-copy).
- **Supabase:** project `fnykldftbkrccihdjayl`. `signal_sources` (active-source registry),
  `signal_leads` (retrieved leads), `signals`. Scheduler infra already proven here: the Smartlead
  sync runs on `pg_cron` + `pg_net` pulling URL/token from Vault secrets.
- **Tokens/env:** `~/.navreo-keys.env`; server reads secrets env-first via `KEYS.get(...)`.

## Authoritative target architecture (do NOT use local launchd)

`pg_cron` job **`signal-pull-tick`**, every 3 hours → `pg_net` POST → **`POST /api/cron/pull-all`**
on the Render server (token-guarded, header `x-navreo-token` = `SIGNAL_PULL_TOKEN`) → runs the
`run_daily` pipeline (pull every active source + autopilot push). URL + token come from Supabase
**Vault** secrets, mirroring `smartlead-daily-sync-tick`. This is laptop-independent and spends
zero Claude credits.

**Local launchd is explicitly rejected.** The iCloud-path plist (`db/ai.navreo.signalpull.plist`)
silently dies ("Operation not permitted" reading the script from iCloud Drive) — the same failure
that killed the daily Smartlead job. Step 6 disables it so there is exactly one authoritative scheduler.

**Gotcha:** `do_POST` already wraps each route in `drafts_lock()`. A batch handler must **not**
re-enter the lock per source — call `pull_source` directly inside the already-held lock (as
`run_daily.py` does), or dispatch `/api/cron/pull-all` outside the global lock. The lock does not nest.

---

## Steps (each has a checkable done-rule; cap = 3 attempts)

**Step 1 — Batch trigger endpoint exists and is guarded.**
Ensure `POST /api/cron/pull-all` is deployed on Render: with the correct `x-navreo-token` it runs
the full `run_daily` pipeline and returns `{ok:true, sources:[...], signals:N, leads:N}`; without/with
a wrong token it returns 401. Add the route + `SIGNAL_PULL_TOKEN` env if missing, then deploy
(surgical copy → commit → push; wait for Render).
*Done-rule:* `curl -s -X POST -H "x-navreo-token: $SIGNAL_PULL_TOKEN" https://navreo-signals.onrender.com/api/cron/pull-all`
returns HTTP 200 with an `ok:true` JSON body **and** the same call with a bad token returns 401.

**Step 2 — One real batch invocation pulls every active source.**
Hit the endpoint once (or run `python3 app/run_daily.py` locally if Render deploy is still propagating).
Confirm it iterates all active, non-deleted sources and each returns either real results or the
legitimate "no live job posts today" message (that is a PASS, not a failure).
*Done-rule:* the invocation's per-source log lists **every** active source, and **zero** sources error
(a "no jobs today" note counts as handled). Evidence: the returned `sources[]` array / `db/state/signal_pull.log`
or `app/data/daily_log.json` tail.

**Step 3 — pg_cron job scheduled every 3 hours.**
Create/verify `pg_cron` job `signal-pull-tick` with schedule `0 */3 * * *` that `pg_net`-POSTs the
endpoint, reading URL + token from Vault secrets (`navreo_project_url` and a new
`navreo_signal_pull_token`). Mirror `smartlead-daily-sync-tick`.
*Done-rule:* `select jobname, schedule, active from cron.job where jobname='signal-pull-tick'` returns
one row, `active=true`, schedule fires ≤ every 3h.

**Step 4 — The scheduled trigger actually reaches the server.**
Confirm the most recent `pg_net` call from the job got a 200 (not a timeout / 401 / DNS error).
*Done-rule:* the latest `net._http_response` row correlated to the job has `status_code=200`;
`cron.job_run_details` for `signal-pull-tick` shows `status='succeeded'` on its last run.

**Step 5 — Lead retrieval verified (the spot check).**
Confirm the pull produced retrievable leads. Query `signal_leads` for rows created/updated in the
window of the Step 2/4 run; open 2–3 of them and sanity-check the fields (name, company_domain,
linkedin_url, email present or intentionally blank, job-anchored icebreaker not empty/garbled), and
confirm they render in the tool's Leads tab for their source.
*Done-rule:* ≥1 active source shows `signal_leads` rows from the recent run (or, if **every** source
legitimately returned "no jobs today", that is documented as the reason for zero) **and** the spot-checked
leads have valid, non-fixture fields visible in the Leads tab. Never pass on fixture/invented leads.

**Step 6 — Exactly one authoritative scheduler; dead ones disabled.**
Ensure the old daily plist is not competing: confirm no loaded `navreo` launchd signal job
(`launchctl list | grep -i navreo` empty) and leave `db/ai.navreo.signalpull.plist` unloaded/disabled.
Record that `pg_cron` is the sole scheduler.
*Done-rule:* `launchctl list | grep -i navreo` returns nothing for the signal pull, and the only enabled
signal scheduler is the `pg_cron` job from Step 3.

---

## Overall done-rule (the run is DONE when ALL hold)

1. `pg_cron` job `signal-pull-tick` is `active`, schedule ≤ 3h (Step 3).
2. Its last real fire hit the endpoint with a 200 and ran the pipeline (Steps 1, 4).
3. A real invocation processed **every** active source with zero errors (Step 2).
4. Spot-checked `signal_leads` rows from the recent run are present and valid in the Leads tab —
   or every source legitimately had "no jobs today", documented (Step 5).
5. No competing/dead local scheduler is enabled; `pg_cron` is authoritative (Step 6).

If the cap trips on any step, the run STOPS and reports the failing step + evidence instead of
declaring done.

## Report format

End every run with: mode (ON/OFF), each step's status (`green` / `re-run` / `skipped` / `FAILED`),
the pg_cron job state, the last trigger's HTTP status, and the spot-checked lead sample
(source → 2–3 leads with the fields inspected). Keep it to one screen.
