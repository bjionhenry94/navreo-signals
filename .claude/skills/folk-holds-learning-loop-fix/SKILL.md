---
name: folk-holds-learning-loop-fix
description: Static orchestration skill that clears BOTH reds from the 2026-07-16 signals daily health check — sorts the ~49 folk_ledger missing_held leads ("Not in Folk; client campaign - held for approved processing", growing 24→45/day, zero of them the 4 expected names) by sharing the full list with Bjion, executing his per-lead rulings (repush to Folk vs terminal skip), and stopping the regrowth; and restores confidence in the Learning Loop schedule (no sync_runs row in today's window) with a manual run plus a one-time mock scheduled run 2 days out that proves the trigger path fires. One fixed step list, each step with a checkable done-rule, retry caps, and a Loop Training Mode toggle. Use when the user says "fix the two reds", "sort the folk holds", "clear the missing_held backlog", "the learning loop didn't run", or "/folk-holds-learning-loop-fix".
---

# Folk Holds + Learning Loop Fix

The 2026-07-16 daily health check raised two reds. **Red 1 — Folk self-heal:** `folk_ledger` (Supabase `fnykldftbkrccihdjayl`) holds ~49 distinct leads with verdict `missing_held`, every row reasoned `"Not in Folk; client campaign - held for approved processing."` The health check expects only Byteplus / Olivia Duncan / PushGroup / WantMoreLeads held — **zero of the 49 are those names**, and the distinct-per-day count climbs steadily (24→25→27→29→30→42→45). The backlog grows because the watchdog's not-in-Folk branch keeps holding new client-campaign leads while nobody triages them. **Red 2 — Learning Loop:** no `sync_runs` row existed for today at 08:37 UTC. The task `learning-loop-daily` IS enabled (cron 06:31 local) but scheduled tasks only fire while the app is open — the app was closed overnight and every task back-ran at ~08:32–08:36 UTC on launch, so the miss is an app-closed gap, not a broken task.

This loop shares the full held list with Bjion, executes his ruling on every one of them, stops the regrowth, gets today's Learning Loop row written, and schedules a mock run 2 days out to prove the trigger path. Static loop — fixed steps, each has a done-rule, Training Mode controls the pauses.

**Model routing (house convention):** judgment — triage proposals, pass/fail against done-rules, Bjion-ruling interpretation — runs on the orchestrating session (Fable 5). Execution — SQL, Make/Folk API calls, scheduled-task edits — runs on Sonnet 5 subagents (`model: sonnet`).

---

## ⚙ Loop Training Mode: **ON**   ← flip this ONE line to OFF to run autonomously

**ON (default):** pause at EVERY step boundary and wait for the user's explicit approval before continuing. Before starting a step, check its done-rule first — if it already passes, report "Step N already passes, skipping" and move on. Only re-run steps whose done-rule fails. Show what you're about to do before doing it.

**OFF:** run all steps end-to-end with no pauses. The done-rule checks, skip-if-passing behaviour, and retry caps stay exactly the same — only the pauses go.

**Retry cap (both modes):** each step retries **max 3** times against its done-rule. On cap-hit: record the step FAILED with the reason, continue to the next step if it doesn't depend on the failed one, and surface every FAILED step in the final report. Never silently exceed the cap. Never declare the skill done on a cap-hit.

---

## Safety gates (both modes, non-negotiable)

- **No lead is ever emailed by this loop.** Sorting a hold means Folk/ledger bookkeeping only — no Smartlead send, no subsequence push, no Setter action.
- **The 2 permanently-skipped leads stay skipped:** `cael@mugsy.com` (soft-no) and `dr.francescopensato@gmail.com` (off-ICP) must NEVER be added to Folk or any portal, whatever list they appear on (ruling 11 Jul 2026).
- **Bjion's ruling is the only authority on the sort.** No lead gets repushed to Folk without his explicit per-lead or per-bucket approval (Step 2). Propose defaults; never self-approve. A question is not authorization.
- **Never delete folk_ledger history.** A sorted lead gets a NEW terminal verdict row (`missing_repushed`, `verified`, or a skip verdict) — existing rows stay for audit. Sole exception: the one junk row with a blank email may be deleted after Bjion confirms.
- **Make scenarios are patched only if reachable.** Recent Make-API patches have been blocked on stored-token issues (Asteri 9187631 precedent). If the watchdog scenario can't be modified, do the sort via direct Folk API / SQL and report the scenario untouched — never half-patch.
- **The Learning Loop stays record-only.** The manual run and the mock run record data; they never apply campaign changes.
- **Mock run must be verifiable, not just scheduled.** It writes its own proof (a `sync_runs` row or Slack post) when it fires; creating the task is not the same as proving the path.

---

## THE DONE-RULE (single source of truth — the brief's verification bar)

> **(1) All held leads sorted:** the full missing_held list was shared with Bjion, and after execution a fresh SQL count shows **0 distinct emails with a live `missing_held` as their latest verdict** — every one of the ~49 carries a terminal verdict (repushed/verified/skipped) as its most recent row. Health-check query #5 re-run passes.
> **(2) Regrowth stopped:** the standing rule Bjion approves in Step 2 is implemented, so tomorrow's health check does not open with fresh unexplained holds (or, if he rules the holds intended, the health-check expectation is updated so the check grades correctly).
> **(3) Manual Learning Loop run done:** `sync_runs` has a `learning-daily` row for today with `status='success'` and `rows_written > 0`, and no new red `ll_alerts`.
> **(4) Mock scheduled run exists:** a one-time scheduled task with `fireAt` 2 days from run date (~2026-07-18 09:00 UK) is visible in `list_scheduled_tasks` with the correct `nextRunAt`, and its prompt makes it write self-proving output (sync_runs row + Slack line) when it fires.

**All 4, or it isn't done.** On any cap-hit, report the gap honestly — never declare done.

---

## STATE 2026-07-16 ~09:20 UTC — most of this loop was executed interactively the same morning

- **Steps 1–3 DONE.** Mechanism found: `folk_failsafe_queue` is a **VIEW** over `replies` (positives since 2026-03-10, LIMIT 10 alphabetical, one row per email) excluding leads with a terminal ledger verdict; `missing_held` was not terminal, hence the daily re-hold churn. Bjion's ruling: the whole held list is never meant to be in Folk/any CRM → dismissed permanently. Shipped: migration `folk_ledger_allow_dismissed_verdict` (CHECK now allows `dismissed`), migration `folk_failsafe_queue_dismissed_terminal` (view treats `dismissed` as terminal), 49 `dismissed` rows inserted (ledger ids 1090–1138, incl. the blank-email junk row). Verified: 0 unsorted holds, 0 dismissed emails in the view.
- **Step 4 PARTIAL.** Dismissed leads can never resurface (view excludes them). Health-check check #5 rewritten (grade by campaign→client join; unsorted = missing_held with no terminal verdict). OPEN: watchdog branch "Missing + client campaign" (module 13, scenario 9507769) still writes `missing_held` for NEW not-in-Folk client-campaign leads — standing rule (auto-dismiss vs keep-hold-and-ask) awaiting Bjion.
- **Step 5 SKIPPED-passing.** learning-daily success 2026-07-16 08:41 UTC, 311 rows (app-launch catch-up; the "missing" row was an app-closed-overnight gap, not a fault).
- **Step 6 DONE.** One-time task `learning-loop-mock-proof` created, fireAt 2026-07-18 ~09:00 UK, self-proving Slack post, auto-disables.
- Remaining if re-run: Step 4's standing rule once ruled, and Step 7's closing Slack thread reply.

## Ground truth (verified 2026-07-16 ~08:45 UTC — RE-VERIFY in Step 1, counts drift daily)

- **The held list:** 49 distinct emails + 1 junk row with blank email/campaign (folk_ledger id to be confirmed in Step 1). First-held dates span 07-10 → 07-16; hold_rows per lead 1–9 (the watchdog re-holds daily, so rows ≫ leads). Campaign ids seen: 2973668, 2986697, 2990194, 2994653, 2999138, 3022882, 3084240, 3104027, 3278380, 3506961, 3642625 — map each to its client in Step 1 (Smartlead `get_campaigns` or the Supabase `campaigns` table).
- **Every hold has the identical detail:** `"Not in Folk; client campaign - held for approved processing."` — one branch, one cause. The 4 "expected" names (Byteplus, Olivia Duncan, PushGroup, WantMoreLeads) have **zero** rows in the last 30 days; that expectation is stale (recorded in memory `signals-health-check-baselines`).
- **Folk machinery:** watchdog = Make scenario **9507769** (healthy as of 11 Jul). Ledger verdicts in use: `verified`, `client_healed`, `missing_repushed`, `missing_held`. The repush path exists (4 `missing_repushed` in the last 24h) — Step 1 confirms exactly how it's invoked (watchdog branch vs direct Folk API) before Step 3 reuses it.
- **Open context:** the Make↔Notion per-DB re-share (folk-selfheal handoff Item 1) is still open; `notion-portal-selfheal` (every 3h) covers the portals meanwhile. The holds are RELATED but separate — do not conflate sorting the ledger with the Notion re-share.
- **Learning Loop:** task `learning-loop-daily`, cron `30 6 * * *` local, **enabled**, `lastRunAt 2026-07-16T08:34Z` (app-launch catch-up — may already have written today's row by the time this loop runs; Step 5's done-rule check will catch that and skip). Yesterday's run failed first on a missing Smartlead MCP connection and succeeded on retry — check MCP connectivity before any manual run. Normal landing window when the app is open: ~06:47–07:55 UTC.
- **Reporting:** Slack `#inbox-management` = `C07TTLZKU56`; today's health-check post is at p1784191172824849 (thread replies there).
- **Health-check queries to re-run for the bar:** #5 = distinct `missing_held` in 24h vs expected set; #9 = `sync_runs` row today + `ll_alerts` 24h.

---

## Steps

### Step 1 — Re-verify ground truth + build the triage table
Sonnet execution agent: pull the fresh distinct `missing_held` list (latest-verdict-per-email, not raw rows) with first-held date, hold-row count, campaign id; map every campaign id → client name; identify the junk blank-email row's ledger id. Confirm the repush mechanism (read watchdog scenario 9507769's branches via Make MCP; if unreachable, locate the direct Folk API path the self-heal uses). Check whether today's `learning-daily` sync_runs row has landed since 08:37 (the catch-up run may have finished). Confirm Smartlead MCP is connected.
- **Done-rule:** (a) triage table built — one row per distinct email with campaign + client + first-held + hold-rows; (b) count stated and reconciled against the ~49 baseline; (c) repush mechanism named with evidence (scenario branch or API endpoint); (d) junk row id captured; (e) today's sync_runs state recorded; (f) Smartlead MCP state recorded.

