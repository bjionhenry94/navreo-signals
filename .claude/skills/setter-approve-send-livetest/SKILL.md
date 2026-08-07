---
name: setter-approve-send-livetest
description: Static orchestration skill that proves the Appointment Setter's edit → approve → send
  flow really delivers into Smartlead, using ONE real "not interested" reply as a safe test lead
  (no active positive lead is risked) and reading the result back from Smartlead's own thread rather
  than the app's "sent" label. Temporarily surfaces one not-interested reply into Needs-review, lets
  the human draft + click Approve in the live UI, verifies delivery from the destination, caps real
  sends at 3, then reverts the surfacing. One fixed step list, each step with a checkable done-rule,
  retry caps, and a Loop Training Mode toggle. Use when the user says "test the setter approve send",
  "prove approve actually sends", "does clicking approve reach Smartlead", "run the setter send
  live-test", or "/setter-approve-send-livetest".
---

# Setter Approve → Send Live-Test

Proves — end to end, on the live system — that when a human edits a drafted Appointment Setter reply
and clicks **Approve**, the reply actually leaves Smartlead. It does this without risking an active
positive lead: it borrows ONE genuine "not interested" reply as the test subject, lets the human
drive the real Approve in the live UI, then confirms delivery from **Smartlead's own thread** (never
the app's "sent" pill, which has historically lied). Static loop — fixed steps, each has a done-rule,
Training Mode controls the pauses.

## ⚙ Loop Training Mode: **OFF**   ← flip this line to ON to pause at every step

**ON:** pause at EVERY step boundary and wait for the user's explicit approval before continuing.
Before starting a step, check its done-rule first — if it already passes, report "Step N already
passes, skipping" and move on. Only re-run steps whose done-rule fails. Show what you're about to do
before doing it.

**OFF:** run all steps end-to-end with no pauses. The done-rule checks, skip-if-passing behaviour,
and retry caps stay exactly the same — only the pauses go.

**Retry cap (both modes):** each step retries **max 3** times against its done-rule. On cap-hit:
record the step as FAILED with the reason, continue to the next step only if it doesn't depend on the
failed one, and surface every FAILED step in the final report. Never silently exceed the cap. Never
declare the skill done on a cap-hit.

**Destructive-action gate (both modes, non-negotiable):** the ONLY outward action is the **human**
clicking Approve on the surfaced not-interested row in the live UI — the loop itself NEVER calls the
send endpoint or auto-approves on the user's behalf (Step 5 is human-driven). **Max real sends = 3
total**, tracked across the whole run; a cap-hit is reported FAILED with the gap, never a pass. The
send emails a **real person who said not interested** — before it can happen, the exact lead (name,
email, campaign, reply text) is shown to the user for explicit go-ahead. **Never touch the
autopilot/master-send switch** — it governs auto-responses only and is irrelevant to a manual Approve.
Every other reply in the queue is untouched.

## Goal

> One real not-interested reply is surfaced into Needs-review, drafted and **Approved by the human in
> the live Setter UI**, and the reply is confirmed present in **Smartlead's own message thread** for
> that lead/campaign — proving the approve→send path works end to end. Afterward the temporary
> surfacing is reverted so not-interested stays out of Needs-review. All six verification checks
> below pass, or it is not done. On a retry/send cap-hit, stop and report the gap honestly.

## Ground truth (verified 2026-07-15 — re-verify in Step 1, line numbers drift)

- **Queue table:** Supabase `setter_queue`, project `fnykldftbkrccihdjayl`. `WORKSPACE`-scoped.
  `QUEUE_TABLE = "setter_queue"` (`app/setter.py:57`).
