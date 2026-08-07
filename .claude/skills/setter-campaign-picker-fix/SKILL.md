---
name: setter-campaign-picker-fix
description: Static orchestration skill that fixes the Appointment Setter Agents-editor campaign picker so every campaign with a queued or recent positive reply is selectable — union the status-filtered `campaigns` mirror with any campaign_id already in setter_queue, so COMPLETED and mirror-missing campaigns stop stranding as "No agent" — plus self-heal the backlog on attach. One fixed step list, each step with a checkable done-rule, retry caps, and a Loop Training Mode toggle. Use when the user says "fix the setter campaign picker", "campaigns aren't showing in the Agents editor", "these aren't picking up their agent", "run the campaign picker fix", or "/setter-campaign-picker-fix".
---

# Setter Campaign-Picker Fix

Closes the gap behind "these replies aren't picking up the campaigns their agent is attached to." The real defect is the Agents-editor **campaign picker**: it lists only `campaigns`-mirror rows with `status IN (ACTIVE,PAUSED,STOPPED)`, so a COMPLETED campaign (3477411 "Meeting Request") is hidden and a campaign missing from the mirror (3642625, not yet synced) is invisible — either way the owner can't tick it, so its positive replies strand in the queue with the "No agent" pill. This skill makes any campaign that already has a queued/recent reply attachable, then self-heals the stranded backlog on attach.

Static loop — fixed steps, each has a done-rule, Loop Training Mode controls the pauses.

## ⚙ Loop Training Mode: **OFF**   ← flip this line to ON to pause at every step

**ON:** pause at EVERY step boundary and wait for the user's explicit approval before
continuing. Before starting a step, check its done-rule first — if it already passes,
report "Step N already passes, skipping" and move on. Only re-run steps whose done-rule
fails. Show what you're about to do before doing it.

**OFF:** run all steps end-to-end with no pauses. The done-rule checks, skip-if-passing
behaviour, and retry caps stay exactly the same — only the pauses go.

**Retry cap (both modes):** each step retries **max 3** times against its done-rule.
On cap-hit: record the step as FAILED with the reason, continue to the next step if it
doesn't depend on the failed one, and surface every FAILED step in the final report.
Never silently exceed the cap. Never declare the skill done on a cap-hit.

## Destructive / outward-action gate (both modes, non-negotiable)

The backlog self-heal on attach **NEVER auto-sends**. The only thing it ever writes is
`needs_review` queue rows with a generated draft — no outbound email to any historical
reply, regardless of the agent's `mode` (autopilot is globally OFF today, and this path
must stay send-safe even if it's later turned on). Backlog window is **7 days only**
(user ruling 2026-07-15): `campaign_assigned_at[cid]` is stamped to **now-minus-7-days**
on attach so only replies inside that window are eligible; nothing older is swept. In
Training Mode ON, additionally show the list of rows about to be retro-assigned/drafted
and get approval before writing them. No queue row for the touched campaigns may ever
flip to `auto_sent`/`sent` as a result of this skill.

## Goal

1. In the live Agents editor, campaign **3642625** and campaign **3477411** both render as
   tickable checkboxes and can be attached and saved to their agents.
2. Any campaign showing the "No agent" pill in the setter queue is always attachable in the picker.
3. On attach, the four currently-stranded rows are retro-assigned to the correct agent and drafted.

> Both 3642625 and 3477411 are selectable in the rendered picker **and** persist to the
> agent's `campaign_ids` **and** the four stranded rows carry a correct agent_id + non-empty
> draft **and** nothing sent retroactively. Anything less than all four = not done. On a
> retry cap-hit, stop and report the gap honestly — do not declare done.

## Ground truth (verified 2026-07-15 — re-verify in Step 1, line numbers drift; this is the iCloud copy, NOT the deployed build)

