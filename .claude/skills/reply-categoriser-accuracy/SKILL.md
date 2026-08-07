---
name: reply-categoriser-accuracy
description: Static orchestration skill that audits 3-4 months of Smartlead replies for mis-categorised non-positives, diagnoses and kills the "lead gets re-categorised after first tag" bug, upgrades the categoriser prompt in the Make scenario (Navreo 9251436), and proves the fix by replaying the same messages plus a positive control sample through the new prompt. Fixed step list, checkable done-rules, retry caps, Loop Training Mode toggle. Use when the user says "audit the reply categoriser", "find mis-categorised replies", "leads are getting re-tagged", "fix the categoriser prompt", or "/reply-categoriser-accuracy".
---

# reply-categoriser-accuracy

Find every reply from the last 3-4 months that the categoriser tagged as non-positive but should have been positive, fix the Make scenario so (a) the prompt categorises better and (b) a lead is only ever categorised ONCE — on the first reply ever received — then prove both fixes by replay. Static loop: fixed steps, each with a done-rule, Loop Training Mode controls pausing.

**Sibling skill:** `reply-categoriser-hardening` owns *resilience* (scenario never auto-deactivates). This skill owns *accuracy*. Do not undo any hardening (statusCode guards, stopOnHttpError:false, dlq) while editing.

---

## ⚙️ LOOP TRAINING MODE  →  **OFF**

Flip it by editing this one line:

    LOOP_TRAINING_MODE = OFF       # ON = approve every step · OFF = run autonomous

**When ON**
- Pause at the end of **every** step and wait for my explicit approval before starting the next.
- Before running a step, check its done-rule first. **If it already passes, skip it** — say so and move on.
- Only (re-)run steps that fail their done-rule.
- Retry cap applies (below). Never loop a step forever.

**When OFF**
- Run all steps autonomously, no pauses.
- Still check every step's done-rule and still honour the retry cap. Report at the end, not between steps.

**Retry cap (both modes):** any single step retries **max 3** times against its done-rule. On cap-hit, stop that step, record it FAILED with the reason, keep going, surface it in the final report. Step 6 (prompt verification) has its own cap: **max 3 prompt-iterate→re-replay rounds**, then stop and report the residual error rate.

---

## THE TARGET

**Scenario:** Navreo `9251436` (Make zone `eu2.make.com`, org `1634255`, team `536258`, hook `4135325`, Smartlead key `a8f9359c…`). Flow: `EMAIL_REPLY` webhook → GET `/leads/?email=` → gate "only if no existing category" → GET message-history → **GPT-4o-mini into 8 buckets** → POST `/category` → Slack positives. Router after module `29`: routeA = categorise flow, routeB = 🚨 alert-only re-reply module `51` (must NEVER tag).

Asteri `9187631` shares the same categoriser prompt (tagging only, no Slack) — apply the final prompt + once-only fix there too, but all audit/verification work runs on Navreo.

**Editing:** Make MCP — `scenarios_get` → `validate_blueprint_schema` → `scenarios_update`; inspect with `executions_list` / `executions_get-detail`. Direct-API fallback needs a Make token that is NOT in `~/.navreo-keys.env` — ask Bjion only if the MCP path fails.

**Category-id map** (Smartlead `/leads/fetch-categories`): 1 Interested, 2 Meeting Request, 3 Not Interested, 4 Do Not Contact, 5 Information Request, 6 Out Of Office, 7 Wrong Person, 78386 Re: Interested, 83039 Call Booked, 125938 [Manual] Interested. **Positive set** = `{1, 2, 5, 78386, 83039, 83731, 86207, 125938}`. **Known quirk to preserve:** the scenario posts AI-"Interested" AND AI-"Meeting Request" both as `category_id 2`; do not change that mapping without explicit user sign-off.

**Do-no-harm rules:**
- **Never replay verification through the live scenario** — that would re-POST categories and re-post Slack. Verification is offline: same model + candidate prompt called directly, verdicts compared on paper.
- **Never re-tag already-categorised leads in Smartlead** as part of this skill's autonomous flow (additive-never-replace). Historical corrections are a proposal in the final report; apply only on explicit per-batch approval.
- **Respect the 200 req/min Smartlead cap** — pull the reply corpus from the Supabase data layer first (replies are synced there; see `lilly-data`); hit the Smartlead API only for gaps, throttled.
- Keep all of `reply-categoriser-hardening`'s error-handling intact: `stopOnHttpError:false` everywhere, `statusCode = 200` filter guards, no `sequential:true`.

---

## THE STEPS

### Step 1 — Pull the reply corpus (last 4 months)
- Window: replies received in the last 4 months (from today back). Source order: Supabase `replies` / contact_history via `lilly-data` first; fill gaps from Smartlead master-inbox / message-history APIs, throttled.
- For each reply capture: lead email, campaign, reply body (first inbound message text), current Smartlead `lead_category_id`, reply timestamp, and — where recoverable — whether the category changed after first assignment.
- Save to scratch as `reply_corpus.csv`.
- Done-rule: `reply_corpus.csv` exists, covers the full window, and every row has a non-empty body + current category id. Row count and per-category counts reported.

