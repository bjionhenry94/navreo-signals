---
name: setter-slot-consistency-audit
description: Static orchestration skill that audits and then makes consistent the
  Appointment Setter's call-slot proposing — fictitious is_test replies injected across
  EVERY agent plus agentless, each scenario twice, verdicts judged against a direct
  Calendly API read, Calendly-side availability gaps reported for manual fix, genuine
  code bugs fixed + deployed + re-proven, all test rows cleaned up. One fixed step list,
  each step with a checkable done-rule, retry caps, and a Loop Training Mode toggle.
  Use when the user says "audit the setter call slots", "why do some replies get no
  call times", "run the slot consistency audit", or "/setter-slot-consistency-audit".
---

# Setter call-slot consistency audit

The Setter offers two Calendly times for some replies and falls back to "no call times
proposed" + booking link for others, with no visible reason. This loop proves exactly
when and why each outcome fires — per agent, per timezone, agented and agentless — then
fixes what's genuinely broken and proves the fix live. Static loop: fixed steps, each
has a done-rule, Training Mode controls the pauses.

## ⚙ Loop Training Mode: **ON**   ← flip this line to OFF to run without pauses

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

**Destructive-action gates (both modes, non-negotiable):**
- **Inject cap:** max **60** test rows created across the whole loop (inject route +
  direct inserts + re-proof runs combined). A cap-hit = FAILED with the gap, never done.
- **Test rows only:** every row this loop creates carries `is_test: true` AND a lead
  email matching `slotaudit-*@example.com` — that marker is the ONLY thing cleanup may
  delete. The ~25 pre-existing test rows and ALL real rows are untouchable, by any verb.
- **No sends:** `is_test` rows can never reach Smartlead (setter.py `_send_reply` forces
  dry). Never flip autopilot, never call queue/action `send`, never edit any agent's
  instructions or settings doc (read-only on both).
- **Calendly is read-only:** the loop only ever GETs availability. The availability fix
  itself is the OWNER's manual action in Calendly (ruling, 2026-07-15) — the loop
  reports the exact missing windows and pauses, even in Training Mode OFF.
- **Code fixes:** only for proven bugs from Step 4's failure classes, committed in
  `~/navreo-signals` (NEVER the iCloud copy), shown as a diff before push when ON.

## Goal — THE DONE-RULE (single source of truth)

> Every reply — any agent or agentless, any timezone — gets the same deterministic slot
> outcome for the same inputs: two proposed times whenever qualifying Calendly
> availability truly exists (lead-local weekday 9–5, ≤10 working days, ≥20h out), and
> the booking-link fallback only when it truly doesn't. Proven by all four checks in
> Step 9's composite verification. Anything less = not done.

## Ground truth (verified 2026-07-15 — re-verify in Step 1, line numbers drift)

- Deploy repo: `~/navreo-signals` (git push = deploy to Render service `navreo-signals`,
  live host assumed `https://navreo-signals.onrender.com` — **confirm via `/healthz` in
  Step 1**). The iCloud copy under `.../Navreo/Claude/Navreo` REVERTS edits — never work there.
- Auth: all setter GET/POST routes (incl. `/api/setter/test/inject`) sit behind the
  `navreo_session` cookie. Mint it yourself (server.py:11591–11601): secret =
  `sha256(SUPABASE_SERVICE_ROLE_KEY + ":navreo-session-v1")`, payload =
  `admin@navreo.ai|<epoch now + 86400>` (expiry must be FUTURE epoch — known gotcha),
  cookie = `urlsafe_b64(payload).rstrip("=") + "." + hmac_sha256_hex`. SRK lives in
  `~/.navreo-keys.env`.
- Slot pipeline, `app/setter.py`: tz gate ~line 2445 (no tz → `tz_unknown`, Calendly
  never called; tz comes from classification of the reply text, so scenario bodies must
  steer it — e.g. "I'm based in Los Angeles" / a UK landline in the signature);
  `get_calendly_availability` ~1318 (statuses `ok/not_configured/none_available/error`;
  per-agent event-type slug from `agent.calendly_event_url` matched against the ONE
  workspace `calendly_token`'s event types — mismatch returns status `error`; chunked
  7-day windows, chunk errors surface only when ALL chunks fail); `pick_slots` ~489
  (keeps weekday, lead-local `work_start..work_end` [settings, default 9–17], ≤
  `HORIZON_WORKING_DAYS` = 10 [~line 80], ≥20h out; empty → `none_available`); fallback
  flag `slots_fallback = slot_status != "ok"` ~2478; lint's fallback anchor rule ~626.
- Test inject: `POST /api/setter/test/inject` → `route_test_inject` ~3423. Requires an
  agent on the campaign (400 otherwise), builds `is_test: true` reply, runs the FULL
  `process_reply` pipeline. `_send_reply` ~1869–1874: is_test NEVER hits Smartlead.