- **Picker source endpoint:** `route_campaigns_get`, `app/setter.py:2715` — GETs `campaigns?workspace=eq.navreo&select=smartlead_campaign_id,name,status&status=in.(ACTIVE,PAUSED,STOPPED)&order=created_at_smartlead.desc`, drops rows whose name is empty or matches `_SUBSEQUENCE_NAME`. Registered at `app/setter.py:5362` as `"/api/setter/campaigns"`.
- **Front-end checklist:** `renderCampaignChecklist`, `app/setter.html:2012` — renders every row the endpoint returns (filtered only by the search box), no truncation. Source list `CAMPAIGNS` loaded in `loadAgentsAndCampaigns` (`app/setter.html:756`) from `/api/setter/campaigns`. **Fix belongs in the endpoint, not the front-end.**
- **Agent→campaign resolution:** `_agent_for_campaign`, `app/setter.py:1426` — matches `campaign_id` (str-coerced) against each agent's static `campaign_ids`. Attachment saved via `_save_agent` (`app/setter.py:1437`), which merges partial payloads and re-stamps `campaign_assigned_at` (`app/setter.py:1489-1500`) to keys present in `campaign_ids`.
- **Intake / backlog sweep:** `run_poll` (`app/setter.py:2220`) and `setter_backfill.py:select_candidates` (`:108`) both pull CORE_FOUR positives for enabled agents' campaigns and honour `campaign_assigned_at`. `process_reply` (`app/setter.py:1884`) tolerates `agent=None` and stamps `agent_id` from `agent.get("id")`. Tables: `WORKSPACE="navreo"`, `AGENTS_TABLE="setter_agents"`, `QUEUE_TABLE="setter_queue"` (`app/setter.py:51-53`).
- **Data facts (Supabase, verified 2026-07-15):**
  - `3477411` "Meeting Request" IS in `campaigns` mirror, status **COMPLETED** → excluded by the status filter.
  - `3642625` is **absent** from the `campaigns` mirror entirely → the Smartlead→Supabase sync hasn't captured it.
  - `campaigns` mirror = **782** navreo rows, **229** currently pickable, 405 with null `created_at_smartlead` — keep any union query bounded.
  - Four stranded `setter_queue` rows, `agent_id=null`, `status=needs_review`, `is_test=false`:
    - `msscosmetics68@gmail.com` — campaign 3642625 → Amplifyy agent **agent-70fd17e5**
    - `delder@aaopticalco.com` — campaign 3642625 → **agent-70fd17e5**
    - `info@forget-about-age.com` — campaign 3642625 → **agent-70fd17e5**
    - `gwiatrowski@incentco.com` — campaign 3477411 → Navreo agent **agent-55f4fe5f**
- **Gotchas:** (a) iCloud reverts edits and the deploy repo is separate — the DEPLOYED intake creates agentless rows while this copy's `run_poll`/`handle_inbound` hard-skip no-agent campaigns, so the live build ≠ this copy. **Step 1 must re-read the live deployed `setter.py` before editing** (memory `signals-deploy-repo`). (b) PostgREST sends the query string raw, so any timestamp filter must be `quote()`-encoded — the "+"-as-space bug class. (c) Deploy proof = poll-log / marker-grep on the live host, never the iCloud file (memory `reference_setter_live_verify_auth`).

## Steps

### Step 1 — Re-verify ground truth against the deployed build
Re-read `route_campaigns_get`, `renderCampaignChecklist`, `_agent_for_campaign`, `_save_agent`, and `process_reply` at their current lines in the **deployed** setter (reconcile repo↔iCloud). Re-run the two data probes: confirm 3477411 status and 3642625 absence, and re-confirm the four stranded rows still exist as `agent_id=null`. Resolve any line drift.
- **Done-rule:** (a) every Ground-truth file+line bullet re-confirmed against deployed code or corrected; (b) SQL re-run shows 3477411=COMPLETED, 3642625 absent from `campaigns`, and the four stranded rows still `agent_id=null`/`needs_review`. If any stranded row is already fixed, note it and skip it downstream.

### Step 2 — Broaden the picker endpoint to a union
Edit `route_campaigns_get` so the returned list is the **union** of: (i) the existing status-filtered mirror rows, and (ii) every distinct `smartlead_campaign_id` present in `setter_queue` for workspace `navreo` (and/or `replies`), regardless of mirror status or mirror presence. For union-only ids, resolve the display name from the mirror if present, else the queue/reply row's campaign name, else `"Campaign {id}"`. Keep the `_SUBSEQUENCE_NAME` and empty-name exclusions. De-dupe by id. Keep the query bounded (don't unbounded-scan; select distinct campaign ids from the queue, then look up names).
- **Done-rule:** GET `/api/setter/campaigns` on the running server returns a list that (a) includes both `3642625` AND `3477411`, (b) still includes a normal ACTIVE campaign, (c) still EXCLUDES a subsequence-named row, (d) has no duplicate ids.

