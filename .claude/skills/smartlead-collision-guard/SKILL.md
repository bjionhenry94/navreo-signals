---
name: smartlead-collision-guard
description: Static orchestration skill that ends same-client cross-collisions in Smartlead — the same person live in two campaigns at once, or re-emailed by a recontact build. Routes out the existing backlog (pause the loser, keep the best-performing campaign), closes the two entry leaks (un-gated lead pushes, recontact netting against stale data), stands up a daily zero-target detector, then proves zero over a two-week watch. One fixed step list, checkable done-rules, retry cap, Loop Training Mode toggle (ON by default). Use when the user says "run the collision guard", "stop the duplicate outreach", "why did we email them twice", "/smartlead-collision-guard".
---

# Smartlead Collision Guard

## ⚙ Loop Training Mode: **OFF**   ← flip this line to ON to pause at every step

**ON (default):** pause at EVERY step boundary and wait for the user's explicit approval
before continuing. Before starting a step, check its done-rule FIRST — if it already
passes, report "Step N already passes, skipping" and move to the next pause. Only re-run
steps whose done-rule fails. Say what you are about to do before doing it.

**OFF:** run all steps end-to-end with no pauses. Done-rule checks, skip-if-passing, and
the retry cap stay exactly the same — only the pauses go.

**Retry cap (both modes):** each step retries **max 3** times against its done-rule. On
cap-hit: record the step FAILED with the reason, continue to the next step only if it
does not depend on the failed one, and surface every FAILED step in the final report.
Never silently exceed the cap. Never declare the skill done on a cap-hit.

**Live-sending gate (both modes, non-negotiable):** Step 3 pauses real leads in real
campaigns. Before the FIRST bulk pause fires, show the plan summary (leads, campaigns,
which campaign wins each tie) and get explicit approval — in BOTH modes, because this
mutates live sending. Pausing is reversible; deleting is not. **Never delete a lead.**

## Config (the rulings, in one place)

```
SAME_CLIENT_ONLY:        true    # HARD RULE (Bjion, 2026-07-24): cross-client overlap
                                 # is NOT a collision. A person in a Navreo campaign AND
                                 # an Amplifyy campaign is fine. Never flag it, never
                                 # pause for it, never report it.
CLIENT_RESOLUTION:       client token found ANYWHERE in the campaign NAME — never a
                                 # prefix test, never campaigns.client_id (it defaults
                                 # everything to navreo). 29 of 65 campaigns are named
                                 # "Reconnect: Amplifyy - …" / "Recontact (June): Navreo
                                 # - …", so startswith() filed 6 Amplifyy + 3 Arnic
                                 # campaigns under Navreo and invented 118 false
                                 # cross-client collisions on the first run.
                                 # 'navreo' WINS when two tokens appear: "Navreo - Arnic
                                 # List" and "ValSoft | B2B SaaS (Navreo)" are Navreo's.
                                 # NO token -> its own 'Unknown' bucket, never Navreo.
LIVE_STATUSES:           STARTED, INPROGRESS      # COMPLETED is not live
RESEND_WINDOW_DAYS:      30      # ONE window for everything: a send inside 30 days
                                 # collides with a new push AND blocks a recontact build.
                                 # Bjion's ruling 2026-07-25 (asked for 30; I had put 90).
                                 # For the record, so nobody "fixes" this back up: over
                                 # 270d of sent_messages the gap between two campaigns
                                 # emailing the same person was 0-30d ×1,199, 30-60d ×322,
                                 # 60-89d ×209, then thin — so 30d catches ~63% of
                                 # re-contacts and the 30-90d band is knowingly allowed.
                                 # 30 days is the policy; do not raise it without Bjion.
SUBSEQUENCE_NAMES:       "Interested Reply", "Meeting Request"
RETRY_CAP:               3
WATCH_DAYS:              14      # Step 7 consecutive-clean-days target
```

