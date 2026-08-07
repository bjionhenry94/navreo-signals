---
name: onboard-client
description: Static orchestration skill that onboards a NEW client into the Navreo signals tool end-to-end, for BOTH client types — an in-our-workspace client (like ThunderBird: campaigns live inside our Smartlead account, told apart by campaign-name token) and an own-workspace client (like Grout: their own Smartlead account + API key). One run wires every integration surface so the client is fully managed in the tool: the reply pipeline is set up as an ACCOUNT-WIDE Smartlead webhook (so new campaigns are auto-covered and never launch uncategorised) feeding a Make router/categoriser that does BOTH halves — sets the category + posts the positive card to the client's Slack channel AND archives the reply to the Setter; campaigns show on the Campaigns page, their lists show in the Lists section, and their analytics show in the Analytics/Deliverability section. Also owns the persistent DEMO client (a fake client that STAYS, for showing prospects) plus a Settings toggle to show/hide demo clients in day-to-day use. Verifies with synthetic mocks — never touches real prospects. Fixed steps, per-step done-rules, retry cap, Loop Training Mode (default ON). Use when the user says "onboard a new client", "add a new client", "onboard [client]", "connect [client]", "set up [client] in the tool", "create the demo client", or "/onboard-client".
---

# Onboard Client — one loop, both client shapes

Make onboarding a new client boring and repeatable. Two shapes of client, one process,
every integration surface lit up and mock-verified before we call it done.

## ⚙️ LOOP TRAINING MODE — the toggle (flip it here)

```
LOOP_TRAINING_MODE: ON     ← flip to OFF to run autonomously
RETRY_CAP: 3               ← per step, both modes
```
A `training off` / `training on` in the invoking message overrides this for that run only.

