---
name: trigify-fleet-repoint
description: Orchestration skill that migrates the existing Trigify engagement-monitoring fleet (the "[Person] Engagers → Make" workflows feeding Clay/Make/Sheets) into the Navreo signals tool. Creates ONE manual signals campaign under Navreo (client-1) in the tool, then recreates every fleet workflow bound to its existing saved search but pushing to Supabase engagement_events instead of Clay, deleting the old workflow after each swap. Static plan with pre-baked done-rules, retry caps, and a Loop Training Mode toggle. Trigger on: 'repoint the trigify fleet', 'migrate trigify workflows off Clay', 'move the engager workflows into the tool', '/trigify-fleet-repoint'.
---

# Trigify Fleet Repoint

## ⚙️ Loop Training Mode — TOGGLE HERE

```
LOOP_TRAINING_MODE: OFF
```

Flip the value above (`ON` / `OFF`). Read it at the start of every run.

**When ON (default):**
- PAUSE at every step boundary. Show the step's plan + done-rule, wait for
  explicit approval ("go" / "approve") before executing.
- Before executing any step, TEST its done-rule first. If it already passes,
  SKIP it (report "Step N already passes — skipped").
- Only re-run steps whose done-rule FAILS. Never re-run a passing step.
- Retry cap: max 2 re-runs per step (3 attempts total). On exhaustion, HALT
  and report the failing done-rule verbatim with evidence.

**When OFF:** run autonomously, no pauses, but KEEP the done-rule checks,
skip-if-passing, and the retry cap.

Either mode: a done-rule passes only with observed evidence (API response
bodies, DB rows, screenshots) — never on faith.

---

## Goal

Competitor LinkedIn engagement monitoring runs through the tool. Every
existing Trigify engagement workflow that today POSTs to Clay/Make is
recreated to POST into Supabase `engagement_events`, owned by ONE new manual
signals campaign under Navreo in the tool.

**Overall done-rule:** zero Trigify workflows still push to Clay/Make URLs; a
new campaign exists in the tool under Navreo (client-1) with one engagement
source whose `config.engagement.trigify[]` covers every migrated profile and
shows `monitoring N/N`; a test-fired migrated workflow lands a row in
`engagement_events` with the new source_id.

## Context (verified 2026-07-05, this repo)

- Fleet: ~46 workflows named "[Person] Engagers → Make" (49 total in the
  account), each bound to a "Profile Monitor — [Person]" saved search, each
  ending in an `http_request` step to `run.revcode.app/...` or
  `hook.*.make.com/...` (the Clay/Make path).
- Trigify REST: base `https://api.trigify.io/v1`, header `x-api-key`,
  BROWSER User-Agent required (Cloudflare 1010), list pagination max
  `limit=100`. Full spec: GET `/docs`.
- Tool side already built by `engagement-signal-ship`: `engagement_events`
  table, `qualify_engager`, `pull_engagement_source`, provisioning helpers
  `trigify_api` / `_eng_workflow_def` / `_trigify_deprovision` in
  app/server.py, server on localhost:7901 (launchd
  `com.navreo.signals-server`).

## THE ONE TRAP (2026-06-23 incident, do not repeat)

`social_saved_search_id` binds a workflow to its search ONLY at create time.
`update_workflow` / `PATCH /workflows/{id}` silently strips the binding — the
workflow stops firing forever. **Repointing is therefore NEVER an update.**
Per workflow: CREATE a new workflow with `search_id` set → verify it →
DELETE the old one. Old-then-new order is also wrong (a gap drops posts);
always create-verify-delete.

Other create-time facts: `builtin:loop` validates as exactly 2 outgoing
edges, so the exit branch needs a real `{"id": "_exit_done", "kind":
"builtin:exit"}` action; omit count/boolean fields from the push body
(Trigify renders missing refs as `""`, which fails Postgres int/bool casts);
never delete saved searches during this migration (they are all pre-existing
fleet searches, the adopted-search rule applies).

---

## Steps

### Step 1 — Discover and inventory the fleet

List ALL workflows (paginate at 100). Classify as MIGRATE when the workflow
has a `linkedin_get_post_comments` action AND an `http_request` action whose
URL is NOT the Supabase PostgREST endpoint. For each, capture: workflow id,
name, `social_saved_search_id`, the monitored person (from the name and the
hardcoded `postAuthorName` in the push body), the search's `profile_url`
(GET `/searches/{id}` → `query.profile_url`), enabled/status, and
`maxComments`. Write the inventory to
`~/.claude/skills/trigify-fleet-repoint/state/inventory.json`.

**Done-rule:** inventory file exists, its MIGRATE count equals the count of
non-Supabase engagement workflows returned by a fresh API sweep, and every
MIGRATE entry has a non-null search_id and profile_url. Surface the list
(names + profiles) to the user before any mutation.

