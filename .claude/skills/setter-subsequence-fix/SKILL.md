---
name: setter-subsequence-fix
description: Static orchestration skill that makes the Appointment Setter's push-to-subsequence feature provably work END-TO-END. Live probe 2026-07-22 showed the push API itself lands (3/3 spot-checked leads enrolled) — the real defects are downstream and invisible: pushed leads that never get sent the follow-up (delivery starvation), dead follow-up tracks (DRAFTED/COMPLETED subsequences) pickable with no warning, and 'pushed' meaning only "API accepted" with no sent-check anywhere. This loop audits ALL setter-pushed rows against Smartlead ground truth (enrolled? actually SENT?), fixes what the audit proves, repairs the backlog with approval-gated re-pushes/resumes, and ships visibility so a silent non-send can't stay green. Fixed step list, per-step done-rules, retry cap 3, Loop Training Mode toggle (ON by default). Use when the user says "run the subsequence fix", "fix the setter subsequence push", "the subsequence feature isn't working", "audit the subsequence pushes", or "/setter-subsequence-fix".
---

# Setter Subsequence Fix

**Goal:** every follow-up-track push from the setter provably lands in Smartlead AND actually sends — past pushes audited one by one, defects fixed, silent failures impossible.

---

## ⚙ Loop Training Mode: **OFF**   ← THE TOGGLE. Flip this ONE word to ON to pause at every step. (Set OFF by Bjion 2026-07-22 for the first run.)

**ON (default):** pause at EVERY step and wait for Bjion's explicit approval before continuing. Before starting a step, check its done-rule first — if it already passes, report "Step N already passes, skipping" and move on. Only re-run steps whose done-rule fails. Show what you're about to do before doing it.

**OFF:** run autonomously, no pauses — but the done-rule checks, skip-if-passing behaviour, and the retry cap stay exactly the same. Only the pauses go. (Exception: the real-send gate below pauses in BOTH modes.)

**Retry cap (both modes):** each step retries **max 3** times against its done-rule. On cap-hit: record the step FAILED with the reason, continue to steps that don't depend on it, and surface every FAILED step in the final report. Never silently exceed the cap. Never declare the skill done on a cap-hit.

**Model routing (house convention):** judgment — verdicts against done-rules, defect naming, backlog eligibility — stays on the orchestrating session. Execution — API sweeps, SQL reads, code edits, deploy mechanics, browser verification — runs on Sonnet subagents (`model: sonnet`).

---

## Safety gates (both modes, non-negotiable)

- **Real-send gate — pauses in BOTH modes:** anything that can cause email to a real lead (re-pushing a lead, resuming/activating a DRAFTED/COMPLETED/PAUSED subsequence campaign, resuming a stopped lead, a fresh live proof push) is listed first, item by item, and waits for Bjion's explicit yes. No exceptions, even with Training Mode OFF.
- **Steps 1–2 are read-only.** No writes to Supabase, Smartlead, or code while auditing and diagnosing.
- **Deploy-repo law:** the ONLY source of truth is `~/navreo-signals` (git → Render auto-deploys on push to main). The iCloud `app/` copy is deprecated — proven again 2026-07-22: its setter.py is still pre-gate. Never edit it, never diagnose from it.
- **Foreign-WIP law:** at skill-write time `~/navreo-signals` had ~470 lines of UNCOMMITTED work on setter.html / setter.py / server.py / test_setter.py (a panel restyle that also touches the legacy subsequence checkbox). Never stash, reset, checkout, or clobber it. Ship via the isolated-worktree recipe: `git worktree add --detach <tmp> origin/main` → apply ONLY this fix's hunks → commit → `git push origin HEAD:main` → `git worktree remove`. In ON mode, show Bjion the WIP status before Step 3 and let him rule; the final report must warn that local WIP predates the fix and needs a rebase before its own ship.
- **Additive, never replace:** this fix adds status + visibility to the shipped P2 send-gate; it never removes or redesigns it. Anything outside the Step-3 menu = surface to Bjion first.
- **Picker stays suggestion-free (owner ruling 2026-07-17):** chips stay neutral and equal — no stars, no "recommended", no pre-highlight. Status FACTS on a chip (Active / Completed / Drafted) are allowed; recommendations are not.
- **setter_queue schema-freeze:** a row-dict key without a matching column kills the whole PATCH silently. Any new field → add the column via migration FIRST, then write.
- **server POST-body law:** any new/edited POST/PATCH route reads `self._post_body`, never `self.rfile.read()`.
- **Smartlead API laws:** 200 can carry `ok:false` — parse the body (`_push_to_subsequence` already does; keep it that way). Paginate stopping ONLY on an empty page — an error mid-page reads as end-of-list and silently truncates. Throttle ~1 req/s (200/min hard cap). Never read-modify the master switch or autopilot.
- **Tests law:** full suite `python3 -m pytest app/test_setter.py` stays green (a handful of pre-existing flaky failures identical on untouched baseline are acceptable); call `settle_background_reads()` before asserting `sb.calls` or seeded GETs.
- **Live UI evidence law:** the rendered page on navreo-signals.onrender.com is the ONLY done-evidence for UI changes (app is login-gated — mint `navreo_session` via the SRK in `~/.navreo-keys.env`, or use authed Chrome). A grep of a deployed file is a deploy check, never done-evidence.
- **Scope fence:** Slack/notification behaviour when a subsequence reply flips category belongs to `once-positive-always-notify`, not this loop. Don't double-fix it here.

