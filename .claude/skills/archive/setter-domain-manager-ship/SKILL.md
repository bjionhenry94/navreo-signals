---
name: setter-domain-manager-ship
description: Static orchestration skill for the Navreo signals tool covering TWO workstreams. (A) Build the "Appointment Setter" autopilot tab — per-agent auto-responders assigned to specific Smartlead campaigns that classify inbound replies, auto-send only simple resource/pricing asks at >=90% confidence, draft everything else for a human, propose Calendly times in the lead's timezone, and track a per-lead subsequence checkbox; goal is sub-15-minute response time on non-bespoke replies. (B) Rebuild the Inbox & Domain Manager as a domain-level view with 7/14/30-day window presets, one-click warm-up for below-floor domains, and a shared data load so sub-tabs stop taking 5 minutes. One fixed step list, checkable done-rules, retry caps, and a Loop Training Mode toggle (ON by default). Use when the user says "run the setter ship", "build the appointment setter", "rebuild the inbox & domain manager", or "/setter-domain-manager-ship".
---

# Appointment Setter Autopilot + Inbox & Domain Manager Rebuild

## ⚙ Loop Training Mode: **ON**   ← flip this line to OFF to run autonomously

**ON (default):** pause at EVERY step boundary and wait for the user's explicit approval
before continuing. Before starting a step, check its done-rule first. If it already
passes, report "Step N already passes, skipping" and move to the next pause. Only re-run
steps whose done-rule fails. Show what you're about to do before doing it.

**OFF:** run all steps end-to-end with no pauses. The done-rule checks, skip-if-passing
behaviour, and retry caps stay exactly the same. Only the pauses go.

**Retry cap (both modes):** each step retries **max 3** times against its done-rule.
On cap-hit: record the step as FAILED with the reason, continue to the next step if it
doesn't depend on the failed one, and surface every FAILED step in the final report.
Never silently exceed the cap. Never declare the skill done on a cap-hit.

**Outbound-send gate (both modes, non-negotiable):** no email is EVER sent to a real
prospect during build or testing. All tests use synthetic inbound replies and dry-run
sends. In production, an auto-reply fires only when ALL of these hold: the campaign is
explicitly assigned to an agent by the user, that agent's mode is `autopilot` (not
`draft_all`), classifier confidence >= 0.90, the intent is a simple ask the agent has a
fixed asset for, and the global kill switch is ON. The kill switch ships OFF; the user
flips it after reviewing live drafts. Everything that fails any condition becomes a
draft in the needs-you queue. No exceptions, including in Training Mode OFF.

**Model routing:** delegate mechanical build/execution work to `model: sonnet`
subagents; scoring panels, classification-quality judgment, and go/no-go calls stay
with the orchestrator.

## Goals

Two independent workstreams on https://navreo-signals.onrender.com (run A then B by
default; either can be invoked alone):

**A. Appointment Setter tab (new).** Average response time on non-bespoke replies
under 15 minutes. Per-agent auto-responders: each agent is trained on one offer
(resource links, pricing by niche, tone) and assigned to specific campaigns. Simple
asks ("sure", "send it", "what's the price") get an automatic reply with the asset plus
two proposed call times; anything bespoke (Loom, custom breakdown) gets a ready draft
for a human. Panel targets: 5 simulated non-technical setters score UX >= 8/10, a
simulated CSM scores safety/reliability >= 8/10, decision accuracy ~90% on real
historical replies.

**B. Inbox & Domain Manager rebuild.** Domain-level (not inbox-level) manager with
window presets (Last 7/14/30 days), min-sent + reply-floor kept as background defaults,
four fast flows: (1) below-floor domains with one-click "warm up all mailboxes on this
domain", (2) spot anything not currently warming, (3) in-warmup list with due dates,
restore buttons, and an Overview-tab flag when restores are due, (4) mailboxes needing
reconnect. Sub-tabs must render instantly after one shared data load (today they feel
dead for ~5 minutes). Panel target: 5 simulated GTMEs score ease-of-use >= 8/10.