### Step 3 — Self-heal backlog on attach
In the agent-save path (`_save_agent` or its route caller), when a campaign id is **newly added** to an agent's `campaign_ids`, for each newly-added cid: stamp `campaign_assigned_at[cid] = now-minus-7-days` (quote()-encoded where it hits PostgREST), sweep that campaign's last-7-days CORE_FOUR positive replies into the queue as `needs_review` drafts, and retro-assign `agent_id` + generate a draft on any existing `setter_queue` rows for that cid that are currently `agent_id=null`. Reuse the existing `process_reply` / backfill draft path — **draft only, never send**. Do not re-stamp or disturb campaigns already assigned.
- **Done-rule:** (a) attaching a test campaign stamps `campaign_assigned_at[cid]` to ~now-7d, not epoch/now; (b) a pre-existing `agent_id=null` queue row for that cid gains the correct agent_id and a non-empty `draft_body`; (c) NO row for that cid is `auto_sent`/`sent`; (d) replies older than 7 days are not swept.

### Step 4 — Deploy
Push to the deploy repo, wait for the live host, marker-grep the deployed artifact to confirm the union logic and the on-attach self-heal shipped (not just the iCloud copy). Reconcile repo↔iCloud.
- **Done-rule:** deployed `setter.py` on the live host contains the union query and the on-attach 7-day stamp (grep the live artifact / confirm via a live GET), and `/api/setter/campaigns` on the live host returns both ids.

### Step 5 — Live browser proof + stranded-row heal
On the deployed host: open the Agents editor, open the Amplifyy agent (agent-70fd17e5) modal, confirm **3642625** renders as a checkbox, tick + save; open the Navreo agent (agent-55f4fe5f) modal, confirm **3477411** renders as a checkbox, tick + save. Reload. Then read back from the DB.
- **Done-rule (all lettered parts):**
  - (a) Both campaigns rendered as tickable checkboxes in the live rendered modal (screenshot evidence).
  - (b) `setter_agents.doc->campaign_ids` for agent-70fd17e5 now includes 3642625 and for agent-55f4fe5f includes 3477411 — read from the DB, NOT the save toast.
  - (c) The four named stranded `setter_queue` rows now carry the correct agent_id and a non-empty `draft_body` (SQL read-back).
  - (d) Zero rows for 3642625/3477411 are `auto_sent`/`sent`; `campaign_assigned_at` for both is stamped ~now-7d.
  - (e) A subsequence-named campaign is still absent from the picker (regression — the fix didn't just return everything).

## Final report (always, both modes)

One summary: each step passed / skipped / FAILED with reason; the endpoint's returned id count and whether 3642625 + 3477411 are present; the two agents' post-save `campaign_ids`; the four stranded rows' final agent_id + whether each got a draft (list by email); confirmation that zero rows sent retroactively and the `campaign_assigned_at` timestamps; the regression check result; deploy commit + live-verify evidence (screenshot paths, marker-grep). Name the real numbers — "done" is not a report. On any cap-hit, report the FAILED step and the gap; do not declare done.

## Hard don'ts

- **Never auto-send** any historical/backlog reply — the self-heal writes `needs_review` drafts only, no outbound, regardless of agent mode.
- **Never sweep older than 7 days** on attach; never stamp `campaign_assigned_at` to epoch or to "now" (that would strand or over-sweep).
- **Never fix the front-end checklist instead of the endpoint** — `renderCampaignChecklist` already renders everything; the union belongs in `route_campaigns_get`.
- **Never drop the `_SUBSEQUENCE_NAME` / empty-name exclusions**, and never "just return everything" — the picker must stay curated (regression check (e) guards this).
- **Never trust the iCloud copy as live** — re-read and marker-grep the deployed build; a push is not a deploy until the live host confirms.
- **Never verify from a save toast or a 200 response** — read `campaign_ids` and queue rows back from Supabase directly.
- **Never re-stamp or re-sweep campaigns already assigned** to an agent — only newly-added cids self-heal.
- **Never exceed a retry cap or report done while any done-rule fails.**