---

## THE DONE-RULE (the bar for "the feature is working")

> **(1) Audited:** every `setter_queue` row with `subsequence_decision='pushed'` (`is_test=false`, all workspaces) carries an evidenced verdict — ENROLLED+SENT / ENROLLED+SCHEDULED (cause named) / ENROLLED-STALLED (cause named) / NEVER-LANDED — written to a dated audit file in `runs/`. Zero "unknown".
> **(2) Nothing silent:** every non-working row is repaired (send observed, or verifiably scheduled with the cause fixed) or explicitly SKIPPED by Bjion, row by row.
> **(3) Tool proven:** ≥1 post-fix push verified end-to-end via API reads (enrolled in the right subsequence AND sent/scheduled); dead tracks can no longer be picked silently; a push that lands but hasn't sent within 48h resurfaces in the tray instead of staying green forever.
> **(4) Shipped clean:** suite green, fix on `~/navreo-signals` main, Render live-verified with rendered-UI evidence, zero `is_test` residue.

**All four, or it isn't done.** On any cap-hit, report the gap honestly — never declare done.

---

## Ground truth (probed live 2026-07-22 — re-verify in Step 1; repo HEAD was `fef955c`, line numbers drift)

- **The push API works.** 3/3 spot-checked pushed leads ARE enrolled in the right subsequence (GET `/leads/?email=` → `lead_campaign_data`): carl@morph.ae→3322612, daan@gritgrowth.io→3576109, gabriel@silver.dev→3356263.
- **Delivery is where it dies.** carl: sub sent 21 min after push (works, lead even replied). gabriel: sent 3 days later (Fri push → Mon send — schedule window suspected, and his sub reply is the Benmergui notification miss handled by the other skill). daan: enrolled `STARTED` in an ACTIVE sub with 6 mailboxes, **zero sends ~40h later** — that sub's own stats: 7 leads = 3 notStarted / 1 stopped / 2 inprogress / 1 completed, sent_count 3. Starvation is real and bigger than one lead.
- **Dead tracks are silently pickable.** Among ledger parents: 3322674 "Meeting Request" is DRAFTED (never sends); 3576110 + 3506960 "Meeting Request" are COMPLETED (may never send). Chips carry no status; a push into them still goes green.
- **`pushed` only means "API accepted".** `_subsequence_choice_worker` (setter.py ~:4394, daemon thread after Approve) stamps `pushed` on API success; the tray reconcile (~:4318) confirms ENROLMENT only. Nothing anywhere checks a send happened. `push_failed` today: 0 rows.
- **Ledger (Supabase `setter_queue`, 2026-07-22):** 23 pushed (all `workspace='navreo'`, 0 test) / 21 none / 165 NULL / 0 push_failed. No column records WHICH sub was chosen → the audit infers it from enrolment. Superset note: the reconciler also stamps Smartlead-UI enrolments as `pushed`; audit them all the same.
- **Code sites (deploy repo `~/navreo-signals/app/setter.py`):** `_push_to_subsequence` :1297 (explicit-positive parse; sends `stop_lead_on_parent_campaign_reply: True`, delay 0); `_sl_campaign_lead_map_id` :1249 (by-email first — the 2k-paging bug is already fixed, `6b65094`); send path applies the gate choice :5231–41; legacy checkbox action :5166; opt-out :5187; row-less `route_subsequence_push` :5248 (registered :7981) — leaves NO ledger trace anywhere; chips GET :4208 (10-min cache); `_sl_find_subsequences` :4147; unresolved tray :4346 (14-day window).
- **Audit recipes (curl; `source ~/.navreo-keys.env`; per-workspace keys for any future non-navreo rows):** subs map = ONE `GET /campaigns/` (~900 rows; children carry `parent_campaign_id`); enrolment = `GET /leads/?email=` → `lead_campaign_data` ∩ subs-of-parent; sends = `GET /campaigns/{sub}/leads/{lead_id}/message-history`; lead state in sub = `GET /campaigns/{sub}/leads` paged.

---

## Steps

### Step 1 — Audit every pushed row (read-only)
Re-confirm the code sites above against current `~/navreo-signals` HEAD (note drift + WIP status). Then, for EVERY `subsequence_decision='pushed'` row (`is_test=false`): resolve the parent's subsequences from one cached `/campaigns/` map; check enrolment; for enrolled leads pull message-history in the sub and the lead's state; record the sub-campaign's status (ACTIVE/DRAFTED/COMPLETED/PAUSED). Verdict each row: ENROLLED+SENT / ENROLLED+SCHEDULED / ENROLLED-STALLED / NEVER-LANDED. Also sweep the 21 `none` rows' count and confirm `push_failed` is still 0 (a non-zero count joins the audit). Save `runs/subsequence-audit-<date>.md` (+ CSV) with one line per row: email, campaign, sub, sub-status, lead-state, last-send time, verdict.
- **Done-rule:** every pushed row has a verdict with API evidence, zero "unknown"; the audit file exists; code-site drift and WIP status stated in writing.