## Ground truth (verified 2026-07-11 — re-verify in Step A1/B1, line numbers drift)

- Working copy: `~/navreo-signals/` (the git/Render repo). There is ALSO an iCloud copy
  under the project dir; iCloud can REVERT edits — after any merge, diff-check the two
  (memory `signals-deploy-repo`). Local dev: `python3 app/server.py` then
  `http://localhost:7901/app/<page>.html`.
- Rail nav + shared shell live in `app/shell.js` (~770 lines): `ICONS` map + nav
  builder near the top, background-jobs sidebar from ~:276. A new tab = new html page
  (copy the `deliverability.html` thin-shell pattern, 24 lines) + its own `<name>-tab.js`
  + one rail entry in shell.js.
- Fleet health audit: `app/deliverability-tab.js` (~7,216 lines). Sub-tab shell at
  ~:1223-1232 (`blacklist`, `manager`, `batch`, `reminders`); the manager panel renders
  around ~:3550-3624. Mutating deliverability actions go through `liveAction()` which
  POSTs `/api/deliverability/<action>`; server.py forwards to the standalone audit
  service (navreo-email-deliverability-audit.onrender.com).
- `app/server.py` (~8,600 lines) already talks to Smartlead, Supabase
  (service-role, `app_activity_log` helper ~:782), and has a background-job registry
  feeding the shell.js sidebar. Register setter jobs there; don't build a second one.
- Replies data: Supabase `replies` (archived inbound) and `sent_messages` (ALL outbound
  thread messages) — synced daily, so they are fine for BACKTESTING but too slow for
  live intake. Live intake = Smartlead campaign webhook (EMAIL_REPLY) POSTing to
  server.py, with a master-inbox polling fallback. The Make reply-categoriser
  (scenarios 9251436/9187631) also consumes Smartlead webhooks: ADD a new webhook via
  API, never overwrite or replace the existing webhook list, and never touch the Make
  scenarios.
- Replying in-thread: Smartlead reply-email-thread endpoint (MCP `reply_to_email`)
  keeps the reply inside the campaign thread. API cap 200 req/min.
- **No Calendly key exists** in `~/.navreo-keys.env`. Step A1 must ask the user for a
  Calendly personal access token + the booking link/event type to offer, then add it to
  `~/.navreo-keys.env` AND the Render env. Availability comes from Calendly's
  event-type available-times endpoint (verify exact shape against current docs in A1).
- Timezone: lead location is already in Supabase (companies/contact_history) or on the
  Smartlead lead record. No LinkedIn scraping — map location string to IANA timezone
  with a small static map, mark low-confidence guesses as such.
- Simulated-panel testing pattern already exists in this repo (`app/ux_sim.py` et al.):
  personas of mixed ability drive the UI, score 1-10, findings feed the next iteration.

## Phase A — Appointment Setter

### Step A1 — Re-verify ground truth + collect the missing inputs
Confirm every bullet above against current code. Ask the user for: the Calendly token +
event type, and the FIRST agent's training (which campaigns, the resource link(s),
pricing by niche if any, one or two example replies they'd call perfect). Store the
Calendly key in `~/.navreo-keys.env` and Render env.
- **Done-rule:** a live Calendly API call returns real available slots for the next 5
  working days; one agent's training brief is written down and user-confirmed; you can
  name the webhook-registration endpoint and prove the existing webhook list is intact.