- Agentless: `_intake_agentless` ~2092 inserts `agent_id: None`, skips classify/draft/
  decide entirely → agentless rows NEVER get slots by design (decision_reason "No agent
  is assigned…"). The audit records this as the expected agentless outcome — divergence
  from THAT is the bug, not the absence of slots. Direct Supabase insert into
  `setter_queue` mimicking that exact row shape (with `is_test: true` + marker email)
  is the agentless test path, since inject 400s.
- Supabase: project `fnykldftbkrccihdjayl`, table `setter_queue` (QUEUE_TABLE,
  setter.py:57). **Schema-freeze:** never invent row keys that aren't real columns —
  a PATCH with an unknown key dies silently. Read columns `slot_status` does NOT exist
  as a column — slots/decision/classification/timezone/decision_reason/error do;
  slot_status is inside `decision_reason`/derivable from `slots` + `error` — **verify
  actual columns in Step 1 before writing the matrix reader.**
- Calendly direct read (verdict oracle): token = settings doc `calendly_token` (read
  via SRK from the agents/settings table — find `SETTINGS_ID` doc in Step 1);
  `GET /event_type_available_times?event_type=<uri>&start_time=&end_time=` with 7-day
  max windows, start strictly in the future.
- Agents list: `GET /api/setter/agents` (cookie-authed). Campaign→agent mapping needed
  to pick one campaign id per agent for injects.
- New POST routes, if any fix needs one: read `self._post_body`, NEVER `rfile.read`.
- Unknowns for Step 1: live host URL, setter_queue column list, each agent's
  `calendly_event_url` + whether every slug resolves, settings `work_start/work_end`,
  current Calendly availability shape per event type.

## Budget ledger

| Spend | Cap | Notes |
|---|---|---|
| Test rows created | **60** hard | inject + direct inserts + re-proofs combined; track a running count in the matrix file |
| LLM calls | ~3 per inject (classify/draft/proofread), server-side | no separate cap; bounded by the 60 rows |
| Calendly API | read-only GETs | free; unlimited within reason |

At 48 rows (80%): pause and report (ON) / stop and report (OFF) before spending more.

## Steps

### Step 1 — Re-verify ground truth and open the doors
Confirm every Ground-truth bullet against current code (re-find drifted line numbers).
Resolve the unknowns: confirm live host via `/healthz`; mint the cookie and prove it
with an authed `GET /api/setter/agents` (200 + agent list); list `setter_queue` real
columns via Supabase; read the settings doc (calendly_token present, work_start/work_end);
for EVERY agent record `calendly_event_url` and prove its slug resolves against the
token's event types with one direct Calendly GET each; snapshot each event type's raw
availability for the next 14 days into the working file
`~/.claude/skills/setter-slot-consistency-audit/runs/<date>-matrix.json`. Count
pre-existing `is_test` rows (baseline for cleanup proof).
- **Done-rule:** (a) authed agents GET returns 200 with N≥1 agents; (b) every agent's
  slug resolution result recorded (resolved or NOT — a failure here is a FINDING, not a
  step failure); (c) one Calendly availability response saved verbatim per event type;
  (d) setter_queue column list saved; (e) baseline is_test count recorded.

### Step 2 — Build the matrix plan
4 scenarios, bodies written to steer classification: **S1** UK-tz scheduling ask ("keen
to chat, I'm on 020 7… London" + asks for a call), **S2** US-tz scheduling ask ("I'm
based in Los Angeles, happy to talk"), **S3** no-timezone scheduling ask (no location
signal anywhere), **S4** resource-only ask (no scheduling intent). Matrix = every agent
× 4 scenarios × 2 identical runs, + 2 agentless direct-insert rows (1 scheduling-shaped,
1 resource-shaped) — total must be ≤ 52 so ≥8 of the 60-row budget survives for Step 7
re-proofs; if agents × scenarios × 2 exceeds that, trim to 1 run for S4 (weakest
determinism signal) and say so in the report. Every lead email `slotaudit-<agent>-<scenario>-<run>@example.com`.
For each planned row, pre-compute the EXPECTED outcome from Step 1's availability
snapshot + the pick_slots rules (lead-local weekday 9–5, ≤10 working days, ≥20h out).
- **Done-rule:** the matrix file lists every planned row with campaign_id, body,
  expected slot outcome, and the running row-count ≤52; expected outcomes are derived
  from the saved Calendly snapshots, not guessed.

### Step 3 — Run the matrix
Fire the injects (agented rows via `POST /api/setter/test/inject`; agentless via direct
Supabase insert in `_intake_agentless`'s exact row shape, only real columns). Take a
fresh Calendly availability snapshot per event type immediately before each agent's
batch (the verdict oracle must be contemporaneous). Then read every resulting row back
**from the setter_queue table via Supabase** — never the inject response — capturing
timezone, slots, decision, decision_reason, error, draft_body.
- **Done-rule:** (a) every planned row exists in setter_queue with `is_test=true` and
  the marker email, read back independently; (b) each has its contemporaneous Calendly
  snapshot attached in the matrix file; (c) running count ≤ the cap; rows that errored
  are recorded as results (errors are findings), not retried past the step cap.

### Step 4 — Judge every row
For each row, compare actual vs expected: **slots offered** must mean ≥2 qualifying
slots existed in the snapshot and the draft contains both deep links; **fallback** must
mean the snapshot genuinely had no qualifying slot (after the lead-local 9–5 rule) OR
tz was genuinely unsteerable — and the draft must still contain an allowed calendar
anchor. Determinism: run-1 vs run-2 of the same cell must match in outcome shape (same
slots-vs-fallback verdict; slot times may drift with real availability). Classify every
mismatch into: tz-inference flap, slug-match error, false `none_available` (real
availability existed), chunk error, agentless divergence (differs from the documented
agentless design), lint/draft omission, other-nondeterminism.
- **Done-rule:** every matrix row has a verdict (PASS / FAIL+class), zero rows left
  unjudged, and the per-class failure tally is written into the matrix file.

### Step 5 — Findings report + the Calendly gap report
Write the findings: per-agent, per-scenario outcome table, failure classes, and — if
S2-type rows correctly fell back because the calendar has no US-friendly hours — the
exact missing availability windows per event type (e.g. "event X needs Mon–Fri 17:00–
20:00 UK to serve US-Pacific leads 9–12 their time"). **Ruling (owner, 2026-07-15): the
lead-local 9–5 filter stays; this class is fixed in Calendly by the owner, not in code.**
Pause here (BOTH modes) for the owner to update Calendly if a gap was found.
- **Done-rule:** report delivered in chat with real numbers; if a Calendly gap exists,
  the exact windows are stated and the pause taken; if not, explicitly state "no
  Calendly-side gap" and continue.

### Step 6 — Fix genuine code bugs (only if Step 4 found any)
For each proven code-bug class (nondeterminism, slug-match `error`, false
none_available/chunk error, tz flap, agentless divergence, lint omission): fix in
`~/navreo-signals`, respecting schema-freeze and `self._post_body`. Commit, push,
confirm deploy live (poll-log / marker-grep the deployed artifact), then reconcile the
iCloud copy if the convention requires it. Skip the whole step (say so) if Step 4 found
zero code bugs.
- **Done-rule:** for each fix: (a) diff shown (approval in ON); (b) pushed; (c) the
  deployed live host serves the marker (grep the served file or a version endpoint via
  authed request) — a local commit alone never passes.

### Step 7 — Re-prove the failing cells
Re-run ONLY the previously failing matrix cells (plus their determinism twin) within
the remaining row budget, same read-back and same contemporaneous-snapshot judging as
Steps 3–4. This is where the owner's Calendly update gets proven too: S2 cells must now
offer two slots.
- **Done-rule:** every previously-FAILED cell now passes its Step 4 judgement, within
  the 60-row cap; any cell that still fails after the retry cap is reported FAILED with
  its class — never hidden.

### Step 8 — Live UI proof
On the live host, in a real browser (mint the cookie into the browser), open the Setter
tab with "Show test items" on, open one of this loop's test rows that should have slots,
and screenshot it rendering **two proposed call times** in the draft. Also screenshot
one fallback-correct row showing the booking-link phrasing.
- **Done-rule:** two screenshots from the LIVE host (not localhost, not a grep) — one
  showing two slot links rendered in a slotaudit row's draft, one showing a correct
  fallback row.

### Step 9 — Cleanup + composite verification
Delete every setter_queue row where `is_test=true` AND `lead_email LIKE
'slotaudit-%'` — nothing else. Then verify the four checks: **(1)** matrix table read
back from Supabase showed identical outcome shape for identical inputs, zero unexplained
`error` statuses; **(2)** every verdict was judged against a contemporaneous direct
Calendly read; **(3)** previously-failing scenarios re-ran green on the deployed live
host AND the Step 8 screenshots exist; **(4)** a final Supabase query returns ZERO
slotaudit rows and the pre-existing is_test count from Step 1 is unchanged.
- **Done-rule:** all four checks pass, evidenced by the final query outputs pasted into
  the report. All 4, or it isn't done.

## Final report (always, both modes)

One summary: steps passed/skipped/FAILED; rows created vs the 60 cap; the full
per-agent × per-scenario outcome table with determinism verdicts; failure classes found
and which were fixed in code (commit hashes) vs fixed in Calendly (windows added) vs
still open; screenshot paths; cleanup query output (0 slotaudit rows, baseline is_test
count intact); anything deferred.

## Hard don'ts

- Never touch real (non-test) queue rows, the ~25 pre-existing test rows, agent docs,
  or the settings doc — reads only. Cleanup deletes ONLY `is_test=true` +
  `slotaudit-%` rows.
- Never send anything to Smartlead, never enable autopilot, never call queue/action
  `send` — even on test rows.
- Never exceed 60 created rows; a cap-hit is FAILED-with-gap, never done.
- Never trust the inject response, the app's own labels, or a local commit as evidence —
  Supabase read-back, contemporaneous Calendly reads, deployed-host proof, and browser
  screenshots are the only currency.
- Never edit code in the iCloud copy; never invent setter_queue columns; never read a
  POST body via `rfile.read` in new routes.
- Never change the lead-local 9–5 pick_slots rule — the availability gap is fixed in
  Calendly by the owner (ruling 2026-07-15). Never write to Calendly.
- Never skip the Step 5 pause when a Calendly gap is found, even in Training Mode OFF.