### Step 2 — Share the list + capture Bjion's rulings
Present the FULL triage table to Bjion in chat (grouped by client, so he can rule per-bucket) AND post it as a thread reply under today's health-check Slack post so it's captured. Propose a default per bucket — e.g. "positive client-campaign leads → repush to Folk" — plus the standing rule for future holds (auto-repush this branch / keep holding but alert / other). Explicitly list the 2 banned leads as excluded if present. Wait for his ruling on: (i) each bucket/lead, (ii) the junk row deletion, (iii) the standing rule.
- **Done-rule:** list demonstrably shared (chat + Slack thread link), and an explicit ruling recorded for every distinct email (bucket-level rulings count), the junk row, and the standing rule. No ruling = the step is NOT done; on retry-cap in a headless run, mark FAILED-awaiting-ruling and stop the Folk half (Steps 3–4 depend on it) — never self-approve.

### Step 3 — Execute the sort
For every repush-ruled lead: invoke the confirmed repush path so the lead lands in Folk, then write the terminal ledger verdict (`missing_repushed`, flipping to `verified` when the watchdog confirms). For every skip-ruled lead: write the terminal skip verdict Bjion approved. Delete the junk row if ruled. Never touch the 2 banned leads. Batch with care — verify after each batch, don't fire-and-forget 49 calls.
- **Done-rule:** fresh SQL — for each email on the triage table, the LATEST folk_ledger verdict is terminal per Bjion's ruling; 0 emails still latest-verdict `missing_held`; spot-check ≥3 repushed leads actually exist in Folk (API read-back, not just our own write).

