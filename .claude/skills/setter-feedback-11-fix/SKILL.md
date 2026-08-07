---
name: setter-feedback-11-fix
description: Static orchestration skill that clears the eleven owner-reported defects on the Appointment Setter page (navreo-signals.onrender.com/app/setter.html) - regenerate ignoring time feedback, first-regenerate-after-agent-assign failing, non-positive leads sitting in the follow-up reminder, the reminder tray auto-opening after every send, new replies not appearing on "Check for new replies", the tray Dismiss error-and-restart, out-of-touch drafts on later replies, the duplicated "Needs review" plus dead Settings/Try-it buttons, no assign-an-agent prompt, the conversation scroll jumping, and links stripped out of earlier messages. One fixed step list, each step with a checkable done-rule, retry caps, a hard no-real-lead-action gate, and a Loop Training Mode toggle. Use when the user says "run the setter feedback fix", "fix the setter bugs", "the setter feedback list", or "/setter-feedback-11-fix".
---

# Setter: the eleven owner-reported defects, cleared and live-verified

Eleven pieces of user feedback on the Appointment Setter, collected 2026-07-25. They span
three surfaces: the drafter (`app/setter.py` `draft_reply` / `route_queue_redraft`), the
follow-up reminder tray (`route_subsequence_unresolved` / `route_queue_action`), and the
page itself (`app/setter.html`). Static loop - fixed steps, each has a done-rule, Training
Mode controls the pauses.

## Loop Training Mode: **ON**   <- flip this line to OFF to run autonomously

**ON:** pause at EVERY step boundary and wait for the user's explicit approval before
continuing. Before starting a step, check its done-rule FIRST - if it already passes,
report "Step N already passes, skipping" and move on without asking. Only re-run steps
whose done-rule fails. Say what you are about to do before you do it.

**OFF:** run all steps end to end with no pauses. The done-rule checks, the
skip-if-already-passing behaviour, and the retry caps are all unchanged - only the
pauses go.

**Retry cap (both modes):** each step retries **max 3** times against its done-rule.
On cap-hit: record the step FAILED with the reason, continue to the next step if it does
not depend on the failed one, and surface every FAILED step in the final report. Never
silently exceed the cap. Never declare the skill done on a cap-hit.

## Non-negotiable safety gate (both modes)

> **No email is ever sent to a real prospect, and no real lead or row is ever changed.**

- Every live exercise runs on **`is_test` rows only**, created via
  `POST /api/setter/test/inject` (`is_test: true`, never sends, shows in the tray).
- **Approve / send is never clicked on a real row.** Not once, in either mode.
- Never call `recategorise`, `dismiss`, `subsequence*`, or `queue/action` against a row
  where `is_test` is false. Read-only GETs against real rows are fine and are how most
  done-rules are checked.
- Smartlead writes (category writes, subsequence pushes) only ever fire from a test row,
  which short-circuits before the Smartlead call.
- Redrafts are allowed on test rows only, **max 10 across the whole run**.
- The deploy repo is `~/navreo-signals`; **push to `main` = deploy**. The iCloud copy under
  `Bjion [2023]/Navreo/Claude/Navreo` diverges and reverts edits - never edit it as the fix.

## Goal

> All eleven reported defects are gone on the LIVE host, each one verified individually in
> the live UI (rendered DOM, not curl alone), with the setter test suite still green and
> nothing sent to or changed on a real prospect.

## Ground truth (verified 2026-07-25 - re-verify in Step 1, line numbers drift)

Live source: `~/navreo-signals`, files `app/setter.py` (~443KB), `app/setter.html` (~221KB),
tests `app/test_setter.py`.

