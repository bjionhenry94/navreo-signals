---
name: reply-sync-supabase-backstop
description: Static orchestration skill that makes Supabase `replies` the single source of truth for reply categorisation by (A) building a new backstop cron `/api/cron/reply-sync` that pulls the Smartlead master inbox every ~3 min and feeds each unseen reply to the existing Make categoriser hook (dedup-collapsed with the webhook fast-path), and (B) confirming the Setter reads exclusively from `replies`. One fixed step list, each with a checkable done-rule, retry caps, and a Loop Training Mode toggle. Use when the user says "build the reply-sync backstop cron", "make replies the source of truth", "run the reply pipeline supabase redesign", or "/reply-sync-supabase-backstop".
---

# Reply-Sync → Supabase Backstop

Make Supabase `replies` (project `fnykldftbkrccihdjayl`) the single source of truth for reply categorisation. Today the Smartlead **webhook** is the only path into the categoriser, and it never fires for subsequence campaigns (e.g. "Interested Reply" / "Meeting Request" subsequences) or when webhook delivery lags. This loop adds a **backstop cron** that pulls the master inbox directly and feeds unseen replies to the SAME Make categoriser, dedup-collapsed so every reply is categorised exactly once — then confirms the Setter reads only from `replies`.

**Two deliverables:**
- **(A)** New cron route `/api/cron/reply-sync` (pg_cron → pg_net → POST, ~every 3 min, header-gated `x-navreo-token == SIGNAL_PULL_TOKEN`). Reads the Smartlead master inbox for replies since a stored watermark, and for each not-already-processed reply POSTs an `EMAIL_REPLY` payload to the Make categoriser hook. **Does NOT re-implement GPT categorisation** — reuses Make scenario 9251436 via its hook (owner decision). Webhook stays as fast-path; this is the BACKSTOP.
- **(B)** Confirm the Setter intake sources exclusively from `replies` (the cron keeps it complete, incl. subsequences). The Setter's campaign webhook was already removed 2026-07-15 (`ensure_webhooks` is a no-op) — do NOT re-add it.

Repo: `/Users/bjionhenry/navreo-signals` (Render auto-deploys on push to `main`). Keys: `/Users/bjionhenry/.navreo-keys.env`.

**Read first (the full design + owner decisions + categoriser internals live here, not in this file):**
- `…/memory/project_reply_pipeline_supabase_redesign.md`
- `…/memory/reference_smartlead_reply_categoriser.md`

**Model routing (house convention):** judgment — endpoint discovery, dedup-key reasoning, pass/fail against done-rules — runs on the orchestrating session (Fable 5 / default subagents). Execution — code edits, SQL, deploy mechanics, live verification — runs on Sonnet 5 subagents (`model: sonnet`). The product's runtime LLM is untouched; categorisation stays in Make.

---

## ⚙ Loop Training Mode: **OFF**   ← running autonomously. Flip this ONE line to ON to pause at every step for approval

**ON (default):** pause at EVERY step boundary and wait for the user's explicit approval before continuing. Before starting a step, check its done-rule first — if it already passes, report "Step N already passes, skipping" and move on. Only re-run steps whose done-rule fails. Show what you're about to do before doing it.

**OFF:** run all steps end-to-end with no pauses. The done-rule checks, skip-if-passing behaviour, and retry caps stay exactly the same — only the pauses go.

**Retry cap (both modes):** each step retries **max 3** times against its done-rule. On cap-hit: record the step FAILED with the reason, continue to the next step only if it doesn't depend on the failed one, and surface every FAILED step in the final report. Never silently exceed the cap. Never declare the skill done on a cap-hit.

---

## Safety gates (both modes, non-negotiable)

