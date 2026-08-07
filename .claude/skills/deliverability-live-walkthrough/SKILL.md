---
name: deliverability-live-walkthrough
description: Static orchestration skill that rides alongside a live, operator-driven user test of the Navreo deliverability page — Claude watches frontend + backend, hands the operator the campaign context they lack before each click, greenlights or warns, then proves at the true destination (Smartlead / audit service, never the app toast) whether the click landed, and fixes any FE/BE bug live on approval. One fixed step list, each step with a checkable done-rule, retry caps, and a Loop Training Mode toggle. Use when the user says "run the deliverability walkthrough", "let's do the real user test on deliverability", "sit with me on the deliverability alerts", or "/deliverability-live-walkthrough".
---

# Deliverability Live Walkthrough

Opens a real user test on real domains in real campaigns. A human **operator** drives every click in the deliverability UI; Claude is the co-pilot — it observes frontend and backend in lock-step, supplies the campaign/domain context the clicker doesn't have, gives an informed go/no-go, and reads the true destination to confirm the click worked. The only thing Claude itself writes and deploys is a code fix, and only on your approval. Static loop — fixed steps, each has a done-rule, Training Mode controls the pauses.

## ⚙ Loop Training Mode: **OFF**   ← flip this line to ON to pause at every step (owner ruling 2026-07-15: run autonomously; pause ONLY for per-action approval on real-data state changes. Same ruling: Claude MAY drive the UI clicks itself — the per-action approval from the owner replaces the operator-clicks-only rule.)

**ON:** pause at EVERY step boundary and wait for the user's explicit approval before continuing. Before starting a step, check its done-rule first — if it already passes, report "Step N already passes, skipping" and move on. Only re-run steps whose done-rule fails. Show what you're about to do before doing it. **This is a first live test on real client sending — keep it ON.**