| # | Feedback | Where it lives | Root cause found |
|---|---|---|---|
| 1 | Regenerate ignores "offer different times" / "offer next week" | `setter.py` `route_queue_redraft` ~5620 (`pick_slots`), `DRAFT_SYSTEM` ~1005 | Slots are re-picked identically every redraft, and `DRAFT_SYSTEM` orders the two proposed times used "verbatim", "not optional", "does not depend on the intent" - which outranks typed feedback |
| 2 | First Regenerate after an agent is assigned fails, second works | `setter.py` `_save_agent` adoption PATCH ~1730; `setter.html` `doRedraft` ~3286 | Adoption PATCH writes `agent_id` straight through `_SB` and never calls `_bust_read_caches()`, so the queue read cache keeps serving the pre-assign row; `doRedraft` then repaints from `loadQueue()` instead of the redraft response it already holds |
| 3 | Non-positive lead category still lands in the follow-up reminder | `setter.py` `route_subsequence_unresolved` ~4563 | The tray query filters on status / `added_to_subsequence` / `subsequence_decision` only - it never looks at the lead's category |
| 4 | Every send re-opens "Sent without follow-up", even after a choice | `setter.py` `route_queue_action` send branch ~5500; `setter.html` `renderUnresolvedTray` ~1251 | A send-gate choice of "none" writes `subsequence_decision='none'`, which the 2026-07-22 ruling deliberately KEEPS in the tray; a "push" choice is async so the row is still unresolved when the tray reloads. Count rises -> `n > _lastTrayCount` -> auto-expand |
| 5 | New replies missing, "Check for new replies" does not surface them | `setter.py` `run_poll` ~3781; `setter.html` checkNow handler ~3420 | Query is `order=replied_at.asc&limit=200` over a 48h window, so once the window holds 200+ replies the NEWEST fall off the page entirely; and the button reloads on a blind 2.5s timer while the sweep (15 replies x classify+draft) is still running |
| 6 | Dismissing a "sent without follow-up" row errors, then restarts | `setter.py` `route_queue_action` `subsequence_dismiss` ~5462; `setter.html` `retroFollowupDismiss` ~1362 | The row lookup is not workspace-scoped and is not idempotent, and any failure path calls `showError` then `loadUnresolvedTray()`, which repaints the whole tray - the "restart" |
| 7 | Later replies get a draft that ignores the new message and re-pitches a call | `setter.py` `DRAFT_SYSTEM` ~1005 | Same clause as #1: whenever slots exist the two-call-times paragraph is mandatory "and does not depend on the intent", so a thread that already has a call on the table gets one pitched again |
| 8 | "Needs review" shown twice; Settings + Try it not wanted | `setter.html` `renderKpis` ~1488, toolbar ~637-638 | The KPI strip and the filter chip both render it; the two buttons and their drawers are legacy |
| 9 | No agent on a campaign should prompt you to assign one | `setter.html` `leadPanelHtml` ~2263 | It is a passive muted line ("No agent is assigned to this campaign."), no call to action |
| 10 | Conversation scroll jumps around | `setter.html` `wireDetailEvents` ~2870 | `curMsg.scrollIntoView({block:"center"})` runs on EVERY `renderDetail`, and `renderDetail` fires on thread refresh, retro decisions, redraft and poll - not just on selecting a row |
| 11 | Earlier messages should keep their links | `setter.html` `convoMsgHtml` ~2449 | `esc(cleanBody(body))` - `cleanBody` strips every tag including `<a href>`, so the URL is gone before escaping |

Cross-cutting: `_apply_patch` busts read caches, raw `_SB(...)` calls do not.
`setter_queue` is schema-frozen - **add no columns**; new VALUES in the existing
`subsequence_decision` text column are fine.

## First run (2026-07-25) - all eleven PASS

Shipped `cabfc1a` + `ef818fd`. Training Mode was flipped OFF for that run on request.
Re-running this skill re-verifies; every step's done-rule is written to be re-checkable,
so a step that still passes is skipped. See memory
`project_setter_eleven_feedback_fixes_ship` for the root causes and the verify gotchas
(cookie HMAC signs RAW bytes; `grep -a` for setter.html; run the test file as a SCRIPT;
baseline failures are 7).

## Steps

Fix order is deliberate: pure-frontend first (zero live-data risk), then backend
behaviour, then the two that need a live reproduce, then tests, deploy, verify.

### Step 1 - Re-verify ground truth
Confirm `~/navreo-signals` is the deploy repo and clean, re-locate every anchor in the
table above (line numbers drift), and note the live commit.
**Done-rule:** every row of the ground-truth table has a confirmed current file:line, and
`git status` shows no unexpected staged work.

### Step 2 - Page clutter and chrome (#8, #9, #10, #11)
`app/setter.html` only.
- **#8** Drop the `Needs review <b>N</b>` span from `renderKpis()` (the filter chip already
  carries the live count); delete `#openSettingsBtn` and `#openTryItBtn`, their click
  wiring, and their drawer markup.
- **#9** Replace the muted "No agent is assigned to this campaign." line with a real prompt:
  the sentence plus an **Assign an agent** button that opens the Agents drawer with this
  row's campaign pre-selected.
- **#10** Auto-scroll to `.thread-msg.current` only when the selected row actually CHANGED.
  Track the last-scrolled row id; a re-render of the same row never moves the scroll.
- **#11** `convoMsgHtml` keeps anchors: extract `<a href>` targets before `cleanBody` strips
  tags, re-emit them as real clickable links after escaping, and linkify bare URLs. Escaping
  stays on for everything else - no raw lead HTML reaches the DOM.
**Done-rule:** "Needs review" appears exactly once in the rendered page; no Settings/Try-it
buttons; re-rendering the open conversation leaves `scrollTop` unchanged; a prior message
containing a link renders an `<a href>`; and the assign flow is walked to COMPLETION -
prompt -> drawer -> agent editor with the campaign pinned FIRST, ticked and visible without
scrolling -> Save -> the open conversation loses its "No agent" line and Assign button.

> **A prompt that appears is not a flow that works.** The first run passed this step on
> "the campaign is pre-ticked" and shipped two defects: the tick sat at position 140 of 142
> in a 168px scroller (invisible), and `loadQueue()` never repainted the open conversation,
> so a successful save changed nothing on screen. Every done-rule here ends at the state the
> USER is looking at after the last click, never at an intermediate one. To exercise a real
> save without touching a real lead, assign a campaign that has ZERO queue rows (adoption
> matches nothing), then delete the throwaway agent.