### Step A2 — Backend: agents, intake, brain (`app/server.py` + Supabase)
Two tables (create via migration): `setter_agents` {id, name, training (offer, assets,
pricing, tone), campaign_ids[], mode: draft_all|autopilot, confidence_min default 0.90,
calendly_event_type, active} and `setter_queue` {id, campaign_id, lead (email, name,
location, tz_guess), reply_text, received_at, intent, confidence, draft_text,
proposed_slots, status: auto_sent|needs_you|sent_by_human|dismissed,
subsequence_added bool, responded_at}. Endpoints: CRUD for agents;
`POST /api/setter/inbound` (webhook target; also accepts `{test: true}` synthetic
replies, which are flagged and can never trigger a real send); `GET /api/setter/queue`;
`POST /api/setter/send/<id>` (human-approved send); `POST /api/setter/toggle-subseq/<id>`;
global kill switch. The brain, per inbound reply: classify intent (simple ask the agent
has an asset for / bespoke / not-interested / other) + confidence → infer timezone from
location → pull Calendly slots, pick two between 9:00-17:00 in the LEAD's timezone
within the next 5 working days (if none, force status `needs_you` with reason
"no slots") → draft the reply in the agent's tone: answer the exact ask, include the
asset/pricing, propose the two times with a soft value-driven reason for the call, no
em-dashes ever in email copy → apply the Outbound-send gate to decide auto_sent vs
needs_you. Auto-sends go through the reply-email-thread endpoint and are logged to
`app_activity_log`. Register the EMAIL_REPLY webhook (additive) on the assigned
campaigns only.
- **Done-rule:** a synthetic inbound POSTed to localhost flows to a queue row with
  intent, confidence, tz, two real Calendly slots, and a draft; the gate provably
  blocks a send when any single condition fails (test each condition); existing
  campaign webhooks are byte-identical before/after registration.

### Step A3 — Frontend: the Setter tab (`app/setter.html` + `app/setter-tab.js`)
New rail entry "Setter". Two panes, nothing more (simplest possible version):
1. **Queue** (default): needs-you drafts first (reply shown, editable draft, proposed
   times, one Send button, subsequence checkbox, dismiss), then a collapsed auto-sent
   log (what fired, when, response time). Response-time-to-reply shown per row and as
   a header average vs the 15-minute target.
2. **Agents**: card per agent — name, training summary, assigned campaigns
   (multi-select), mode toggle draft_all/autopilot, active toggle. Plus the global kill
   switch, clearly labelled.
Follow the existing app conventions (navreo.css, colour-as-severity, no emoji).
- **Done-rule:** on localhost, a synthetic inbound appears in the queue without reload
  (poll or refresh interval), its draft is editable, Send fires the human-approved path
  (dry-run locally), the subsequence checkbox persists, and the agents pane round-trips
  a config edit. Zero console errors.

### Step A4 — Backtest on real history (read-only)
Sample 100+ real inbound replies across the assigned campaigns from Supabase `replies`,
with the real human answers from `sent_messages`. Run the brain on each (no sends).
Score: (a) decision accuracy — would-auto-send vs should-have (simple ask with fixed
asset) >= 90%, with ZERO false auto-sends on bespoke/not-interested replies at the 0.90
threshold; (b) draft closeness to the real human reply, LLM-judged 1-10, avg >= 8.
Iterate prompt/threshold within the retry cap; each iteration re-runs the full sample.
- **Done-rule:** both scores hit on a fresh (non-tuning) sample, and a table of every
  false-positive/false-negative with its fix is in the report.

### Step A5 — End-to-end synthetic + panel verification (browser)
Inject fictitious inbounds covering at least: plain "send it", pricing ask by niche,
vague interest, bespoke Loom ask, not-interested, no-Calendly-slot week, ambiguous
timezone. Verify each lands correctly (auto vs needs-you) in the RENDERED browser UI —
the rendered page is the only done-evidence for UI work. Then run the two simulated
panels: 5 non-technical appointment setters work the queue (can they see where their
input is needed, edit, send?) and 1 CSM judges safety/accuracy of what auto-fired.
Iterate on findings within the retry cap.
- **Done-rule:** every synthetic case routes correctly in-browser; setter panel avg
  >= 8/10; CSM >= 8/10; screenshots of the queue in the report.

