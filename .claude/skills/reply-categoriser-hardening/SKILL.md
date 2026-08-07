---
name: reply-categoriser-hardening
description: Static orchestration skill that hardens the Smartlead reply-categoriser Make scenarios (Navreo 9251436, Asteri 9187631) so a single bad reply can never auto-deactivate them. Fixed step list, each with a checkable done-rule, plus a Loop Training Mode toggle. The goal is resilience: feed the scenario every failure that has happened plus the ones we anticipate, and it stays ACTIVE every time. Use when the user says "fix my reply categoriser", "the categoriser keeps turning off", "harden the Make reply scenario", or "/reply-categoriser-hardening".
---

# reply-categoriser-hardening

Make the two reply-categoriser scenarios **un-turn-off-able**. A Make scenario auto-deactivates after enough consecutive *errored* executions, so the real fix is that **nothing throws** — every module either succeeds or is cleanly skipped/caught. Static loop: the steps below are fixed, each has a done-rule, and Loop Training Mode controls whether you pause between them.

**The two scenarios** (Make zone `eu2.make.com`, org `1634255`, team `536258`):
- **Navreo `9251436`** — hook `4135325`, Smartlead key `a8f9359c…`. Full flow: categorise + Slack + 🚨 re-reply branch.
- **Asteri `9187631`** — hook `4105127`, key `1417c9a6…`. Tagging only, no Slack.

**Flow** (per scenario): `EMAIL_REPLY` webhook → GET `/leads/?email=` → gate (only if no existing category) → GET `/campaigns/{cid}/leads/{lead_id}/message-history` → GPT-4o-mini into 8 buckets → POST `/category` → (Navreo) Slack. Router after module `29`: routeA = original, routeB = 🚨 module `51` (positive lead replied again).

**Editing:** blueprints are edited via the **Make MCP** (server `Make`): `scenarios_get` to pull, `validate_blueprint_schema` before write, `scenarios_update` to patch, `scenarios_run` to test-run, `executions_list` / `executions_get-detail` to inspect, `scenarios_activate` to re-enable. Direct API fallback: PATCH `/api/v2/scenarios/{id}` with `{blueprint:<stringified>}`, header `Authorization: Token …` — that token is **not** in `~/.navreo-keys.env`, so ask Bjion for it only if the MCP write path fails.

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

**Retry cap (both modes):** any single step retries **max 3** times against its done-rule. On cap-hit, stop that step, record it as FAILED with the reason, keep going, and surface it in the final report. Never silently exceed. The test step (Step 7) has its own cap: **max 3 hardening→retest rounds** total, then stop and report whatever cases still fail.

---

## THE GOAL

Both scenarios survive **every** failure a reply can trigger and **stay ACTIVE** — no auto-deactivation, ever. **Done means:** after replaying the full failure matrix (Step 7) through each scenario, its status is still ACTIVE and no execution errored in a way that throws. A bad reply is either processed correctly or cleanly ignored; it never kills the scenario.