**When ON (default):** pause at EVERY step — announce what it will do, do it, show the
evidence, then WAIT for Bjion's explicit approval before the next step. Before running a
step, check its done-rule first; **if it already passes, skip it** (say so, show the
evidence, move on). Only re-run steps that FAIL. "go / yes / continue" advances; anything
else is revision feedback (Bjion-requested re-runs don't count against the cap).

**When OFF:** run all steps autonomously, no pauses — but keep EVERY done-rule check,
every skip-if-passing, and the SAME retry cap. Report at the end, not between steps.

**Both modes — retry cap:** any single step runs **max `RETRY_CAP` (3)** times against its
done-rule; only the failing unit re-runs. On cap-hit, record **FAILED** with the honest
reason, keep going where you safely can, and surface it in the final report. Never fake a
green, never silently exceed the cap.

## HARD RULE — never send to real prospects
Every verification uses a **synthetic webhook payload** (an `is_test` / clearly-labelled
"PIPELINE TEST" lead), never a Smartlead send and never a real lead row. This is the
[[never-send-to-real-prospects]] invariant. If a step can only be proven by a real send,
mark it FAILED and hand back to Bjion — do not improvise a real send.

## STEP 0 — Intake (decide the shape, gather the inputs)

Ask Bjion (or read from the request) and write these into the run record:
- **Client name** + **display label** (e.g. "Grout", "KRG Advisors").
- **Shape:**
  - **IN-WORKSPACE** — campaigns live in OUR Smartlead account, named with a token
    (e.g. every campaign name contains "thunderbird"). No separate key.
  - **OWN-WORKSPACE** — their own Smartlead account. Needs their API key.
- **Campaign-name token** — the lowercase substring that identifies their campaigns
  (used for Slack routing + name-gating). E.g. `thunderbird`, `grout`, `krg`.
- **OWN-WORKSPACE only:** their Smartlead API key → store in `~/.navreo-keys.env` as
  `<SLUG>_SMARTLEAD_API_KEY`, **never** in this file or the repo.
- **Slack channel** — the client-facing channel id for positive replies (find with a
  Slack channel search; the client-facing one is the `…-navreo` channel, not `…-private`).
- **Reply-router hook** — the Make hook URL for this client's router/categoriser scenario
  (own-workspace: clone one in step 3c if new). This is what the account-wide Smartlead
  webhook (step 3) points at. Record it in the run record.
- **DEMO?** — is this the persistent demo client? (see the DEMO section). Real clients: no.

**Done-rule:** the run record names the shape, token, label, Slack channel id, and (own-
workspace) confirms the key resolves — `ws_key_for_campaign(<one of their campaign ids>)`
returns a non-empty key that is NOT the navreo env key.

## THE STEPS (each has a done-rule; skip any already-passing one)

### 1 · Register the client in the tool
- **OWN-WORKSPACE:** `POST /api/workspaces` (`api_workspaces_add`) with slug + display_label
  + key env name. This one row feeds all four surfaces via `workspaces.display_label`
  ([[client-workspace-labels-one-source]]) — no per-surface edits.
- **IN-WORKSPACE:** add `("<token>", "<Label>")` to `_SHARED_WS_CLIENTS` in `app/server.py`
  (~line 13868) AND to the analytics client registry (~line 14435) so campaigns name-gate
  to this client instead of falling into `__unassigned` or inflating Navreo.
- **Done-rule:** the client appears in `/api/workspaces` (own) or `_SHARED_WS_CLIENTS`
  (in-workspace); a known campaign of theirs resolves to their label, not Navreo/unassigned.

### 2 · Campaigns show on the Campaigns page
- Run the workspace/campaign sync so `campaign_scorecard` rows are stamped with the
  right `workspace` (own) or name-gated client (in-workspace).
- **Done-rule:** on the LIVE Campaigns page, filtering to this client shows their
  campaigns with real sent/reply/positive counts — and no other client's.

### 3 · Wire the reply pipeline — ACCOUNT-WIDE webhook, both halves
This is the step that stops the recurring "positives not reaching Slack or the Setter"
bug ([[client-positive-pipeline-map]]). Two non-negotiables:

**(a) The reply webhook must be ACCOUNT-WIDE, never per-campaign.** Per-campaign webhooks
mean every new campaign a launch skill creates silently starts with NO categorisation —
the exact failure that hit KRG (5 live campaigns, 25 uncategorised replies) and Asteri
(84 webhook-less campaigns). Set ONE account-level `Email Reply` (EMAIL_REPLY) webhook in
the client's Smartlead workspace UI (**Settings → Webhooks → Add Webhook**), pointed at
the client's Make router/categoriser hook. New campaigns are then auto-covered forever.
- **UI-only, and you cannot do it via API** — every account-webhook API path 404s. Bjion
  sets it in the Smartlead UI (walk him through it, or drive his Chrome). Give him the
  exact event (**Email Reply**, NOT "Lead Category Updated", NOT "Untracked Replies") and
  the workspace's hook URL.
- Own-workspace hooks on file: KRG `wvqbmh5dyvhyw61ou4gkciijvwlrfsv2`, Asteri
  `mi39u1ax894q3r3y2b4uxblajginn4je`, Grout `4mlkjiuly67am9qkpxcos5emxhaxehuo`. A NEW
  client needs its own router scenario cloned first (see 3c).

**(b) The workspace's scenario must do BOTH halves — category+card AND Setter archive.**
The "router" half (sets Smartlead category, fires the client Slack card + Notion portal,
DNC→pause+blocklist) and the "archive" half (POSTs the reply to the Supabase `ingest`
function → `replies` table, which is what the Setter reads) are separate modules. A
scenario missing the archive module categorises + cards but the reply NEVER reaches the
Setter — KRG's exact bug (router fed Slack, not the Setter, for 8 days). Confirm the
client's scenario contains the `Supabase reply archive (<slug>)` http module: it POSTs
`https://fnykldftbkrccihdjayl.supabase.co/functions/v1/ingest` (header
`x-navreo-token=NAVREO_INGEST_TOKEN`, qs `type=reply, workspace, client_id, campaign_id,
email, category, message_id=<lead_id>-<reply_time>, replied_at`, body = reply text).

- IN-WORKSPACE: replies already flow through the shared categoriser → Setter intake.
- OWN-WORKSPACE: replies depend ENTIRELY on this webhook+scenario — there is NO reply-sync
  backstop for client workspaces ([[client-workspace-reply-backstop-gap]]).
- **Done-rule:** a synthetic positive for this client (i) sets a category in Smartlead,
  (ii) appears as a Setter queue row for the right client, categorised + draftable, AND
  (iii) has a row in Supabase `replies`. All three, or the archive half is missing.

### 3c · The client's router/categoriser scenario (own-workspace, new client)
A brand-new own-workspace client needs its own Make scenario before 3(a) has a hook to
point at. Clone a proven one — KRG router **9580455** is the reference (webhook → lead
lookup → only-if-no-category guard → GPT categorise → per-category Smartlead write-back →
positive branch: Slack card + Notion portal + phone enrich → **Supabase archive module**).
- `scenarios_get` 9580455, swap the Smartlead API key (client's), the Slack channel id,
  the Notion portal DB id, and the `workspace`/`client_id` qs values in the archive module
  to the new slug; `scenarios_create`/`update`; re-fetch and diff.
- **Done-rule:** the new scenario is active, its hook URL is recorded for step 3(a), and
  its flow contains BOTH the Slack-card module and the Supabase archive module.

### 3b · Create the client's Setter agent (automatic — no UI clicking)
Registering the workspace/token (step 1) already federates the client's replies into
the Setter list + intake (monitor-only, commit aaacee0) — zero code edits. What does
NOT happen by itself is drafting: a client with no setter agent gets queue rows but no
drafts. Wire it here, every onboarding, via the live API (the same routes
[[lilly-appointment-setter]] uses):
- Gather the mini-brief during STEP 0 intake: pricing, resources + when to send each,
  booking link. If Bjion hasn't supplied them, ask ONCE at intake — never at this step.
- `GET /api/setter/campaigns` → resolve the client's campaign ids (their token / workspace).
- `POST /api/setter/agents/save` `{name: "<Label> Setter", instructions: <house-shape
  brief>, campaign_ids: [...], booking_link}` — or `agents/duplicate` from a proven
  agent when the offer matches, then `agents/save` the campaign ids onto the clone.
- **Done-rule:** `GET /api/setter/agents` lists the client's agent with their campaign
  ids attached, and a synthetic test row for one of their campaigns drafts with that
  agent (draft-only via `POST /api/setter/queue/redraft` — never a send).

### 4 · Positive replies post to the client's Slack channel
- Add a router branch to **Make scenario 8946472** ("SmartLead Positive Reply (Navreo)
  → Folk + HeyReach"), cloned from the ThunderBird/Grout/KRG branches: a `slack:CreateMessage`
  card + BetterContact phone-enrichment + threaded phone reply, `__IMTCONN__ 9254394`
  (NAVREO BOT), pointed at the client's channel.
- **Filter:** `{{lower(1.campaign_name)}}` **text:contain** `<token>`. Use `lower()` —
  Make's `text:contain` is CASE-SENSITIVE; a lowercase token vs a `ThunderBird…` name
  silently never matches (this exact bug cost a whole test cycle).
- OWN-WORKSPACE relies on the shipped fix: `positive_card_notify` resolves the client's
  Smartlead key for the `/leads/?email=` lookup (commit 7edde38) — without it the card
  never builds. Confirm that deploy is live before testing an own-workspace client.
- The Make **NAVREO BOT app must be a member of the private channel** or the post fails
  `not_in_channel` — Bjion invites `@make`; you cannot.
- Wholesale-replace safety: `scenarios_get` first, append the branch, `scenarios_update`,
  then re-fetch and **diff** — every existing route must be byte-identical.
- **Done-rule:** a synthetic positive for this client posts the card to the right channel
  (verify by reading the channel). Note the ~8-min latency: 8946472 runs its router
  branches sequentially behind two ~4-min enrichment waits.

### 5 · Their lists show in the Lists section
- Ensure the client's lists surface in `app/lists.html`, scoped to their workspace/label.
- **Done-rule:** the Lists section, filtered to this client, shows their lists.

### 6 · Their analytics show in the Analytics/Deliverability section
- Confirm the client appears in the Deliverability page's client filter and that their
  client-window analytics (`/api/client-windows`) compute.
- **Done-rule:** the Deliverability page filtered to this client renders their real
  messaging/reply/deliverability numbers.

### 7 · Mock verification (all surfaces, synthetic only)
- Fire a synthetic `LEAD_CATEGORY_UPDATED` payload (`navreo_source: categoriser`,
  `new_name: Interested`, campaign_name containing `<token>`, an obviously-fake
  "PIPELINE TEST — please ignore" lead) at the positive-card hook
  `https://hook.eu2.make.com/qt3b07kefg9ogusrgd044qh1uae7hu27`.
- **Done-rule:** within one run cycle — (a) card lands in the client's Slack channel,
  (b) the row shows in the Setter for the right client AND has a Supabase `replies` row
  (the archive half — a Slack card WITHOUT a `replies` row is the split-scenario bug),
  (c) Campaigns/Lists/Analytics each show the client. Record which surfaces passed; any
  miss = FAILED for that surface.
- **After onboarding, run `/positive-push-guard`** for this client (or add it to the
  daily guard's workspace list) — it re-verifies webhook coverage, zero uncategorised,
  Setter parity, and Slack cards, and is the standing net that catches this class of bug.
- Cleanup note (hand back to Bjion, don't do destructively): each mock leaves a labelled
  Slack test card + one Folk "Clients pipeline" test contact — list them for deletion.

## THE DEMO CLIENT (persistent — build once, then it just exists)

A fake client — **"Navreo Demo Co"** — that STAYS in the tool so Bjion can show prospects
what the platform looks like with live-looking campaigns, positives, lists, and analytics.

- Onboard it exactly like a real IN-WORKSPACE client (token `demo`), but seed it with
  synthetic-but-realistic data across all surfaces so every section looks populated.
- Mark it demo: add an **`is_demo` boolean** on the client record — `workspaces.is_demo`
  for own-workspace-style, and a demo entry in the client registry flagged demo for the
  name-gated path. Demo data must never mix into a real client's numbers.
- **Settings toggle:** on `app/settings.html`, a **"Show demo clients"** switch
  (persisted; default **OFF/hidden** in day-to-day). When OFF, demo clients are filtered
  out of Campaigns, Lists, Analytics, and the Setter everywhere. When ON, they appear
  labelled as demo (a small "DEMO" badge) so no one confuses them with a real client.
- **Done-rule:** with the toggle **OFF**, "Navreo Demo Co" is invisible on all four
  surfaces and the Setter; with it **ON**, it appears (badged DEMO) with populated,
  clearly-synthetic data — and toggling never alters any real client's numbers.

## OVERALL DONE-RULE
For the onboarded client (real or demo), on the LIVE host: campaigns visible, positives
reach the Setter, positives post to the right Slack channel, lists visible, analytics
visible — all mock-verified — AND the demo client + show/hide toggle behave per their
done-rules. Every step green by its own rule (or explicitly FAILED with the honest
reason). Nothing sent to a real prospect. End with a one-screen report: per-step
pass/FAILED, the client's token + channel, and the cleanup list (test cards + Folk rows).

## KNOWN GOTCHAS (learned the hard way — check these first)
- **Reply webhook MUST be account-wide, not per-campaign** → per-campaign hooks mean every
  new campaign starts uncategorised (KRG: 25 missed; Asteri: 84 campaigns). Account-wide is
  UI-only (API 404s); Bjion sets it, event = **Email Reply**.
- **Account-wide webhooks are invisible to the Smartlead API** → you CANNOT verify coverage
  by listing `/campaigns/{id}/webhooks`. Verify by OUTCOMES instead: zero uncategorised
  replies (`lead_category_id` null in the master inbox), Setter parity, Slack cards present.
- **Scenario must do BOTH halves** → category+Slack card AND the Supabase `ingest` archive
  module. A card-only scenario means positives hit Slack but never the Setter (KRG, 8 days).
- **`POST /campaigns/{id}/webhooks` rejects `"categories": []`** → omit the field entirely.
- **Master-inbox field is `lead_category_id`** (not `lead_category`, which doesn't exist).
- **Manual archive backfill** for replies missed while a scenario was broken: POST reply
  text to the `ingest` function with the qs in step 3(b); it dedupes on `message_id`.
- **Make `text:contain` is case-sensitive** → always filter on `{{lower(1.campaign_name)}}`.
- **`positive_card_notify` was navreo-key-hardwired** → own-workspace clients need the
  `campaign_id`-threaded key resolution (commit 7edde38 on `main`); confirm it's deployed.
- **Client-workspace replies have no backstop** → they live or die by the Make webhook.
- **8946472 is a shared production scenario** → always get→append→update→re-fetch→diff.
- **`@make` must be in the client's private channel** → else `not_in_channel`; Bjion invites.
- **~8-min card latency** is expected (sequential branches behind two 4-min enrichment waits).
- **Demo DATA is not seedable via `campaign_scorecard`** → the Campaigns page
  (`campaigns_unified`) and analytics daily lines read LIVE from Smartlead, so fake
  scorecard rows never surface there, and unfiltered SQL aggregates (`collective_30d`,
  `analytics_hub_v1`) get corrupted by fake sends. Populate a demo client via a real
  low-volume campaign OR a proper synthesised demo-data layer — never bare scorecard rows.
  (The `is_demo` flag + `_client_hidden` filter + Settings toggle ARE the right machinery.)