- **Exactly-once, always.** The dedup key IS the categoriser's own archive key `message_id = "{sl_email_lead_id}-{reply_message.time}"` (categoriser module 60). The cron's payload MUST reproduce that exact key so a pull-pushed reply and a webhook-delivered one collapse to ONE `replies` row (else double rows + double Slack). This is the whole point — verify it before deploy and again live.
- **Backstop, not replacement.** Keep the Smartlead webhook running (owner decision). The cron only catches what the webhook misses/lags; dedup guarantees one categorisation per reply.
- **Never re-implement categorisation.** No GPT calls in server code. The cron POSTs to the Make hook `https://hook.eu2.make.com/6mda3nqyrtm8u4x9ihilymra4z70aaug` and lets scenario 9251436 do the work.
- **No MCP tools in server code.** `fetch_master_inbox_replies` (MCP) CANNOT be called from the server. There is NO raw master-inbox list endpoint anywhere in `app/*.py` today — `run_poll` (`app/setter.py:~2369`) and `app/setter_backfill.py` both read Supabase `replies`, not Smartlead. Step 1 must DISCOVER the raw Smartlead master-inbox list endpoint (Smartlead API docs / capture what the MCP wraps) and build on the raw helper `_sl_get()` (`app/setter.py:~1110`; base URL + key from `~/.navreo-keys.env`).
- **Cap = 300 replies/run, and a cap-hit is REPORTED FAILED with the gap — never silently truncated.** If a run would exceed 300, it stops, records the unprocessed gap, and surfaces FAILED.
- **First run seeds the watermark at now-minus-2h.** A fresh/empty watermark must NOT flood thousands of historical rows — only the last 2h.
- **Idempotent watermark + processed-ids table.** Persist both in a new Supabase table; running the cron twice back-to-back creates zero new duplicate rows.
- **Deploy discipline (proven by commit `0e0fea5`, 2026-07-15).** The repo HEAD moves and may hold the owner's uncommitted WIP. ALWAYS `git -C /Users/bjionhenry/navreo-signals status` FIRST, then build in a **git worktree off the latest `origin/main`** and push from there so WIP is untouched. iCloud is NOT the deploy repo and can revert edits.
- **Never re-add the Setter campaign webhook.** `ensure_webhooks` is intentionally a no-op since 2026-07-15.
- **Re-verify every line number in Step 1** — they drift (server.py ~9991 cron pattern, ~12363/13022 auth check, ~11575/12960/13021 allowlists; setter.py ~1110 `_sl_get`, ~2369 `run_poll`). A grep of a local file is NEVER done-evidence for a live behaviour.

---

## THE DONE-RULE (single source of truth — the 6-check bar, all read LIVE after deploy)

None of these trust an app log; each reads the actual surface.

> **(1) Subsequence reply lands categorised:** a reply in a subsequence "Interested Reply"/"Meeting Request" campaign (which the webhook never delivers) appears categorised in Supabase `replies` within one cron cycle (~3 min) — read back FROM `replies`, not any app log.
> **(2) No double-processing:** a reply already handled by the webhook is NOT re-processed — `select count(*) from replies where message_id = <id>` returns **1, not 2**, and no second #interested-replies Slack fires for it (confirmed by reading Slack).
> **(3) Idempotent + watermark advances:** running `/api/cron/reply-sync` twice back-to-back creates **zero** new duplicate `replies` rows and advances the watermark row.
> **(4) First-run window + cap:** on a fresh/empty watermark the run processes **≤300** replies and only ones from the **last 2h** — no multi-thousand-row flood — and any cap-hit is reported **FAILED with the gap**.
> **(5) Setter reads the one table:** a subsequence reply that reached `replies` via the cron then shows up in the Setter's live queue/UI — read from the Setter surface, not a code path.
> **(6) Exactly one Slack:** with BOTH webhook and cron running, one positive reply yields exactly **ONE** Slack alert.

**All 6, or it isn't done.** On any cap-hit, report the gap honestly — never declare done.

---

## Steps

### Step 1 — Discover the raw endpoint + re-verify ground truth (WIP-safe)
`git -C /Users/bjionhenry/navreo-signals status` FIRST (record any WIP). Create a worktree off latest `origin/main`. Read both memory files. Discover the raw Smartlead master-inbox **list** endpoint (Smartlead API docs, or capture what the `fetch_master_inbox_replies` MCP tool calls) — the exact path, params, pagination, and time-filter for "replies since T". Confirm `_sl_get()` shape and key source (`~/.navreo-keys.env`). Re-verify the cron pattern (`cron_pull_all`/`/api/cron/mailbox-sync`, server.py ~9991), the auth check (~12363/13022), and the three allowlists (~11575/12960/13021) with REAL current line numbers. Confirm the categoriser's `message_id` formula `"{sl_email_lead_id}-{reply_message.time}"` (module 60) against `reference_smartlead_reply_categoriser.md`.
- **Done-rule:** (a) WIP recorded and worktree created off latest `origin/main`; (b) raw master-inbox list endpoint named with path/params/pagination/time-filter, buildable on `_sl_get()`, MCP-free; (c) real current line numbers captured for cron pattern + auth + 3 allowlists; (d) the exact `message_id` dedup formula confirmed against the categoriser reference.

### Step 2 — Watermark/processed-ids table (idempotent)
Create the new Supabase table holding the watermark timestamp + the set of processed `message_id`s (or a design that makes re-processing a no-op). Idempotent DDL (`create table if not exists`). Seed logic: on empty watermark, use now-minus-2h.
- **Done-rule:** table exists in `fnykldftbkrccihdjayl`; a dry insert/read proves watermark read+advance and processed-id lookup work; DDL is safely re-runnable.

