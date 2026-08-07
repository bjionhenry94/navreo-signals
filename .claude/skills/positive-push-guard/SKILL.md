---
name: positive-push-guard
description: Audit + repair the positive-reply pipeline across ALL client workspaces so every new positive automatically reaches (a) the client's shared Slack channel and (b) the setter tool. Sweeps webhook coverage on every non-draft Smartlead campaign, re-drives missed replies, live-tests with real/synthetic positives, and installs a temporary daily guard routine. Use when positives are missing from client channels or the setter, when onboarding a new client workspace, or on "run the positive push guard", "audit response notifications", "/positive-push-guard".
---

# Positive-Push Guard — response-notification audit loop

## ⚙️ LOOP TRAINING MODE: **ON** ← flip this line to OFF to run autonomously

**ON** (default): pause at EVERY step below and wait for Bjion's explicit approval
before continuing. Skip any step that already passes its done-rule. Only re-run
steps that fail. **OFF**: run all steps autonomously with no pauses — but keep
every done-rule check and the retry cap.

**Retry cap: 3 attempts per step.** A step failing 3 times = STOP the loop,
report the blocker, wait for Bjion. Never loop past the cap in either mode.

## Goal (done-rule for the whole loop)

Every ENABLED workspace (Supabase `workspaces`, status=enabled): all non-draft
Smartlead campaigns carry that workspace's reply-router/categoriser webhook, the
master inbox has ZERO uncategorised replies (`lead_category_id` null), every
recent positive shows a card in the client's shared Slack channel AND a row in
the setter (Supabase `replies`), at least one live test positive has traversed
the whole pipe per workspace, and the daily guard routine exists. All green in
one final read-only sweep = loop closed.

## Architecture truth (read before Step 1 — do NOT rediscover this)

- Categorisation per client workspace = Smartlead **per-campaign** EMAIL_REPLY
  webhook → Make scenario → GPT category → POSTs category back to Smartlead;
  positives → client Slack channel card + Notion portal DB; DNC → pause +
  domain-blocklist. **No webhook on a campaign = replies invisible everywhere.**
  Client workspaces have NO backstop (reply-sync in the signals repo is
  Navreo-only) — see memory `client-workspace-reply-backstop-gap`.
- Known Make scenarios (team 536258): KRG router **9580455** (hook
  `wvqbmh5dyvhyw61ou4gkciijvwlrfsv2`, has an only-if-no-category guard, THE live
  KRG path); Asteri categoriser **9187631** (hook `yxjoi7s...`); Grout
  `smartlead-reply_categoriser-Grout`; Navreo **9251436** (+ server backstop +
  positive-card hook 4001002 → scenario 8946472). Older per-client categoriser
  scenarios may be superseded by router scenarios — trust **executions_list**
  (what actually fires on fresh replies), not scenario names.
- Keys: `~/.navreo-keys.env` (Supabase + Navreo Smartlead). Per-workspace
  Smartlead keys: Supabase `workspaces.api_key`.
