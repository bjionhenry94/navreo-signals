---
name: setter-edit-learning-default
description: Static orchestration skill that makes the Appointment Setter learn from hand-edits by default — when you rewrite a generated draft and approve it, the difference between what it wrote and what you sent becomes a timeless lesson merged into the agent's instructions, with no extra clicks. Snapshots the pristine generated draft (new setter_queue column) before the first keystroke can destroy it, teaches at send-time from the diff, and ships the one simple visible toggle the code already expects but nobody ever built. One fixed step list, each with a checkable done-rule, retry caps, and a Loop Training Mode toggle. Use when the user says "make setter learning the default", "learn from my edits", "run the edit-learning ship", or "/setter-edit-learning-default".
---

# Setter: Learning From Edits, By Default

Today the Appointment Setter only learns when you **type feedback** into the Regenerate box. If you do what people actually do — click into the draft, rewrite it in your own words, hit Approve — the agent learns **nothing**. It writes the same wrong draft tomorrow. This loop closes that: the edit itself IS the lesson.

Static loop — fixed steps, each has a done-rule, Loop Training Mode controls the pauses.

## ⚙ Loop Training Mode: **OFF**   ← flip this line to ON to pause at every step

**ON:** pause at EVERY step boundary and wait for the user's explicit approval before continuing. Before starting a step, check its done-rule first — if it already passes, report "Step N already passes, skipping" and move on. Only re-run steps whose done-rule fails. Show what you're about to do before doing it.

**OFF:** run all steps end-to-end with no pauses. The done-rule checks, skip-if-passing behaviour, and retry caps stay exactly the same — only the pauses go.

**Retry cap (both modes):** each step retries **max 3** times against its done-rule. On cap-hit: record the step as FAILED with the reason, continue to the next step if it doesn't depend on the failed one, and surface every FAILED step in the final report. Never silently exceed the cap. Never declare the skill done on a cap-hit.

**Model routing:** judgment (is this diff a real lesson? did the panel pass? does the done-rule pass?) runs on the orchestrating session. Execution (code edits, migrations, test runs, deploy mechanics) runs on Sonnet 5 subagents (`model: sonnet`). The product's own runtime LLM stays gpt-5-mini as shipped.

### Non-negotiable gates (both modes)

- **No real sends, ever.** The global autopilot master switch stays OFF for the whole loop. Every send-path proof runs on `is_test` rows — `_send_reply` dry-runs those regardless of `SETTER_DRY_RUN` (setter.py:2010). Re-confirm the switch is OFF at Step 9.
- **Live-brain writes are scoped to a throwaway clone.** Every learning proof runs against a **duplicated test agent** (`POST /api/setter/agents/duplicate` → draft_only, no campaigns). Never write a lesson into `agent-d403bbcd`, the Amplifyy agent, or any agent assigned to live campaigns. Snapshot the clone's doc before Step 6 so you can diff and roll back.
- **No live queue rows are touched.** Test rows are minted by the loop and deleted at Step 9.
- **LLM spend cap:** ≤ 200 gpt-5-mini calls total. At 80%: pause and report (ON) / stop and report (OFF).

## Goal

Editing a draft and approving it teaches the agent, automatically, with no extra clicks — and one simple visible toggle turns that off for the rare situational edit.

1. The **pristine generated draft is preserved** the moment the row is drafted, so the reviewer's first keystroke can't destroy the thing we need to diff against.
2. On **Approve**, if the sent body differs from what the agent generated, the difference is turned into a **timeless rule** and merged into the agent's `instructions` — the same single living manual typed feedback already writes to.
3. **Silence is a valid outcome.** Edits that are only per-lead facts (a name, a date, a link, a tidied space) teach nothing. A lesson is only written when the edit expresses a preference that would apply again.
4. **One toggle, default ON**, governing every learning path in the review pane (typed feedback AND edit-diff). Not a per-reply question — the owner ruling on this is settled ([[feedback_setter_feedback_is_training]]).

### THE DONE-RULE (single source of truth — the 6-part bar)