**Convention (reuse, don't reinvent):** this is a *hardening* pass on the existing blueprints, not a rebuild. Preserve the flow, the router, the 8-bucket prompt, the category-id map, and the channel routing exactly. Change only the error-handling surface: `stopOnHttpError`, filter guards, empty-id gates, and module-level error handlers. Never re-tag a lead that already has a category (additive-only). Do not touch Asteri's separate Slack/Notion routing scenario `9414775`.

**CONFIRMED ROOT CAUSE (2026-07-06), fix already shipped to Navreo:** the repeat deactivations were `Failed to evaluate filter '0-0'` IMLErrors — a Smartlead **429** returns the rate-limit string as the lookup body, and the old truthiness guard `if(29.data.lead_campaign_data; …)` lets that truthy string reach `map()`, which throws on a non-array. Fix = guard on HTTP status instead: `{{if(29.statusCode = 200; get(map(29.data.lead_campaign_data; …); 1); "")}}` on all 8 routeB conditions, and gate routeA (module 2) with `29.statusCode=200` + `sl_email_lead_id exist`. Plus `maxErrors` 3→10 and `maximum_runs_per_minute` 60→30. Do NOT set `sequential:true` (240s BetterContact sleep would serialise the queue). If the categoriser deactivates again, Step 7's job is to find the *next* distinct throw — this class is closed.

**Do-no-harm rules:**
- **Do not reactivate a dead scenario mid-work if its 3-day webhook queue still holds a backlog** — reactivating auto-replays queued webhooks. Finish hardening first, then reactivate once, and let Make replay; never also reconstruct replies manually or you double-post.
- Never poll the Smartlead key with `curl` while testing — that eats into the 200 req/min cap and can itself cause the rate-limit cascade you're trying to fix.

---

## THE STEPS

### Step 1 — Snapshot both blueprints
- `scenarios_get` for `9251436` and `9187631`. Save each blueprint JSON to scratch. Record: current status (active/dead), every `http:MakeRequest` module id, every filter expression, and the current `stopOnHttpError` / `dlq` / auto-disable settings.
- Done-rule: both blueprints saved to scratch; a written inventory lists each HTTP module id and each filter/router condition per scenario, with its current error setting noted.

### Step 2 — Kill `stopOnHttpError` on every HTTP module
- Set `stopOnHttpError:false` on **all** `http:MakeRequest` modules — GET `/leads/`, GET message-history, POST `/category`, and any auth/refresh calls — in **both** scenarios. A 404 (deleted lead / archived campaign), 429 (rate limit), 500/503 (transient) must return a value the flow can branch on, not throw.
- Done-rule: a grep/scan of both blueprints shows **zero** modules with `stopOnHttpError:true`; every HTTP module also has `metadata.scenario.dlq:true`.

### Step 3 — Gate the empty-lead-id case
- The POST failure that showed as `/leads//category` (double slash) is an empty `sl_email_lead_id` in the webhook. Add a guard so the POST module (and message-history GET) only runs when the lead id is non-empty; otherwise skip cleanly. Same for an empty/missing `email` or `campaign_id` on the inbound webhook — skip, don't build a broken URL.
- Done-rule: with a synthetic webhook missing `sl_email_lead_id`, the flow reaches the skip path and produces **no** `/leads//category` request; the run completes without error.

### Step 4 — Guard every filter that calls `map()`
- `map()` throws on a non-array → "Failed to evaluate filter" → deactivation. The routeB hi-priority filter used `get(map(29.data.lead_campaign_data; …))`. Wrap any such expression so a non-array yields a safe default instead of throwing: `{{if(29.data.lead_campaign_data; get(map(...); 1); "")}}`. Audit **all** router/filter conditions in both scenarios for the same pattern (`[]` accessors are already tolerant; only `map()` throws).
- Done-rule: every filter/router condition referencing an array is wrapped in an `if(<exists>; …; <default>)` guard; feeding a payload where `lead_campaign_data` is absent/non-array evaluates the filter without a "Failed to evaluate filter" error.

### Step 5 — Harden the lookup-returns-not-an-array cascade
- A 429 makes GET `/leads/` return an error object, not an array; downstream array access then throws. Add a shape check after each lookup: if the response isn't the expected array/object, route to the skip path. Optionally add a short retry-with-interval on 429 so genuine replies aren't dropped — but the non-negotiable is that a rate-limited lookup **never throws**.
- Done-rule: with a simulated non-array / error-shaped lookup response, the flow branches to skip (or retries then skips) and the execution completes without error.

### Step 6 — Harden the AI + Slack tail
- GPT-4o-mini: if it returns a bucket outside the 8 known categories, malformed JSON, or errors, fall back to a safe default (no category set / skip the POST) rather than throwing. Preserve the existing quirk map (AI "Interested" + "Meeting Request" → `category_id 2`) — do not change categorisation logic, only its failure handling.
- Slack (Navreo modules incl. 🚨 `51`): set the Slack modules to not stop on error (a gone channel or Slack 429 must not kill the scenario). Alert-only branch still must **not** re-tag.
- Done-rule: a malformed/out-of-range AI output and a failing Slack call each leave the run erroring-free; categorisation logic and channel routing are byte-for-byte unchanged from Step 1.

### Step 7 — Replay the failure matrix (THE VERIFICATION)
- Test each case below against **both** scenarios via `scenarios_run` with a synthetic `EMAIL_REPLY` payload (or a controlled webhook post). After each, check `executions_list` — the run may branch/skip, but must **not** leave an errored execution — and confirm the scenario is still ACTIVE.
- **Known (have happened):**
  1. Deleted lead → GET `/leads/` 404
  2. Archived campaign → message-history 404
  3. Empty `sl_email_lead_id` → `/leads//category` double-slash
  4. Rate-limit 429 (lookup returns error, not array)
  5. `map()` on non-array `lead_campaign_data` → filter throw
  6. Backlog drain blowing the 200/min cap (burst of payloads)
- **Anticipated (design for these too):**
  7. Webhook missing `email` / `campaign_id`
  8. Malformed / non-JSON webhook body
  9. Smartlead transient 500/503
  10. Empty message-history array
  11. Lead in multiple campaigns (multi-element `lead_campaign_data`)
  12. AI returns valid JSON, wrong shape / unknown bucket
  13. Slack channel gone / Slack 429
  14. HTTP module timeout
- On any case that leaves an errored execution or flips the scenario off: fix the responsible module (loop back to the relevant step), then re-run the **whole** matrix. Max 3 hardening→retest rounds, then stop and report remaining failures.
- Done-rule: all 14 cases run against both scenarios with **zero** throwing executions and both scenarios ACTIVE after the full matrix.

### Step 8 — Reactivate cleanly and confirm live health
- If either scenario was dead: reactivate it **once** (`scenarios_activate`). If its webhook queue is within the 3-day retention it will auto-replay the backlog — let it; do **not** manually reconstruct.
- Watch the first replayed/live executions in `executions_list`.
- Done-rule: both scenarios status = ACTIVE; the most recent real executions show success or clean-skip, no throws; no double-posting to Slack from a manual + auto replay.

---

## HOW TO RUN

1. Read the mode line above. If **ON**, do one step at a time and stop for approval after each; skip any step whose done-rule already passes. If **OFF**, run all eight in order without pausing.
2. For each step: make the blueprint edit via the Make MCP (`validate_blueprint_schema` → `scenarios_update`), then check the done-rule — scan the patched blueprint for the setting, and for Steps 3–7 actually `scenarios_run` the case and read `executions_list`. Retry a step up to 3× on failure, then mark FAILED and continue.
3. Step 7 is the real proof and Step 8 is outward-facing (a reactivate replays a live queue). In ON mode the pauses gate them; in OFF mode still confirm each done-rule passed before moving on.

## OVERALL DONE-RULE

- No `http:MakeRequest` module in either scenario has `stopOnHttpError:true`; every array-touching filter is `if()`-guarded; empty-id / missing-field paths skip cleanly.
- The full 14-case failure matrix (Step 7) runs against both scenarios with zero throwing executions and both stay ACTIVE.
- Both scenarios ACTIVE at the end, categorisation + routing logic unchanged from the Step 1 snapshot.
- Final report: one line per step — DONE / SKIPPED (already passed) / FAILED (with reason) — plus a 14-row matrix result (PASS/FAIL per case per scenario).
