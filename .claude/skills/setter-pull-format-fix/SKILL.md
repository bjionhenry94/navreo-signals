---
name: setter-pull-format-fix
description: Static orchestration skill that fixes two proven Appointment Setter defects — the poll that always logs checked=0/queued=0 while eligible CORE_FOUR replies sit unqueued (prime suspect: the replies GET returning a non-list on the deployed host, error swallowed) plus the agent-save that bulk re-stamps campaign_assigned_at and silently disqualifies earlier replies; and the raw Gmail/Outlook HTML that renders as literal <html> tags in the inbox list preview and conversation pane (fix at render time only by porting clean_body() into the frontend, never rewriting the DB). One fixed step list, each step with a checkable done-rule, retry caps, and a Loop Training Mode toggle. Use when the user says "run the setter pull+format fix", "fix the setter poll", "the setter isn't pulling replies", "the setter shows raw HTML", or "/setter-pull-format-fix".
---

# Setter Pull + Format Fix

The Appointment Setter (`app/setter.py`, `app/setter.html`, `app/server.py`; live at navreo-signals.onrender.com; Supabase `fnykldftbkrccihdjayl`) has two proven defects. **Defect 1 — pull failure:** `/api/setter/poll` runs every ~5 min and on manual "Check for new replies" but always logs `setter_poll_done` with `checked=0/queued=0` while eligible replies sit in the 48h window (verified 2026-07-14: 21 CORE_FOUR replies, incl. `daniel@leadhq.io`/campaign 3509012, Information Request, replied 08:32 UTC — passes every gate in `run_poll` yet never queued). Prime suspect: the replies GET (~setter.py:2136) silently returns a non-list on the deployed host, the error is swallowed, and an all-zero summary is returned. A verified secondary leak: saving/editing an agent bulk re-stamps `campaign_assigned_at` (Amplifyy agent-70fd17e5 had all 30 campaigns re-stamped 2026-07-14T12:05:01), disqualifying earlier replies. **Defect 2 — formatting:** raw Gmail/Outlook HTML documents are stored verbatim in `setter_queue.reply_body` and `thread[].body` (~setter.py:1864, :1210) and the frontend escapes them into literal `<html><head>…` text in the list preview and conversation pane (`convoMsgHtml`, ~setter.html:1062).

This loop diagnoses on the LIVE host first, fixes both defects at the correct layer, intakes the missed 48h backlog **as needs_review only**, and proves everything with six independent checks that never trust the app's own success labels. Static loop — fixed steps, each has a done-rule, Training Mode controls the pauses.

**Model routing (house convention):** judgment — diagnosis calls, pass/fail against done-rules, backlog eligibility, render-clean verdicts — runs on the orchestrating session (Fable 5 / default-model subagents). Execution — code edits, SQL reads, deploy mechanics, browser verification — runs on Sonnet 5 subagents (`model: sonnet`). The product's own runtime LLM is untouched.

---

## ⚙ Loop Training Mode: **OFF**   ← running autonomously. Flip this ONE line to ON to pause at every step

**ON (default):** pause at EVERY step boundary and wait for the user's explicit approval before continuing. Before starting a step, check its done-rule first — if it already passes, report "Step N already passes, skipping" and move on. Only re-run steps whose done-rule fails. Show what you're about to do before doing it.

**OFF:** run all steps end-to-end with no pauses. The done-rule checks, skip-if-passing behaviour, and retry caps stay exactly the same — only the pauses go.

**Retry cap (both modes):** each step retries **max 3** times against its done-rule. On cap-hit: record the step FAILED with the reason, continue to the next step if it doesn't depend on the failed one, and surface every FAILED step in the final report. Never silently exceed the cap. Never declare the skill done on a cap-hit.

---

## Safety gates (both modes, non-negotiable)

