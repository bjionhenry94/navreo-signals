---
name: client-workspaces-hub
description: Static orchestration skill that turns the Navreo signals tool (navreo-signals.onrender.com) into the ONE central hub for every client — DFY clients already in our Smartlead PLUS done-with-you clients running in their own Smartlead workspaces. Ships the workspaces data model, per-workspace API-key routing, federated daily sync, and a new Settings page (app/settings.html) that lists connected workspaces, carries a copy-the-add-prompt button (adding runs inside Claude because Make scenarios and other automations also need wiring), and a typed-confirmation Remove that purges ALL of a workspace's data in one go. Their campaigns, deliverability, appointment setting and optimisation data aggregate ON TOP of existing Navreo data; their lists stay out (lists are built on our side). Fixed step list, per-step done-rules, retry cap, Loop Training Mode toggle (ON by default). First workspace: Asteri Partners — key lives in ~/.navreo-keys.env as ASTERI_SMARTLEAD_API_KEY, never in this file. Use when the user says "run the client workspaces hub", "build the settings page", "add a workspace", "add [client]'s Smartlead workspace", "connect [client]'s workspace", "remove [client]'s workspace", or "/client-workspaces-hub".
---

# Client Workspaces Hub

One central hub: every client's outbound — DFY (our Smartlead) and done-with-you (their Smartlead, via their API key) — visible and manageable in the signals tool, aggregated on top of what's already there.

## Loop Training Mode — the toggle (flip it here)

```
LOOP_TRAINING_MODE: ON     ← flip to OFF to run autonomously
RETRY_CAP: 3               ← per step, both modes
```

**When ON (default):** pause at EVERY step and wait for Bjion's approval before continuing. Skip any step that already passes its done-rule (say so, show the evidence, move on). Only re-run steps that fail. Retries are capped so it can't loop forever.

**When OFF:** run autonomously, no pauses — but keep every done-rule check and the retry cap.

**Both modes:** a step that still fails its done-rule after `RETRY_CAP` attempts HALTS the loop with a plain-English report of what failed, what was tried, and the exact evidence. Never mark a step done without its done-rule passing. Never silently skip.

## The goal (overall done-rule)

The loop is DONE when, on the LIVE host with real data:
1. `app/settings.html` lists all connected workspaces (masked keys), with a working copy-add-prompt button and a typed-confirmation Remove that purges everything in one go.
2. Asteri Partners' workspace is connected via their API key and their campaigns, deliverability, appointment-setting and optimisation data render in the hub **on top of** the existing aggregate — totals = old baseline + Asteri, and not one existing Navreo row lost.

## Entry modes

