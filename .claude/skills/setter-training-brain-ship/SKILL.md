---
name: setter-training-brain-ship
description: Static orchestration skill that ships the Appointment Setter's four missing capabilities — scenario-based training UX with a rising readiness score, corrections that persist to the LIVE brain (one-off vs remember-forever), multi-turn autonomy for simple later-turn asks, and REAL Smartlead sub-sequence enrolment — plus brain duplication and a unified waiting-leads view. One fixed step list, each step with a checkable done-rule, retry caps, and a Loop Training Mode toggle. Use when the user says "run the setter training ship", "ship the setter brain", "build the setter onboarding", or "/setter-training-brain-ship".
---

# Setter Training + Brain Ship

The setter (shipped 2026-07-11, v2 2026-07-12) decides and drafts well, but its training loop is a dead end: the temporary grading page's relearn never reaches the live pipeline, corrections don't persist, a lead's second message always goes to a human, and the sub-sequence checkbox is a DB flag that enrols nobody. This loop closes all four gaps and proves them against the proven-setter bar. Static loop — fixed steps, each has a done-rule, Training Mode controls the pauses.

**Model routing (user ruling 2026-07-13):** judgment — scenario realism vetting, readiness scoring, judge panels, pass/fail calls against done-rules — runs on Fable 5 (the orchestrating session / default-model subagents). Execution — code edits, corpus pulls, test runs, deploy mechanics — runs on Sonnet 5 subagents (`model: sonnet`). The product's own runtime LLM stays gpt-5-mini as shipped.

## ⚙ Loop Training Mode: **ON**   ← flip this line to OFF to run without pauses

**ON:** pause at EVERY step boundary and wait for the user's explicit approval before continuing. Before starting a step, check its done-rule first — if it already passes, report "Step N already passes, skipping" and move on. Only re-run steps whose done-rule fails. Show what you're about to do before doing it.

**OFF:** run all steps end-to-end with no pauses. The done-rule checks, skip-if-passing behaviour, and retry caps stay exactly the same — only the pauses go.

**Retry cap (both modes):** each step retries **max 3** times against its done-rule. On cap-hit: record the step as FAILED with the reason, continue to the next step if it doesn't depend on the failed one, and surface every FAILED step in the final report. Never silently exceed the cap. Never declare the skill done on a cap-hit.

**Destructive-action gates (both modes, non-negotiable):**
- **No real sends, ever.** The global autopilot master switch stays OFF for the entire loop — never flip it, never send a reply to a real lead. Every send-path proof uses `is_test` rows via `/api/setter/test/inject` or dry-run. Master switch state is re-confirmed at the end (Step 11).
- **Sub-sequence push fires ONLY at the user-named target.** Step 7's real Smartlead enrolment is BLOCKED until the user names, in chat, the test campaign id + subsequence id + burner lead email. Never enrol into a real-prospect campaign. Enrolment is read back FROM Smartlead's API, then the burner lead is removed/reset. Max **3** live enrolment calls total.
- **Live-brain writes are scoped.** "Remember going forward" writes touch ONLY the target agent's doc in `setter_agents` — never another agent, never `setter_queue` rows, never campaigns or webhooks. During this loop, live-brain proofs run against a CLONED test agent, not `agent-d403bbcd`, until Step 10's final check.
- **LLM spend cap:** ≤ 600 gpt-5-mini calls per eval round, max 3 full eval rounds, ≤ 150 calls for scenario generation. At 80% of any cap: pause and report (ON) / stop and report (OFF).

## Goal

1. An in-nav **Training** flow streams realistic scenarios from the real reply corpus (open-ended count — feedback begets scenarios, later scenarios conditioned on all prior advice), skewed to the most-common intents, each carrying original-outbound + campaign context + prior human-SDR history where it exists; the trainer answers intervene-vs-leave + good-reply + free-text, and a **readiness score (0–100)** visibly climbs toward "ready to unleash".
2. Every correction (training page AND live inbox edits/regens) carries **one-off vs remember-forward**; remembered corrections write into the live agent brain with no per-write approval and change live `decide()`/`draft_reply()` behaviour immediately; one-offs are logged and change nothing.
3. A **simple later-turn ask auto-answers** even after a human took message 1 — every other gate intact; complex later-turn asks still hold.
4. The subsequence checkbox performs a **real `push_to_master_inbox_subsequence`** enrolment (Smartlead owns delay/follow-up/stop-on-reply), working for leads with no queue row.
5. **Brain duplication** clones a trained agent into an independent new agent; a unified operator view shows held/escalated messages and leads awaiting our response together.