- **No sends, ever.** No email reaches any lead during this loop. Every intaken reply lands as `needs_review` only — no auto-send path fires. **Autopilot and the master switch stay untouched** (never read-modify-write them; confirm unchanged in Step 8).
- **Never rewrite the database bodies.** `reply_body` and `thread[]` keep raw fidelity — Defect 2 is fixed at RENDER time only. No UPDATE/PATCH to those columns.
- **Backlog is last-48h CORE_FOUR only.** Do not intake anything older than 48h from now, and only CORE_FOUR intents. Every intaken row = `needs_review`.
- **Uncovered campaigns are surface-only.** Campaigns with 48h CORE_FOUR replies and no enabled agent (e.g. 3576107, 7 missed positives, no agent) get REPORTED. Never auto-assign an agent, never intake their replies.
- **schema-freeze law:** `setter_queue` PATCHes die silently if the row-dict carries any key without a matching column. Any new field → add the column first, or the whole write fails and rows stay `new`. Verify column existence before writing.
- **Smartlead can return 200 with `ok:false`** — never trust the HTTP status alone; parse the body.
- **The drafter's own `draft_body` is intentionally HTML** — it must keep rendering as HTML. The render-clean logic applies to `reply_body` / thread bodies ONLY, not to drafts.
- **Deploy = push to the deploy repo, then verify on navreo-signals.onrender.com.** A grep of a local file is NEVER done-evidence. The iCloud working copy is NOT the deploy repo and iCloud can revert edits — re-verify every line number (they drift).

---

## THE DONE-RULE (single source of truth — the 6-check bar)

None of these trust the app's own success labels.

> **(1) Pull works:** POST `/api/setter/poll` on navreo-signals.onrender.com, then read `app_activity_log` directly — `setter_poll_done` shows `checked>0`, AND the verified missed replies still in-window (e.g. `daniel@leadhq.io`/3509012) exist as `needs_review` rows read back from `setter_queue` via SQL (not the UI).
> **(2) Formatting fixed:** live-browser proof on navreo-signals.onrender.com — for a row whose stored `reply_body` is a full HTML document, the inbox list preview AND the conversation pane render readable sentences with zero visible tags or entities; screenshot taken (rendered page is the only done-evidence for UI).
> **(3) No re-stamp leak:** edit-and-save an agent, then read `setter_agents.doc` back via SQL — `campaign_assigned_at` for pre-existing campaigns is unchanged to the second.
> **(4) No sends:** SQL send-gate audit — zero `setter_queue` rows gained `status='auto_sent'` or a `sent_at` timestamp during the run, and no send action appears in `app_activity_log` for the intaken rows.
> **(5) Uncovered report:** every campaign with 48h CORE_FOUR replies and no enabled agent is listed, cross-checked against the two SQL sources.
> **(6) Cleanup:** any rows created purely for verification are deleted or flagged `is_test` so the next run can't false-pass.

**All 6, or it isn't done.** On any cap-hit, report the gap honestly — never declare done.

---

## Ground truth (verified from the brief 2026-07-14 — RE-VERIFY in Step 1, line numbers drift)

- **Files:** `app/setter.py`, `app/setter.html`, `app/server.py`. Working copy = iCloud dir; **deploy repo is separate** (push there, then verify on Render). iCloud can REVERT edits — every line number below is approximate and must be re-confirmed against BOTH the local copy and the deployed host before editing.
- **Pull path:** `run_poll` (~setter.py:2117) — gates confirmed for agent-d403bbcd (enabled, assigned 2026-07-11, workspace=navreo). The replies GET (~setter.py:2136) is the prime suspect: on the deployed host it may return a non-list; the surrounding error handling swallows it and returns the all-zero summary. Diagnose ON THE LIVE HOST.
- **Re-stamp leak:** the agent save/edit path bulk-writes `campaign_assigned_at` for every campaign in the doc. Fix = preserve the original per-campaign `assigned_at` on edit; only newly-added campaigns get a fresh stamp.
- **Storage (Defect 2):** raw HTML stored verbatim at ~setter.py:1864 (`reply_body`) and ~:1210 (`thread[].body`). Frontend escapes it at `convoMsgHtml` (~setter.html:1062) and in the list preview.
- **The porting target:** `clean_body()` (~setter.py:203) — strips `<style>` blocks and tags, unescapes entities, keeps line breaks. Port THIS logic into the frontend for list previews and thread/reply bodies. Do not call the backend to clean; render-time in JS.
- **Name fallback (default, veto-able):** where `lead_first_name` is the generic fallback `"there"` or empty, display the email local-part (before the `@`) in the list AND the detail header instead.
- **CORE_FOUR + uncovered:** the CORE_FOUR intent set is whatever `run_poll` already treats as eligible (confirm the exact set in Step 1). Uncovered example: campaign 3576107 — 7 missed positives, no agent.