- **FULL BUILD** (default, first run): steps 0–8.
- **ADD WORKSPACE <client>** (what the settings page's copied prompt triggers): steps 0 (key-validate + baseline only), 6, 7, 8 for that client.
- **REMOVE WORKSPACE <client>**: the Remove flow at the bottom. Never touches `workspace='navreo'`.

## Where things live

- **Deploy repo (the ONLY place to edit):** `~/navreo-signals` (git → Render auto-deploys on push to `main`). The iCloud copy is deprecated — never edit it. One session in this repo at a time (parallel sessions clobber WIP).
- **Supabase:** project `fnykldftbkrccihdjayl` — tables `campaigns`, `campaign_versions`, `contact_history`, `replies`, `sent_messages`, `campaign_scorecard`, `mailbox_stats_daily`, `sync_progress`; edge function `smartlead-daily-sync` (pg_cron tick every 5 min); `db/backfill_smartlead.py --workspace <slug>` is ALREADY workspace-parameterised, `sync_progress` is already keyed `(workspace, sync_date)` — build on that, don't reinvent.
- **Keys:** `~/.navreo-keys.env`. Asteri's is `ASTERI_SMARTLEAD_API_KEY`. New client keys pasted in chat get appended there (`<CLIENT>_SMARTLEAD_API_KEY`) AND stored in the `workspaces` table. Keys NEVER go in this skill, any git-tracked file, Notion, or any API response/UI unmasked.
- **Make scenarios that bind to workspaces:** reply categoriser `9251436` (Navreo) / `9187631` (Asteri — was PENDING exactly this token), Asteri positive-reply routing `9414775` (webhooks must be RE-REGISTERED on every new campaign).

## Standing laws (bind every step)

- Safe-deploy procedure: `git fetch` + `git merge --ff-only origin/main` BEFORE editing; check `git rev-list --left-right --count HEAD...origin/main`; surgical edits; stage files explicitly (never `git add -A`); `git diff` must show only the intended hunks.
- New POST/PATCH handlers in server.py read `self._post_body` — NEVER `rfile.read`.
- Smartlead API: 200 req/min; paginate until an EMPTY page — an error mid-pagination reads as end-of-list and silently truncates, so retry the page, never stop on error. Sequence saves only with explicit user approval AND the ID-intact recipe (verified 2026-08-02): fresh `get_campaign_sequences` immediately before → POST `{"sequences":[...]}` translating `sequence_variants`→`seq_variants`, `delayInDays`→`delay_in_days` → EVERY step id + variant id echoed unchanged (dropped id = that variant's stats orphaned forever, no recovery; new variant = no id; disable = keep id + percentage 0) → verify by re-GET (ids identical) + `get_campaign_variant_statistics` (history intact); 429 → ~70s backoff, never skip the verify. Worked example: `lilly-bot` → "THE ID-INTACT RECIPE". Client-workspace calls use the CLIENT's key.
- The live app is login-gated: anonymous curl 302s to login and `/api/version` 401s headless. Verify rendered pages through the authed browser (claude-in-chrome with Bjion's Chrome session, or the cookie-mint recipe in the `deliverability-backend-perf-pass` memory). Rendered live page = the only done-evidence for UI.
- Deploy lag: the static bundle updates ~1 min AFTER `/api/version` flips — verify by served marker/byte-length, not version alone.
- Edge-function redeploys RESET `verify_jwt` — re-set it OFF after every deploy of `smartlead-daily-sync`.
- Additive, never replace: existing Navreo data must never shrink. The ONLY deletion path is the typed-confirmation workspace purge.
- Times render browser-local with a named timezone. UI matches the existing app chrome (`navreo.css` tokens, no emoji).
- **Out of scope:** client lists (built on our side — do not sync or render theirs) and HeyReach (Smartlead workspaces only).

## Steps

### Step 0 — Preflight + baseline
**Do:** `~/navreo-signals` clean and fast-forwarded to `origin/main`. Supabase reachable. `ASTERI_SMARTLEAD_API_KEY` present in `~/.navreo-keys.env`. Validate the key with ONE Smartlead GET (campaigns list, their key) — record their campaign count and names. Record the BASELINE: current unified-list campaign count (e.g. 874 SL + 19 HR), collective-strip totals (leads/sent/replied/positives), and per-table SQL counts (`campaigns`, `contact_history`, `replies`, `sent_messages`, `campaign_scorecard`).
**Done-rule:** key returns 200 with a non-empty campaign list; every baseline number written down in the session log.

### Step 1 — Schema: workspaces table + workspace column
**Do:** Migration: `workspaces` table (`id` slug PK, `name`, `api_key`, `status`, `added_at`, `last_sync_at`; RLS on, no policies — service-role only, same posture as the rest). Add `workspace text not null default 'navreo'` to every federated table (`campaigns`, `campaign_scorecard`, `contact_history`, `replies`, `sent_messages`, `mailbox_stats_daily`, plus anything else the sync writes). Backfill existing rows to `'navreo'`. Seed the `navreo` workspace row (our own key, read from env — uniform code path).
**Done-rule:** SQL proves: table exists; every federated table has the column; `count(*) where workspace='navreo'` equals the Step-0 baseline per table; zero NULL/blank workspace values.

### Step 2 — Server: per-workspace key routing + workspace API
**Do:** In `app/server.py`: load enabled workspaces from Supabase at boot (with periodic refresh); EVERY Smartlead call on a federated path resolves its key by workspace — the unified campaigns list, `campaign-readonly`, `campaign-platform-leads`, the scorecard sweep (`_scorecard_sync_all` loops workspaces), and the deliverability/mailbox + reply/inbox endpoints. Rows and API responses carry `workspace`. New endpoints: `GET /api/workspaces` (keys masked to last 4), `POST /api/workspaces`, `DELETE /api/workspaces/<id>` = full purge of that workspace's rows across ALL federated tables plus the workspace row itself.
**Done-rule:** `grep -n SMARTLEAD_API_KEY app/server.py` shows only the workspace-resolver/env-seed path — no per-endpoint hardcoded key on a federated path. A local run round-trips a `smoketest` workspace: create → appears in GET → delete → SQL shows ZERO residue in every federated table.

### Step 3 — Sync federation
**Do:** Extend `smartlead-daily-sync` (edge function) to loop enabled workspaces from the `workspaces` table, per-workspace `sync_progress` rows, per-workspace key. Keep the standing archive scope rule (skip <500-send and never-live drafts; ALWAYS keep sub-sequences). `db/backfill_smartlead.py --workspace <slug>` runs against a client key end-to-end. Redeploy the function; re-set `verify_jwt` OFF.
**Done-rule:** a manually-triggered tick syncs a non-navreo workspace's campaigns into Supabase tagged with the right `workspace`; Navreo per-table counts unchanged from baseline.

### Step 4 — Settings page
**Do:** New `app/settings.html` (+ nav link app-wide): table of workspaces — name, masked key (last 4), campaign count, last sync (browser-local + tz), status. Buttons: **Copy add-prompt** (puts the canonical prompt below on the clipboard, placeholders for client + key) and **Remove** → modal requiring the client's name TYPED exactly → calls the DELETE purge → row and all data gone. No raw key ever reaches the page or its JS.
**Done-rule:** rendered in the authed browser (live host, or local `/api/_mock/dev-login` mock first): list shows `navreo` + `smoketest`; copy button fills the clipboard; removing `smoketest` purges it (SQL zero residue) and the row disappears without errors.

### Step 5 — Deploy
**Do:** Surgical commits (server.py, settings.html, nav touches, db/ mirror of the edge function), push to `main`, Render deploys.
**Done-rule:** `/api/version` = new commit AND the settings.html marker is in the served bundle (deploy-lag law) AND boot ledger/logs clean.

### Step 6 — ADD Asteri (the task's verification)
**Do:** Insert the workspace row (`asteri` / "Asteri Partners" / key from env). Run the backfill for `--workspace asteri`; let the scorecard sweep pick their campaigns up.
**Done-rule — all four, on the LIVE host, evidence recorded:**
1. Unified campaigns list shows Asteri's campaigns ON TOP of the baseline: row count = Step-0 baseline + Asteri's campaign count from Step 0.
2. Collective strip totals rose by exactly Asteri's sums — cross-checked against `select workspace, sum(...) from campaign_scorecard group by workspace`.
3. Opening one Asteri campaign shows real Live-performance stats and its real leads; deliverability surface lists their inboxes via their key.
4. Not one existing row lost: per-table `workspace='navreo'` counts still equal baseline.

### Step 7 — Automations pass (the reason adding runs in Claude)
**Do:** Wire the non-dashboard plumbing for the new workspace: patch reply categoriser `9187631` with the token (it was pending exactly this) and activate; verify positive-reply routing `9414775` webhooks are registered on their CURRENT campaigns (and note the re-register-on-new-campaign law); register reply webhooks / confirm the reply-sync backstop covers this workspace so the appointment setter sees their replies.
**Done-rule:** each scenario runs green on one test or replayed reply, OR is explicitly reported blocked-with-reason. Nothing silently skipped.

### Step 8 — Full live walk + wrap
**Do:** House law: walk the WHOLE journey in the authed browser on the live host — campaigns home (aggregate) → an Asteri campaign detail → deliverability → settings (Asteri listed) — screenshots at each stop. Do NOT test Remove on Asteri (destructive; `smoketest` already proved the purge). Write the ship memory (commits, schema, gotchas hit) + update MEMORY.md.
**Done-rule:** journey clean end-to-end with screenshots; memory written; final report shows before/after aggregate numbers.

## The canonical add prompt (what the settings page's Copy button carries)

```
Add a new client workspace to the Navreo hub.
Client: <CLIENT NAME>
Smartlead API key: <PASTE KEY>
Campaign filter (optional): only include campaigns whose title contains <TERMS — leave out for all campaigns>

Run /client-workspaces-hub in ADD WORKSPACE mode: validate the key, store it
(~/.navreo-keys.env as <CLIENT>_SMARTLEAD_API_KEY + the Supabase workspaces
table), backfill their data, wire the Make scenarios and other automations,
then verify on the live host that their campaigns, deliverability and replies
aggregate ON TOP of the existing data with nothing lost.
```

**Campaign filter** (added 2026-07-21, Bjion's ruling for Asteri): `workspaces.campaign_filter`
= comma-separated case-insensitive substrings; a client campaign enters the hub ONLY if its
title contains one (NULL = all). Enforced at all four seams — server (unified list +
scorecard sweep), daily-sync edge function (sub-sequences ALWAYS kept regardless — they hold
positive-reply data under generic names), backfill script (`name_filter` in WORKSPACES), and
the Make archive module's filter. Asteri = `navreo` (13 campaigns, STRICT — Bjion explicitly
excluded the webhook-carrying "Supply Chain US/CA" campaign). Changing a filter needs the
same four seams + a data cleanup of already-ingested non-matching rows.

## Remove flow

Normal path is the settings page (typed confirmation → one-go purge). From chat: require Bjion to type the exact client name in his message, then `DELETE /api/workspaces/<slug>`, then prove SQL zero-residue across every federated table and that surfaces dropped the rows while `workspace='navreo'` counts are untouched. Removing `navreo` is forbidden.
