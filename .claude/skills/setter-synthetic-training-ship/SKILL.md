---
name: setter-synthetic-training-ship
description: Static orchestration skill that upgrades the setter training engine (app/setter.py training section + app/setter-train.html) so scenario generation never dead-ends — when real archived replies run out, gpt-5-mini invents lead-side-only synthetic "Practice" scenarios to fill the batch, following the 80/20 actionable mix, deduped against unanswered cases, provenance-flagged, never polluting used_reply_ids, running inside the existing daemon worker/lock/poll flow, with Supabase usage logging, new tests, deploy, and a 5-check live proof on agent-70fd17e5. One fixed step list, each with a checkable done-rule, retry caps, and a Loop Training Mode toggle. Use when the user says "run the synthetic training ship", "fix the training dead-end", "ship practice scenarios", or "/setter-synthetic-training-ship".
---

# Setter Synthetic Training Ship

The training engine (shipped 2026-07-14) turns real archived replies into scenarios, but it dead-ends: when `_select_training_replies` runs dry the trainer sees "No new real replies were available" and is stuck. This loop makes generation shortfall-proof — the worker tops up any shortfall (including a full batch of zero) with synthetic scenarios invented by gpt-5-mini, so the trainer always gets a full batch and keeps rating. Static loop — fixed steps, each has a done-rule, Training Mode controls the pauses.

**Model routing (standing ruling):** judgment — realism vetting, pass/fail calls against done-rules, live-proof judging — runs on Fable 5 (the orchestrating session / default-model subagents). Execution — code edits, test runs, deploy mechanics — runs on Sonnet 5 subagents (`model: sonnet`). The product's runtime LLM stays gpt-5-mini.

## ⚙ Loop Training Mode: **OFF**   ← flip this line to ON to pause at every step

**ON:** pause at EVERY step boundary and wait for the user's explicit approval before continuing. Before starting a step, check its done-rule first — if it already passes, report "Step N already passes, skipping" and move on. Only re-run steps whose done-rule fails. Show what you're about to do before doing it.

**OFF:** run all steps end-to-end with no pauses. The done-rule checks, skip-if-passing behaviour, and retry caps stay exactly the same — only the pauses go.

**Retry cap (both modes):** each step retries **max 3** times against its done-rule. On cap-hit: record the step as FAILED with the reason, continue to the next step if it doesn't depend on the failed one, and surface every FAILED step in the final report. Never silently exceed the cap. Never declare the skill done on a cap-hit.

**Safety gates (both modes, non-negotiable):**
- **No send path, ever.** Nothing in this work may email a lead. The training section already has no send path (doctrine comment, setter.py:2950 area) — keep it that way; synthetic generation adds none.
- **Realism law amendment (the ONLY licensed relaxation):** synthetic generation may invent the LEAD side only — lead name, company, and the wording of the inbound reply. It must NEVER fabricate agent-side facts: pricing, resources, availability, links, offers. The agent's decision and draft still run through the real `classify`/`decide`/`draft_reply` pipeline with the live brain and memory.
- **used_reply_ids purity:** synthetic cases NEVER add ids (fake or real) to `used_reply_ids`. That list stays a pure record of consumed real replies.
- **No new spend cap:** the existing owner/share unanswered caps (`TRAINING_MAX_UNANSWERED` 40 / `TRAINING_MAX_UNANSWERED_SHARE` 20) remain the only throttle on generation. Do not invent one; do not remove them.
- **Live verification is additive:** the proof runs on the REAL exhausted agent `agent-70fd17e5` via its existing share link, with NO deletions — the synthetic cases stay in its queue as genuine training material.

## Goal

An agent in training never runs out of scenarios. When `_select_training_replies` returns fewer cases than the requested batch (including zero), the generation worker fills the shortfall with synthetic scenarios invented by gpt-5-mini: 80/20 actionable/clear-negative mix, biased toward the most common simple reply types (Interested, Information Request, Meeting Request; clear negatives like Not Interested, Out Of Office), deduped against existing unanswered cases, provenance-flagged, badged "Practice" in the UI (share links included), counted toward readiness exactly like real cases, and logged to Supabase so lilly-data can query usage.