### THE DONE-RULE (single source of truth — the 7-part bar)
> (1) decision accuracy **≥95%**, **0 unsafe auto-sends**, **0 dropped leads** on a fresh held-out corpus of **≥120** real replies never used in training, including later-turn cases (Fable 5 judge panel); (2) readiness rises monotonically-on-average to **≥90/100** in a full simulated training run, AND a "remember" correction demonstrably changes live output on a matching `is_test` inject (before/after `setter_queue` diff) while a "one-off" demonstrably does NOT; (3) a cloned brain's doc diverges independently when edited (both docs read back from `setter_agents`); (4) subsequence enrolment confirmed by reading the burner lead back FROM Smartlead's API, then reset; (5) 8 mixed-ability simulated trainers average **≥8/10** on training-flow clarity; (6) **188+ tests green** AND the deployed Render page browser-verified (rendered page, not a grep); (7) master switch confirmed **OFF**. **All 7, or it isn't done.** On any cap-hit, report the gap honestly — never declare done.

## Ground truth (verified 2026-07-13 — re-verify in Step 1, line numbers drift)

- **Files:** `app/setter.py` (2374 lines), `app/setter.html` (1733), `app/setter-grade.html` (temporary grading page, NOT in nav), `app/generate_grading.py`, `app/test_setter.py` (188 tests, `python3 app/test_setter.py`), `app/setter_eval.py` (corpus eval harness), `app/shell.js` (nav). Working copy = iCloud dir; **deploy repo = `~/navreo-signals`** (currently on `main` @ 39a5740, clean-ish; parallel sessions move branches — fetch+rebase before push).
- **Brain:** per-agent JSON docs in `setter_agents` (jsonb); `instructions` field (legacy fallback `pricing_notes`), ONE Calendly link, `confidence_threshold` default 0.9 (setter.py:619), `allowed_intents`, `mode`. Settings doc id `__settings__` holds `calendly_token`/`autopilot_enabled`/webhooks. `_save_agent` MERGES onto stored doc (partial saves once wiped pricing_notes). **No clone/duplicate route exists.**
- **Gates (`decide()` setter.py:564):** clear-negative → answered_since_reply (:600) → hydrated → allowed intents → simple_ask+confidence ≥0.9 (:622) → same-day → red flags → categoriser veto → **first-touch-only :637 (`ctx["first_touch"]`) — the gate Step 5 relaxes** → timezone+tz_confident → slots → len≤1500 (on `clean_body()`!) → lint → agent mode → **master switch LAST :669** (held rows keep the most informative reason — preserve this ordering).
- **Relearn today (setter.py:2036–2260):** grading-doc-only; feedback_log → `_feedback_digest()` → re-classify/re-draft still-unanswered grading cases via `classify(owner_hints=digest)` + `draft_reply(regen_feedback=digest)`. **Never touches the live path** — that's the gap. `__grading__` doc in settings table; relearn thread + lock, 900s stale self-heal.
- **Routes (setter.py:2358–2373):** GET agents/campaigns/queue/grading; POST agents/save, agents/delete, settings/save, queue/action (send|dismiss|subsequence — subsequence at :1950 **only patches the `added_to_subsequence` bool, no Smartlead call**), queue/redraft (takes `feedback`), grading/answer, grading/reset, test/inject (`is_test` rows, full pipeline).
- **Subsequence reality:** Smartlead subsequences live in `campaigns` under generic names, regex `_SUBSEQUENCE_NAME` setter.py:1861 ("meeting request|interested reply|information request"). MCP tool `mcp__smartlead__push_to_master_inbox_subsequence` exists — **unproven; prove read-adjacent shape in Step 1, first live call only in Step 7 at the user-named target.**
- **Corpus:** Supabase `fnykldftbkrccihdjayl` — `replies` + `sent_messages` (ALL outbound thread msgs incl. human-SDR replies = the historical-answer training source). `setter_eval.py --n 120 --offset N` slices fresh corpus; offsets used so far are in that file's history — Step 1 must pick genuinely unused offsets.
- **Gotchas (each cost a debug cycle):** Calendly needs a real User-Agent (Cloudflare 1010) and strictly-future start_time; Smartlead webhook POST must OMIT `categories` entirely and register additively; reply bodies can be full Outlook HTML — `clean_body()` before any length/classify; gpt-5-mini once emitted U+0019 — scrub post-draft; **eval realism law: placeholder pricing/resources leak into judged drafts and corrupt scores — scenarios must be verified-real**; minted `navreo_session` cookie works on localhost+prod but the browser pane drops it — re-set via document.cookie; iCloud copy NEVER deploys anything — git-commit→Render only.
- **Unknowns for Step 1:** exact `push_to_master_inbox_subsequence` request/response shape; whether `sent_messages` reliably joins human answers to their inbound reply (needed for "what the human said before" context); current readiness-relevant answer counts in `__grading__`.