### Step 3 - Follow-up reminder correctness (#3, #4)
`app/setter.py`.
- **#4** A decision made AT SEND leaves the tray. In the send branch, gate choice `none`
  writes `subsequence_decision="none_at_send"`, and a `push` choice stamps `"pushing"`
  synchronously before `_subsequence_choice_async` fires. `route_subsequence_unresolved`
  excludes both. The tray's own "No follow-up needed" still writes `"none"` and still stays
  (owner ruling 2026-07-22 is untouched).
- **#3** `route_subsequence_unresolved` drops any candidate whose current lead category is
  not positive (`POSITIVE_CATEGORY_NAMES`), reading the queue row's `category` and
  cross-checking the `replies` table in ONE batched GET for the candidate set. A non-positive
  recategorise in `route_queue_recategorise` also stamps `subsequence_decision="dismissed"`
  so it leaves the reminder immediately.
**Done-rule:** a test row sent with a gate choice never appears in
`GET /api/setter/subsequence/unresolved`; a test row whose category is flipped to a
non-positive disappears from it; a tray row marked "No follow-up needed" still stays.

### Step 4 - Regenerate honours what was typed (#1, #7)
`app/setter.py`.
- **#1** In `route_queue_redraft`, detect time-shaped feedback (different/other times, next
  week, later, earlier, a named weekday) and re-pick slots for it - excluding the slots the
  previous draft already offered (`row["slots"]`) and/or shifting the search window - then
  draft with the new set. Never invent a time: only slots the calendar actually returned.
  Soften the `DRAFT_SYSTEM` "verbatim / not optional" clause so `reviewer_feedback` may
  choose WHICH supplied slots are proposed, while the never-invent rule stays absolute.
- **#7** Make the two-call-times paragraph conditional on conversation state, not
  unconditional: pass an explicit call-ask directive computed from
  `classification.all_intents` plus thread history, and when a call is already on the table
  and the newest inbound is not about scheduling, answer THAT message instead of re-pitching.
**Done-rule:** on a test row, "offer different times" produces a draft whose proposed slots
differ from the previous draft's; "offer next week" produces slots dated next week or an
explicit can't-comply note; and a test row whose latest inbound is a non-scheduling question
after a call was already proposed drafts an answer without a fresh call pitch.

### Step 5 - First Regenerate after an agent is assigned (#2)
Reproduce first on a test row (inject on an agented campaign, clear its `agent_id`, save the
agent to trigger adoption, then Regenerate ONCE). Then fix: `_save_agent`'s adoption PATCH
calls `_bust_read_caches()`, and `doRedraft` paints from the redraft response it already
holds rather than waiting on `loadQueue()`.
**Done-rule:** the reproduce produces a correct drafted reply on the FIRST Regenerate, three
times running.

### Step 6 - New replies actually show up (#5)
`app/setter.py` + `app/setter.html`.
- `run_poll` fetches `order=replied_at.desc` (still processing oldest-first from what it
  fetched) so a busy 48h window can never starve the newest replies.
- "Check for new replies" waits for the sweep to finish instead of a blind 2.5s timer -
  poll a lightweight status until the run completes (with a timeout), then reload and report
  what it found ("N new replies" / "No new replies").
**Done-rule:** a freshly injected test reply is visible in the inbox after one click of
"Check for new replies", with no manual page reload, and the button reports a real count.

### Step 7 - Tray Dismiss (#6)
Reproduce on test rows, then harden: `subsequence_dismiss` is workspace-scoped and idempotent
(already-dismissed answers 200, not 404), and the frontend keeps the row out optimistically
and never repaints the whole tray on an error.
**Done-rule:** dismissing a test tray row 5 times in a row - including a double-click and an
already-dismissed row - always removes it with no error banner and no tray repaint.

### Step 8 - Tests
Run `app/test_setter.py`. Add coverage for each changed backend behaviour (tray exclusions,
redraft slot re-pick, poll ordering, dismiss idempotency). Call
`settle_background_reads()` before asserting on `sb.calls` or seeded GETs.
**Done-rule:** the suite passes with zero failures and the new cases are in it.

### Step 9 - Deploy
Commit with a message naming the eleven fixes and push `main` from `~/navreo-signals`.
Confirm the deploy landed (`shell.js` / page `Last-Modified` moves, or `/api/version`).
**Done-rule:** the live host serves the new build.

### Step 10 - Live verification, one defect at a time
On `https://navreo-signals.onrender.com/app/setter.html`, authenticated, reading the
**rendered DOM** (JS reads, not screenshots - the Browser pane renders this page blank).
Walk all eleven in order and record PASS/FAIL with the evidence for each. Test rows only.
**Done-rule:** eleven PASS lines, each with its own evidence. Any FAIL sends that defect's
step back through the retry cap.

### Step 11 - Report
One table: defect -> what changed (file:line) -> live evidence -> PASS/FAIL. Name every
FAILED step and why. Then save a memory record and reconcile the iCloud copy.
**Done-rule:** the report exists and every one of the eleven has a verdict.

## Done-rule for the whole skill

All eleven show PASS in Step 10 against the live host, the test suite is green, the build is
deployed, and no real prospect was emailed or modified. Anything short of that is reported as
partial, with the failures named.