**The sub-sequence rule reads two ways and both are correct.** A lead sitting in a cold
campaign *and* its own follow-up sub-sequence is by design — do NOT pause it (Step 3
excludes sub-sequences). But cold-LOADING a new list with someone currently in a
follow-up flow is a collision — they are mid-conversation (Step 5 counts them).

## Goal

Zero same-client collisions, and they stay at zero. Three outcomes:

1. **Backlog routed out.** No person is live in 2+ same-client active campaigns.
2. **Both entry leaks closed.** No route into Smartlead can create a collision —
   including ad-hoc API pushes that never call the QA gate, and recontact builds that
   net against stale data.
3. **Standing proof.** A daily detector reports the collision count, alerts on any
   number above zero, and the count is observed at zero for `WATCH_DAYS` running days.

## Ground truth (measured 2026-07-24 — re-measure in Step 1, numbers drift)

- **Root cause is recontact GENERATIONS, not random import overlap.** Successive
  recontacts of the same follower audience all left ACTIVE at once. Worst pairs on the
  first run: "Recontact: Navreo - Followers Recovered" (June) vs the same name "[July]"
  = 611 leads live in BOTH; "Recontact (July): Salesloft Follower" 218; "Recontact
  (July): 6sense Followers" 132. One lead (areiter@cloudtask.com) sat in **18**
  campaigns across the Jan/April/June Salesloft generations and replied "You already
  send me this dude!". Look for same-stem names differing only by month.
- **Backlog measured 2026-07-25:** 1,489 leads live in 2+ same-client ACTIVE campaigns
  (Navreo 1,488, Amplifyy 1) across 94 reachable campaigns. Two earlier partial answers
  on the same day were 2,976 (Supabase, 86% ghosts) and 418 (live but scoped to 65
  campaigns) — see the Step 1/2 warnings for why both were wrong.
- ⚠️ **12 ACTIVE campaigns cannot be audited with the main API key** — they 404 because
  they live in client workspaces: Alpine, PestCo, ValSoft, KRG ×4, and the
  Geopolitical/Social/AI-Reputation set. Their collisions are UNAUDITED. To cover them,
  re-run per workspace with that workspace's key (`client-workspaces-hub`).
- ⚠️ **`contact_history` lags, and it will lie to you.** Today's manual sweep paused
  1,892 memberships, but only 274 `contact_history` rows changed in the last 24h and
  total `PAUSED` sits at 1,252. Pauses land eventually, not immediately. **A detector
  reading Supabase alone reports ghost collisions.** Every candidate must be confirmed
  live in Smartlead before it is acted on (Step 2), and the census must be re-derived
  after a fresh sync, not before (Step 1).
- Tables: `contact_history` (person↔campaign, `status`, `smartlead_campaign_id`),
  `sent_messages` (every outbound, `sent_at`), `campaigns` (`name`, `status`),
  `suppressions`, `list_upload_qa_runs` + `qa_gate_runs` (gate receipts).
- Existing gate: `lilly-upload-gate` already has a cross-campaign collision check
  (its Step 5.4). It is not the problem — **being skippable is the problem.** Ad-hoc
  `add_leads_to_campaign` / `push_leads_to_campaign` calls and Smartlead's own CSV
  import never touch it.
- Pause primitive (reversible, preferred over delete):
  `POST server.smartlead.ai/api/v1/campaigns/{cid}/leads/{lead_id}/pause?api_key=`.
  200 req/min cap → pace 0.5s, back off 25s on a rate-limit error.
  **Use `curl`, not `urllib`** — urllib throws SSL CERTIFICATE_VERIFY_FAILED on this Mac.
- ⚠️ Smartlead pagination truncates on rate-limit: an error mid-page reads as
  end-of-list. Stop only on a genuinely empty page.