## Steps

### Step 1 — Re-verify ground truth + resolve unknowns
Sonnet execution agent: confirm every Ground-truth bullet against current code (line drift), pick fresh unused eval offsets, prove the `replies`↔`sent_messages` human-answer join with 5 real examples, read the `push_to_master_inbox_subsequence` tool schema and prove the read side (list subsequences on any campaign — zero writes), snapshot `agent-d403bbcd`'s doc as rollback artifact.
- **Done-rule:** (a) every bullet confirmed or corrected in writing; (b) 5 real inbound→human-answer pairs shown; (c) subsequence list read returns real ids; (d) agent doc snapshot saved to the skill folder; (e) fresh offsets named.

### Step 2 — Backend: persistent learning layer (the live-brain gap)
Add an agent-doc `memory` list (each entry: text, source case/queue id, timestamp) + routes: correction intake with `scope: one_off | remember`. `remember` appends to the live agent's `memory` and it is fed into `classify(owner_hints=…)` + `draft_reply(regen_feedback=…)` + `decide()` context on EVERY live pass; `one_off` appends to a log only. Wire the same choice into inbox Approve-with-edits/Regenerate-with-feedback. Cap memory digest at the existing 2000-char pattern (newest-first). Respect `_save_agent` merge semantics.
- **Done-rule:** (a) unit tests prove remembered text reaches classify+draft on a subsequent pipeline run and one-off does not; (b) a `remember` on a CLONED test agent changes the draft for a matching `/api/setter/test/inject` before→after (diff read from `setter_queue`); (c) the one-off equivalent produces byte-identical decision behaviour.

### Step 3 — Backend: brain duplication
`POST /api/setter/agents/duplicate` — deep-copies the agent doc (instructions, memory, allowed_intents, threshold; NEW id, name "+ copy", `mode: draft-only`, campaigns UNASSIGNED so a clone never silently claims live traffic).
- **Done-rule:** duplicate → edit clone → read BOTH docs from `setter_agents`: clone diverges, original untouched, clone has no campaigns and draft-only mode.

### Step 4 — Backend: training/scenario engine + readiness score
Promote grading into a permanent per-agent training system: scenario generator draws from real `replies` (+ human answers from `sent_messages` when the join exists, else blank-canvas), skewed to most-common intents (weight by actual intent frequency in the corpus — no invented edge cases), open-ended batches (answering + feedback triggers generation of the next conditioned batch), every scenario verified-real (real pricing/resources only — eval realism law). Readiness score 0–100: transparent formula over recent-N agreement rate (trainer's intervene-call vs pipeline's, and reply-quality verdicts), weighted to recent, exposed via API with a plain-English breakdown. Feedback with `remember` scope flows into Step 2's memory; the existing relearn re-run keeps working on unanswered cases.
- **Done-rule:** (a) generated scenarios' intent mix within ±15pp of the real corpus mix (measured); (b) 0 placeholder facts in a 20-scenario Fable-vetted sample; (c) readiness recomputes after each answer and the API returns score + breakdown; (d) a scripted 30-answer simulated run moves the score in the correct direction for correct/incorrect streaks.

### Step 5 — Backend: multi-turn autonomy
Replace the binary first-touch hold (setter.py:637): a non-first-touch reply may proceed IFF classification is a simple ask within allowed intents AND every downstream gate passes; add thread context so the draft reads as a continuation. Complex later-turn asks still hold with an informative reason. Preserve gate ORDER and the master-switch-last property.
- **Done-rule:** new tests prove (a) simple later-turn ask ("when are you free?") reaches `auto_send` verdict with switch simulated ON; (b) complex later-turn ask holds; (c) answered_since_reply still blocks; (d) all pre-existing gate tests green.