- **Not-interested replies get NO queue row at all:** the sync loop `continue`s when
  `category not in CORE_FOUR` (`app/setter.py:2274`; `CORE_FOUR = {Interested, Information Request,
  Meeting Request, positive-re-reply}`, `app/setter.py:66`). So "surfacing" = **minting one real,
  hydrated `setter_queue` row** from a genuine not-interested reply that exists in Supabase `replies`
  — NOT flipping a status on an existing row (there isn't one).
- **The surfaced row must be REAL and hydrated:** `is_test=false` (test rows are hard-blocked from
  Smartlead, `app/setter.py:1812` — they prove nothing), `status='review'` (`route_reply_decision`
  returns `"review"` for held rows, `app/setter.py:643`+), and carry the reply's **real**
  `smartlead_campaign_id`, `lead_email`, `message_id`, and `email_stats_id` so the Smartlead thread
  reference resolves (hydration path around `app/setter.py:1994`). A row missing the thread anchors
  will 502 on send.
- **Approve → send flow:** live UI `doSend` (`app/setter.html`, ~`:1499`) → `POST
  /api/setter/queue/action {id, action:"send", subject_override?, body_override?}` →
  `route_queue_action` `action=="send"` (`app/setter.py:2845`) → `_send_reply` (`app/setter.py:1809`)
  → Smartlead `POST /campaigns/{campaign_id}/reply-email-thread` (`app/setter.py:1838`). On success
  the row flips to `status='sent'`.
- **The app's success signal cannot be trusted:** Smartlead answers a successful send with a
  **non-JSON OK body**, and "nothing happened" on screen has historically meant the email actually
  went (fix `3fcd695`; memory `reference_setter_approve_nonjson_2xx_send`). Proof MUST come from
  Smartlead's own thread, never the pill / 200 / `setter_queue.status`.
- **Dry-run guard:** `_dry_run()` = `SETTER_DRY_RUN == "1"` (`app/setter.py:1803`). If set on the live
  host, a manual Approve is silently skipped — must be confirmed **OFF** before the test send.
- **Live-host gotchas (memory):** exercise on the **live Render host, not localhost** — the iCloud
  working copy is NOT live and iCloud can revert edits (`push=deploy, iCloud≠live`,
  `signals-deploy-repo`). Driving the live setter UI needs a minted **`navreo_session`** cookie
  (`reference_signals_session_cookie_mint`, `reference_setter_live_verify_auth`). Keys in
  `~/.navreo-keys.env`.
- **Unknowns for Step 1 to resolve:** current line numbers for the four flow anchors; whether
  `SETTER_DRY_RUN` is set on the live host; which genuine not-interested reply in `replies` to use
  (real `message_id` + campaign that has a live agent/mailbox so the thread can be replied to).

## Steps

### Step 1 — Re-verify ground truth + pick the test reply
Re-grep the four flow anchors (`doSend`, `route_queue_action` `action=="send"`, `_send_reply`, the
`reply-email-thread` call) and confirm current line numbers. Confirm the live host is reachable and a
`navreo_session` cookie can be minted. Query Supabase for a genuine **not-interested** reply in
`replies` on a **real campaign that still has a working mailbox/thread** (so a reply can actually
thread), capturing its real `message_id`, `smartlead_campaign_id`, `lead_email`, `email_stats_id`,
name, and reply text. Confirm `SETTER_DRY_RUN` is **OFF** on the live host.
- **Done-rule:** (a) all four code anchors located with current line numbers; (b) a valid
  `navreo_session` cookie is minted and the live setter loads authenticated; (c) one real
  not-interested reply is identified with all thread anchors present (`message_id`, campaign,
  `lead_email`, `email_stats_id`); (d) `SETTER_DRY_RUN` confirmed OFF on the live host. Any missing =
  FAILED (do not proceed to a send with dry-run unknown).

### Step 2 — Surface exactly one not-interested reply into Needs-review
Mint ONE real `setter_queue` row from the Step-1 reply: `is_test=false`, `status='review'`, category
tag marking it not-interested, all thread anchors populated (hydrate via the existing path so the
Smartlead reference resolves), and a starter draft body/subject the human can edit. Mark the row
identifiably (e.g. a note/tag) so it can be found and reverted later. Do NOT create more than one row.
- **Done-rule:** exactly one new `setter_queue` row exists with `is_test=false`, `status='review'`,
  not-interested category, all thread anchors non-null, read back from Supabase (not from the write
  response). The live Needs-review list shows it. More than one row, or `is_test=true`, or a null
  thread anchor = FAILED.

### Step 3 — Show the human the exact test lead and get go-ahead
Present the surfaced lead in full: name, email, campaign id, the original not-interested reply text,
and the starter draft — stating plainly that clicking Approve will email this real person. Wait for
the user's explicit go-ahead. (In Training Mode OFF this is still a hard gate because the send is
outward and irreversible.)
- **Done-rule:** the user has been shown the exact lead + draft and has explicitly said to proceed.
  No go-ahead = STOP here (reported, not FAILED).