### Step 4 — Stop the regrowth
Implement the standing rule from Step 2 so tomorrow doesn't reopen the red: either (a) patch watchdog 9507769's not-in-Folk branch per the rule (only if Make access works — see safety gate), or (b) if holds remain intended, update the `signals-daily-health-check` task file's check #5 expectation (via update_scheduled_task) + the `signals-health-check-baselines` memory so the check grades the approved behaviour ✅ instead of red.
- **Done-rule:** the chosen mechanism is live and shown (scenario module diff, or updated task prompt text), and a dry re-run of health-check query #5 against the post-sort ledger grades ✅ under the new expectation.

### Step 5 — Manual Learning Loop run (skip if the catch-up already landed it)
If Step 1 found today's `learning-daily` success row: skip. Otherwise run the daily pipeline manually (the `navreo-learning-loop` skill's daily stages), watching for the Smartlead MCP dependency that broke yesterday's first attempt.
- **Done-rule:** `sync_runs` has a `learning-daily` row for today, `status='success'`, `rows_written > 0`; no new red `ll_alerts` in the last hour.

### Step 6 — Mock scheduled run, 2 days out
Create a ONE-TIME scheduled task (`fireAt` ≈ 2026-07-18T09:00 +01:00, i.e. 2 days from run date, mid-morning so the app is likely open) named like `learning-loop-mock-proof`. Its prompt: run the learning-loop daily pipeline (record-only), then post one line to #inbox-management stating the sync_runs row id it wrote — self-proving. Note in the prompt that it auto-disables after firing.
- **Done-rule:** `list_scheduled_tasks` shows the task with the correct `fireAt`/`nextRunAt` ~2 days out and `enabled`; its prompt contains the self-proof requirement. (Its actual firing is verified when it fires — by design outside this loop's sitting.)

### Step 7 — The 4-check bar + closing report
Re-run health-check queries #5 and #9 against live data; walk THE DONE-RULE checks (1)–(4); post the outcome as a thread reply under today's health-check Slack post (sorted count, per-verdict tallies, standing rule chosen, sync_runs row id, mock task fireAt).
- **Done-rule:** all 4 checks pass with numbers recorded and the Slack thread reply posted. Any FAILED step surfaced honestly.

---

## Final report (always, both modes)

One summary: per-step PASS / SKIPPED / FAILED with retry counts; the real numbers — held count before→after, per-verdict tallies (repushed / skipped / junk-deleted), Folk read-back spot-check results, the standing rule chosen and where it now lives, today's `sync_runs` row id + rows_written, the mock task id + fireAt; artifacts — Slack thread links, SQL snippets, scenario/task diffs; anything deferred or FAILED, stated plainly. Never report done while any of the 4 checks fails.

## Hard don'ts

- Never email, enroll, or Setter-touch any lead in this loop — ledger and Folk bookkeeping only.
- Never add `cael@mugsy.com` or `dr.francescopensato@gmail.com` to Folk or any portal, under any ruling ambiguity.
- Never repush or skip a lead without Bjion's explicit ruling; never treat silence or a question as approval.
- Never delete folk_ledger history (sole exception: the blank-email junk row, after his confirmation).
- Never half-patch the Make watchdog — if the API/token blocks the edit, leave the scenario untouched and route around it, reporting so.
- Never mark check (4) passed on task creation alone without the self-proof requirement in its prompt.
- Never exceed a retry cap, and never report done while any of the 4 checks fails.