### THE DONE-RULE (single source of truth — the 5-check bar)
> (1) the new test_setter.py tests pass AND the full existing suite is green (`python3 app/test_setter.py` exits 0); (2) live browser proof on the deployed `agent-70fd17e5` share link — request more scenarios and watch a full batch land containing Practice-badged cards on the RENDERED page (the only acceptable UI evidence; a grep of deployed JS is a deploy check, not done-evidence); (3) independent read-back of `GET /api/setter/training` (or the Supabase `training-agent-70fd17e5` doc row directly) showing the new cases flagged synthetic, a plausible category mix, and `used_reply_ids` untouched by synthetic cases; (4) rate one synthetic scenario live and confirm the ratings count and readiness inputs moved by re-fetching the training doc — never by trusting the page's own label; (5) a zero-reply fresh agent proven in tests to receive a full all-synthetic batch. **All 5, or it isn't done.** On any cap-hit, report the gap honestly — never declare done.

## Ground truth (verified 2026-07-14 — re-verify in Step 1, line numbers drift)

- **Files:** `app/setter.py` (training section from ~:2949; doctrine comment ~:2950 states the realism law this loop amends), `app/setter-train.html` (dead-end banner "No new real replies were available…" at :436, zero-scenario empty state `renderEmpty()` at :573), `app/test_setter.py`. Working copy = iCloud dir; **deploy repo = `~/navreo-signals`** (parallel sessions move branches — fetch+rebase before push; iCloud copy NEVER deploys anything). Live host: navreo-signals.onrender.com.
- **⚠ Suite is currently RED in the iCloud copy:** `python3 app/test_setter.py` dies at :3795 — `NameError: test_correction_remember_route_grows_memory` is called but not defined (a `…_merges_instructions` variant exists). Step 1 must determine whether this is iCloud drift vs the deploy repo and restore a green baseline BEFORE any new work, or "keep the suite green" is unfalsifiable.
- **Training engine shape:** doc row id `training-<agent_id>` (reserved-row pattern like `__settings__`/`__grading__`). Constants: `TRAINING_BATCH_DEFAULT` 8, `TRAINING_BATCH_MAX` 10, `TRAINING_MAX_UNANSWERED` 40, `TRAINING_MAX_UNANSWERED_SHARE` 20, `TRAINING_ACTIONABLE_SHARE` 0.8, `_TRAINING_ACTIONABLE_WEIGHTS` (real corpus counts: Interested 650, Information Request 482, Meeting Request 263, …).
- **Worker flow:** per-agent generation locks `_TRAINING_GEN_LOCKS` (~:3002); `_training_generate_threadmain` (~:3589) → `_training_generate_worker` (~:3624) selects via `_select_training_replies(doc, batch_size, allowed_campaign_ids)` (~:3204, share mode = campaign-scoped), builds cases (≤2 gpt-5-mini calls per scenario: classify + draft), then RELOADS the doc fresh before saving (`fresh_doc["used_reply_ids"] = … + new_used_ids` ~:3698 — the lost-update protection). Frontend polls until done (Render's ~100s edge timeout is why generation is a background daemon + poll, never a long request). All synthetic work must live INSIDE this same worker, under the same lock, same poll flow, same reload-before-save.
- **Scenario pipeline:** each case runs the exact same `classify`/`decide`/`draft_reply`/`lint_draft` pieces as grading, as-if master switch and agent mode were ON. No send path exists in the section.
- **Supabase logging pattern to reuse:** `server.py` already writes best-effort `provider_usage` rows (`sb("POST", "provider_usage", {...})`, ~server.py:4227) — the synthetic-generation usage log (agent, count, trigger) should follow this ledger pattern so lilly-data can query it. Evaluate per the signals-feature recording rule whether `provider_usage` or a dedicated table fits; pick and document.
- **Readiness:** synthetic answers count toward the readiness score exactly like real ones (user ruling 2026-07-14) — no weighting, no exclusion.
- **Gotchas (each cost a debug cycle before):** minted `navreo_session` cookie works on localhost+prod but the browser pane drops it — re-set via document.cookie; reply bodies can be full Outlook HTML — `clean_body()` before any length/classify; gpt-5-mini once emitted U+0019 — scrub post-draft; ALL interruptions on Render are redeploys; **no em-dashes in any new UI copy**.
- **Unknowns for Step 1:** exact shape of case objects and gists available for dedupe; whether the share-link page renders any per-case metadata today (badge insertion point); whether `provider_usage` schema fits a non-provider event or needs a `trigger` column/detail field.

## Steps

### Step 1 — Re-verify ground truth + restore green baseline
Sonnet execution agent: confirm every Ground-truth bullet against current code (line drift), resolve the three unknowns, and fix the pre-existing `NameError` so `python3 app/test_setter.py` exits 0 BEFORE any feature work (check `~/navreo-signals` to see if the fix already exists there — reconcile, don't fork). Snapshot the `training-agent-70fd17e5` doc row as a before-artifact (read-only — no deletions ever).
- **Done-rule:** (a) every bullet confirmed or corrected in writing; (b) full suite green on the working copy; (c) unknowns answered; (d) agent-70fd17e5 training-doc snapshot saved to the skill folder.

### Step 2 — Backend: synthetic scenario generator + doctrine amendment
Amend the section doctrine comment at setter.py:~2950: real replies remain verbatim-real; synthetic scenarios may invent the LEAD side only (name, company, inbound wording) and never agent-side facts (pricing, resources, availability); decision + draft still run the real pipeline with live brain and memory. Then build the generator: one gpt-5-mini call invents N lead-side scenarios following the 80/20 actionable/clear-negative mix biased to common simple types (Interested, Information Request, Meeting Request; Not Interested, Out Of Office). Prompt inputs: a sample of the agent's real archived replies as tone-and-shape reference — including already-used ones, campaign-scoped in share mode; for an agent with zero replies anywhere, fall back to the agent's brain, campaign copy, and offer context. Pass existing unanswered case gists so nothing duplicates. Each synthetic case gets an explicit provenance flag (e.g. `"synthetic": true`) in the training doc and contributes NOTHING to `used_reply_ids`. Each then runs through the real classify/decide/draft/lint pipeline exactly like a real case.
- **Done-rule:** unit-level proof (mocked LLM) that (a) generated cases carry the provenance flag; (b) `used_reply_ids` is byte-identical before/after a synthetic-only generation; (c) the category mix of a generated batch honours 80/20 within rounding; (d) the prompt payload contains reply samples when they exist and brain/copy/offer context when they don't; (e) existing-gist dedupe inputs reach the prompt; (f) the doctrine comment reads as amended.

### Step 3 — Backend: shortfall top-up inside the existing worker
Wire the generator into `_training_generate_worker`: after `_select_training_replies` returns, if `len(replies) < batch_size` (including 0), invent the shortfall synthetically. Same per-agent lock, same daemon thread, same poll-until-done contract (Render ~100s edge timeout), same reload-before-save lost-update protection — real `new_used_ids` still append; synthetic cases append to `cases` only. The 40/20 unanswered caps remain the only throttle: never generate past the applicable cap; no new spend cap.
- **Done-rule:** tests prove (a) shortfall top-up: 3 real + batch 8 → 8 cases, 3 real-flagged, 5 synthetic-flagged, exactly 3 new used ids; (b) pure-synthetic: 0 real → full all-synthetic batch (the zero-reply fresh-agent check, bar part 5); (c) cap respected: an agent at its unanswered cap generates nothing; (d) a concurrent save between load and save does not lose answers (reload-before-save still holds with synthetic in play).

### Step 4 — Supabase usage logging (signals-feature recording rule)
Log every synthetic generation event — agent id, synthetic count, trigger (`shortfall` | `zero_replies`), and share vs owner context — following the `provider_usage` ledger pattern (best-effort, never blocks the worker). Confirm lilly-data can answer "how many synthetic scenarios did agent X get this week" from it.
- **Done-rule:** (a) a generation run writes exactly one row with agent/count/trigger; (b) a failed log write does NOT fail generation; (c) a documented example query returns the row.

### Step 5 — Frontend: Practice badge + dead-end copy
`setter-train.html`: render a subtle "Practice" badge on synthetic cards (from the provenance flag), visible on client share links too. Replace the dead-end banner at :436 and the zero-scenario empty state at :573 so the trainer is NEVER told to wait — the copy says practice scenarios are being created and the flow continues into the normal poll. No em-dashes anywhere in the new copy. Real cards look exactly as before.
- **Done-rule:** on localhost, browser-rendered: (a) a mixed batch shows Practice badges on synthetic cards only; (b) the share-link view shows the same badges; (c) neither dead-end message can be reached when generation succeeds, and the replacement copy contains no em-dash characters (verified by grep of the new strings); (d) real-only batches render unchanged.

### Step 6 — Tests green
Extend `app/test_setter.py`: shortfall top-up, pure-synthetic zero-reply batch, provenance flags, `used_reply_ids` purity, readiness movement when a synthetic answer is rated (score inputs move exactly as a real answer would), usage-log row emission. Keep every pre-existing test passing.
- **Done-rule:** `python3 app/test_setter.py` exits 0 with all new tests present and zero pre-existing tests skipped or weakened.

### Step 7 — Deploy
Reconcile iCloud→repo, fetch+rebase `~/navreo-signals` main, commit, push, wait for Render live, marker-grep the deployed asset (deploy check only), then browser-verify the rendered live page (re-set `navreo_session` cookie if the pane drops it).
- **Done-rule:** (a) commit on origin/main; (b) unique marker present in the deployed asset; (c) the live setter-train page renders — a grep alone does not pass this.

### Step 8 — Live proof: the 5-check bar on agent-70fd17e5
Against PROD via the agent's existing share link, no deletions: (bar 2) request more scenarios, watch the poll complete, and screenshot a full batch containing Practice-badged cards on the rendered page; (bar 3) independently read `GET /api/setter/training` or the `training-agent-70fd17e5` doc row — new cases flagged synthetic, plausible category mix, `used_reply_ids` unchanged vs Step 1's snapshot except any REAL replies consumed; (bar 4) rate ONE synthetic scenario, re-fetch the doc, confirm answer count and readiness inputs moved; (bar 1 and 5) already proven in Step 6 — re-confirm suite green post-deploy. The synthetic cases STAY in the queue as genuine training material.
- **Done-rule:** all 5 bar parts pass with evidence recorded (screenshot, doc-row diffs, before/after readiness numbers). Zero rows deleted from the agent's training doc.

## Final report (always, both modes)

One summary: per-step pass/skip/FAILED with retry counts; the real numbers — test count before/after, synthetic vs real case counts in the live batch, category mix observed, readiness before/after the rated synthetic answer, usage-log rows written; artifacts — commit SHA, screenshot, training-doc snapshot path, example lilly-data query; anything deferred or FAILED, stated plainly.

## Hard don'ts

- Never add a send path — nothing in training may ever email a lead.
- Never fabricate agent-side facts in a synthetic scenario: no invented pricing, resources, availability, links, or offers. Lead side only.
- Never let a synthetic case touch `used_reply_ids`, and never mint fake reply ids.
- Never bypass the per-agent generation lock, the poll-until-done flow, or the reload-before-save protection — synthetic work lives inside the existing worker or not at all.
- Never add a new spend cap and never remove the 40/20 unanswered caps — they are the throttle.
- Never delete or reset anything on `agent-70fd17e5` — the live proof is additive; its synthetic cases remain as real training material.
- Never tell the trainer to wait in any UI copy, and never use an em-dash in new UI copy.
- Never trust the page's own labels for verification — bar parts 3 and 4 read the doc back independently.
- Never deploy from the iCloud copy or skip fetch+rebase; never declare done while any of the 5 checks fails or a retry cap was hit.