### Step 2 — Audit: find mis-categorised non-positives
- Re-judge **every** reply whose current category is outside the positive set, using a strong LLM judge with the reply body + short thread context. Judge question: "should this have been tagged positive (Interested / Meeting Request / Information Request / Call Booked)?" — verdict + one-line reason each.
- Anything the judge flags positive is a **suspected false negative**. Also spot-check 30 random currently-positive replies to estimate false positives (context only, not the target).
- Per `feedback_reply_category_label_drift`: report the headline as a single count + rate over the whole window; do not trend one category across sub-periods.
- Done-rule: 100% of non-positive replies in the corpus judged; a `false_negatives.csv` exists with lead, campaign, body excerpt, current tag, judged tag, reason; headline numbers reported (X of Y non-positives mis-categorised, Z% of all replies).

### Step 3 — Diagnose the re-categorisation bug
- The invariant: a lead is categorised ONCE, on the first reply ever received. Find where that breaks. Pull the Navreo blueprint (`scenarios_get`) and inspect the "only if no existing category" gate: what exactly does it check (per-campaign `lead_category_id` vs global? what happens when the GET `/leads/?email=` lookup fails or returns statusCode ≠ 200 — does the gate fail-open?). Cross-check `executions_list` / `executions_get-detail` for concrete leads from Step 1 whose category changed: find the execution pair (first tag → overwrite) and identify which module re-POSTed.
- Candidate culprits to rule in/out: gate fails open on lookup 429/404; gate checks the wrong campaign's category when a lead sits in multiple campaigns; routeB mis-wired to tag; a second writer (another scenario or manual inbox tagging).
- Done-rule: root cause named in one sentence with evidence (execution IDs or blueprint line showing the overwrite path), or every candidate explicitly ruled out with evidence and the change is confirmed to come from outside the scenario (then say so and treat Step 4's once-only gate as belt-and-braces).

### Step 4 — Fix the scenario: better prompt + once-only gate
- **Prompt:** rewrite the GPT-4o-mini categoriser prompt using the Step 2 false negatives as the improvement spec — add the misread patterns (e.g. soft interest, "send me info", replies with questions, forwarded-to-colleague, positive-with-objection) as explicit rules and few-shot examples. Keep the same 8 output buckets and the id-2 quirk mapping.
- **Once-only gate:** make categorisation strictly first-reply-only. The gate must fail CLOSED — if the existing-category lookup errors, rate-limits, or returns an unexpected shape, skip categorisation (never overwrite). If a lead has ANY existing category in the campaign, routeA must not run; the re-reply case belongs to routeB (alert-only) exclusively.
- Apply to Navreo `9251436` via `validate_blueprint_schema` → `scenarios_update`; mirror prompt + gate to Asteri `9187631`. Preserve all hardening settings byte-for-byte.
- Done-rule: both blueprints updated and schema-valid; diff shows ONLY the prompt text and the gate conditions changed; both scenarios ACTIVE; a synthetic re-reply for an already-categorised lead routes to routeB and produces no `/category` POST.

### Step 5 — Verify: replay the false negatives (offline)
- Run every Step 2 false-negative message through the NEW prompt (direct LLM calls, same model as the scenario — never through the live scenario). Compare output bucket to the judged-correct bucket.
- Done-rule: ≥ 90% of the false-negative set now lands in the correct (positive) bucket. Below that → iterate the prompt and re-replay (counts toward Step 6's 3-round cap, since the control must re-run too).

### Step 6 — Verify: positive + random control samples (no regressions)
- Replay through the new prompt: (a) a random sample of ≥ 30 previously-positive replies — they must stay positive; (b) a random batch of ≥ 50 replies across all categories (OOO, wrong person, not interested included) — verdicts must match a fresh LLM-judge reading of each.
- Done-rule: ≥ 95% of the positive control stays positive AND ≥ 90% agreement on the random batch. If either fails, iterate the prompt and re-run Steps 5+6 together — **max 3 rounds**, then stop and report the best prompt's residual numbers.

### Step 7 — Final report + historical corrections proposal
- Report: headline mis-categorisation count/rate from Step 2, the re-categorisation root cause and fix from Steps 3-4, before/after accuracy from Steps 5-6, and per-step DONE / SKIPPED / FAILED lines.
- Attach the list of leads whose historical tag should be corrected to positive — as a **proposal only**. Apply corrections (via `update_lead_category`) only after explicit approval, in named batches, never silently.
- Done-rule: report delivered; no historical tag was changed without an explicit user "yes" in this conversation.

---

## HOW TO RUN

1. Read the mode line above. If **ON**, one step at a time, stop for approval after each, skip steps whose done-rule already passes. If **OFF**, run all seven in order, no pauses.
2. For each step, actually check the done-rule against artefacts (CSVs in scratch, blueprint diffs, execution logs) — never mark a step done on intent. Retry up to 3× on failure, then mark FAILED and continue.
3. Steps 4 is the only live write to Make; Step 7's tag corrections are the only possible Smartlead writes and are approval-gated regardless of mode.

## OVERALL DONE-RULE

- The 4-month audit is complete with a headline mis-categorisation count and a `false_negatives.csv`.
- The re-categorisation path is identified and closed: an already-categorised lead can never be re-tagged by the scenario (gate fails closed; routeB alert-only).
- New prompt live in both scenarios, both ACTIVE, hardening intact.
- Replay proof: ≥ 90% of former false negatives corrected, ≥ 95% of positive controls unchanged, ≥ 90% random-batch agreement — or 3 rounds exhausted and residuals reported honestly.
- Final report delivered; any historical re-tagging happened only with explicit approval.