- Server code lives in `~/navreo-signals` (git repo, Render auto-deploys on push to
  `main`). The iCloud copy is deprecated — never edit it. Cron endpoints follow the
  `POST /api/cron/<name>` + `x-navreo-token` pattern, token =
  `sha256(SERVICE_ROLE_KEY + ":signal-pull-v1")[:40]`, fired by pg_cron → pg_net.
- Harness hooks live in `~/.claude/settings.json` + `~/.claude/hooks/`. There is a
  working precedent to copy: `list-autopush-guard.sh` (a `Stop` hook).

## Steps

### Step 1 — Scope from the CAMPAIGN LIST, never from `contact_history`
⚠️ **The scope is every ACTIVE non-sub-sequence campaign — full stop.** On the first
run (2026-07-24) this step built its candidate set from `contact_history` instead, which
scoped the work to the 65 campaigns that happened to appear in a stale snapshot. Two
campaigns created *that same day* were invisible to the whole run, and one of them
(`3635581`) turned out to hold 611 real collisions. A candidate list derived from lagging
data cannot tell you what it is missing.
So: `select smartlead_campaign_id from campaigns where status='ACTIVE' and name !~*
'interested reply|meeting request'` — that list, every time. Supabase is used for the
tie-break and for context, never to decide which campaigns get looked at.
- **Done-rule:** the campaign list comes from `campaigns` (not `contact_history`), its
  count is stated, and every id in it is either exported in Step 2 or explicitly recorded
  as unreachable with the reason.

### Step 2 — Build the census from LIVE Smartlead data
**Use `GET /api/v1/campaigns/{id}/leads-export?api_key=` — ONE request returns the whole
campaign as CSV** (`id`, `status`, `email`, …). The first run started by paging
`/campaigns/{id}/leads?limit=100`, which capped at 100/page and needed 3,130 requests for
306k leads (~90 min, and it tripped the 200/min limit); the export endpoint did the same
job in 106 requests. Pace ~1.2s, retry on non-200, never treat an error as end-of-list.
Then compute collisions purely from that CSV: live = status `INPROGRESS`/`STARTED` in an
ACTIVE campaign. Supabase's count is a hypothesis to be checked, not an input.
Expect a large ghost rate — on the first run Supabase claimed 2,976 and live truth was
418 (86% ghosts, already paused by an earlier sweep the sync had not caught up with).
- **Done-rule:** the census is rebuilt from exports covering every campaign from Step 1;
  the ghost count (Supabase said collision, live disagreed) and the live-only count
  (Supabase missed it) are both reported. A zero ghost rate means the live read didn't
  actually run — check it.

### Step 3 — Route out the backlog (pause the loser, keep the winner)
For each confirmed lead, the campaign that KEEPS it is the one with the highest
**positives per 1,000 sent** (`campaign_lead_stats.interested / sent_count` from
`get_campaign_analytics`). Pause the lead in every other same-client campaign.
Runner must be resumable keyed on **(campaign_id, lead_id)** — one lead can lose in two
campaigns — and pace 0.5s with a 25s rate-limit backoff.
**Fire the live-sending gate before the first pause.**
- **Done-rule:** every confirmed lead is live in exactly one same-client campaign,
  verified by re-reading a random sample of 25 from Smartlead (not from the plan file);
  the paused-count delta shows up in `get_campaign_analytics`; every skip/failure is
  listed with its reason.

### Step 4 — Close entry leak #1: un-gated pushes
Make the gate unskippable at the harness level, not by good intentions. Add a
`PreToolUse` hook in `~/.claude/settings.json` matching the Smartlead lead-push tools
(`add_leads_to_campaign`, `push_leads_to_campaign`) that blocks the call unless a recent
`qa_gate_runs` / `list_upload_qa_runs` receipt covers that campaign and row set. Model
it on `list-autopush-guard.sh`. Keep `lilly-upload-gate`'s **Force upload** escape hatch
working and make the hook name it in its block message — a broken gate must never stop a
campaign going live (standing user rule), but the bypass must be a decision, not an
accident. Pair it with the server-side check so the Smartlead UI import route is covered
too, or record explicitly that UI imports remain uncovered.
- **Done-rule:** an un-gated `add_leads_to_campaign` call is blocked in a real session
  and the block message names the fix; a gated call with a valid receipt passes; the
  Force-upload path still works. All three demonstrated, not asserted.

