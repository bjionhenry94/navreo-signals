---
name: setter-uncategorised-intake
description: Static orchestration skill that overhauls uncategorised-reply handling end to end. Reroutes the "Categoriser lookup FAILED ... NOT auto-categorised" Slack alert out of the interested-replies channel (C096Q9LHQGZ) into #inbox-management (C07TTLZKU56), pulls uncategorised replies into the Appointment Setter inbox clearly labelled UNCATEGORISED with no auto-draft, and adds a recategorise dropdown fed live from Smartlead lead categories. Pick a CORE_FOUR category and the item converts to the normal setter flow; pick anything else and it is discarded from the tool; every choice is written back to Smartlead as the authoritative manual category. Includes late-category auto-resolve, a mock-data trial on the live host, and a simulated appointment-setter panel that must score the after-flow 9/10 or higher. Loop Training Mode ON by default. Use when the user says "run the setter uncategorised intake", "fix uncategorised replies", "stop the categoriser alerts in the interested channel", "uncategorised leads should reach the setter", or "/setter-uncategorised-intake".
---

# Setter Uncategorised Intake

When the auto-categoriser fails on a reply (rate limit, timeout, AI gave up), two bad things happen today: a "please categorise manually" alert fires into the interested-replies Slack channel where it is noise, and the reply itself never enters the Appointment Setter, so a hidden positive dies silently. Roughly 44 replies per 30 days sit uncategorised (2,763 all time). This skill moves the alert to #inbox-management and makes uncategorised replies first-class citizens of the setter: visible, labelled, one dropdown away from being rescued or discarded.

## Loop Training Mode

```
LOOP_TRAINING_MODE: OFF    <- flipped by Bjion 2026-07-20; ON pauses at every step for approval
```

- **When ON**: pause at every step and wait for Bjion's approval before continuing. At each step, evaluate the done-rule FIRST: if it already passes, log SKIP and move on without asking. Only re-run steps that fail. Retries are capped so the loop can never run forever.
- **When OFF**: run autonomously with no pauses, but keep every done-rule check and the retry cap exactly as written.
- **Retry cap**: 3 attempts per step. Panel (Step 7): max 3 rounds. On hitting a cap, halt, write a blocker report to the evidence folder, and surface it to Bjion. Never push past a failing gate.

## Goal

Better handling of uncategorised leads:
1. The categoriser-failure alert posts in #inbox-management (C07TTLZKU56), never in the interested-replies channel (C096Q9LHQGZ).
2. Uncategorised replies still enter the Appointment Setter, clearly labelled UNCATEGORISED, with no auto-draft until a human decides.
3. A dropdown on the item (options pulled live from Smartlead) recategorises it: CORE_FOUR category = treated as positive and converted to the normal flow; anything else = discarded from the tool. Either way the category is written back to Smartlead.

## Overall done-rule

All step done-rules green, the live mock-data trial passed on every leg, the simulated appointment-setter panel scores the after-flow >= 9/10 (avg, no individual below 8), the full test suite is green at or above its pre-change count, and zero test residue remains in Slack, Supabase, or Smartlead.

## Ground truth (recon 2026-07-20)

