---
name: campaigns-platform-mirror
description: Static orchestration skill that reworks the Campaigns section of the unified prototype (~/navreo-signals/app/unified.html + server.py, port 7955) so app campaigns stop being their own entity and become a live mirror of the outreach platforms — one row per Smartlead campaign (exact name + live ACTIVE/PAUSED/DRAFTED status) and one row per HeyReach LIST — with a gated additive migration of the campaign_drafts Supabase table (Arnic dual-destination doc split in two, sources attached to both), status/client/Unlinked filters, a 10-min background sync + manual Refresh, and sources as the centrepiece (pulled-vs-remaining + per-source analytics). Fixed step list, checkable done-rules, retry caps, Loop Training Mode toggle. Use when the user says "run the campaigns platform mirror", "mirror Smartlead/HeyReach in the campaigns tab", "kill the app-campaign layer", or "/campaigns-platform-mirror".
---

# Campaigns Platform Mirror

## ⚙️ Loop Training Mode

```
LOOP_TRAINING_MODE: ON   ← flip to OFF for autonomous runs
MAX_RETRIES_PER_STEP: 3
```

- **ON (default):** pause at EVERY step and wait for Bjion's approval before continuing. Skip any step that already passes its done-rule. Only re-run steps that fail. Never exceed MAX_RETRIES_PER_STEP re-runs of one step — on the 3rd failure, stop and report the blocker.
- **OFF:** run all steps autonomously with no pauses, but still check every done-rule and still honour the retry cap.

## Model routing

Fable 5 (the main loop) does all judgment: verification reads, migration decisions, done-rule checks. Mechanical execution (bulk edits, file surgery, test scaffolding) goes to subagents spawned with `model: sonnet`.

## Goal

The Campaigns tab is a live mirror of Smartlead campaigns and HeyReach lists — filterable by status and client, each campaign openable to add sources and signals and to see pulled-vs-remaining and per-source analytics — with no separate app-campaign layer left.

## Hard facts (do not rediscover)

- **LIVE code:** `~/navreo-signals/app/unified.html` + `~/navreo-signals/app/server.py`, served at `http://127.0.0.1:7955/app/unified.html`. **NEVER edit the iCloud copy** under `Bjion [2023]/Navreo/Claude/Navreo` — it reverts edits and is not the running code.
- **State:** Supabase project `fnykldftbkrccihdjayl`, jsonb-doc table `campaign_drafts` (7 docs). Each doc has `destination` {smartlead_campaign_id, heyreach_list_id, heyreach_list_name} and inline `sources[]`.
- **Dual-destination doc:** `cdraft-0e504d37` (Arnic): Smartlead `3591996` + HeyReach list `768931` "Arna test". Split into two campaigns; its 2 sources attach to BOTH halves. Pull tracking stays shared per source; analytics per campaign.
- **Rulings (2026-07-12):** HeyReach rows are LIST-level, not HeyReach-campaign-level; lists have no platform status → show in default view with a HeyReach badge. Keep in-app creation → destination-less docs = "Unlinked" drafts behind an Unlinked filter, hidden from default view.
- **Sync:** extend existing `_OUTREACH_DESTS_SWR` cache in server.py (~line 5029) to a ~10-minute background refresh + visible manual Refresh button. NO new external cron. Respect Smartlead's shared 200/min budget.
- **Known bug:** on 2026-07-12, GET /campaigns with SMARTLEAD_API_KEY from `~/.navreo-keys.env` returned "Invalid API Key", and server.py's isinstance-list guard silently turns that into 0 campaigns. This MUST become a loud UI error state, never a silently empty tab.
- **Source fields already exist** (surfacing, not a new pipeline): `companies_scanned`, `left_for_next_run`, `total`, `last_pull` on sources; `pulled_count`/`total_tam` on `list_pulls`.
- Local-only: commit to the navreo-signals repo, do NOT deploy.

## Steps

### Step 1 — Verify the Smartlead key, make failure loud
Parse SMARTLEAD_API_KEY from `~/.navreo-keys.env`, hit GET /campaigns directly. If invalid, diagnose (stale key? parsing bug — quotes/whitespace? env var shadowing?) and fix or surface to Bjion before anything else. Then patch server.py's isinstance-list guard so an API error propagates as an error payload, and unified.html renders a visible error state (banner/badge), never an empty tab.
**Done-rule:** a direct curl with the parsed key returns a campaign list (or the key problem is escalated to Bjion and confirmed fixed), AND killing the key deliberately in a test shows the UI error state in the rendered page.