---

## Steps

### Step 1 — Re-verify ground truth (local vs deployed) + resolve the exact CORE_FOUR set
Sonnet execution agent: confirm every Ground-truth bullet against BOTH the local copy and the deployed host (line drift + iCloud-vs-deploy divergence). Read `run_poll`, the replies GET, the agent-save path, `clean_body()`, and the `convoMsgHtml`/list-preview render sites — record actual current line numbers. Confirm the exact CORE_FOUR intent set `run_poll` gates on. Read `agent-d403bbcd`'s doc and the `setter_queue` schema (column list) as rollback + schema-freeze reference. Snapshot, via SQL, the current `daniel@leadhq.io`/3509012 reply state and the 48h CORE_FOUR reply count.
- **Done-rule:** (a) every bullet confirmed or corrected in writing with real line numbers; (b) local-vs-deploy drift explicitly stated (same or how they differ); (c) CORE_FOUR set named; (d) `setter_queue` column list captured; (e) baseline SQL counts recorded (48h CORE_FOUR replies, and daniel/3509012 confirmed NOT yet queued).

### Step 2 — Diagnose the pull failure ON THE LIVE HOST
Reproduce `checked=0/queued=0` against navreo-signals.onrender.com (POST `/api/setter/poll`, read `app_activity_log`). Prove what the replies GET actually returns on the deployed host (shape, not the swallowed summary) — is it a non-list, an error object, an auth/empty payload? Confirm this is why `checked` stays 0 despite in-window eligible replies. Rule the prime suspect in or out with evidence.
- **Done-rule:** root cause named in one sentence with evidence from the LIVE host (the actual non-list/error payload, or the specific gate/line that drops it), OR the suspect ruled out and the true cause evidenced instead. Never diagnose from the local file alone.

### Step 3 — Fix the pull failure (backend)
Fix so the replies GET's real response is handled: when it returns a non-list/error, do NOT swallow into an all-zero summary — surface it and, on a well-formed list, iterate normally so eligible CORE_FOUR replies get queued as `needs_review`. Respect the schema-freeze law on any `setter_queue` write. No change to gate ordering or the master switch.
- **Done-rule:** unit/local proof that a well-formed replies payload now yields `checked>0` and queues an eligible CORE_FOUR reply as `needs_review`; a non-list payload surfaces an honest error instead of a false all-zero success. (Live proof is Step 6/7.)

### Step 4 — Fix the campaign_assigned_at re-stamp leak (backend)
On agent save/edit, preserve the original per-campaign `assigned_at`; only newly-added campaigns receive a fresh stamp. Removed campaigns handled sanely. Merge semantics respected so nothing else in the doc is clobbered.
- **Done-rule:** local test — load an agent doc with known per-campaign stamps, edit an unrelated field, save, reload: pre-existing `campaign_assigned_at` values are byte-identical; a genuinely new campaign gets a new stamp. (Live proof = check (3) in Step 8.)

### Step 5 — Fix the formatting at render time (frontend only)
Port the `clean_body()` logic (strip `<style>` blocks + tags, unescape entities, keep line breaks) into `setter.html` as a JS helper. Apply it to: (a) the inbox list preview, (b) the conversation pane / `convoMsgHtml` reply and thread bodies. **Do NOT apply it to `draft_body`** — drafts stay HTML. **Do NOT touch the DB** — `reply_body`/`thread[]` keep raw fidelity. Add the veto-able name fallback: where `lead_first_name` is `"there"` or empty, show the email local-part in the list and the detail header.
- **Done-rule:** local browser render of a row whose body is a full HTML document shows clean readable text with zero visible tags/entities in both preview and conversation pane; `draft_body` still renders as HTML; DB bodies unchanged (no write issued). Name fallback shows the local-part for a `"there"`/empty first name.