- **Channels**: interested replies = `C096Q9LHQGZ`. Inbox management = `C07TTLZKU56` (private; already the home of the pipeline's other ops alerts: Folk-fail and HeyReach-fail messages from scenario 8946472 post there).
- **The alert**: "⚠️ Categoriser lookup FAILED (HTTP 429) - reply was NOT auto-categorised, please categorise manually." plus Lead Email / Campaign ID / Time of Reply / Reply body. Example: the message Bjion linked in the brief (C096Q9LHQGZ, ts 1784567547.890389, lead kaveh@riseopp.com, campaign 3322612).
- **Alert source**: NOT in app code (zero hits for the channel ID in `~/navreo-signals`) and NOT in the local 8946472 backups. Prime suspect: the Make reply-categoriser scenario **9251436** (sibling **9187631**, Asteri org, may be unreachable pending token: if so, list it in the blocker report, do not silently skip). Locate by pulling live blueprints and finding Slack module(s) whose text contains "NOT auto-categorised".
- **False-alarm nuance**: the kaveh example above was stamped `positive-re-reply` by ingest the same day even though the Make lookup 429'd. Alerts can fire for replies that DID get categorised downstream, and late categorisation via reply-sync is normal. This is why Step 1 includes late-category auto-resolve.
- **Setter code** (`~/navreo-signals/app/setter.py`, deployed on Render at `https://navreo-signals.onrender.com`):
  - `CORE_FOUR` at line ~82 = `{"Interested", "Information Request", "Meeting Request", "positive-re-reply"}`; `CORE_FOUR_CATEGORY_FILTER` at ~90.
  - Supabase poll pulls `replies` with that category filter at ~3290-3294; client-side category guards at ~2394, ~3322, ~3456; Smartlead-webhook positive-only intake gate (`payload["lead_category"]`, ruling 2026-07-14) at ~3437; `setter_backfill.py` mirrors the gate at ~162.
  - Line numbers are as of recon day: re-grep before editing, never trust them blind.
- **Data**: Supabase `replies` (project fnykldftbkrccihdjayl) columns: id, workspace, smartlead_campaign_id, client_id, email, person_id, replied_at, category, reply_subject, reply_body, smartlead_message_id, raw. Uncategorised = category IS NULL, empty/whitespace, or the legacy literal `Uncategorizable by Ai`.
- **Smartlead**: category list via `GET /api/v1/leads/fetch-categories` (MCP mirror: `get_lead_categories`); write-back via the lead-category update endpoint (MCP mirror: `update_lead_category`). The categoriser blueprint pulled in Step 0 contains the exact working update call: copy that, do not guess.
- **App auth for API/browser checks**: `navreo_session` cookie recipe documented in the `lilly-appointment-setter` skill (Ground truth section).
- **Test baseline**: `app/test_setter.py` has ~223 tests; the whole suite is ~1003. Record the exact pre-change counts in Step 0 and treat them as the floor.

## Scope rulings (pre-agreed, do not relitigate)

- Additive, never replace: only the categoriser-failure alert changes channel. Positive-reply cards and everything else in the interested channel stay untouched.
- Positive set = CORE_FOUR membership exactly. No new list.
- Dropdown options come live from Smartlead fetch-categories (server-side cache <= 1h). Never hardcode the list. Show all Smartlead categories.
- A manual dropdown choice is authoritative: stamp `category_source = "manual"` (in the queue row and replies.raw), write it to Smartlead and Supabase, and nothing automated may ever overwrite it (house law: manual triage tags are authoritative).
- Uncategorised items get NO auto-draft and NO agent run until converted.
- Intake scope mirrors existing CORE_FOUR intake exactly (same campaigns-with-agents scoping, same lookback window, same paths: poll + webhook + backfill helpers). Go-forward only; a bounded 7-day historical backfill (~10 items) is OFFERED to Bjion in Step 8, never auto-run.
- Discard = removed from the setter inbox using the EXISTING status machinery (reuse the dismissed/needs-review vocabulary; building a parallel state store fails the step). The Supabase replies row is never deleted.
- Late-category auto-resolve: on each poll, any queued uncategorised item whose replies row now has a category (and no manual stamp) auto-resolves: CORE_FOUR converts to normal flow, anything else is discarded, both logged.
- Recategorise actions are recorded platform-side (the Supabase-recording check): the stamp plus an entry the Learning Loop could later read.

## Steps

### Step 0 - Preflight and BEFORE evidence
**Do**: Create evidence folder `runs/setter-uncategorised-intake-<date>/`. Check `git -C ~/navreo-signals status` for parallel-session WIP (untracked protos are fine; modified tracked files are not: stop and ask). Run the full test suite, record exact green counts. Pull and save the live blueprint(s) of scenario 9251436 (and 9187631 if reachable) to `scenario-backups/` as rollback copies, and extract from them: the Slack alert module id(s) and the working Smartlead category-update call. Capture BEFORE pack: permalink of Bjion's example alert, SQL counts of uncategorised replies (all-time and last-30d), screenshot of the live setter inbox showing zero uncategorised items.
**Done-rule**: evidence folder holds the BEFORE pack + blueprint backups + recorded suite counts; repo has no modified tracked files; the alert module and category-update call are identified with the blueprint JSON as proof.
**On fail**: if the categoriser scenario cannot be reached via the Make MCP, halt this step and surface which org/token is missing; the app steps (1-4) may still proceed with approval.

### Step 1 - Uncategorised intake into the setter (code)
**Do**: In `setter.py`: extend the poll with a second pull for uncategorised rows (NULL, empty, `Uncategorizable by Ai`) over the same window and scope; queue them with the uncategorised flag, reusing existing status machinery; teach every category guard (~2394, ~3322, ~3456) and the webhook gate (~3437) the uncategorised branch so those replies queue instead of being dropped; mirror in `setter_backfill.py`. No draft generation for uncategorised items. Add late-category auto-resolve on poll. New/changed POST or PATCH handlers read `self._post_body` (LAW: never rfile.read).
**Done-rule**: new tests prove: uncategorised reply queues with the flag via poll AND via webhook path; no draft is generated; late-category auto-resolve converts (CORE_FOUR) and discards (non-CORE_FOUR) correctly; a manually-stamped item is never auto-resolved. Suite green at or above baseline. Tests call `settle_background_reads()` before asserting fake-Smartlead calls.
**On fail**: fix and re-run failing tests only, max 3 attempts.

### Step 2 - Recategorise dropdown wired to Smartlead (code + UI)
**Do**: Add `GET /api/setter/categories` proxying Smartlead fetch-categories (cached <= 1h). Add `POST /api/setter/replies/recategorise` {reply_id, category}: writes the category to Smartlead using the exact call lifted from the categoriser blueprint, updates Supabase `replies.category`, stamps `category_source = "manual"`, then converts (CORE_FOUR: item enters the normal flow and drafting kicks in exactly as if the categoriser had set it) or discards (everything else: removed from inbox, audit-logged). In `setter.html`: UNCATEGORISED label chip on list rows and in the conversation pane, dropdown in both places on uncategorised items only, and a stable URL/filter view that shows only uncategorised items (the alert will deep-link to it). No em-dashes in any UI copy.
**Done-rule**: tests prove both paths end to end against the Smartlead fake, including the write-back call being recorded and the convert path producing a draft; an integration check asserts the dropdown options equal the live Smartlead category list; suite green at or above baseline.
**On fail**: fix and re-run failing tests only, max 3 attempts.

### Step 3 - Full suite gate
**Do**: Run the entire test suite (not just setter files).
**Done-rule**: everything green, total count >= Step 0 baseline plus the new tests.
**On fail**: fix, re-run, max 3 attempts.

### Step 4 - Deploy and live smoke
**Do**: Commit and push `~/navreo-signals` (Render deploy). Verify the live host actually serves the new code (iCloud/parallel-session reverts are real: check a fingerprint of the changed code on the live host, re-push if reverted). Confirm clean boot (boot ledger / no error spike in Render logs). No edge-function redeploy is planned; if one somehow becomes necessary, remember deploys reset `verify_jwt` and it must be restored.
**Done-rule**: live host serves the new build (fingerprint match), boots clean, and `GET /api/setter/categories` returns the Smartlead list live.
**On fail**: re-deploy or roll back to the previous commit, max 3 attempts.

### Step 5 - Reroute the alert (Make)
**Do**: In scenario 9251436 (and 9187631 if reachable): flip the categoriser-failure Slack module channel from `C096Q9LHQGZ` to `C07TTLZKU56`, and append one line to the alert text linking the setter's uncategorised view ("Triage it in the Setter: <url from Step 2>"). Touch nothing else in the blueprint. Backups from Step 0 are the rollback. Then test-fire the failure branch (Run once with a replayed/mock bundle).
**Done-rule**: test alert visible in #inbox-management (capture the permalink); zero new messages in the interested channel; the blueprint diff shows only the channel + text-line change.
**On fail**: restore the Step 0 backup blueprint, max 3 attempts. Unreachable sibling scenario goes in the blocker report, not silently skipped.

### Step 6 - Mock-data trial (live host)
**Do**: Run every leg and save evidence (screenshots, permalinks, SQL reads) to the evidence folder:
1. **Alert leg**: Step 5's test-fire evidence counts (re-fire if stale).
2. **Intake + label leg**: insert ONE mock reply row into Supabase (workspace `navreo`, a real agent-assigned campaign id, email like `setter-test-uncat@navreo-test.invalid`, category NULL, body marked TEST, fake `smartlead_message_id` prefixed TEST-). Confirm it appears in the live setter inbox labelled UNCATEGORISED with no draft. Delete the row and its queue item afterwards.
3. **Dropdown leg**: live dropdown options match Smartlead's fetch-categories exactly.
4. **Convert leg**: pick a REAL uncategorised reply (there are ~44 recent; choose at the pause, with Bjion when training mode is ON) whose content is clearly positive; recategorise via the dropdown to the true CORE_FOUR category; confirm it converts, drafting starts, and Smartlead now shows that category on the real lead.
5. **Discard leg**: same with a clearly non-positive real uncategorised reply (e.g. an obvious OOO); confirm it leaves the inbox and Smartlead shows the category.
Mock rows cover UI legs; REAL replies cover the Smartlead write-back legs, because a fake lead can never prove a real write-back (the fake-lead write path is already proven in Steps 1-2 tests).
**Done-rule**: all five legs evidenced from the live rendered UI (browser evidence is the only done-evidence for UI); no TEST residue left anywhere.
**On fail**: diagnose, fix (re-running the smallest failing earlier step), re-trial only the failed legs, max 3 attempts.

### Step 7 - Appointment-setter panel, 9/10 gate
**Do**: Convene 5 simulated appointment setters (personas: people who work this inbox daily and are graded on booked calls). Show each the BEFORE pack (Step 0) and the AFTER pack (Step 6). Each scores the after-flow /10 on: nothing gets lost, label clarity, speed to triage an uncategorised reply, trust in the alert channel, and category fidelity with Smartlead. Collect verbatim objections.
**Done-rule**: average >= 9.0 AND no individual score < 8. Verdicts and quotes saved to the evidence folder.
**On fail**: turn objections into fixes, re-run only the affected steps (respecting their caps), re-panel. Max 3 panel rounds, then halt with the blocker report.

### Step 8 - Wrap
**Do**: Final report to Bjion in chat, plain English: what changed, the two channels, how the dropdown works, panel score, links to evidence. Offer (never auto-run) the bounded 7-day backfill of historical uncategorised replies. Update memory (ship record + any new gotchas). Confirm suite green one last time.
**Done-rule**: report delivered; memory written; suite green; no open blockers except any explicitly listed (e.g. Asteri scenario token).
**On fail**: n/a (reporting step; if something upstream broke, the loop re-enters the failing step instead).

## Laws (do not break, ever)

- POST/PATCH handlers read `self._post_body`, never `rfile.read`.
- Tests call `settle_background_reads()` before asserting fake calls or seeded GETs.
- Manual categories are authoritative; automation never re-tags them.
- Additive, never replace; confirm any removal with Bjion first.
- No em-dashes in UI copy, alert text, or anything the agent might quote.
- Blueprint edits only after a saved rollback backup in `scenario-backups/`.
- Never touch autopilot settings, agent instructions, or the positive-card modules.

## Execution notes

- Fable orchestrates; delegate mechanical execution (test runs, greps, bulk edits) to Sonnet subagents.
- Evidence folder: `runs/setter-uncategorised-intake-<date>/` in the Navreo working directory.
- Live line numbers drift: re-grep every anchor before editing.
