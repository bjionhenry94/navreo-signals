---
name: engagement-signal-ship
description: Orchestration skill that ships the "warm leads engaging with LinkedIn profiles" signal in the Navreo signals tool (app/campaigns.html + app/server.py + Supabase). Mirrors the lilly-trigify-setup duplicate-workflow pattern but repoints the Trigify push at OUR tool/Supabase instead of Clay/Make. Builds the setup wizard (LinkedIn URLs to monitor, post-topic checklist + wildcard, engager qualifying criteria), a GPT-5-mini qualification layer, daily engager processing, and auto-push into HeyReach/Smartlead. Static plan with pre-baked done-rules, retry caps, and a Loop Training Mode toggle. Trigger on: 'ship the engagement signal', 'build the warm-leads LinkedIn signal', 'run engagement-signal-ship', '/engagement-signal-ship'.
---

# Engagement Signal Ship

## ⚙️ Loop Training Mode — TOGGLE HERE

```
LOOP_TRAINING_MODE: OFF
```

Flip the value above (`ON` / `OFF`) to change behaviour. This line is the single
source of truth; read it at the start of every run.

**When ON (default):**
- PAUSE at every step boundary. Show the step's plan + its done-rule, wait for
  explicit user approval ("go" / "approve") before executing.
- Before executing any step, TEST its done-rule first. If it already passes,
  SKIP the step (report "Step N already passes — skipped") and move on.
- Only re-run steps whose done-rule FAILS. Never re-run a passing step.
- Retry cap: max 2 re-runs per step (3 attempts total). On exhaustion, HALT the
  loop and report the failing done-rule verbatim with the evidence.

**When OFF:**
- Run all steps autonomously, no pauses, in order.
- KEEP the done-rule check before and after every step (skip-if-passing still
  applies) and KEEP the retry cap (2 re-runs, then halt and report).

Either mode: never mark a step done on faith — a done-rule passes only with
observed evidence (a curl response, a DB row, a screenshot, a Trigify API body).

---

## Goal

Users of the tool at `http://localhost:7901/app/campaigns.html` can provide a
list of LinkedIn profile URLs to monitor, receive the people engaging with
those profiles' posts on a daily basis, have each engager qualified by
GPT-5-mini (post-topic fit + person fit), and have qualified engagers pushed
automatically into the campaign's HeyReach list or Smartlead campaign.

**Overall done-rule:** an engagement-signal campaign exists in the tool, its
Trigify workflows exist and are bound to the right saved searches, a test push
from Trigify lands a prospect visible in the tool's Leads tab AND as a row in
Supabase, and that prospect (when qualified) push-routes to the campaign's
destination.

## Architecture (target state)

```
Trigify saved search (1 per monitored LinkedIn URL, DAILY)
  └─ Trigify Workflow (1 per search — the pushToClay step REPOINTED)
       http_request → Supabase PostgREST insert → engagement_events (staging)
                                    │
app/server.py daily processing (pull_engagement_source, mirrors pull_hiring_source)
       reads staging → GPT-5-mini qualify (post gate + person gate)
       → prospects in the campaign draft (Leads tab) → signals table
       → auto-push: EXCLUSIVE routing (email → Smartlead, else HeyReach)
```

Key repo anchors: `ROUTES` dict at app/server.py:1722, `pull_hiring_source`
at :1382 (the pattern to mirror), `push_prospect`/`auto_push_new_leads`/
`resolve_destination` at :1181/:1237/:1166, wizard mechanism catalogue at
app/campaigns.html:1193 (the `engagement` tile already exists but is unwired),
`signals` table at db/schema.sql:146 (`signal_type='engagement'`,
`source='trigify'`). Supabase project: `fnykldftbkrccihdjayl`.

Reference skills (read, do not invoke): `lilly-trigify-setup` (workflow
duplication + verified webhook payload schema in its Phase 4b),
`lilly-trigify-data-processing` (4-gate qualification semantics, HARD RULE on
never referencing competitor posts in copy).

Keys: `~/.navreo-keys.env` — needs `TRIGIFY_API_KEY`, `OPENAI_API_KEY`,
`SUPABASE_*`, `SMARTLEAD_API_KEY`, `HEYREACH_API_KEY`.

---

## Steps

### Step 1 — Staging table + ingest path in Supabase

Create `engagement_events` staging table (migration via Supabase MCP
`apply_migration`): columns mirroring the VERIFIED Trigify payload from
lilly-trigify-setup Phase 4b (`postUrl`, `postAuthorName`, `postText`,
`engagementType`, `commentText`, `engagerFullName`, `engagerLinkedinUrl`,
`engagerJobTitle`, `engagerCompanyName`, `engagerCompanyDomain`,
`engagerCompanyHeadCount`, `engagerCountry`, …) plus `source_id` (which tool
campaign it belongs to), `status` (`NEW`/`QUALIFIED`/`OFF_BRIEF`/`PUSHED`),
`raw` jsonb, `received_at`. Unique index on
(`source_id`, `engagerLinkedinUrl`, `postUrl`).

