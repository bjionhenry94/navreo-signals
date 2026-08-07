---
name: setter-approve-send-fix
description: Static orchestration skill that diagnoses why clicking Approve on a human-reviewed
  Appointment Setter draft silently fails to send, gets ONE specific real reply out the door
  (Haarcosmetica, setter_queue row 266), and applies the safe contained fix so a failed Approve
  can never again masquerade as "Reply sent". One fixed step list, each step with a checkable
  done-rule, retry caps, and a Loop Training Mode toggle. Use when the user says "run the setter
  approve fix", "the approve button doesn't send", "clicking approve does nothing", or
  "/setter-approve-send-fix".
---

# Setter Approve → Send Fix

Closes the gap where a human clicks **Approve** on a drafted Appointment Setter reply and the
reply never leaves — no error, sometimes a false "Reply sent" toast, the row silently reappears.
This loop reproduces the failure on the LIVE host, names the exact cause from network/DB evidence
(not a guess), gets the one confirmed-correct reply out to a real lead, and applies the safe fix.
Static loop — fixed steps, each has a done-rule, Training Mode controls the pauses.

## ⚙ Loop Training Mode: **OFF**   ← flip this line to ON to pause at every step

**ON:** pause at EVERY step boundary and wait for the user's explicit approval before continuing.
Before starting a step, check its done-rule first — if it already passes, report "Step N already
passes, skipping" and move on. Only re-run steps whose done-rule fails. Show what you're about to
do before doing it.

**OFF:** run all steps end-to-end with no pauses. The done-rule checks, skip-if-passing behaviour,
and retry caps stay exactly the same — only the pauses go.

**Retry cap (both modes):** each step retries **max 3** times against its done-rule. On cap-hit:
record the step as FAILED with the reason, continue to the next step only if it doesn't depend on
the failed one, and surface every FAILED step in the final report. Never silently exceed the cap.
Never declare the skill done on a cap-hit.

Default is ON because **Step 5 fires a real email to a real lead**. Do not flip to OFF for this run.

**Destructive-action gate (both modes, non-negotiable):** the ONLY outward action this loop ever
takes is sending **exactly one** reply — `setter_queue` **row 266** (lead keratineuropa@gmail.com),
using the **current draft body verbatim, as-is** (user confirmed the messaging is correct). No other
queued reply is ever sent, edited, dismissed, or mutated. **Max sends = 1.** In Training Mode ON,
show the exact draft body and the target (lead 4012416553 / campaign 3507001) and get explicit
approval in the moment before the send fires. The **autopilot/master-send switch governs ONLY
auto-responses** — NEVER flip or touch it; a manual Approve must always send regardless of it.

## Goal

> The user clicks Approve on the Haarcosmetica reply in the **live** setter UI and the reply
> **actually leaves Smartlead** to keratineuropa@gmail.com (proven from the destination, not the
> toast), the silent-failure cause is named from evidence, and any **safe, contained** fix is applied
> so a failed Approve surfaces a real error instead of "Reply sent". All six verification checks
> below pass, or it is not done. On a retry cap-hit, stop and report the gap honestly.

## Ground truth (verified 2026-07-15 — re-verify in Step 1, line numbers drift)

- **Target row** (Supabase `setter_queue`, project `fnykldftbkrccihdjayl`): `id=266`,
  `lead_email=keratineuropa@gmail.com`, `lead_first_name="Haarcosmetica in Europa team"`,
  **`is_test=false`** (REAL lead), `status=needs_review`, `sent_at=null`,
  **`error="Couldn't find this agent's Calendly event type."`**, `smartlead_campaign_id=3507001`,
  `smartlead_lead_id=4012416553`, `email_stats_id` + `message_id` populated, `agent_id=agent-70fd17e5`.
  The real-send path is fully wired — nothing is missing from the row.
- **Flow:** Approve → `doSend(btn)` (`app/setter.html:1499`) → `POST /api/setter/queue/action
  {id, action:"send", body_override}` → `route_queue_action` (`app/setter.py:2773`) → `_send_reply`
  (`app/setter.py:1795`) → Smartlead `/campaigns/{id}/reply-email-thread` (`app/setter.py:1824`).
- **Silent-failure surface A (backend):** `_send_reply` reverts the row to `needs_review` with an
  `error` on any Smartlead/exception failure (`app/setter.py:1826-1843`) yet `route_queue_action`
  still returns **HTTP 200** carrying only `ok:false` in the JSON body (`app/setter.py:2815`).
- **Silent-failure surface B (frontend):** `doSend` checks only **`res.ok`** (HTTP status), never
  **`res.data.ok`** (`app/setter.html:1548`) — so a failed send flashes "Reply sent" and reloads
  while the row silently reappears. This is the literal "nothing happened" symptom and the prime
  systemic-fix candidate.
- **Prime send-failure suspect:** the live `Couldn't find this agent's Calendly event type` error
  means booking/slot resolution is the likely reason the actual send never completes. **Reproduce
  live to name it — do not assume.** Resolve WHERE that string is raised in Step 2.
- **dry-run tell:** a real send logs `sent_via != "dry_run"` (`app/setter.py:1807` is the dry-run
  stub, `:1811`). `_dry_run()` = `SETTER_DRY_RUN` env (`app/setter.py` ~`:1789`). A dry-run stub marks
  the row `sent` WITHOUT emailing — never accept that as proof. If a global dry-run is suppressing a
  *manual* approve, that is a bug to surface (and fix only if contained), NOT the master switch.
- **Live-host gotchas (memory):** exercise on the **live Render host, not localhost** — the iCloud
  working copy is NOT live and iCloud can revert edits, so any code fix goes through the **deploy repo
  + push**, then verify on the live host (`push=deploy, iCloud≠live`, `signals-deploy-repo`). Driving
  the live setter UI needs a minted **`navreo_session`** cookie (`reference_signals_session_cookie_mint`,
  `reference_setter_live_verify_auth`). Keys in `~/.navreo-keys.env`.