**OFF:** run all steps end-to-end with no pauses. The done-rule checks, skip-if-passing behaviour, and retry caps stay exactly the same — only the pauses go. (Note: even OFF, Claude never fires a state-changing deliverability action — see the gate. OFF only removes Claude's *own* pauses; the operator still drives every click.)

**Retry cap (both modes):** each step retries **max 3** times against its done-rule. On cap-hit: record the step as FAILED with the reason, continue to the next step if it doesn't depend on the failed one, and surface every FAILED step in the final report. Never silently exceed the cap. Never declare the skill done on a cap-hit.

## Destructive / actor gate (both modes, non-negotiable)

- **Claude never fires a state-changing deliverability action.** The operator clicks the UI; Claude only observes, advises, verifies, and (for code) fixes. Claude's own live calls are read-only: `restore-plan` reads, `dry_run` restore, Smartlead re-fetch. If Claude is ever about to POST a state change to a deliverability endpoint, STOP — that's the operator's click, not Claude's.
- **No deletions this run.** Any mailbox or lead DELETION is advised against and NEVER greenlit — Claude reports what it would do instead. The reversible set the operator may click on Claude's go-ahead: `blacklist_pause`, `warmup_pause`, `warmup_resume`, `reenable`, `reconnect`, `reply_caps`, `restore_live`, `signatures`, `verify_run`.
- **Every operator action is briefed and greenlit individually.** Any domain on the page is in-scope, but each action gets its own context hand-off + go/no-go before the operator commits (satisfies "confirm before anything").
- **Code fixes are the only thing Claude deploys**, one approval pause per fix.

## Goal

> Every live optimisation and alert on the deliverability page has been walked with the operator, each action they chose greenlit-with-context and confirmed at its real destination, and every bug found fixed and redeployed — leaving the page clean enough to run a real user test on real campaigns. Composite done-rule below; anything short of all six = not done. On a retry/round cap-hit, stop and report the gap honestly — do not declare done.

## Ground truth (verified 2026-07-15 — re-verify in Step 1, line numbers drift)

- **Source of truth for code = git repo `~/navreo-signals` (branch `main`, remote github.com/bjionhenry94/navreo-signals).** Render auto-deploys on push to `main`. The iCloud copy (`…/Navreo/Claude/Navreo/app/…`) is **DEPRECATED — never edit it or treat it as source** (memory `signals-deploy-repo`). At verify time the repo HEAD was `4489825` (setter work) — the repo carries other sessions' uncommitted WIP, so stage ONLY target hunks, never `git add -A`.
- **Live host `navreo-signals.onrender.com` is behind a Supabase login gate.** Anonymous `curl` → 302 /app/login.html. Live observation/verify goes through the operator's authenticated real Chrome via **claude-in-chrome** (`list_connected_browsers` → `navigate` → `get_page_text`/screenshot), OR a **`navreo_session` cookie minted at +86400s** for API probes (default +3600s expires mid-run → APIs silently return `auth_required`; recipe: `test_deliverability_flows.py`). Static JS is cached hard — `fetch(url,{cache:'reload'})` before judging any deploy.
- **Surfaces:** `app/deliverability.html` (loader), `app/deliverability-tab.js` (UI; restore queue at §17), `app/server.py` (backend). Endpoints: `GET /api/restore-plan`, `POST /api/restore-live` `{id?,domains?,campaign_ids,dry_run?,force_early?}`, `POST /api/warmup-job`, `POST /api/deliverability/*`.
- **Action families (severity order as the operator reaches them).** Actionable: `blacklist_pause`, `warmup_pause`, `warmup_resume`, `reenable`, `reconnect`, `reply_caps`, `restore_live`, `signatures`, `verify_run`, `process_new`. Bookkeeping-only (no hand-off needed): `mark_done/undone`, `reminder_add/removed`, `view_data`, `restore_dismissed`, `copy`, `hypertide_draft`.
- **Backend-ledger gotcha (load-bearing):** server.py's POST router returns `_proxy_deliverability("POST")` BEFORE `log_activity()`, so NO deliverability action lands in `app_activity_log` / Supabase EXCEPT `restore_live` (one row, `action=restore_live`). **Confirm every click's effect from Smartlead** (campaign membership via `GET /campaigns/{id}/email-accounts`, mailbox status) **and the audit-service response — NEVER the app's success toast.**
- **Restore facts:** the real sending gate is **campaign attachment**, not caps. SURBL/blacklisted domains are correctly refused with **409**; pre-due restores need `force_early`. Flag both to the operator as **correct refusals, never override**. Memory `restore-queue-capacity-forecast`.
- **Smartlead WAF 403s a `Python-urllib` UA** — the server already sends a browser UA; MCP `mcp__smartlead__*` tools are the clean read path.
- **Known-open bugs to watch for** (memories `deliverability-essentialism-proto`, `restore-queue-capacity-forecast`): no success toast after bulk applies; process-new offering one campaign across mixed-brand mailboxes; manager tables render stale after writes until ↻ Refresh; "Restore all due" no-oping while per-row works; campaign picker "didn't load" with no retry; read-only View modal stacking a fresh overlay per open (Close dismisses only the top).
- **Unknown until Step 1:** which alerts are actually live on the page right now, and their exact counts — enumerate from the rendered page + `/api/restore-plan`, don't assume.

## Steps

### Step 1 — Re-verify ground truth + open the live page
Confirm repo is on `main` and ff-clean (`git -C ~/navreo-signals fetch && git rev-list --left-right --count HEAD...origin/main`). Establish the observation channel: operator's real Chrome via claude-in-chrome, or mint `navreo_session` at **+86400s**. Load the deliverability page cache-busted and screenshot it. Re-check the Ground-truth line refs against current `deliverability-tab.js` / `server.py`.
- **Done-rule:** (a) repo on `main`, divergence counted; (b) live page rendered in the operator's authenticated browser (or an API probe returns non-`auth_required` JSON); (c) the backend-ledger gotcha and endpoint list re-confirmed against current source. Any drift recorded before proceeding.

### Step 2 — Inventory the live alerts, FE↔BE
Enumerate every alert/optimisation currently rendering, and for each reconcile the **rendered card against its backend source** (`/api/restore-plan`, audit-service blob) — a card with no backend source, or backend state with no card, is itself a bug (log it for Step 5). Produce a **severity-ordered worklist** of actionable alerts.
- **Done-rule:** every rendered alert is matched to a backend source (or explicitly flagged as an FE-only / BE-only mismatch), and the severity-ordered worklist exists. Asserted from BOTH sides, never one.

### Step 3 — Per-action context hand-off + go/no-go (operator loop)
For each actionable alert the operator signals intent to click, BEFORE they commit return: **what the action does · which campaign/domain/mailboxes it touches** (the context they lack) **· the expected frontend AND backend result · any reason it will be refused** (SURBL/blacklist 409, pre-due needing `force_early`, caps-vs-attachment). Then an informed **go / no-go**. Gather context with read-only probes only (`restore-plan`, `dry_run` restore, Smartlead re-fetch). In Training ON, this is a pause per action. Bookkeeping-only actions need no hand-off.
- **Done-rule (per action):** a context brief was delivered naming the **real** campaign/domain touched and the expected result before the operator clicked; any refusal reason was surfaced as correct, never framed as something to override. FAILED if Claude ever fires the state change itself.

### Step 4 — Verify each fired action at its true destination
After the operator clicks, confirm the effect from the destination: Smartlead campaign membership / mailbox status via re-fetch, or the audit-service response. **Never the app toast, never `app_activity_log`** — except `restore_live`, which is confirmed by BOTH its one `app_activity_log` row AND a Smartlead re-fetch showing the domains now attached to the named campaigns.
- **Done-rule:** each fired action has a destination read-back proving the state change (for `restore_live`: ledger row present AND attach confirmed). A green toast alone is NOT a pass. Mismatches (toast says done, destination unchanged) are logged as bugs for Step 5.

### Step 5 — Bug triage + live fix (per-fix approval)
When a FE/BE bug surfaces (the known-open list, or any Step 2/4 mismatch): reproduce it with steps, show the proposed diff, and on your approval fix it live — edit `~/navreo-signals`, `git fetch` + `merge --ff-only origin/main`, **stage ONLY the target hunks (never `git add -A`)**, push, wait for Render redeploy, then re-verify on the **rendered live page with `cache:'reload'`** (marker-grep of deployed JS is a deploy check, not done-evidence). Reconcile repo→iCloud forward only if needed (don't overwrite the repo from stale iCloud). Each fix is its own approval pause; retry cap 3 per fix.
- **Done-rule:** each bug is (a) reproduced with steps, (b) fixed with a target-hunk-only commit, (c) Render-redeployed, (d) re-verified on the live rendered page cache-busted. Un-fixed bugs are recorded as FAILED, never hidden.

### Step 6 — Composite done-check + final report
Confirm the whole bar before declaring done.
- **Done-rule (all six or not done):** (1) every live alert reconciled FE↔BE; (2) every fired action verified at its true destination (not the toast); (3) every hand-off named the real campaign/domain + expected result, every 409/pre-due/cap surfaced as a correct refusal; (4) every bug reproduced→fixed→redeployed→re-verified live; (5) **no mailbox or lead deleted, and Claude fired no state-changing deliverability action** — the operator drove every one; (6) every live alert is actioned-and-verified-at-destination or explicitly deferred by the operator, zero unfixed FE/BE errors remaining.

## Final report (always, both modes)
One summary listing: alerts inventoried (count + severity order), actions the operator fired (each with domain/campaign + destination-verified result), refusals surfaced (SURBL/pre-due/cap, with domains), bugs found (repro → fix commit sha → live re-verify screenshot, or FAILED with reason), anything deferred by the operator, and the Step 6 six-part verdict. Name the real numbers and ids — "a summary" is not a spec. If any retry/round cap was hit, report it as FAILED with the gap; never declare done on a cap-hit.

## Hard don'ts
- **Never fire a state-changing deliverability action** (`blacklist_pause`, `warmup_*`, `reenable`, `reconnect`, `reply_caps`, `restore_live`, `signatures`, `verify_run`, `process_new`) — those are the operator's clicks. Claude's live calls are read-only / `dry_run` only.
- **Never delete** a mailbox or lead, or greenlit a deletion, this run — report what it would do instead.
- **Never trust the app's success toast or `app_activity_log`** as proof — verify at Smartlead / audit-service (except `restore_live`'s one ledger row, which still also needs the Smartlead attach re-fetch).
- **Never override a SURBL 409, pre-due block, or cap** — surface it as the correct refusal.
- **Never edit the iCloud copy as source**, and never `git add -A` in `~/navreo-signals` (foreign WIP lives there) — stage only target hunks.
- **Never judge a deploy without a cache-bust** (`fetch(url,{cache:'reload'})`); a JS marker-grep is a deploy check, not UI done-evidence.
- **Never exceed a retry cap, and never report done while any of the six done-rule parts fails.**
