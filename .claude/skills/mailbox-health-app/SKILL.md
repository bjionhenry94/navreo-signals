---
name: mailbox-health-app
description: Static orchestration skill that turns app/mailboxes.html from an illustrative mock into a working deliverability app — real Smartlead-derived fix cards, a real apply path, live data, verified by cross-referencing every number against Smartlead and by a 10-person non-technical tester panel scoring ≥8/10 on fast-and-easy. Fixed step list, each with a done-rule, plus a Loop Training Mode toggle. Use when the user says "make the mailboxes page real", "run the mailbox health app build", "fix the deliverability app", or "/mailbox-health-app".
---

# mailbox-health-app

Make `https://navreo-signals.onrender.com/app/mailboxes.html` a functioning app: see suggested fixes for deliverability, act on them, and trust the numbers. Static loop — the steps below are fixed, each has a done-rule, and Loop Training Mode controls whether you pause between them.

Files: `app/mailboxes.html` (UI), `app/server.py` (needs mailbox routes), `app/fetch_data.py` (GET-only Smartlead collector), `app/data/mailboxes.json` + `meta.json` (the snapshot). Local: `http://localhost:7901/app/mailboxes.html`.

---

## ⚙️ LOOP TRAINING MODE  →  **ON** (default)

Flip it by editing this one line:

    LOOP_TRAINING_MODE = ON        # ON = approve every step · OFF = run autonomous

**When ON**
- Pause at the end of **every** step and wait for my explicit approval before starting the next.
- Before running a step, check its done-rule first. **If it already passes, skip it** — say so and move on.
- Only (re-)run steps that fail their done-rule.
- Retry cap applies (see below). Never loop a step forever.

**When OFF**
- Run all steps autonomously, no pauses.
- Still check every step's done-rule and still honour the retry cap. Report at the end, not between steps.

**Retry cap (both modes):** any single step retries **max 3** times against its done-rule. The tester loop (Steps 6-7) runs **max 4 rounds**. On cap-hit, stop that step, record it as FAILED with the reason, keep going, and surface it in the final report. Never silently exceed. Never declare done on a cap-hit.

---

## THE GOAL

A non-technical operator opens the page, sees **what is actually wrong with our deliverability right now**, understands each fix in plain English, and acts on it in one click. Fast to load, obvious to use, and **every number on the page is true**.

Done means all three: the fixes are **real** (derived from live Smartlead, not fixtures), the apply button **actually does something** (writes to Smartlead or queues a reviewable draft), and the panel **agrees it's easy** (≥8/10, all ten testers).

---

## THE GAP (don't rediscover this)

- **The fix cards are fake.** `mailboxes.html:337` starts a hardcoded `DATA` array of 9 fixtures — fake clients (`Hypertide`), fake domains (`getboldreach.com`), rows synthesized by `genRows()`. Line ~748 literally renders *"Fix cards below are illustrative."*
- **Apply is a no-op.** `m-confirm` (`:674`) mutates local state only. No API call. No persistence. Reload = gone.
- **Data is a stale file.** The page fetches `data/mailboxes.json` + `data/meta.json` (`:710`) — a snapshot from `fetch_data.py`, currently days old. Header stats are real; nothing else is. `server.py` has **no** mailbox routes at all.
- **Fields available today** per account: `id, email, name, domain, smtp_ok, imap_ok, daily_limit, warmup_status, warmup_reputation`. Bounce rate, reply rate, SPF/DKIM/DMARC and nameservers are **not** in the snapshot — a fix rule that needs them must fetch them or must not ship.

**Reads** (GET, free): `get_email_accounts`, `get_mailbox_domain_wise_health_metrics`, `get_mailbox_name_wise_health_metrics`, `get_mailbox_overall_stats`, `get_email_warmup_stats`, `check_mailbox_domain_deliverability`, `check_signature_missing`, `check_campaign_bounce_or_lead_quality`, `get_campaign_analytics_by_date`.
**Writes** (only ones permitted): `update_email_warmup_details`, `update_email_account_details`, `reconnect_failed_email_accounts`, `update_campaign_status` (pause). Everything else = draft for human send.

---

## THE STEPS

### Step 1 — Ground truth: what is actually wrong
Pull the live fleet from Smartlead and write the real defect set. No UI work yet.
- Done-rule: a `MAILBOX-TRUTH-<date>.md` exists listing every real defect with its Smartlead evidence (account ids, domains, counts). Fleet totals reconcile with `get_mailbox_overall_stats` exactly. Zero invented entities.

### Step 2 — Replace fixtures with a real rule engine
Delete the `DATA` array. Derive cards from Step 1's defect set, one rule per card type.
- **Hard exclusion — Maildoso warmup.** `warmup_status: INACTIVE` on a Maildoso inbox is **intentional** (they warm externally). It must **never** produce a fix card. The current fixture `{id:'warmup'}` proposing to re-enable 33 Maildoso mailboxes is exactly the banned suggestion. Suppress the whole class and exclude Maildoso from warmup counts.
- A rule may only ship if its evidence comes from a real read. No rule may cite a field the data doesn't have.
- Keep the existing card shape, `GLOSSARY`, plain-English `why`/`approve`/`skip`. The design is good; the data is not.
- Done-rule: `grep -n "Hypertide\|getboldreach\|genRows\|illustrative" app/mailboxes.html` returns nothing. Every rendered card traces to a real account id. Maildoso warmup produces zero cards.

