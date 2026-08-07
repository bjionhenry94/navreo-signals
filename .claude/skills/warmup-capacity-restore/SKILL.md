---
name: warmup-capacity-restore
description: Static orchestration skill for the Navreo signals tool — rebuild the "Restore reminders" tab on deliverability.html into a due-date-ranked restore queue with a ONE-CLICK "Restore to sending" action that really restores saved daily caps in Smartlead, plus a per-client capacity view showing what's parked in warm-up now, when each domain is due back, and projected total daily sending volume for the upcoming days as due-backs land. One fixed step list, checkable done-rules, retry caps, Loop Training Mode toggle (ON by default). Use when the user says "run the warmup capacity restore", "rebuild the restore reminders", "show the warm-up capacity impact", or "/warmup-capacity-restore".
---

# Signals: Ranked Restore Queue + Warm-up Capacity Forecast

## ⚙ Loop Training Mode: **OFF**   ← flip this line to ON to pause at every step

**ON (default):** pause at EVERY step boundary and wait for the user's explicit approval
before continuing. Before starting a step, check its done-rule first — if it already
passes, report "Step N already passes, skipping" and move to the next pause. Only re-run
steps whose done-rule fails. Show what you're about to do before doing it.

**OFF:** run all steps end-to-end with no pauses. The done-rule checks, skip-if-passing
behaviour, and retry caps stay exactly the same — only the pauses go.

**Retry cap (both modes):** each step retries **max 3** times against its done-rule.
On cap-hit: record the step as FAILED with the reason, continue to the next step if it
doesn't depend on the failed one, and surface every FAILED step in the final report.
Never silently exceed the cap. Never declare the skill done on a cap-hit.

**Destructive-action gate (both modes, non-negotiable):** "Restore to sending" mutates
live Smartlead daily caps. Before ANY real restore fires: show the domain(s), every
mailbox, and the exact cap each will get back, and get explicit user approval — in BOTH
modes, because this is a live-sending change, not a UI change. Never restore a domain
that is currently blacklisted. Restoring before its due date needs an extra confirm.

## Goal

Four user-visible outcomes on https://navreo-signals.onrender.com (deliverability page,
"Restore reminders" tab — which this ships as a restore QUEUE):

1. **Ranked by urgency, not entry order.** Pending entries sorted by due date — overdue
   first, then soonest due. No one re-enters dates; domains already resting in the live
   data appear automatically even when nobody added a reminder.
2. **One push back to live sending.** A "Restore to sending" button per entry that
   actually restores each mailbox's saved daily cap in Smartlead (the thing today's
   "✓ Mark added" pretends to be), then marks the reminder done and logs it.
3. **Exact due-back dates + capacity per entry.** Every row shows when it's due back,
   how many mailboxes, and "+X/day when restored" from real parked caps.
4. **Per-client capacity forecast.** What's parked in warm-up now (domains, mailboxes,
   volume/day) and projected total daily sending volume for each of the next 14 days,
   client by client, stepping up as each due-back lands — so upcoming capacity is
   plannable at a glance.

## Ground truth (verified 2026-07-11 — re-verify in Step 1, line numbers drift)

- Working copy: `~/navreo-signals` ONLY (git repo, Render auto-deploys on push to
  `main`). The iCloud app copy is DEPRECATED (user directive 2026-07-07) — never edit
  it. Local dev: `python3 app/server.py` → `http://localhost:7901/app/deliverability.html`.
- Panel code: §17 of `app/deliverability-tab.js` — `renderRemindersPanel` (~:3702),
  `renderReminderRow` (~:3671), sub-tab key `"reminders"` (~:1030, switch ~:4090).
  Rows render in insertion order today, NOT due-date order.
- Reminder data lives server-side in the standalone audit service, reached through the
  `/api/deliverability/` proxy (`server.py` ~:8354 →
  `navreo-email-deliverability-audit.onrender.com/api/`): `GET reminders`,
  `POST reminder?domains=&date=`, `POST reminder-done?id=`,
  `POST reminder-enable-warmup?id=`. There is NO delete endpoint — "Remove" is
  local-only by design; keep it that way.
