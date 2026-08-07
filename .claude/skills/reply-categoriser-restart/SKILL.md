---
name: reply-categoriser-restart
description: Static orchestration skill that gets the Smartlead reply-categoriser (Make scenario 9251436)
  running again, identifies and permanently fixes the exact trigger that turned it off, then
  backfills every missed reply — categorising them, Slacking the positives, and writing Arnic/Amplifyy
  positives to their Notion portals. One fixed step list, each step with a checkable done-rule, retry
  caps, and a Loop Training Mode toggle. Use when the user says "the categoriser turned off again",
  "fix the reply categoriser", "the interested-replies Slack went quiet", or "/reply-categoriser-restart".
---

# Reply-Categoriser Restart & Backfill

The Smartlead reply-categoriser (Make scenario **9251436**) turns itself off on a recurring
basis, and when it does, replies stop being tagged and positives stop hitting Slack. This loop
does the whole recovery: diagnose which documented failure actually fired, reactivate + permanently
fix it, then sweep every reply missed during the outage back through categorisation, Slack, and (for
clients) Notion. Static loop — fixed steps, each has a done-rule, Training Mode controls the pauses.

## ⚙ Loop Training Mode: **OFF**   ← flip this line to ON to pause at every step

**ON:** pause at EVERY step boundary and wait for the user's explicit approval before continuing.
Before starting a step, check its done-rule first — if it already passes, report "Step N already
passes, skipping" and move on. Only re-run steps whose done-rule fails. Show what you're about to do
before doing it (especially before any hook POST that fires Slack).

**OFF:** run all steps end-to-end with no pauses. The done-rule checks, skip-if-passing behaviour,
and retry caps stay exactly the same — only the pauses go.

**Retry cap (both modes):** each step retries **max 3** times against its done-rule. On cap-hit:
record the step as FAILED with the reason, continue to the next step if it doesn't depend on the
failed one, and surface every FAILED step in the final report. Never silently exceed the cap. Never
declare the skill done on a cap-hit.

## Destructive / spend / outward gate (both modes, non-negotiable)

- **Slack is outward.** Backfilled positives fire Slack cards. In Training Mode ON, show the exact
  list of positives about to be replayed and get approval before the FIRST hook POST. Cap the replay
  batch and **throttle** (see Step 5) — a fast drain blows the Smartlead 429 cap and re-breaks the
  scenario.
- **Slack-notification-only ruling (user, 2026-07-15):** positives are Slacked via the categoriser
  hook only. **NEVER** route them through the enrichment pipeline **8946472 / hook 4001002** — that
  spends BetterContact + Prospeo credits per lead. Zero credits are spent this run.
- **Additive only:** NEVER re-tag a reply that already carries a category. Backfill only touches
  replies with NO category on their own campaign.