- Gotchas: POST `/campaigns/{id}/webhooks` 400s on `"categories": []` — omit the
  field, keep `{"id": null, "name", "webhook_url", "event_types": ["EMAIL_REPLY"]}`.
  Master-inbox field is `lead_category_id` (`lead_category` doesn't exist).
  Re-drive payload = `{"event_type":"EMAIL_REPLY","sl_lead_email","sl_email_lead_id",
  "campaign_id","reply_message":{"text","time"}}` posted straight to the Make hook.
  Reply text: fetch `/campaigns/{cid}/leads/{lid}/message-history`, last
  type=REPLY, strip HTML. Positive categories = Interested(1), Meeting
  Request(2), Information Request(5) + manual variants; ids can differ per
  workspace — resolve via `/leads/fetch-categories` each time.

## Steps

### Step 1 — Inventory (read-only)
For each enabled workspace: campaigns list (id/status/name), the Make scenario
that ACTUALLY fires on its replies (match executions_list timestamps to fresh
master-inbox replies), its hook URL, the client shared Slack channel id (from
the scenario blueprint's slack:CreateMessage module), and whether the scenario
has the only-if-no-category guard.
**Done-rule:** a table (workspace → scenario id, hook URL, Slack channel,
guard yes/no, campaign count) with no unknowns. Unknown scenario for a
workspace = that IS the finding — record it and continue; Step 3 will surface
the damage.

### Step 2 — Webhook coverage sweep + fix
Every non-draft campaign (ACTIVE/PAUSED/COMPLETED/STOPPED — completed campaigns
still receive replies) must carry its workspace's hook as an EMAIL_REPLY
webhook. Attach where missing. DRAFTED campaigns get it too (cheap, and they
launch without warning).
**Done-rule:** re-list webhooks on every campaign — 100% coverage.

### Step 3 — Uncategorised backlog re-drive
Per workspace: pull master inbox (`replyTimeBetween` last 30d, paginate by 20),
find `lead_category_id` null. Re-drive each through the workspace hook (payload
above, ~4s apart). If the scenario has NO only-if-no-category guard, still safe
here (these have no category by definition) — but never re-drive already-
categorised replies through a guardless scenario.
**Done-rule:** re-poll after ~2 min — zero uncategorised remain. Replies with
permanently-empty bodies may be skipped; list them explicitly.

### Step 4 — Positive parity check (Slack + setter)
For every positive-categorised reply in the last 14d per workspace: (a) card in
the client's shared Slack channel (slack_search / read_channel around the reply
time, match lead email), (b) row in Supabase `replies` and visible to the setter
(GET /api/setter/queue or the replies archive it reads). Re-driven replies from
Step 3 count.
**Done-rule:** every positive is in BOTH places, or each miss is repaired
(re-drive fires the Slack card; if the scenario doesn't archive to Supabase
`replies`, that's a scenario defect — fix the scenario or record it as a blocker
for Bjion, don't hand-insert rows silently).

### Step 5 — Live test positives  ⚠️ gates
Per workspace, ONE live proof the pipe works end-to-end:
- **Prefer a real missed positive** re-driven in Step 3/4 — that already IS the
  live test; cite it and skip synthetic.
- Otherwise inject a synthetic positive through the hook for an `is_test` lead
  ONLY (**NEVER a real prospect** — memory `never-send-to-real-prospects`; check
  `row.status`/is_test before any Smartlead write). A synthetic card lands in a
  CLIENT-VISIBLE channel — in Training Mode get Bjion's OK first; in autonomous
  mode use an obviously-labelled test lead ("Navreo Pipeline Test") and follow
  the card with a one-line "ignore — pipeline test" in the same thread.
**Done-rule:** per workspace, one named positive (real or test) verified in
Slack channel + setter, with timestamps.

### Step 6 — Daily guard routine (temporary)
Create a LOCAL scheduled task (scheduled-tasks MCP — visible in the Routines
panel, NOT a cloud trigger; memory `gtm-morning-routines`) named
"Positive-push guard daily check", daily ~08:30, prompt = run Steps 1-4 of this
skill READ-ONLY (no fixes, no test positives) and report: coverage %,
uncategorised count, positive-parity misses, per workspace. Any red = tell
Bjion immediately with the failing workspace/campaign.
**Temporary:** the routine's prompt must state — after 14 consecutive clean
days, propose its own removal to Bjion.
**Done-rule:** task exists in the Routines panel + one manual run of its check
comes back clean.

### Step 7 — Close-out
Final read-only sweep of the whole done-rule. Update memories
(`krg-reply-router-is-categoriser`, `client-workspace-reply-backstop-gap`) with
anything learned; new memory per newly-mapped workspace. Report to Bjion: table
of workspaces × (coverage, backlog cleared, parity, live test, routine), plus
the standing prevention rule: **every new campaign in a client workspace gets
its workspace webhook attached at launch** — wire this into lilly-bot /
onboard-client / smooth-campaign-launch when next touched.
**Done-rule:** report delivered; all steps green or blockers explicitly named.

## Standing rules

- Read-only diagnosis before ANY write; every fix verified live before "done".
- No Smartlead sends, no lead-status changes beyond what scenarios do by design.
- Client-visible side effects (late positive cards) are the pipeline catching up
  — allowed; anything else client-visible needs Bjion's OK.
- Every update to Bjion includes a verified link/proof (memory
  `updates-need-verified-link`).