### Step 6 — Deploy + live-render proof
Reconcile iCloud→deploy repo, push, wait for Render live. Then verify on navreo-signals.onrender.com: (a) a unique marker present in the deployed asset (deploy check only, NOT done-evidence), (b) browser-render the inbox — list preview + conversation pane for an HTML-document row read as clean text, screenshot taken. Re-set the `navreo_session` cookie if the browser pane drops it.
- **Done-rule:** check (2) passes — live screenshot of the rendered page showing zero visible tags/entities. A grep of the deployed file alone does NOT pass this.

### Step 7 — Live pull + intake the missed 48h CORE_FOUR backlog (needs_review only)
POST `/api/setter/poll` on the live host. Read `app_activity_log`: `setter_poll_done` now shows `checked>0`. Confirm the missed in-window CORE_FOUR replies (incl. `daniel@leadhq.io`/3509012) land as `needs_review` rows in `setter_queue`, read back via SQL. Backlog scope = last 48h, CORE_FOUR only. Uncovered-campaign replies are NOT intaken.
- **Done-rule:** check (1) passes — `checked>0` in `app_activity_log` AND the named missed replies exist as `needs_review` rows read from `setter_queue` via SQL, none older than 48h, none from uncovered campaigns.

### Step 8 — The 6-check bar + uncovered report + cleanup
Run all six checks from THE DONE-RULE against PROD, reading directly from Supabase/SQL, never from the UI's success labels:
- (3) edit-and-save an agent → `campaign_assigned_at` for pre-existing campaigns unchanged to the second.
- (4) send-gate audit → zero rows gained `status='auto_sent'` or a `sent_at` during the run; no send action in `app_activity_log` for intaken rows; master switch + autopilot confirmed untouched.
- (5) produce the uncovered-campaigns report — every campaign with 48h CORE_FOUR replies and no enabled agent (e.g. 3576107), cross-checked against the two SQL sources. Surface-only; nothing auto-assigned.
- (6) delete or `is_test`-flag any verification-only rows.
- **Done-rule:** checks (1)–(6) each pass with numbers/artifacts recorded; uncovered report delivered; no verification residue left that could false-pass the next run.

---

## Final report (always, both modes)

One summary: per-step PASS / SKIPPED / FAILED with retry counts; the real numbers — live `checked`/`queued` before→after, count of 48h CORE_FOUR replies intaken as `needs_review`, the daniel/3509012 row id, re-stamp before/after timestamps, send-gate audit (0 sends confirmed), master-switch/autopilot state (untouched); the uncovered-campaigns list with per-campaign missed-reply counts; artifacts — deploy commit SHA, live screenshots, SQL snippets used, `is_test`/deleted verification rows; anything deferred or FAILED, stated plainly. Never report done while any of the 6 checks fails.

## Hard don'ts

- Never send anything to a real lead; never flip or even read-modify the master switch / autopilot. Intaken replies are `needs_review` only.
- Never rewrite `reply_body` or `thread[]` in the database — Defect 2 is render-time only; raw fidelity stays.
- Never apply the clean-body render to `draft_body` — drafts are intentionally HTML.
- Never intake anything older than 48h or outside CORE_FOUR; never auto-assign an agent to an uncovered campaign — surface it and stop.
- Never write a `setter_queue` row-dict key without a matching column (silent PATCH death); never trust a Smartlead 200 without parsing `ok`.
- Never diagnose Defect 1 from the local file — the deployed host is the source of truth; iCloud drifts and reverts.
- Never treat a grep of a local or deployed file as done-evidence for a UI fix — the rendered live page is.
- Never exceed a retry cap, and never report done while any of the 6 checks fails.