### Step 6 — Frontend: training page, learning controls, waiting view (additive only — v2 inbox layout untouched)
Training page in nav via `shell.js` (evolve `setter-grade.html` patterns): scenario card (original outbound + campaign + prior history), two verdicts + feedback box, one-off/remember toggle, prominent readiness dial + "ready to unleash" threshold marker. Inbox additions: one-off/remember on edit/regen flows; Duplicate in the Agents drawer; a **Waiting** view unioning held/escalated queue rows + leads awaiting our response, sorted oldest-first with age badges.
- **Done-rule:** on localhost, browser-rendered (screenshot): (a) training flow completes 5 scenarios end-to-end with the score visibly updating; (b) remember/one-off visible on inbox corrections; (c) Duplicate produces a clone in the UI; (d) Waiting view shows both populations with ages; (e) existing two-pane inbox pixel-unchanged in structure.

### Step 7 — Real sub-sequence enrolment ⛔ BLOCKED until the user names campaign + subsequence + burner lead in chat
Wire the checkbox (and a lead-without-queue-row path) to `push_to_master_inbox_subsequence`. UI state comes from the API result read-back, not the click. Prove at the user-named target with the burner `is_test` lead, read enrolment back FROM Smartlead, then remove/reset the burner lead. Max 3 live calls.
- **Done-rule:** (a) Smartlead API read-back shows the burner lead enrolled in the named subsequence; (b) app reflects the read-back state; (c) burner lead reset confirmed by a second read-back; (d) failure path (bad id) surfaces an honest error, checkbox reverts.

### Step 8 — Tests green
Extend `test_setter.py` to cover memory scoping, duplication, multi-turn gate, readiness math, subsequence action (mocked HTTP). 
- **Done-rule:** `python3 app/test_setter.py` exits 0 with **≥ 188 + new** tests, zero skips of pre-existing tests.

### Step 9 — Deploy
Reconcile iCloud→repo, fetch+rebase `~/navreo-signals` main, commit, push, wait for Render live, marker-grep the deployed artifact, then browser-verify the rendered training page + inbox on navreo-signals.onrender.com (re-set `navreo_session` cookie if dropped).
- **Done-rule:** (a) commit on origin/main; (b) unique marker present in deployed asset; (c) rendered live page screenshot showing the training page in nav — a grep alone does not pass this.

### Step 10 — Live proof: the 7-part bar
Run the composite bar against PROD (Fable 5 judges, Sonnet runners): fresh-corpus eval (≥120 unused replies incl. constructed later-turn threads; ≥95% / 0 unsafe / 0 dropped — an unsafe auto = any auto verdict on a bespoke/negative/complex case; a dropped lead = any no_action on a live interest), full simulated training run to ≥90 readiness, remember-vs-one-off live before/after diffs via `is_test` injects on the cloned agent, clone-divergence read-back, subsequence proof (from Step 7's artifacts), then **8 mixed-ability simulated trainers** score the flow ≥8/10 avg (personas from non-technical setter to power user; max 3 fix-and-rerun rounds on their findings).
- **Done-rule:** parts (1)–(5) of THE DONE-RULE each pass with numbers recorded; every `is_test` artifact row cleaned from `setter_queue` afterward.

### Step 11 — Master-switch + safety close-out
Read `__settings__`: `autopilot_enabled` must be false; `agent-d403bbcd` doc byte-compares to Step 1's snapshot except intentionally shipped fields; no test agents left assigned to real campaigns; test clones deleted or clearly named.
- **Done-rule:** all four checks pass, read directly from Supabase.

## Final report (always, both modes)

One summary: per-step pass/skip/FAILED with retry counts; the real numbers — decision accuracy %, unsafe/dropped counts, readiness trajectory (start→end), trainer-panel scores (all 8), test count, LLM calls spent vs caps, subsequence enrolment ids; artifacts — commit SHAs, screenshots, eval offsets used, `is_test` row ids created+cleaned, agent-doc snapshot path; anything deferred or FAILED, stated plainly.

## Hard don'ts

- Never flip the autopilot master switch, and never send anything to a real lead — `is_test` rows only.
- Never fire the subsequence push anywhere except the user-named test target, never more than 3 live calls, and never trust the app's own success label over the Smartlead read-back.
- Never redesign the v2 two-pane inbox — additive surfaces only.
- Never let a scenario contain placeholder pricing/resources — verified-real or it doesn't ship (this corrupted 2 of 3 draft-score rounds in v1).
- Never write remembered corrections to any agent other than the one being trained; during the loop, live-brain proofs go to the cloned test agent only.
- Never reorder `decide()` so the master switch stops being the LAST gate, and never weaken a non-first-touch gate other than the first-touch check itself.
- Never deploy from the iCloud copy or skip fetch+rebase; never call a Smartlead webhook register with a `categories` key.
- Never exceed a retry cap, spend cap, or report done while any part of the 7-part bar fails.
