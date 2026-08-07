---
name: smartlead-warning-parity
description: One-shot orchestration loop that makes every mailbox warning Smartlead surfaces (SMTP/IMAP connection failures with their real error text, mail-service-disabled Gmail boxes, warmup-off boxes) automatically visible in the navreo-signals Mailboxes manager, without breaking existing rules (stale blocked_reason is never its own view, Maildoso exemptions, client-workspace federation, no double-counting the external audit blob). Trigger phrases - "run the smartlead warning parity loop", "sync smartlead warnings into the tool", "/smartlead-warning-parity".
---

# Smartlead Warning Parity Loop

## LOOP TRAINING MODE — toggle here

```
LOOP_TRAINING_MODE: ON
```

Flip the line above to `OFF` to change behaviour. Rules (exact, both modes share the done-rules and retry cap):

- **ON (default):** pause at EVERY step and wait for Bjion's approval before continuing. Skip any step that already passes its done-rule (say so, don't redo it). Only re-run steps that fail. Retry cap: **2 retries per step** (3 attempts total) — then halt the loop and report what's stuck.
- **OFF:** run all steps autonomously, no pauses. Keep every done-rule check and the same 2-retry cap. Halt and report on cap breach.

## Goal

Any account-level warning Smartlead surfaces in its Email Accounts UI is reflected in our tool's mailbox manager (deliverability engine room) within one sync cycle — with the *reason* shown, not a generic label — and no domain is shown as healthy/"warming"/"ready now" while its boxes are connection-dead. Existing rules stay intact.

## Fixed facts (from the 2026-08-03 diagnosis — re-verify, don't re-derive)

- Ingestion is healthy: `app/sync_mailboxes.py` (pg_cron → `POST /api/cron/mailbox-sync`, daily 04:30 UTC) already stores `smtp_ok`, `imap_ok`, `warmup_status`, `blocked_reason` per box in Supabase `mailboxes`. The render.yaml cron entry is dead — never edit render.yaml expecting it to fire.
- The gap is SURFACING, for the **navreo** workspace only: its manager views come from the external audit-service blob (separate repo, NOT ours to change). That blob missed 110 of 115 SMTP-failed boxes ("RTPS-CE:- Mail service not enabled", all Gmail, warmup INACTIVE, 37 navreo* domains) — they appear in NO view. Client workspaces are already classified locally at `server.py:~14944` (`_deliv_merge_client_ws`).
- `smtp_failure_error` / `imap_failure_error` from Smartlead are ingested nowhere; client-ws reconnect rows show a hard-coded "SMTP/IMAP connection failed".
- The Supabase mirror keeps rows for deleted Smartlead boxes — ALWAYS filter `last_synced_at` to the latest sweep (e.g. `gte.` today) before counting or classifying, else counts inflate (425 vs true 116).
- Smartlead's own "Warmup" issue chip = stale `blocked_reason` text (289 boxes, all timestamps ≥5 days old, mostly on healthy warmup-ACTIVE boxes). Ruling 2026-07-28 stands: blocked_reason is NEVER its own view/warning; it rides along as a row's reason only. Do not "fix" this into a new alert.
- Standing rules: Maildoso is exempt from warmup-off logic; web instance is a 512MB Render starter so heavy sweeps stay in the cron path, not request handlers; no Smartlead writes (reconnect POST stays user-triggered); edit live files directly.

## Steps

**Step 1 — Reconcile (read-only).** Pull all Smartlead accounts (paginate `/email-accounts/`, key from `~/.navreo-keys.env`, strip quotes/CR), pull the mirror (fresh-sweep filter), pull live `/api/deliverability/_audit` + `_bundle` (mint `navreo_session` per signals-live-verify-recipe). Build the parity table: for every Smartlead warning class (smtp fail by error pattern, imap fail, warmup INACTIVE non-Maildoso) → count in Smartlead vs count visible in tool views.
*Done-rule:* every warning class has a counted disposition — surfaced / deliberately-suppressed (cite the ruling) / GAP — and the table is in chat.

**Step 2 — Ingest error text.** Add `smtp_failure_error`, `imap_failure_error` columns to `mailboxes` (+ `mailbox_stats_daily` optional, skip if noisy), capture both in `transform_mailbox` in `app/sync_mailboxes.py`, trigger one sync via `POST /api/cron/mailbox-sync` (x-navreo-token).
*Done-rule:* a known-failing box (e.g. an altiusreachadvisory.info box) shows its real error string in Supabase `mailboxes`.

**Step 3 — Navreo-fleet parity in the manager.** Extend the bundle build so navreo mirror rows fill manager views for boxes the external blob missed — same vocabulary and precedence as `_deliv_merge_client_ws` (reconnect > warmupoff > inwarmup), reason = real error text, Maildoso exempt, fresh-sweep filter mandatory, dedupe by email against blob-supplied rows (blob wins). Additive only — never strip or mutate backend rows.
*Done-rule:* live `_bundle` reconnect view contains every fresh smtp/imap-failed navreo box (±same-day drift), including all "Mail service not enabled" boxes, each with its error text; no email appears twice across views.

**Step 4 — Contradiction guard.** A domain in `restDue`/"ready now"/"warming" whose boxes are ≥1 connection-dead must show a visible conflict marker (e.g. "N boxes can't connect") and its Restore button must not present as clean.
*Done-rule:* getnavreo.biz-class rows (in restDue AND mail-service-disabled) render the marker on the live page (DOM-verify, not screenshot).

**Step 5 — Kill the false-truth paths.** CSV exports hard-code `smtp_ok:true`/`imap_ok:true` (`deliverability-tab.js` ~2147, ~2183) → export real values. `app/fetch_data.py` reads nonexistent `is_smtp_failure`/`is_imap_failure` (~295) → correct to real fields or delete the dead path.
*Done-rule:* grep finds no hard-coded connection booleans; fetch_data reads real fields or is gone.

**Step 6 — Live before/after + hand-over.** Deploy (push to main → Render), poll `/api/version` for the commit (check HTTP status), re-pull `_bundle`, present before/after counts + a verified link Bjion can open.
*Done-rule:* live counts match Step 1's Smartlead truth for every GAP class, link confirmed loading, before/after table in chat.

## Loop done-rule

All six step done-rules pass against the LIVE deploy, and Bjion has seen the before/after table. Then close the loop: update memory (new file or amend `deliverability-count-truth-fix` neighbours) with what shipped + commit hash.