> (1) On a test row: draft → hand-edit → Approve → the agent's `instruction_edits` gains an entry whose `rule` is **timeless** (no "this reply/lead/case" tokens, no lead name, no date) and `instructions` contains it — read back from `setter_agents`, not from the response body.
> (2) **Carry-through proved:** a second, fresh test row on a similar reply drafts in line with the new rule, where the pre-lesson draft did not. Before/after both read from `setter_queue`.
> (3) **Silence proved:** an edit that only changes per-lead facts (swap the first name, fix a date) writes **zero** `instruction_edits` entries and leaves `instructions` byte-identical.
> (4) Toggle OFF ⇒ an identical edit+Approve writes **zero** entries and leaves `instructions` byte-identical; flipping back ON restores learning. Default state on a cleared localStorage is **ON**.
> (5) **868+ tests green** (`python3 app/test_setter.py`, current count is the floor — never fewer) AND the deployed Render page browser-verified: rendered page, not a grep ([[feedback_browser_verify_before_done]]).
> (6) **5 user-testers average ≥8/10** on "did you understand that your edit taught it, and how to stop that?" — and no tester reports a surprise (someone learning only after the fact that their edit trained the agent is a FAIL regardless of score).
>
> **All 6, or it isn't done.** On any cap-hit, report the gap honestly — never declare done.

## Ground truth (verified 2026-07-17 against `~/navreo-signals` @ `467a20c` — re-verify in Step 1, line numbers drift)

- **Files:** `app/setter.py` (6966 lines), `app/setter.html` (2766), `app/test_setter.py` (7701, `python3 app/test_setter.py`). Working copy = iCloud dir; **deploy repo = `~/navreo-signals`**. iCloud NEVER deploys — git commit → Render only. Main is a multi-session surface: ship via a fresh worktree at `origin/main`, and check `git log origin/main` for newer commits before any copy ([[reference_signals_deploy_repo]]).
- **The two real gaps:**
  - **No visible toggle exists.** `trainingModeOn()` (setter.html:1501) reads `localStorage.setterTrainingMode`, defaulting `"on"`. **Nothing in the codebase ever writes that key** — grep for `setItem("setterTrainingMode")` returns nothing. The mode is currently stuck ON and unflippable. The old On/Off switch was removed when the teach control was simplified (comment at setter.html:1511). Step 5 builds the writer.
  - **The original draft is destroyed on first keystroke.** `save_draft` (setter.py:4265) patches `draft_body` with the edited HTML, debounced 800ms from the contenteditable (`SAVE_TIMERS`, setter.html:1766) plus a `sendBeacon` on unload. There is no `original_draft_body` anywhere. By Approve-time, the generated text is gone. Step 2 fixes this and **must land before anything else can diff**.