- **"✓ Mark added" (`remDone`, ~:6119) only flips a done flag and logs. Nothing in this
  panel resumes sending today.** The real primitive already exists elsewhere:
  `liveAction("warmup-resume?domain=X")` (used at ~:5759) restores each mailbox's
  parked cap and resumes sending, returning `{resumed}`.
- Cap model on inbox rows: `r.cap` = current daily cap; `r._savedCap` = cap parked when
  the domain was rested (`warmup-pause`); `r.rested` / `r.restedDue`. "In warm-up" =
  `kind === "ok" && cap === 0 && !rested` (~:937). Beware: several mock paths fall back
  to `cap = 20` when no saved cap exists (~:6064) — that default must NEVER reach a
  live mailbox.
- Client dimension: "batch (client / mailbox pool)" — batch list comes back from
  `GET inboxes?view=&batch=` (`DATA.mgr.batches`, ~:827) and already powers
  "Performance by batch". Whether domain→batch→client is complete is Step 1's to prove.
- Activity/documentation channel: `app_activity_log` Supabase table via the helper in
  `server.py` (service-role only). History rows render in §18 (`renderHistoryRow`).
- Smartlead API: 200 req/min cap. Outlook mailboxes' policy cap is 2/day
  (`max_email_per_day`). Maildoso-batch mailboxes warm EXTERNALLY — Smartlead warmup
  INACTIVE on them is intentional; never re-enable it.

## Steps

### Step 1 — Re-verify ground truth + prove the client mapping
Confirm every bullet above against current code. Then resolve the one real unknown: how
a reminder's domains map to a client. Candidates in likelihood order: batch name from
`GET inboxes` (batch ≈ client/mailbox pool), Smartlead `client_id` on email accounts,
the Notion "Mailboxes by Domain" DB. Prove the chosen mapping end-to-end on 2 real
domains from live pending reminders (domain → mailboxes → client label). If no reliable
mapping exists, the per-client split degrades to per-batch with an honest on-page label
— decide and record which.
- **Done-rule:** you can name (a) the panel render + handler functions with current
  line numbers, (b) the four live reminder endpoints with a captured real
  `GET reminders` response, (c) the field carrying each mailbox's parked cap in the
  LIVE audit blob (not the mock), and (d) the proven domain→client mapping for 2 real
  domains — or the recorded per-batch fallback decision.

### Step 2 — Backend: restore plan + one-click restore (`app/server.py`)
Two endpoints, server-side so every number is computed once, deterministically:
1. **`GET /api/restore-plan`** → `{reminders, forecast}`.
   - `reminders`: every pending reminder from the audit service PLUS any
     currently-rested domain with no reminder row (derived from the cached audit blob),
     deduped by domain and sorted by `dueDate` ascending. Each entry:
     `{id, domains, client, restoredDate, dueDate, days_left, overdue, mailboxes,
     parked_capacity, health, source: "reminder"|"auto"}` where `parked_capacity` =
     sum of saved caps (the /day volume this entry returns when restored).
   - `forecast`: next 14 calendar days × per-client rows:
     `{date, weekday, client, sending_now, returning, projected_total}` where
     `returning` = sum of parked caps of entries due on/before that date. Weekends
     flagged. Real caps only — no estimates, no defaults.
2. **`POST /api/restore-live`** body `{id, domains, dry_run?}` → for each domain call
   the SAME `warmup-resume` the audit service already implements (through the existing
   forwarder — do NOT re-implement cap logic), collect per-domain `{resumed}` results,
   then `POST reminder-done` for the covering reminder, write ONE `app_activity_log`
   row `{domains, mailboxes_resumed, caps_restored_total}`, and return everything.
   Per-domain failures report their real error; partial success is reported per-domain,
   never rolled up as OK. `dry_run: true` returns the exact mailbox+cap plan without
   mutating anything.
- **Done-rule:** on localhost, `GET /api/restore-plan` returns pending entries sorted
  by dueDate with non-null `parked_capacity`, and a 14-day forecast whose day-0
  `sending_now` matches the audit blob's sending-mailbox cap sum; `restore-live` with
  `dry_run: true` returns the correct per-mailbox plan and mutates nothing.