Ingest is a direct PostgREST insert (Trigify's `http_request` step can POST
anywhere; localhost cannot receive it, Supabase can). Also add a local
`/api/trigify-webhook` POST route in server.py that accepts the same payload
and writes to the same table — used for local test pushes and as the
documented relay target if the user later fronts it with a tunnel.

**Done-rule:** `curl` a sample Trigify-shaped payload into the PostgREST
endpoint AND into `/api/trigify-webhook`; both return 2xx and
`select count(*)` on `engagement_events` shows both rows, deduped correctly on
re-send.

### Step 2 — Setup wizard in campaigns.html

Wire the existing `engagement` mechanism tile into a real setup flow. The
wizard step must capture:

1. **LinkedIn URLs to monitor** — textarea, one URL per line, validate
   `linkedin.com/in/` or `/company/` shape, dedupe, show count.
2. **Post types to scrape off the back of** — TWO lists, both editable chips
   plus a wildcard free-text field appended to the qualifier prompt:
   - **Topic INCLUDE list** — per-client, seeded from the client's offer
     (Navreo example: Tooling, AI-for-sales, GTM strategy, GTM tutorials and
     giveaways). A post must match the include list to pass the post gate.
   - **Topic AVOID list** — defaults pre-filled: anniversaries, personal
     stories, stories about struggles and triumphs, life lessons, sad or
     unfortunate posts or news. An avoid-list match fails the post gate even
     when the engager is a perfect person-fit.
