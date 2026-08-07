---
name: lilly-appointment-setter
description: Create and manage AI appointment-setter agents in the Navreo signals tool from chat - no UI clicking. Gathers the brief (client, campaigns, pricing, resources and when to send each), composes the agent's instructions in the house shape, creates or updates the agent via the live API, assigns campaigns, and optionally mints a public client training link and pulls the first training batch. Also duplicates a proven agent for a new campaign set and teaches standing corrections. Use whenever the user wants to create, edit, clone, list, or teach a setter agent. Trigger phrases: "create a setter agent", "new appointment setter for [client]", "set up an agent for [campaign]", "duplicate the [agent] for [client]", "give the agent these instructions", "share a training link for [agent]", "lilly appointment setter", "/lilly-appointment-setter".
---

# Lilly Appointment Setter

Creates and manages the Appointment Setter's agents (the per-campaign auto-responders on navreo-signals.onrender.com/app/setter.html) entirely from chat. An agent is ONE jsonb doc whose brain is a single free-text `instructions` field - pricing, resource links, and plain-English when-to-send-which rules all live in that text (owner ruling 2026-07-14: no structured resource fields). Nothing this skill does can ever send an email: new agents start in draft-only mode and the global autopilot master switch is untouched.

## Ground truth (verified 2026-07-14)

- **API base**: `https://navreo-signals.onrender.com`. Auth = `navreo_session` cookie, minted locally:
  ```python
  import hmac, hashlib, base64, time
  from pathlib import Path
  keys = {}
  for line in (Path.home()/".navreo-keys.env").read_text().splitlines():
      line = line.strip()
      if line.startswith("export "): line = line[7:]          # lines are `export KEY=...`
      if line and not line.startswith("#") and "=" in line:
          k, v = line.split("=", 1); keys[k.strip()] = v.strip().strip('"').strip("'")
  secret = hashlib.sha256((keys["SUPABASE_SERVICE_ROLE_KEY"] + ":navreo-session-v1").encode()).digest()
  payload = f"bjion@navreo.ai|{int(time.time()) + 86400}".encode()
  cookie = base64.urlsafe_b64encode(payload).decode().rstrip("=") + "." + hmac.new(secret, payload, hashlib.sha256).hexdigest()
  # send as header: Cookie: navreo_session=<cookie>
  ```