- **Where learning already works (copy this path, don't invent a second one):** `merge_correction_into_instructions(agent, note, source)` (setter.py:1823) — gpt-5-mini rewrites the manual with the smallest edit that makes the correction stick; validates that every pre-existing URL survives, text is non-empty, and length ≤ `max(20000, old_len*1.5)`; falls back to a dated `Training note:` append on any failure; appends `{note, rule, at, source, how}` to the agent doc's `instruction_edits`. **Never raises.** `route_queue_redraft` (setter.py:4319) calls it at :4340 with `source=str(qid)` when `scope == "remember"`.
- **The generalisation guard is the whole ballgame.** `merge_correction_into_instructions` already rejects a `general_rule` containing `"this reply" / "this lead" / "this case"` and falls back to the raw note. A live incident ([[project_setter_training_brain_ship]], commit af9c1dd): a case-specific note entered the LATEST OWNER RULES block verbatim and **an English lead got a Spanish draft**. An edit-diff is far more case-specific than a typed note — it is full of names, times and links. Step 3 is where this loop lives or dies.
- **Schema freeze law:** a key in a row-dict with no matching `setter_queue` column makes the PATCH **die silently** — `_apply_patch` (setter.py:1939) swallows the exception ([[reference_setter_queue_schema_freeze_gotcha]]). A new column is a real Supabase migration (`mcp__supabase__apply_migration`, project `fnykldftbkrccihdjayl`), applied and read back BEFORE any code writes to it.
- **`/api/setter/test/inject` does NOT persist** — it returns the fully processed row with `id: null`, nothing reaches `setter_queue`. Fine for before/after draft proofs, useless for `save_draft`/`send` (both need an id). **Step 4 mints a real `is_test` row** via SQL insert instead. `is_test` rows never reach Smartlead (setter.py:2010).
- **Proofread interference:** `proofread_draft()` runs a second sweep on every draft and can normalise exact wording ("Appreciate the patience" → "your patience") — see [[project_setter_regen_feedback_fix_ship]]. A diff-derived "use these exact words" lesson may not survive verbatim. Judge the **preference**, not the characters.
- **Auth for live verification:** mint a `navreo_session` cookie ([[reference_signals_session_cookie_mint]]); `~/.navreo-keys.env` lines are `export KEY=...` — strip the prefix. Browser pane drops the cookie — re-set via `document.cookie`. Poll-log = deploy proof ([[reference_setter_live_verify_auth]]).
- **Unknowns for Step 1:** whether `sent_body` is reliably populated on the dry-run path for diffing (setter.py:2014 suggests yes — confirm); the current exact test count; whether any other surface writes `draft_body` between draft-time and send-time.

## Steps

### Step 1 — Re-verify ground truth
Sonnet subagent: confirm every Ground-truth bullet against current code (line drift), confirm no visible toggle writer exists, confirm `setter_queue` has no original-draft column, list every code path that writes `draft_body`, and snapshot the current test count.
- **Done-rule:** every bullet confirmed or corrected **in writing**; the `draft_body` writer list is complete; test count recorded.

### Step 2 — Snapshot the generated draft ⚠ must land first
Migration: add `original_draft_body` (text, nullable) to `setter_queue`. Stamp it **once**, wherever a draft is first written to a row, and **never overwrite it** — a regenerate replaces `draft_body`, so the snapshot must follow the regenerate (the agent's latest generated draft is the diff baseline, not the first one it ever wrote). `save_draft` must never touch it. Backfill nothing; forward-only.
- **Done-rule:** (a) migration applied and the column read back from Supabase; (b) a fresh test row carries a non-empty `original_draft_body` equal to `draft_body` at draft-time; (c) 3 `save_draft` calls with different bodies leave `original_draft_body` byte-identical; (d) a regenerate re-stamps it to the new generated draft.

### Step 3 — The diff → lesson learner (the hard one)
A function that takes (generated, sent, thread context) and returns **a timeless rule or nothing**. Route it through `merge_correction_into_instructions` — do not build a second merge path. The prompt's job is refusal as much as generalisation: an edit is a lesson only if it expresses a **preference that would apply to a different lead tomorrow**. It is NOT a lesson when the change is a per-lead fact (name, company, date, time, a link the reviewer pasted), whitespace/HTML noise, or an `Add link` button insertion. Reuse the existing case-specific token rejection and add name/date detection. Bias hard toward silence: a missed lesson costs nothing, a bad rule mis-drafts every future reply.
- **Done-rule:** on a hand-labelled set of **≥20 real edit pairs** (pulled from `sent_messages` vs the drafts that preceded them, or constructed from the corpus): **zero** rules containing a lead name, company name, date, or case-specific token; ≥70% of the pairs labelled "genuine preference" produce a rule; **100%** of the pairs labelled "per-lead fact only" produce **nothing**. The false-positive number is the one that gates — 70% recall with 0 bad rules passes, 95% recall with 1 bad rule FAILS.

### Step 4 — Wire it to Approve + mint the test-row helper
Call the learner from the `send` action in `route_queue_action` (setter.py:4283), **after** the send succeeds — a failed send must never teach. Compare `original_draft_body` vs the body actually sent. Skip silently and cheaply when: bodies match, `original_draft_body` is empty, the row has no `agent_id` (agentless rows have no brain to teach — [[feedback_setter_positives_regardless_of_agent]]), or the request says training is off. Learning runs in a **background thread** — the reviewer's Approve must not wait on a gpt-5-mini call ([[project_setter_perf_loadspeed_ship]] set the bar). Also build the throwaway helper that mints a persisted `is_test` queue row by SQL insert (inject can't).
- **Done-rule:** (a) the helper mints an `is_test` row that appears in the queue with a real id; (b) edit + Approve on it writes an `instruction_edits` entry to the **clone** agent, read back from `setter_agents`; (c) Approve returns in under 400ms measured, with the lesson landing after; (d) a forced send failure teaches nothing; (e) an agentless row teaches nothing and errors nothing.

### Step 5 — The toggle (the only UI the user asked for)
Build the missing writer for `localStorage.setterTrainingMode`. **One switch** in the review pane governing both learning paths — the toggle already read by `trainingModeOn()`. Default ON. It must say what it does in plain English, in place, without a tooltip: on = your edits teach it, off = this one's just for this lead. Pass the mode to the server on `send` the same way `scope: "remember"` rides on redraft (setter.py:4335). **Do not** add a second toggle, a per-reply choice, or a confirmation dialog — settled ruling. No em-dashes in the copy ([[feedback_no_em_dashes]]). Navreo design system for any new component ([[feedback_artifacts_navreo_design_system]]).
- **Done-rule:** browser-rendered on localhost (screenshot, not a grep): (a) toggle visible and ON with localStorage cleared; (b) flipping it OFF then editing + approving writes zero `instruction_edits`; (c) flipping back ON restores learning; (d) the state survives a reload; (e) the existing feedback-placeholder swap (setter.html:1504) still tracks the same switch; (f) the two-pane inbox layout is structurally unchanged.

### Step 6 — Live proof on the clone: teach, then carry through
Duplicate a real agent → snapshot the clone's doc. On the clone: mint test row → read the generated draft → hand-edit it to express a real preference → Approve → read `instruction_edits` + `instructions` back from `setter_agents`. Then mint a **second, fresh** test row on a similar reply and prove the new draft honours the rule where the pre-lesson draft did not. Judge the preference, not the characters (proofread normalises wording). Then prove silence: a per-lead-fact-only edit writes nothing.
- **Done-rule:** done-rule parts (1), (2) and (3) of the 6-part bar, evidenced by before/after reads from `setter_queue` and `setter_agents`.

### Step 7 — Tests
Extend `test_setter.py`: snapshot immutability across saves, re-stamp on regenerate, learner refusal cases (per-lead facts, whitespace, link insert), agentless no-op, failed-send no-op, toggle-off no-op, background-thread joinable in tests.
- **Done-rule:** `python3 app/test_setter.py` green, count strictly greater than Step 1's number; no pre-existing test modified to pass.

### Step 8 — Ship + live-verify on Render
Fresh worktree at `origin/main`, rerun the suite there, commit, push, wait for deploy. Re-run Step 6's proof **on the deployed host** with a minted cookie. Walk the whole journey in the live UI before calling it done ([[feedback_full_live_ui_flow_before_handover]]).
- **Done-rule:** done-rule parts (1)–(5) all pass **against navreo-signals.onrender.com**, page browser-verified rendered.

### Step 9 — User-tester panel + cleanup
5 simulated testers of mixed ability walk the live flow cold: generate a draft, rewrite it, approve, then find out whether it learned and how to stop it. Score understanding /10. Any tester surprised that their edit trained the agent = FAIL regardless of score → fix the copy and re-run (counts against the retry cap). Then: delete the test rows, delete the clone agent, confirm the master switch is OFF, confirm no live agent's `instructions` changed (diff against pre-loop state).
- **Done-rule:** part (6) of the bar; zero test rows left in `setter_queue`; clone deleted; master switch confirmed OFF; every production agent's `instructions` byte-identical to its pre-loop snapshot.

### Step 10 — Report + memory
Report every step's status, the 6-part bar line by line, and every FAILED step with its reason. Then write the ship memory and update [[INDEX_setter]]. Ask before `publish-skill`.
- **Done-rule:** report delivered; memory written; index updated.

## Notes

- **The one thing that will go wrong:** the learner writing a case-specific rule that misfires on an unrelated lead. It has happened before, in production, in Spanish. Step 3's false-positive gate is not negotiable down.
- **Related:** [[feedback_setter_feedback_is_training]] (the settled toggle model) · [[project_setter_training_brain_ship]] (instructions = the living manual) · [[project_setter_regen_feedback_fix_ship]] (feedback-first truncation, proofread interference) · [[reference_setter_queue_schema_freeze_gotcha]] · [[reference_setter_live_verify_auth]].