3. **Engager qualifying criteria** — target titles (chip input, Navreo ICP
   defaults), countries (default 14-country high-GDP set), company size band
   (default 10-200), free-text avoid rules ("no recruiters, no direct
   lead-gen agencies").
4. **Copy reference mode** — user decides whether outreach copy may reference
   the engagement. Toggle: "Mention the post in copy?" (default ON). When ON,
   two per-lead merge variables are filled for every pushed prospect:
   `{{WhosePost}}` (post author's full name, from `postAuthorName`) and
   `{{Topic}}` (short human topic label for the post, generated by the Step-3
   GPT-5-mini call from `postText`). When OFF, both variables fill with
   role/company-anchored fallbacks so templates never render empty.
5. **Daily cap** (default 25) and destination (existing destination picker —
   Smartlead campaign or HeyReach list, EXCLUSIVE routing preserved).

Persist all of it in the source config (same shape `save_draft`/`update_source`
already store), under `config.engagement`.

**Done-rule:** in the browser (preview tools), complete the wizard for a test
campaign with 2 LinkedIn URLs; the saved source JSON in the drafts store
contains all five config blocks exactly as entered (URLs, post types +
wildcard, qualifying criteria, copy reference mode, cap + destination), and
reloading the page re-renders them.

### Step 3 — GPT-5-mini qualification layer

Add `qualify_engager(event, cfg)` to server.py: ONE OpenAI Chat Completions
call per engager to model `gpt-5-mini` (`OPENAI_API_KEY` from
`~/.navreo-keys.env`), structured JSON output:
`{post_verdict, person_verdict, verdict: QUALIFIED|BORDERLINE|OFF_BRIEF, reason}`.

The prompt embeds the wizard's post-type checklist + wildcard (post gate) and
the qualifying criteria (person gate). The same call also returns `topic` — a
short human label for the post (e.g. "cold email deliverability") used to fill
`{{Topic}}` — so qualification and topic extraction cost one call, not two.
Cheap string gates run BEFORE the API call: country and headcount checks fail
fast with no token spend, matching the cheapness-order rule from
lilly-trigify-data-processing. Cache verdicts by (`engagerLinkedinUrl`,
`postUrl`) so re-runs are free.

**Done-rule:** a pytest-style script (app/ has precedent: `targeting_test.py`,
`prompt_test.py`) feeds 6 fixture engagers (2 clear-fit, 2 clear-miss on
title/geo, 1 off-topic post, 1 borderline) through `qualify_engager`; the two
clear-fits come back QUALIFIED, the three clear-misses OFF_BRIEF, and the
string-gate misses show zero OpenAI calls in the log.

### Step 4 — Trigify provisioning (duplicate-and-repoint)

Mirror lilly-trigify-setup Phase 5, per monitored LinkedIn URL:

1. `create_linkedin_profile_search` (Trigify MCP) — 1 saved search per URL.
2. `create_workflow` per search — clone the verified workflow shape
   (get_post_likes/comments → person_enrichment → http_request) but the
   `http_request` step POSTs the Step-1 payload to the Supabase PostgREST
   endpoint (apikey + Authorization headers in the workflow's request config,
   `Prefer: resolution=ignore-duplicates`).
3. GOTCHA (memorised, verified): `search_id` is only settable at workflow
   CREATE time — PATCH strips it. Rebind = delete + recreate, never PATCH.
4. Wire this into the wizard's "Launch" action: server.py calls the Trigify
   REST API directly (same endpoints the MCP wraps) so the tool provisions
   without Claude in the loop; store returned search/workflow ids on the
   source config.
5. Comments+likes vs comments-only and `max_engagers` per post: default
   comments-only, cap 25 (the Make-ops-blast lesson).

**Done-rule:** for the test campaign's 2 URLs, `list_searches` +
`get_workflow` show 2 searches and 2 workflows, each workflow's trigger bound
to the right `search_id`, and each `http_request` step's URL is the Supabase
endpoint with `source_id` set to the tool campaign's id.

### Step 5 — Daily processing + auto-push

Add `pull_engagement_source(src, drafts)` to server.py (register in `ROUTES`
via the existing `/api/sources/pull` dispatch, alongside `pull_hiring_source`):

1. Read `engagement_events` rows with `status='NEW'` for this `source_id`.
2. Run Step-3 qualification. Write verdicts back (`QUALIFIED`/`OFF_BRIEF`;
   BORDERLINE stays visible in the tool for a manual keep/drop, never
   auto-pushed).
3. QUALIFIED → build prospect rows (engager IS the lead; email via existing
   `find_email` waterfall only when destination is Smartlead), fill the
   per-lead variables `{{WhosePost}}` + `{{Topic}}` per the campaign's copy
   reference mode (real values when ON, role/company fallbacks when OFF),
   insert `signals` rows (`signal_type='engagement'`, `source='trigify'`),
   append to the draft's leads so the Leads tab shows them.
4. Push via existing `auto_push_new_leads`/`push_prospect` — EXCLUSIVE
   routing (email found → Smartlead, else HeyReach `AddLeadsToListV2`, never
   `AddLeadToCampaign`). Respect the daily cap and the suppression sweep.
5. Register the source in `db/pull_signals.py` so the existing daily runner
   picks it up.

**Done-rule:** seed 3 fixture events (2 pass, 1 fail) as `NEW`, run the pull:
the 2 qualified appear in the tool's Leads tab AND as `signals` rows in
Supabase, statuses flip to `PUSHED`/`OFF_BRIEF`, re-running the pull is a
no-op (idempotent), and the push calls hit the destination for a test-flagged
campaign (or log the exact payload in dry-run when no test destination is
configured).

### Step 6 — End-to-end verification (the task's stated verification)

1. Set up a REAL engagement-signal campaign through the wizard (user's own
   LinkedIn URL + one competitor is a good pair).
2. Confirm in Trigify (API, not faith) that the new searches + workflows
   exist and are bound.
3. Trigger a test push from Trigify where possible (`test_workflow` /
   workflow test-run via API); if Trigify offers no test-fire, POST one
   payload captured from a real prior workflow run instead and say so
   explicitly in the report.
4. Confirm the prospect arrives: `engagement_events` row → qualified →
   visible in the Leads tab → `signals` row → push (or dry-run payload)
   toward the campaign's destination.

**Done-rule:** all four confirmations observed and reported with evidence
(Trigify API response bodies, Supabase row ids, a Leads-tab screenshot, the
push response or dry-run payload). This step passing = overall done-rule met.

---

## Retry + halt protocol

- Attempt counter is per step, per run. 1 initial attempt + 2 retries max.
- A retry must change something (fix the code, correct the payload, rebind
  the workflow) — never re-run the identical failing action verbatim.
- On halt: report which step, which done-rule clause failed, the evidence,
  and the single most likely fix. Do not continue to later steps whose
  done-rules depend on the halted step.
- Steps 1-3 are independent of Trigify and may proceed even if Step 4 is
  blocked (e.g. Trigify tier/auth issues); Steps 5-6 require 1-4.

## Guardrails

- Post references in copy are the USER'S call, made per campaign via the
  wizard's copy reference mode toggle (Step 2.4). When ON, `{{WhosePost}}` and
  `{{Topic}}` carry the post author's full name and the post topic into the
  copy; when OFF they fall back to role/company anchors. The build must not
  hard-ban post references — but the wizard should show a one-line caution
  next to the toggle ("referencing a competitor's post reveals you monitor
  their audience") so the choice is informed.
- Never enrich or push BORDERLINE engagers without an explicit user keep.
- All Smartlead/HeyReach pushes go through the server's existing push
  functions — no new direct-API paths.
- No em-dashes in any user-facing copy the feature generates.