### Step 3 — Make Apply real (and reversible)
Wire `m-confirm` to new `server.py` routes that actually act.
- Safe fixes → the permitted writes above. Provider/DNS fixes → a **draft** the human sends. Never auto-send outbound mail.
- Snapshot before-state to `audit-backups/<date>_<fix>.csv` before any write. Idempotent: re-applying must not double-write. Respect the **200 req/min** Smartlead cap.
- Done-rule: apply one real fix on one real inbox, then confirm the change by re-reading it from Smartlead (not the app's own success toast). Reverse it. Both directions verified live.

### Step 4 — Kill the stale snapshot
The page must never show numbers it can't date.
- Serve mailbox data through `server.py` (fresh read, short cache), or refresh-on-load with a visible age. If data is older than 24h, say so on the page.
- Done-rule: `meta.fetched_at` renders as a human age on load; forcing a stale file shows an explicit staleness warning rather than presenting old numbers as current.

### Step 5 — Fast and obvious
- First contentful paint under **2s** on the Render URL; no layout shift when live stats swap in; the 8,338-row inbox list virtualized or paginated, never rendered whole.
- No jargon outside a `GLOSSARY` tooltip. Every card answers: what's wrong, what happens if I approve, what happens if I skip.
- Done-rule: measured load under 2s; zero console errors; `preview_snapshot` shows no raw field names (`smtp_ok`, `warmup_status`) leaking into user-facing copy.

### Step 6 — Cross-reference every number against Smartlead
The app's claims are checked against the source, field by field.
- Total inboxes, domains, healthy connections, warmup-active, per-domain health, per-campaign bounce/reply — each read independently from Smartlead and diffed against what the page renders.
- Done-rule: a reconciliation table in `MAILBOX-APP-<date>.md` with one row per number: `app value | Smartlead value | match?`. **Every row matches.** A single mismatch fails the step.

### Step 7 — 10 non-technical testers, all ≥8/10
- Personas are **all non-technical**: e.g. VA, founder, ops manager, junior SDR, sceptical CMO, account manager, bookkeeper, intern, client-side marketer, salesperson.
- Each attempts, **cold, using only the UI**: (a) say what's wrong with deliverability right now, (b) approve one safe fix, (c) explain what it did.
- Simulate faithfully — a confused persona must actually get stuck, not be rescued. Never drive the sim with `preview_click`; simulate the human, don't puppet the DOM.
- Capture every confusion, misclick, hesitation, and a **fast-and-easy score /10**.
- Done-rule: 10 transcripts, each scoring **≥8/10** (not an average — every tester). Below that → apply the top friction fixes and loop to Step 7 (Steps 1-6 already pass → skip them). Max 4 rounds.

### Step 8 — Ship it
- Working copy is iCloud; the deployed repo is `~/navreo-signals` → Render. Copy across, **diff-check after the merge** (a rebase has silently dropped work here before), push, confirm the live URL serves the new page.
- If mailbox state changed, re-run `notion-mailbox-sync` so the Notion "Mailboxes by Domain" mirror isn't left stale.
- Done-rule: `https://navreo-signals.onrender.com/app/mailboxes.html` serves the real app; the deployed diff equals the local diff; Notion mirror current.

---

## THE DONE-RULE (single source of truth)

> **All ten** testers score the app **≥8/10** on fast-and-easy, **and** every number on the page reconciles exactly against Smartlead (Step 6 table, zero mismatches), **and** approving a fix provably changes real Smartlead state (or queues a real draft), **and** no fix card is a fixture.

All four, or it isn't done. On the 4-round cap, stop and report the gap honestly.

---

## GUARDRAILS
- **Never re-enable Maildoso warmup.** Inactive is intentional. Exclude from audits and from every fix rule.
- **Campaign-sequence writes need an explicit user go-ahead first** (this skill almost never needs one). If one is ever approved, it MUST use the ID-intact recipe (verified 2026-08-02): (1) `get_campaign_sequences` fresh, immediately before saving; (2) build the POST as `{"sequences":[...]}` translating `sequence_variants`→`seq_variants` and `delayInDays`→`delay_in_days`; (3) echo EVERY step id and variant id unchanged — a dropped id permanently orphans that variant's stats, no recovery; new variant = no id; disable = keep id + `variant_distribution_percentage: 0`; (4) `save_campaign_sequences`; (5) verify: re-GET shows identical ids AND `get_campaign_variant_statistics` still shows prior history (429 → wait ~70s, retry, never skip). Worked example: `lilly-bot` → "THE ID-INTACT RECIPE".
- **Never auto-send outbound email.** Provider and DNS fixes are drafts a human sends.
- **Back up before every write**, respect 200 req/min, and make apply idempotent.
- **Honesty:** verify against the live Smartlead read, never the app's own success state. A page that renders confidently and is wrong is worse than the mock it replaced.