### Step A6 — Deploy + live smoke
Commit in `~/navreo-signals`, push, wait for Render, diff-check the iCloud copy.
Kill switch OFF (drafts only) in production. Fire one synthetic inbound at production;
confirm queue row + Calendly slots render live. Tell the user exactly how to flip the
kill switch once they've reviewed real drafts.
- **Done-rule:** production URL renders the Setter tab with the synthetic row; kill
  switch confirmed OFF; repo↔iCloud diff for touched files is empty.

## Phase B — Inbox & Domain Manager rebuild

### Step B1 — Re-verify + profile the slowness
Reproduce the dead-click: load the fleet health audit, click between sub-tabs, capture
timings and network calls. Name the exact bottleneck (which fetch/recompute runs per
sub-tab, which endpoint, how long) and what the existing warm-up action REALLY does
(rest/rotation vs Smartlead warmup toggle) before touching anything.
- **Done-rule:** you can state "sub-tab X takes Ns because Y" with evidence, and you
  can name the code path of the warm-up button.

### Step B2 — One shared load, instant sub-tabs
Load the audit dataset ONCE per page visit (server-side cache or single fetch shared
across sub-tabs); sub-tabs render from that in-memory dataset. Loading skeleton on
first load; never a dead click (every tab click gives immediate visual response).
- **Done-rule:** after first load, switching between all five sub-tabs takes under 1s
  each, measured in-browser; no duplicate audit fetches in the network log.

### Step B3 — Domain-level manager UI
Rebuild the manager panel: rows are DOMAINS (mailboxes grouped underneath, expandable).
Replace the from/to date pickers with one preset select: Last 7 / 14 / 30 days. Min-sent
and reply-rate floor stay as background defaults (small "advanced" disclosure, not
front-and-centre). Four views matching the four use-cases, each reachable in one click:
below-floor (button: "Warm up domain" = push ALL its mailboxes into warm-up rest, with
confirm), not-warming, in-warmup (due date + Restore button + feeds an Overview-tab
flag when any restore is due), needs-reconnect. Keep existing liveAction plumbing for
the actual mutations.
- **Done-rule:** with dummy data, each of the four flows completes in <=2 clicks from
  tab-open, browser-verified; the Overview tab shows the restore-due flag when (and
  only when) a mailbox is due.

### Step B4 — Dummy-data + panel verification (browser)
Seed dummy data covering: a below-floor domain, a healthy domain, mixed-state mailboxes
under one domain, a restore-due mailbox, a failed connection. Walk every flow in the
rendered browser. Then run 5 simulated GTMEs of mixed ability through the three main
jobs (flag-and-warm-up, spot-not-warming, restore-due) and score ease-of-use + speed
to action. Iterate within the retry cap.
- **Done-rule:** all flows pass in-browser on dummy data; GTME panel avg >= 8/10;
  screenshots in the report.

### Step B5 — Deploy
Commit, push, wait for Render, verify the rebuilt manager live with real data
(read-only walk, no mutations), diff-check iCloud.
- **Done-rule:** production shows the domain-level manager with the preset window
  select; sub-tab switching is fast live; repo↔iCloud diff is empty.

## Final report (always, both modes)
One summary: steps passed/skipped/FAILED per phase; Phase A scores (decision accuracy,
draft closeness, setter panel, CSM) and measured avg response time on synthetics;
Phase B timings before/after and GTME score; kill-switch state; anything deferred.

## Hard don'ts
- Never send any email to a real prospect from a test path, and never auto-send past
  the Outbound-send gate. The kill switch ships OFF.
- Never overwrite or replace a campaign's existing webhook list; only add. Never edit
  the Make categoriser scenarios.
- Never enable Smartlead warmup on Maildoso-fleet inboxes (external warmup is
  intentional — memory `maildoso-warmup-external`). "Warm up" in this tool means rest
  from sending.
- Never put em-dashes in drafted email copy.
- No LLM-guessed availability or timezones presented as fact: slots come from Calendly,
  low-confidence timezone guesses are flagged on the queue row.
- Never leave a mock/synthetic path silently reachable in production sends.
- Never exceed a retry cap or report done while any done-rule fails.