### Step 2 — Backup + additive migration of campaign_drafts
Take a timestamped backup of all campaign_drafts docs (Supabase insert into a backup table or timestamped local JSON committed to the repo — both is best). Then migrate: platform identity becomes the campaign key (one campaign per Smartlead campaign id, one per HeyReach list id). Split `cdraft-0e504d37` into two campaigns, attach both original sources to each. Destination-less doc(s) become Unlinked drafts. Never hard-delete any doc — mark superseded docs, don't remove them.
**Done-rule:** read campaign_drafts back from Supabase: every one of the 7 pre-migration docs accounted for, zero deletions, backup exists and is readable, Arnic split into two campaigns keyed to Smartlead 3591996 and HeyReach list "Arna test", each carrying both original sources.

### Step 3 — Mirror sync (10-min SWR + manual Refresh)
Extend `_OUTREACH_DESTS_SWR` so Smartlead campaigns (name + status) and HeyReach lists refresh on a ~10-minute cadence in the background; add a visible Refresh button that forces a fetch. Errors from either platform surface as the Step 1 error state.
**Done-rule:** server logs show a background refresh cycle; the Refresh button triggers an immediate re-fetch (verified via server logs/network tab); no new cron exists outside the server process.

### Step 4 — Campaigns tab UI rework
One row per Smartlead campaign (exact platform name, live status badge) and one per HeyReach list (HeyReach badge, no status). Default view = ACTIVE Smartlead rows + all HeyReach list rows. One-click filters: Paused, Drafted, Unlinked. Keep the existing client filter. Unlinked drafts hidden from default view. Each row opens to the campaign detail with sources.
**Done-rule:** rendered page shows exactly the default set; each filter shows exactly what an independent platform read says it should; client filter still works.

### Step 5 — Sources centrepiece
Inside any mirrored campaign: add sources, attach signals, see pulled-vs-remaining per source (surface companies_scanned / left_for_next_run / total / last_pull, pulled_count/total_tam) and per-source analytics. Existing add-source, push, and pull flows must keep working against the new platform-keyed campaign identity.
**Done-rule:** in the rendered browser UI, add a source to a mirrored Smartlead campaign; read it back independently from Supabase; pulled-vs-remaining and per-source analytics render for it.

### Step 6 — Lists regression
Touch nothing on the Lists side; verify it anyway.
**Done-rule:** Lists side renders, folders and CSV export intact, in the rendered page.

### Step 7 — Full verification gate (ALL 7, or it isn't done)
1. **Migration audit** — Step 2's done-rule re-checked fresh from Supabase.
2. **Mirror truth** — names/statuses in the tab match an INDEPENDENT direct Smartlead GET /campaigns and HeyReach lists read (never the app's cache or its own success labels).
3. **Filters** — default = ACTIVE Smartlead + HeyReach lists; Paused/Drafted/Unlinked each match the independent read.
4. **Sync proof** — create one throwaway DRAFTED Smartlead campaign; it appears in the tab within 10 minutes with no page action; manual Refresh pulls it instantly; then delete the throwaway.
5. **Add-source E2E** — Step 5's done-rule.
6. **Browser proof** — screenshot of the rendered page at `http://127.0.0.1:7955/app/unified.html` (browser-verify rule: rendered page is the only done-evidence).
7. **Lists regression** — Step 6's done-rule.
**Done-rule:** all 7 pass in the same run.

### Step 8 — Commit (no deploy)
Commit to the navreo-signals repo with a clear message. Do NOT deploy.
**Done-rule:** `git log` in ~/navreo-signals shows the commit; working tree clean; no deploy action taken.

### Step 9 — Supabase-recording evaluation
Per the standing signals-feature recording rule: evaluate whether new user actions (source adds, manual syncs, filter usage) should be logged to Supabase for lilly-data + product decisions. Report a recommendation to Bjion; implement only what he approves (or, in OFF mode, implement the clearly-warranted ones and flag the judgment calls).
**Done-rule:** a written recommendation exists in the final report; any approved logging is implemented and verified with one test row.

## Loop protocol

1. Read LOOP_TRAINING_MODE above.
2. For each step in order: check its done-rule first — if it already passes, SKIP. Otherwise execute (Sonnet subagents for mechanical work), then check the done-rule.
3. On failure: retry (max 3), fixing the cause each time, not re-running blind.
4. In ON mode, after each step (pass, skip, or blocked) report status and WAIT for approval.
5. Finish with a plain-English report: what shipped, the 7-gate results, screenshot, commit hash, and the Step 9 recommendation.