- **Never force-push / hard-reset** the navreo-signals repo (carries the owner's WIP) if any code
  fix is needed.
- **Make token `55f0f8c3-0dc4-41c5-9f85-abed0aa86a13` is for this run only — do NOT persist it to
  disk** (not to `~/.navreo-keys.env`, not to any artifact).

## Goal

1. Scenario **9251436** is `isActive:true` and its latest execution succeeds.
2. The exact trigger that turned it off is named with evidence and **permanently fixed** (re-proven live).
3. Every reply missed during the outage is categorised; its positives are in Slack; its Arnic/Amplifyy
   positives are rows in the client Notion portals (or the Notion 404 is surfaced with ids).
4. No reply is double-posted.

> Done = all 6 verification checks below pass on independent read-back from the destination tools.
> Anything less = not done. On a retry cap-hit, stop and report the gap honestly — do not declare done.

## Ground truth (verified 2026-07-15 — re-verify in Step 1, state drifts)

- **Categoriser = Make scenario `9251436`** (zone `eu2.make.com`, org 1634255, team 536258). Workspace-level
  webhook, hook id `4135325`, live url `https://hook.eu2.make.com/6mda3nqyrtm8u4x9ihilymra4z70aaug`.
  Smartlead key `a8f9359c…`. Flow: `EMAIL_REPLY` → GET `/leads/?email=` → gate "no existing category on
  THIS campaign" → GET message-history → GPT-4o-mini → POST `/category` → Slack positives.
- **Make access:** token `55f0f8c3-0dc4-41c5-9f85-abed0aa86a13`. Read/patch via `GET`/`PATCH
  https://eu2.make.com/api/v2/scenarios/{id}` with header `Authorization: Token <token>`; PATCH body
  `{blueprint:<stringified>}`, blueprint root `{name,flow,metadata}` only, `scheduling` passed
  separately. Reactivate via the scenarios start/activate endpoint. **A Make MCP may not be present —
  use the REST API.**
- **Slack routing:** campaign name contains "Navreo" → `#interested-replies` `C096Q9LHQGZ`; else →
  `#client-interested-replies` `C0B96LNPWDB` (Arnic + Amplifyy land in the client one).
- **Positive category ids:** `1` Interested, `2` Meeting Request, `5` Information Request, `78386`
  Re: Interested, `83039` Call Booked, `125938` [Manual] Interested. (Quirk: automation POSTs AI-Interested
  AND AI-Meeting-Request both as id `2`; real id `1` is never set by the automation.)
- **Supabase** (project `fnykldftbkrccihdjayl`): table `replies` — cols `smartlead_campaign_id, email,
  replied_at, category, reply_body, raw, workspace`. Filter `workspace='navreo'`. Backfill window =
  auto-detect where daily `count(category)` cratered vs `count(*)`.
- **Backfill mechanism (zero credits):** POST each missed reply to the categoriser hook once the scenario
  is ACTIVE — shape `{event_type:"EMAIL_REPLY", sl_lead_email, sl_email_lead_id:<GLOBAL lead id>,
  campaign_id, reply_message:{text,time}}`. The flow reads only those fields; GPT categorises
  `reply_message.text`. This path tags + Slacks positives; it does NOT touch Folk/HeyReach.
- **Three documented failure families (Step 2 must pick the real one):**
  - (a) **Auto-deactivation from errored executions** — non-array into `map()` on a Smartlead 429
    (200 req/min/key cap) or a `404` from deleted lead / archived campaign. Fix invariant: every
    `http:MakeRequest` has `stopOnHttpError:false`; every routeB/route filter guards on
    `29.statusCode = 200`, not truthiness. `scenario.maxErrors`≥10, `maximum_runs_per_minute`≤30.
  - (b) **Campaign-level webhook diverting replies** — once a campaign has its OWN `EMAIL_REPLY`
    webhook, the workspace categoriser is suppressed for it. Setter's `ensure_webhooks` was made a
    no-op in navreo-signals commit `0e0fea5` (2026-07-15), but CONFIRM none re-appeared. Candidate
    campaigns = union of `setter_agents.doc->campaign_ids` + distinct `setter_queue.smartlead_campaign_id`;
    check each via Smartlead `GET /campaigns/{id}/webhooks`.
  - (c) **Fail-closed gate regression** — module 2 reverting to `max(map(...))` makes `max([])=0` →
    blocks EVERY uncategorised reply. Confirm module 2 is the per-campaign `get()` form:
    `{{if(29.statusCode=200; get(map(29.data.lead_campaign_data;"lead_category_id";"campaign_id";1.campaign_id);1);1)}} notexist`.
- **Reactivation auto-replay (webhook retention = 3 days):** reactivating within retention auto-replays
  queued webhooks → may self-drain the backlog. Do NOT also manually replay those same rows (double-post).
- **Notion (clients only):** Arnic + Amplifyy positives → their portal "All Campaign Responses" DBs, written
  DIRECTLY via Notion API/MCP (decoupled from pipeline 8946472). The Make Notion connection `11521245` has a
  **known 404** against these DBs — if a direct write also 404s, surface the DB ids + pending lead list.
- **Relevant memories:** `reference_smartlead_reply_categoriser`, `project_reply_categoriser_accuracy_audit`,
  `reference_manual_positive_reply_replay`, `reference_positive_reply_noname_fix`.
- **Unknown until Step 1/2:** which failure family fired this time; the exact outage-start date; whether the
  Make queue already auto-replayed on any interim reactivation.

## Steps

### Step 1 — Re-verify ground truth & establish current state
Confirm each ground-truth fact against live systems: `GET /scenarios/9251436` (record `isActive` + last
execution status), run the Supabase daily `count(*)` vs `count(category)` query over the last ~21 days to
find the cliff, and note the last known-good date. Resolve the recorded unknowns.
- **Done-rule:** (a) scenario active-state + last-execution status read back from the Make API and recorded;
  (b) the outage-start date is pinned to a specific day from the Supabase cliff; (c) the count of outstanding
  (null-category, workspace=navreo) replies in the window is computed and recorded.

### Step 2 — Diagnose the actual trigger
Determine which of the three failure families fired, with evidence: read the scenario's recent **execution
log** via the Make API (look for the deactivation error + reason), inspect module 2's gate expression and the
`stopOnHttpError`/statusCode guards in the blueprint, and check for campaign-level webhooks on all candidate
campaigns. Name the winner; do not guess.
- **Done-rule:** the root-cause family (a/b/c) is stated with the specific evidence that proves it (the Make
  error line, the offending gate expression, or the diverting webhook id on a named campaign). If multiple
  contributed, all are named. FAILED if no evidence-backed cause can be identified after 3 tries.

### Step 3 — Apply the permanent fix
Fix per the diagnosed family: (a) restore `stopOnHttpError:false` on all HTTP modules + statusCode=200 guards,
bump `maxErrors`/throttle, and PATCH the blueprint; (b) DELETE the diverting campaign-level webhook(s) via
Smartlead `DELETE /campaigns/{id}/webhooks` body `{"id":N}` (if the source is code, fix at source with the
safe worktree procedure — never force-push); (c) restore module 2's per-campaign `get()` gate and PATCH.
Then **reactivate** the scenario.
- **Done-rule:** (a) the specific fix is applied and re-read back from the destination (blueprint field shows
  the corrected expression / `GET webhooks` shows 0 diverting hooks); (b) `GET /scenarios/9251436` returns
  `isActive:true`.

### Step 4 — Prove the fix live
POST ONE real previously-dropped reply from the window to the categoriser hook and confirm it comes back
categorised in Smartlead (`GET /leads/?email=` shows a category on its own campaign) and, if positive, lands
in the correct Slack channel.
- **Done-rule:** the test reply reads back with a non-null category from Smartlead (not from the hook's 200),
  and its Slack card is visible if it was positive. FAILED if the reply stays uncategorised after 3 tries.

### Step 5 — Backfill the outstanding replies (throttled)
First **check whether the Make auto-replay already drained the queue** (compare current outstanding count vs
Step 1; watch the scenario's execution log for a replay burst). For every reply still outstanding in the
window, build the payload (needs the GLOBAL `sl_email_lead_id` — resolve via Smartlead lead lookup) and POST
to the hook, **throttled to stay well under 200 req/min** (e.g. ≤2/sec, and never curl-poll the same key
concurrently). Skip any reply that already carries a category (additive only). Batch cap + Training-Mode
approval per the gate above.
- **Done-rule:** (a) every outstanding reply in the window has been POSTed exactly once OR was confirmed
  already-drained by auto-replay; (b) no reply was double-submitted (reconcile against the auto-replay burst);
  (c) throttle held — no 429 errors appeared in the scenario execution log during the drain.

### Step 6 — Write client positives to Notion
For Arnic + Amplifyy positives in the window, write a row into each client's portal "All Campaign Responses"
Notion DB directly via the Notion API/MCP. If a write 404s, stop and surface the DB id + the pending lead list.
- **Done-rule:** each Arnic/Amplifyy positive from the window is present as a row in its portal DB (read the
  rows back), OR the 404 is surfaced with exact DB ids and the still-pending lead list. Never silently skip.

### Step 7 — Full verification sweep
Run all 6 checks in the Verification section, reading each result back from the destination tool (Make API,
Smartlead re-fetch, Supabase re-query, the two Slack channels, the Notion DBs).
- **Done-rule:** all 6 checks pass. Any failing check = the loop is not done; record it and, if fixable,
  re-run the owning step within the retry cap.

## Final report (always, both modes)

One summary listing: (1) scenario active-state + last-execution status; (2) the named root-cause family + the
exact fix applied + the live re-proof result; (3) outage window (start→now) and the count of replies
backfilled vs auto-replayed vs skipped-already-categorised; (4) count of positives Slacked, per channel, with
a few lead ids as evidence; (5) Arnic/Amplifyy Notion rows written (or the 404 blocker with DB ids + pending
list); (6) double-post reconciliation result; and every step marked passed / skipped / FAILED with reasons.
Name the real numbers — "a summary" is not a spec.

## Hard don'ts

- Never route backfilled positives through pipeline **8946472 / hook 4001002** — Slack-only, zero credits.
- Never re-tag a reply that already carries a category on its own campaign (additive only).
- Never persist the Make token to disk.
- Never drain the backfill without throttling, and never curl-poll the Smartlead key during a drain —
  both blow the 200 req/min cap and re-break the scenario.
- Never double-post: reconcile against Make's 3-day auto-replay before manually replaying.
- Never force-push or hard-reset the navreo-signals repo; use the worktree procedure for any code fix.
- Never silently skip a Notion 404 — surface it with ids.
- Never exceed a retry cap or report done while any of the 6 verification checks fails.