### Step 2 — Create the manual signals campaign under Navreo

Via the tool's API (localhost:7901):
1. POST `/api/campaign-drafts` — name
   `Navreo · Competitor engagers · LinkedIn monitoring`, `client_id:
   "client-1"` (Navreo), goal "Monitor competitor LinkedIn engagements",
   `autopilot: false` (manual review — leads wait for ✓).
2. POST `/api/sources` — ONE engagement source on that campaign:
   `linkedin_urls` = every profile_url from the Step-1 inventory,
   include topics seeded for Navreo (Tooling, AI-for-sales, GTM strategy,
   GTM tutorials and giveaways + wildcard "posts comparing outbound tools"),
   the standard avoid-topic defaults, engager titles = Navreo ICP roles,
   14-country set, size 10-200, copy_reference ON, cap 25.
3. Leave destination unset — the user picks Smartlead/HeyReach in the
   campaign header when ready (nothing pushes until then; manual mode).

**Done-rule:** GET `/api/campaign-drafts` shows the campaign under client-1;
GET `/api/sources` shows the source with all N profile URLs in
`config.engagement.linkedin_urls`; Supabase `signal_sources` mirrors it with
the right client/campaign chain.

### Step 3 — Migrate workflows (create → verify → delete, per workflow)

For each MIGRATE entry, in sequence (pace ~1s between workflows):
1. Build the new definition with `_eng_workflow_def(src, author_name,
   search_id)` — author_name = the person's real name from the old body's
   `postAuthorName` (not a slug guess); keep the old `maxComments` if ≤25,
   else 25.
2. POST `/workflows` with `search_id`, `enabled: true`, `status:
   "PUBLISHED"`, name `"[Person] Engagers → Navreo Tool (<source_id>)"`.
3. Verify by GET: trigger bound to the same search_id, push URL is the
   Supabase endpoint, body carries the new source_id chain.
4. Only then DELETE the old workflow.
5. Append `{profile_url, search_id, workflow_id}` to the source's
   `config.engagement.trigify[]` (via the tool, so Supabase stays in sync)
   and mark the entry done in the state file (idempotent resume).

On any per-workflow failure: leave that OLD workflow untouched, record the
error, continue the batch. The step's retry re-runs failures only.

**Done-rule:** every inventory entry is marked done; for each, the new
workflow GETs back bound + PUBLISHED and the old workflow id returns
not-found; the source row in the tool shows `monitoring N/N`.

### Step 4 — Prove the pipe with one live test-fire

Pick one migrated workflow whose search has a recent post (GET
`/searches/{id}/results`). POST `/workflows/{id}/test` with
`overrides.post_url` = that real post and `test_config.mode:
"real_with_override"`. Then confirm the chain: new row(s) in
`engagement_events` with the new source_id → run the tool's pull → verdicts
written (string-gate rejects are fine — that's the qualifier working) → any
QUALIFIED engager visible in the campaign's Leads tab.

**Done-rule:** at least one engagement_events row from the test fire carries
the new source_id, and its status is no longer NEW after the pull.

### Step 5 — Sweep for stragglers (the user's verification, verbatim)

Fresh full API sweep: no workflow in the account has an `http_request` step
pointing at `run.revcode.app` or `*.make.com`. Report the final state: N
migrated, campaign link (`#<cdraft-id>`), and the explicit note that the OLD
pipeline (Make → Google Sheet → lilly-trigify-data-processing) stops
receiving new engagers from these profiles — the tool owns them now, and the
old Make scenarios/Sheets can be archived whenever the user is ready (do NOT
delete them; historical data lives there).

**Done-rule:** the sweep returns zero Clay/Make-pointing engagement
workflows, and the summary (with workflow counts before/after and the
campaign URL) has been surfaced to the user. This passing = overall
done-rule met.

---

## Retry + halt protocol

- 1 initial attempt + 2 retries per step; a retry must change something.
- Step 3 retries re-run only its FAILED workflows (state file is the
  ledger), never the already-migrated ones.
- On halt: report the step, the failing clause, the evidence, the most
  likely fix — and, for Step 3, the exact list of workflows left on the old
  path so nothing is half-migrated silently.
- Steps 1-2 are read/tool-local and safe; Step 3 is the mutating batch —
  in Loop Training Mode it MUST show the inventory diff and get approval
  before the first delete.

## Guardrails

- NEVER PATCH/update an existing workflow — recreate with `search_id`
  (the trap above).
- NEVER delete a saved search in this migration.
- NEVER delete an old workflow before its replacement is verified bound.
- The old Make scenarios and Google Sheets are archives — leave them.
- No em-dashes in any user-facing copy the campaign generates.