- **Routes** (all JSON):
  - `GET /api/setter/agents` -> {agents: [docs], settings} (settings.autopilot_enabled - NEVER write it)
  - `GET /api/setter/campaigns` -> Smartlead campaigns for name->id resolution
  - `POST /api/setter/agents/save` {id?, name (REQUIRED), instructions, campaign_ids: [ints], allowed_intents, mode, confidence_threshold, calendly_event_url, booking_link} - MERGES onto the stored doc, so send only the fields you're changing (a full-doc echo is never needed and risks clobbering)
  - `POST /api/setter/agents/duplicate` {agent_id} -> clone (new id, "<name> copy", draft-only, NO campaigns)
  - `POST /api/setter/agents/correction` {agent_id, text, scope: "remember"|"one_off", source} - "remember" MERGES the lesson into the agent's instructions text via an editor model (URL-survival guard; falls back to appending a "Training note"); every merge is logged in the agent doc's `instruction_edits` list. The instructions ARE the single living manual - there is no separate memory store for new lessons.
  - `POST /api/setter/training/share` {agent_id, days?} -> {url_path} - public client training link, no login
  - `POST /api/setter/training/generate` {agent_id, batch_size<=10} - pulls real replies and runs the agent on them (costs ~2 gpt-5-mini calls per scenario; takes minutes). Async: returns `{"status":"started"}` immediately, then read results from `GET /api/setter/training?agent_id=<id>` -> {cases:[...]}. Each case has `inbound.body` (the real reply), `original_outreach`, `draft_html` (the agent's draft), `category`, `decision`, `generated_at`. Watermark on the newest `generated_at` before triggering so you can spot the fresh batch. `generate` only pulls whatever real replies happen to exist, so it will NOT reliably surface the specific scenario a given edit targets - use queue/redraft below for a targeted test.
  - `GET /api/setter/training?agent_id=<id>` -> {cases:[...]} - the generated training scenarios (real reply + agent draft), newest by `generated_at`.
  - `GET /api/setter/queue` -> {rows:[...], kpis, last_checked} - the LIVE reply queue. Each row: `id` (row id), `agent_id`, `reply_body` (real inbound, often HTML), `draft_body` (current draft), `category`, `status` (needs_review | sent | dismissed | ...), `is_test`, `smartlead_campaign_id`, `lead_first_name`. Filter by `agent_id` to a single agent.
  - `POST /api/setter/queue/redraft` {id} -> regenerates that row's `draft_body` using the agent's CURRENT instructions and returns the updated row. Draft-only: it NEVER sends. This is the targeted-test lever - pick a real row whose reply matches the behaviour you just changed and redraft it to see the new draft. (`POST /api/setter/queue/redraft/status` {id} exists but is effectively synchronous; just re-read the row.)
- **Agent doc fields that matter**: `name`, `instructions`, `campaign_ids` (ints; saving also registers Smartlead EMAIL_REPLY webhooks additively - never with a `categories` key, the save route handles it), `allowed_intents` (from: send_resource, pricing, scheduling - Director default is all three), `mode` ("draft_only" | "autopilot" - ALWAYS create as draft_only), `confidence_threshold` (default 0.9, leave it), `calendly_event_url`, `booking_link`, `memory` (standing lessons - written via correction, never by hand).
- **Pipeline laws the instructions must respect**: the drafter may only use links that literally appear in the instructions (anything else fails lint); if the instructions contain 2+ links and a lead's original outreach can't be loaded, the reply is held for a human; pricing questions are only auto-answered when the instructions literally contain the answer; em-dashes in copy fail lint - never put one in instructions text the agent might quote.

## The instructions house shape

Compose `instructions` as plain text in this order (each part optional except at least one of pricing/resource):

```
Pricing: <the exact pricing text the agent may quote verbatim - full sentences, real numbers>

Resource: <name> - <link>
<one line on what it is>. Send this link when <plain-English rule tied to what the outreach said, e.g. "the lead asks for the guide, breakdown, or more information offered in the outreach">.

Resource: <name 2> - <link 2>
<what it is>. Only send when <rule, e.g. "the original outreach pitched the AEO/GEO teardown - check the original email">.

<any other standing behaviour, tone notes, or things to never do>
```

Rules tie to what the OUTREACH SAID, not campaign names - the drafter grounds its choice on the original email text it sees above the reply.

## Workflow

### Create an agent
1. Gather (ask ONCE, batched, only for what's missing): client/agent name; which campaigns (names are fine); pricing text (exact, or "no pricing - hold those"); each resource as name + link + when-to-send; Calendly event URL + booking link (default: the Navreo ones already on existing agents); allowed intents (default all three).
2. Resolve campaign names -> ids via `GET /api/setter/campaigns` (fuzzy match, confirm ambiguous matches with the user).
3. Compose instructions in the house shape. No em-dashes. Show the user the final instructions text + campaign list and get one confirmation.
4. `POST /agents/save` (no `id` -> creates; response carries the new id). Verify by reading `GET /agents` back and checking name, campaign_ids, and that every resource link appears in the stored instructions.
5. Offer (don't auto-run): a client training link (`POST /training/share`, hand back the full URL - anyone with it can train that agent for 30 days, no login) and a first training batch (`POST /training/generate` - warn it takes a few minutes; needs the agent's campaigns to have real replies).

### Edit / teach an agent
- Field changes (name, campaigns, calendly, intents, full instructions rewrite): partial `POST /agents/save` with `id` + `name` + only the changed fields. For instructions edits, ALWAYS fetch the current text first and edit it - never compose from memory, the doc may hold lessons the user added elsewhere.
- A standing behavioural lesson ("always lead with the $300 line"): `POST /agents/correction` scope "remember" - this is additive and shows up in the Training page's memory viewer where it can be removed.
- Adding a resource = editing instructions (append a Resource block).
- To change what the drafter actually WRITES (not just what it knows), edit the templates and worked examples it imitates, not only an appended correction. A rule tacked on the bottom loses to the exemplars in the templates/examples; if drafts keep reverting to old phrasing, rewrite the template lines themselves. Never hard-code one vertical's brand names in a worked example - the drafter parrots them onto every lead; keep example names category-generic or varied.

### Verify every edit actually fires (MANDATORY after any save/correction that changes drafting behaviour)
Never leave an edit unverified. A merged correction is not proof the drafter will act on it. Immediately test it against a real reply:
1. `GET /api/setter/queue`, filter to the agent's `agent_id`, and find a real row whose `reply_body` matches the behaviour you just changed (e.g. for a "name category-matched brands on a proof ask" edit, find a row asking for examples / proof / "who have you worked with" / "links to live brands"). If no exact match exists, pick the closest real reply, or fall back to `training/generate` and read the fresh cases.
2. Capture that row's current `draft_body` (the "before").
3. `POST /api/setter/queue/redraft` {id}, then re-read the row for the new `draft_body` (the "after"). This uses the current instructions and never sends.
4. Check the change actually shows up (the new brand names appear, the greeting is fixed, the link is present, etc.). If it did NOT fire, adjust the correction wording (be more explicit / imperative) and repeat from step 3. Iterate until it fires.
5. Show the user the before/after draft so they can see the effect, and flag any new issue the test surfaces (a wrong signer, a lost link, an over-correction). Redrafting a live `needs_review` row is safe (draft-only), but say that you did it.
This find-a-reply-and-redraft loop IS the fastest way to test and adjust - treat it as part of every edit, not an optional extra.

### Duplicate for a new client/campaign set
`POST /agents/duplicate`, then a follow-up `save` on the clone: real name, the new campaign_ids, and edited instructions (usually same pricing, different resources/rules). Clone arrives draft-only with no campaigns - it claims nothing until you assign.

### List / inspect
`GET /agents` -> report per agent: name, mode, campaigns (resolve ids to names), first lines of instructions, memory count, and whether the master switch is on (it should be off unless the user flipped it deliberately).

## Hard don'ts
- Never set `mode: "autopilot"` or touch `autopilot_enabled` - going live is the user's click in the UI, never this skill's.
- Never save an agent without `name` (the API 400s) and never send a partial save that omits `name`.
- Never invent campaign ids - resolve via the campaigns route and confirm fuzzy matches.
- Never put an em-dash, a link the user didn't give, or unverified pricing numbers into instructions.
- Never write to `memory` via save - lessons go through the correction route, which merges them into the instructions with an audit trail (`instruction_edits`). Undoing a lesson = editing the instructions.
- Never call training/generate without warning about the wait, and never loop it (one batch per ask).
- `queue/redraft` only regenerates a draft and is safe to use for testing, but NEVER call any send/approve action (e.g. `queue/action`) on a real row - going live is the user's click. Only redraft `is_test:false` rows when the sole purpose is to read the new draft; never as a step toward sending.