### Step 4 — Human edits the draft and clicks Approve in the live UI
The **user** edits the draft in the live Setter and clicks **Approve**. The loop does NOT click
Approve or call the send endpoint itself. Watch the network response for the `action:"send"` call but
treat it only as a breadcrumb — never as proof.
- **Done-rule:** the user confirms they clicked Approve on the surfaced row in the live UI, and a
  `POST /api/setter/queue/action` with `action:"send"` for that row id was observed. Real-send
  counter incremented (cap 3 total across the run).

### Step 5 — Verify delivery from Smartlead's own thread (the real proof)
Read back from the **destination**, not the app: (a) the `setter_queue` row flipped to `status='sent'`
with `sent_at` set; AND (b) the reply is present in Smartlead's own message thread for that lead +
campaign, via Smartlead API (`get_campaign_lead_message_history` / the campaign lead thread). A status
flip WITHOUT a Smartlead-side match is a FAIL (the "sent" pill lies). If inconclusive, the user may
re-edit and re-Approve — but total real sends must stay ≤ 3.
- **Done-rule:** BOTH true — (a) row `status='sent'` + `sent_at` non-null, read back from Supabase;
  (b) the reply text appears in Smartlead's own thread for the lead/campaign via Smartlead API. Either
  leg missing = FAILED. Total real sends > 3 = FAILED with the gap.

### Step 6 — Revert the temporary surfacing
Remove/neutralise the surfaced row's surfacing so a fresh not-interested reply no longer lands in
Needs-review (i.e. leave the not-interested → no-row behaviour exactly as before), while leaving the
test row itself identifiable as the proof artifact. Confirm no other queue row was touched.
- **Done-rule:** (a) the temporary surfacing is reverted — not-interested still produces no
  Needs-review row on the next sync; (b) the test row remains identifiable (marked/tagged) for the
  record; (c) no `setter_queue` row other than the one test row changed status/sent_at, verified by
  read-back. All three, or FAILED.

## Final report (always, both modes)

List: each step passed / skipped / FAILED with reasons. The surfaced lead (name, email, campaign id,
row id). Whether `SETTER_DRY_RUN` was OFF at send time. The send-proof pair — the `setter_queue` row's
final `status`/`sent_at`, AND the Smartlead-thread confirmation for the lead/campaign. Total real
sends fired (must be ≤ 3). Confirmation that the surfacing was reverted, the test row left
identifiable, autopilot state unchanged, and no other row moved. On a cap-hit: report FAILED with the
gap — never declare done.

## Hard don'ts

- **Never auto-click Approve or call the send endpoint for the user** — the human drives Approve in
  the live UI; the loop only surfaces, watches, and verifies.
- **Never surface or send more than one test reply**, and **never exceed 3 real sends total** — a
  cap-hit is FAILED, not a pass.
- **Never use a test (`is_test=true`) row to prove a send** — test rows are hard-blocked from
  Smartlead and prove nothing.
- **Never accept the "sent" pill, an HTTP 200, or `setter_queue.status` alone as delivery proof** —
  read the reply back from Smartlead's own thread.
- **Never send with `SETTER_DRY_RUN` state unknown** — confirm it is OFF on the live host first.
- **Never flip or touch the autopilot/master-send switch** — it governs auto-responses only.
- **Never edit only the iCloud copy** — any code change goes through the deploy repo + push and is
  verified on the live host (iCloud can revert).
- **Never leave the temporary surfacing in place** — revert it so not-interested stays out of
  Needs-review, leaving only the identifiable test row.
- **Never exceed a retry cap or report done while any done-rule fails.**