### Step 3 — Frontend: the ranked restore queue (`app/deliverability-tab.js` §17)
Rebuild `renderRemindersPanel`/`renderReminderRow` on top of `GET /api/restore-plan`:
- Order: overdue first, then soonest due; done entries collapsed at the bottom.
- Each pending row: domains · client label · "due 2026-07-15 (in 4d)" · N mailboxes ·
  "+X/day when restored" · the existing warming-health line (keep the per-reminder
  Enable-warmup button exactly as it is — do not extend it).
- Primary action: one **"Restore to sending"** button → confirm modal listing every
  mailbox and the exact cap it gets back (dry_run data) → on approval,
  `POST /api/restore-live` → live progress → on success the row flips to done
  ("restored · +X/day live") and a history row appears. Failures show the real
  per-domain error. "✓ Mark added" survives only as a small secondary action for
  bookkeeping (restored outside the app); Undo and Remove keep working.
- Auto-derived entries (`source: "auto"`) are visibly labelled so they're
  distinguishable from manually-added reminders. The add-reminder form stays, below
  the queue.
- **Done-rule:** on localhost with live data, the panel lists pending entries in
  due-date order with capacity numbers matching restore-plan exactly; clicking Restore
  to sending shows the correct dry-run mailbox+cap list; zero console errors.

### Step 4 — Capacity forecast strip (per client)
Above the queue, rendered from the SAME restore-plan payload (no client-side
re-derivation):
- Headline: "In warm-up now: N domains · M mailboxes · X/day parked", with the
  per-client breakdown.
- A compact 14-day view (table or bar strip): per client, projected total /day for each
  upcoming day, visibly stepping up on the day each due-back lands; weekends muted.
  One plain-English caption, e.g. "By Fri 2026-07-17 you're back to ~2,400/day for
  Navreo." Follow the existing conventions: colour-as-severity, no emoji-as-severity.
- **Done-rule:** the strip's day-0 total equals current sending capacity from the
  audit blob; the day after each due date the projected total increases by exactly that
  entry's `parked_capacity`; hand-check passes for 2 dates.

### Step 5 — Deploy
Commit in `~/navreo-signals` (stage files explicitly — never `git add -A` blind; no
secrets/data), push `main`, wait for Render, then confirm the new code is live.
- **Done-rule:** production serves the new panel code (marker grep of the deployed JS)
  and `GET /api/restore-plan` returns 200 JSON on production. (This proves deploy only
  — Step 6 is the done-evidence for the UI.)

### Step 6 — Live proof (browser-verified — the only acceptable done-evidence)
In the browser on `https://navreo-signals.onrender.com/app/deliverability.html`:
1. Confirm the queue is ranked by due date and the forecast renders with real numbers.
2. Pick the single safest due entry (smallest mailbox count, not blacklisted, due or
   overdue) and run ONE real "Restore to sending" — approval gate first, both modes.
   Then fetch those email accounts from Smartlead and assert each cap really equals its
   parked value (Outlook boxes 2/day).
3. Confirm the reminder flipped to done, the history row exists, and the forecast moved
   that entry's volume from "parked" into "sending now".
- **Done-rule:** screenshot of the ranked queue + forecast, plus matching numbers in
  three places: Smartlead caps, the restore-plan payload, and the rendered page.

## Final report (always, both modes)
One summary: steps passed/skipped/FAILED; the shipped queue's top entries (due dates +
parked capacity); the one real restore's numbers (domains, mailboxes resumed, caps
restored); the forecast headline per client; anything deferred.

## Hard don'ts
- Never mutate live Smartlead caps without the per-restore approval gate — in EITHER mode.
- Never restore with guessed caps — only parked/saved values. The mock's `cap = 20`
  fallback must never reach a live mailbox; Outlook mailboxes stay at 2/day.
- Never restore a currently-blacklisted domain; pre-due-date restores need an extra confirm.
- Never touch warmup settings on Maildoso-batch mailboxes (their warmup runs externally
  by design) and never add new bulk enable-warmup actions.
- Never fabricate capacity or forecast numbers — every figure traces to a real cap in
  the audit blob or Smartlead.
- Never edit the iCloud app copy — `~/navreo-signals` only.
- Never exceed a retry cap or report done while any done-rule fails; the rendered
  production page is the only done-evidence for the UI work.