- **Unknowns for Step 1/2 to resolve:** exact current line numbers; the source file/line of the
  Calendly-event-type error; whether the send actually reaches Smartlead or dies before it; whether
  `SETTER_DRY_RUN` is set on the live host.

## Steps

### Step 1 — Re-verify ground truth
Re-query `setter_queue` row 266 (confirm `is_test=false`, still `needs_review`, `sent_at=null`, the
Calendly error still present). Re-grep the four flow anchors and confirm current line numbers for
`doSend`, `route_queue_action`, `_send_reply`, the Smartlead call, and the `res.ok`-only check.
Confirm the live host is reachable and a `navreo_session` cookie can be minted.
- **Done-rule:** (a) row 266 read back matches ground truth (real lead, unsent); (b) all four
  code anchors located with current line numbers; (c) a valid `navreo_session` cookie is minted and
  the live setter loads authenticated. FAILED if any anchor moved unrecoverably or auth can't be minted.

### Step 2 — Reproduce the failure live and name the cause
Drive the **live** setter UI authenticated, open the Haarcosmetica row, click Approve, and capture:
the actual `POST /api/setter/queue/action` **response body** (`ok` field + error text), console
messages, and the row's post-click DB state. Trace the exact failing mechanism — resolve where
`Couldn't find this agent's Calendly event type` is raised and whether the send reached Smartlead or
died before it. Confirm surface B (`doSend` ignoring `res.data.ok`) is why the UI showed nothing.
- **Done-rule:** the exact failure mode is named from evidence (network/DB/console), NOT assumed —
  a specific file:line or Smartlead response, PLUS confirmation that `res.data.ok` is never inspected
  (`app/setter.html`). Guessing without the captured response body = FAILED.

### Step 3 — Design the contained fix (gate on safety)
From Step 2, decide the fix. **Safe/contained** (proceed): wiring `doSend` to honour `res.data.ok`
and show the real error; a narrow booking/Calendly-resolution fix scoped to this failure. **Risky/
global** (do NOT apply — report and stop at Step 6): anything touching the master/autopilot switch,
`SETTER_DRY_RUN` behaviour broadly, or the shared send pipeline in a way that changes other rows.
- **Done-rule:** the fix is classified safe-or-risky with a one-line reason; if risky, no code is
  changed and the loop proceeds straight to reporting. If safe, the exact diff is drafted.

### Step 4 — Apply the safe fix + deploy
Only if Step 3 classified safe. Edit in the **deploy repo** (not the iCloud copy), push, wait for the
live host to pick it up, and marker-grep the **deployed** artifact to confirm the change is live.
Reconcile repo↔iCloud copies.
- **Done-rule:** the deployed `app/setter.html` (fetched from the live host) shows `doSend` inspecting
  `res.data.ok` (or the booking fix present); a stale iCloud edit that never deployed = FAILED.

### Step 5 — Fire the one real send (Training-Mode approval gate)
In Training Mode ON, show the exact draft body + target and get explicit approval. Then click Approve
on row 266 in the **live** UI (post-fix). **Exactly one send. Never touch the autopilot switch.**
- **Done-rule:** proven **from the destination, never the toast** — (a) `setter_queue` row 266 read
  back via Supabase shows `status='sent'`, `sent_at` non-null, `error=null`; (b) the send log shows
  `sent_via != "dry_run"`; (c) the reply is present in Smartlead's thread/sent for lead 4012416553 in
  campaign 3507001 (Smartlead API). Any leg missing = FAILED. Retry cap 3, but **never re-send if a
  prior attempt already flipped the row to `sent`** (check first — the 409 double-send guard).

### Step 6 — Prove the systemic fix + blast radius
Confirm a failed Approve now surfaces a real error in the UI instead of "Reply sent" (observe, e.g.
against a still-failing row or a simulated `ok:false`), and that `doSend` honours `res.data.ok`.
Confirm nothing else moved.
- **Done-rule:** (a) if a fix was applied, a failed send now shows a real error (verified by
  observation), not a false success; (b) autopilot/master-send state is identical before vs after;
  (c) no `setter_queue` row other than 266 changed status/sent_at. All three, or FAILED.

## Final report (always, both modes)

List: each step passed / skipped / FAILED with reasons. The named root cause (file:line or Smartlead
response). Whether a fix was applied and its diff/deploy marker, or why it was withheld as risky. The
send proof triple — row 266 final `status`/`sent_at`/`error`, the `sent_via` value, and the Smartlead
thread confirmation for lead 4012416553. Confirmation that autopilot state is unchanged and no other
row moved. Any deferred/risky fix handed off for a separate task. On a cap-hit: report FAILED with the
gap — never declare done.

## Hard don'ts

- **Never send more than one reply.** Only row 266, only once, draft body verbatim. Every other queued
  reply is untouched.
- **Never flip or touch the autopilot/master-send switch** — it governs auto-responses only; a manual
  Approve must always send regardless of it.
- **Never accept the "Reply sent" toast, an HTTP 200, or a `dry_run` stub as send proof** — read back
  from Supabase AND Smartlead, and require `sent_via != "dry_run"`.
- **Never apply a risky/global fix** (master switch, broad `SETTER_DRY_RUN` change, shared-pipeline
  rewrite) — report it and stop.
- **Never edit only the iCloud copy** — iCloud can revert; code fixes go through the deploy repo + push
  and are verified on the live host.
- **Never re-send after a prior attempt already marked the row `sent`** — check the row first.
- **Never exceed a retry cap or report done while any done-rule fails.**