### Step 5 — Close entry leak #2: recontact netting
A recontact audience must exclude anyone who (a) is live in ANY same-client active
campaign, including sub-sequences, or (b) received a send inside `RESEND_WINDOW_DAYS`,
or (c) is suppressed or has ever replied positively for that client. Net against a
**post-sync** read, and live-confirm the survivors before the draft is built — the same
staleness that produces ghost collisions produces real duplicates here. This is the leak
behind "You already send me this dude!" (areiter@cloudtask.com, campaign 3642940, from a
June recontact build). Update `lilly-recontact` so its netting carries all four rules.
- **Done-rule:** re-running the netting on the campaign that produced that reply now
  excludes that lead, and a fresh recontact build reports zero rows that any of the four
  rules should have caught.

### Step 6 — Stand up the daily detector
**BUILT 2026-07-24 — runs entirely inside Postgres, no app server, no HTTP.** An earlier
draft of this step specified a `/api/cron/collision-check` endpoint; that was the wrong
shape (PostgREST RPCs die at the 8s statement timeout and it couples the detector to a
Render deploy). What shipped instead:
- `collision_ledger` table — one row per UTC day: per-client counts, `double_sent_30d`,
  and `ch_newest` (the newest `contact_history` row the run could see — the staleness
  marker that stops a frozen snapshot reading as "clean").
- `collision_census_run()` — recomputes the Step 1 census and upserts today's row.
- `collision_detector_tick()` — runs the census, writes a `collision_alert` row to
  `app_activity_log` when the count is above zero. pg_cron `collision-check-daily`
  at **03:30 UTC**, deliberately AFTER the smartlead daily sync finishes (~02:25 UTC)
  so it never measures pre-sync data.
- `collision_detector_deadman()` — pg_cron `collision-deadman-daily` at 09:00 UTC.
  FAILS if no run in 30h, or if `contact_history` has not advanced in 48h. A check that
  cannot fail cannot pass.
- ⚠️ **Slack fan-out is NOT wired.** The only Make webhook in the repo is the
  client-facing positive-reply card hook and collision noise must never land there.
  Alerts are in-app (`app_activity_log`, actor `collision_detector`). To add Slack:
  create a Make webhook and `pg_net.http_post` it from `collision_detector_tick()`.
- **Done-rule:** the census returns today's real numbers on a manual fire; a row lands
  in `collision_ledger`; a non-zero count produces an alert row; the dead-man is proven
  to FAIL on stale data (test it in a rolled-back transaction, don't just watch it pass);
  the scheduled fire is confirmed by a run appearing without being triggered by hand.

### Step 7 — Prove it over the watch window
Read the detector ledger and report the trend. Every new collision that appears after
Step 4 is a leak the guard does not yet cover — trace how the lead entered (which
campaign, which push route, gated or not) and fix that route, then re-run Steps 4–6.
- **Done-rule:** `WATCH_DAYS` consecutive detector runs report zero new same-client
  collisions, with the run dates listed. Zero on day one is not the done-rule — new
  collisions being *created* is what is being measured, and that needs elapsed days.
  Until then, report honestly as IN PROGRESS with days elapsed.

## Final report

State per step: PASSED / SKIPPED (already passing) / FAILED (with reason and retry
count). Then: leads routed out, ghosts dropped, leaks closed, leaks still open,
detector status, and days clean out of `WATCH_DAYS`. **Never report the skill as done
while Step 7 is IN PROGRESS** — say what is closed and how many clean days have banked.