### Step 2 — Name the defects
Reduce the audit to named, evidence-backed defects. Expected buckets (confirm or kill each): **(A)** dead-track picks — enrolled into DRAFTED/COMPLETED/PAUSED subs; **(B)** active-but-starved — enrolled + STARTED/notStarted with no send beyond the sub's schedule window (diagnose per campaign: schedule, mailbox caps/health, lead stopped); **(C)** never-landed pushes (any row whose enrolment is absent); **(D)** visibility gap — `pushed` with no sent-check and the row-less push route leaving no trace (already proven; restate with Step-1 numbers).
- **Done-rule:** every non-working row is assigned to exactly one named defect with a one-sentence cause backed by an API-read fact; buckets with zero rows are explicitly declared dead.

### Step 3 — Fix the tool (code, isolated worktree off `~/navreo-signals` origin/main)
Fix ONLY what Step 2 proved, from this menu: **(a)** status-aware gate — chips (and the tray's Add menu) show the sub's real status; DRAFTED/COMPLETED/PAUSED tracks require an explicit "push anyway?" confirm (facts, not recommendations — chips stay neutral); **(b)** close the pushed≠sent gap — extend the existing reconcile so a `pushed` row with no send in the sub within 48h resurfaces in the tray under "Pushed but not sending (N)" with the sub's status shown (additive; existing tray sections untouched); **(c)** record the push properly — migration first: `subsequence_pushed_id` (+ pushed-at) on `setter_queue`, stamped by every push path including the legacy checkbox and the row-less route, so the next audit never has to infer; **(d)** log every push attempt (row-less route included) to `app_activity_log`; **(e)** only if Step 2 proved never-landed rows from a code bug: fix at cause in `_push_to_subsequence`/`_sl_campaign_lead_map_id`. Respect schema-freeze, POST-body, and suggestion-free laws. Add/extend tests for each shipped item.
- **Done-rule:** each shipped menu item has a unit/local test proving the new behaviour (dead track → confirm required; stale pushed row → resurfaces; push → id + activity-log row); full suite green; diff contains ONLY this fix's hunks (foreign WIP untouched).

### Step 4 — Deploy + live proof
Push the worktree commit to main; wait for Render. Live-verify on navreo-signals.onrender.com with an authed session: chips render with status facts on a campaign that has a dead sub (screenshot — rendered page is the only UI evidence); `GET /api/setter/subsequences?campaign_id=` returns the status fields; tray shows the new section when the audit says it should (daan-class rows).
- **Done-rule:** rendered-UI screenshot evidence of (a) status-aware chips and (b) the pushed-but-not-sending tray section populated with the real Step-1 stalled rows; deployed commit SHA recorded.

### Step 5 — Repair the backlog in Smartlead (real-send gate: pauses in BOTH modes)
From the Step-1 verdicts build the repair list, per row: dead-track enrolments → propose resume/activate the sub OR re-push to a live track OR skip; starved-active leads → propose the diagnosed unblock (schedule/mailbox/lead-state); never-landed rows → propose re-push. Present the full list; Bjion approves item by item (or rules a batch). Execute only approved items; re-read Smartlead after each to confirm the state changed.
- **Done-rule:** every non-working row is executed-and-confirmed or explicitly SKIPPED-by-Bjion; zero rows left undecided; nothing executed without its approval line.

### Step 6 — Re-audit + final report
Re-run the Step-1 sweep fresh (now including any post-fix pushes — require ≥1 verified end-to-end: enrolled + sent/scheduled; if none occurred organically, ask Bjion to approve one real reply through the live gate and verify it). Confirm zero `is_test` residue and autopilot/master switch untouched. Score THE DONE-RULE (1)–(4) honestly and write the final report.
- **Done-rule:** all four DONE-RULE checks pass with the fresh audit file as evidence — or the report names exactly which check fails and why.

---

## Final report (always, both modes)

One summary in plain English: per-step PASS / SKIPPED / FAILED with retry counts; the numbers — pushed rows audited, verdict breakdown before→after, backlog items repaired vs skipped, the post-fix end-to-end proof row; artifacts — audit file paths, deploy SHA, screenshots, migration name; the foreign-WIP rebase warning; anything FAILED or deferred, stated plainly. Never report done while any DONE-RULE check fails.

## Hard don'ts

- Never cause a send (re-push, resume, activate, live proof) without Bjion's item-level yes — in EITHER mode.
- Never edit the iCloud copy, never clobber the deploy repo's uncommitted WIP, never `git add -A`.
- Never remove or redesign the P2 gate, and never add recommendation affordances to the picker.
- Never write a `setter_queue` key without its column existing; never trust a Smartlead 200 without parsing the body; never stop paging on an error.
- Never treat "API accepted" or a grep as done-evidence — enrolment + send state read back from Smartlead, and rendered UI for UI.
- Never exceed a retry cap; never declare done with an unexplained row.