### Step 3 — Build `/api/cron/reply-sync` (backend)
Add the route in server.py following the `cron_pull_all`/`mailbox-sync` pattern, gated `x-navreo-token == SIGNAL_PULL_TOKEN`, registered in ALL THREE allowlists. Logic: read watermark → `_sl_get()` the raw master inbox for replies since watermark → for each reply NOT in processed-ids, build the `EMAIL_REPLY` payload `{event_type:"EMAIL_REPLY", sl_lead_email, sl_email_lead_id, campaign_id, reply_message:{text, time}}` where `text` = latest REPLY body, **HTML stripped** → POST to the Make hook → mark processed + advance watermark. **`reply_message.time` MUST be the value that makes `message_id` equal the categoriser's archive key** so pull and webhook collapse to one row. Cap 300/run; a cap-hit STOPS and is reported FAILED with the gap. No MCP tools; no GPT.
- **Done-rule:** route present + in all 3 allowlists + auth-gated; local/unit proof that (i) an unseen reply produces a correctly-shaped `EMAIL_REPLY` with HTML-stripped text and a `message_id` byte-identical to the webhook path's key, (ii) an already-processed reply is skipped, (iii) watermark advances, (iv) >300 eligible → FAILED-with-gap, not truncation.

### Step 4 — Register pg_cron → pg_net job (~3 min)
Add the pg_cron schedule that pg_net-POSTs to `/api/cron/reply-sync` every ~3 min with the `x-navreo-token` header, matching the existing `cron_pull_all`/`mailbox-sync` cron rows. Idempotent (unschedule-if-exists then schedule).
- **Done-rule:** the pg_cron job exists and is listed; a manual invocation of the same POST returns 2xx and does one full cycle; schedule cadence ~3 min confirmed.

### Step 5 — Tests
Add tests alongside `app/test_setter.py` (and siblings) covering: watermark advance, dedup (same reply twice → one categorise call / one processed-id), the 300 cap → FAILED-with-gap, and the first-run now-minus-2h window. Run the FULL existing suite — it must stay green.
- **Done-rule:** new cron tests pass; the full existing suite passes; no regressions.

### Step 6 — Deploy from the worktree
Push from the worktree (not iCloud) so owner WIP is untouched. Wait for Render to go live. Confirm a unique deploy marker is present on the live host (deploy check only, NOT done-evidence).
- **Done-rule:** pushed from worktree off latest `origin/main`; Render live; deploy marker confirmed on the running host; owner WIP confirmed untouched (`git status` clean of your changes on the main working copy).

### Step 7 — Confirm the Setter reads only `replies` (deliverable B)
Verify the Setter intake sources exclusively from the `replies` table (so cron-delivered subsequence replies reach the queue). Confirm `ensure_webhooks` is still a no-op. Do NOT re-add any campaign webhook.
- **Done-rule:** code/read confirmation that Setter intake reads `replies` only; `ensure_webhooks` no-op confirmed; no campaign webhook added.

### Step 8 — The 6-check bar (all LIVE)
Run all six DONE-RULE checks against PROD, each reading the real surface (Supabase SQL for `replies`/watermark, the Setter UI, Slack) — never an app success label:
- (1) subsequence reply categorised in `replies` within one cycle;
- (2) webhook-handled reply `count(*)=1` + no second Slack;
- (3) run cron twice → zero dup rows + watermark advanced;
- (4) fresh watermark → ≤300, last-2h only, cap-hit → FAILED-with-gap;
- (5) that subsequence reply appears in the live Setter queue/UI;
- (6) both paths live → exactly one Slack for one positive reply.
- **Done-rule:** checks (1)–(6) each pass with the actual numbers/artifacts recorded (message_ids, counts, watermark before→after, screenshots, Slack confirmation).

---

## Final report (always, both modes)

One summary: per-step PASS / SKIPPED / FAILED with retry counts; the real artifacts — raw endpoint used, new table name + DDL, the cron route + pg_cron job id, deploy commit SHA (pushed from worktree, owner WIP untouched), the exact `message_id` formula proven identical across pull and webhook; the 6-check results with numbers (subsequence reply message_id, `count(*)` = 1, watermark before→after across the double-run, first-run processed count ≤300 / last-2h, Setter-UI screenshot, single-Slack confirmation); any cap-hit gap; anything deferred or FAILED, stated plainly. Never report done while any of the 6 checks fails.

## Hard don'ts

- Never call an MCP tool from server code; never add GPT categorisation — Make scenario 9251436 stays the only categoriser.
- Never let the cron's `message_id` differ from the categoriser's archive key — divergence = double rows + double Slack.
- Never remove or bypass the Smartlead webhook — it's the fast-path; the cron is the backstop.
- Never flood on first run — now-minus-2h seed, 300/run cap, cap-hit = FAILED-with-gap, never silent truncation.
- Never build in the iCloud copy or push over owner WIP — worktree off latest `origin/main`, `git status` first.
- Never re-add the Setter campaign webhook (`ensure_webhooks` stays a no-op).
- Never trust an app log as done-evidence — read `replies`, the Setter surface, and Slack directly.
- Never exceed a retry cap, and never report done while any of the 6 checks fails.
