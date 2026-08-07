---
name: lilly-aiark-methodology-loop
description: "Static orchestration loop that learns, proves, and ships ONE consistent AI Ark methodology for BOTH company TAM mapping and decision-maker finding, then bakes it into lilly-tam-mapper, lilly-ai-ark-list-builder, and lilly-decision-maker-finder-v2. Fixed 7-step plan with per-step done-rules, retry caps, a 2,500-AI-Ark-credit hard budget, and a Loop Training Mode toggle (ON = pause for approval at every step). Verification = 20 briefs from broad to niche, each mapped to a TAM estimate + DM count, target ≥70% accuracy consistently with realistic TAM magnitudes (broad SaaS 10K+, niche in the hundreds). Use when the user says 'run the AI Ark methodology loop', 'prove the AI Ark approach', 'calibrate AI Ark TAM + DM', or '/lilly-aiark-methodology-loop'."
---

# Lilly AI Ark Methodology Loop

## ⚙️ LOOP TRAINING MODE — the toggle (edit this line to flip it)

```
LOOP_TRAINING_MODE: ON
```

- **ON (default):** PAUSE at every step boundary and wait for the user's approval before continuing. SKIP any step whose done-rule already passes (say so, don't re-run it). RE-RUN only steps that fail their done-rule. Retry caps below are hard — the loop can never spin forever.
- **OFF:** run all 7 steps autonomously, no pauses. Done-rule checks and retry caps still apply exactly as written; the only thing removed is the approval pause.
- Flip it by editing the `LOOP_TRAINING_MODE:` line above (or the user says "training mode off/on" at invocation, which overrides the file for that run only).

## Goal

One consistent, measured AI Ark methodology that covers BOTH halves of list building — **company mapping** (TAM) and **decision-maker finding** — that maximises volume while holding ICP accuracy, proven on 20 briefs, then written into the three downstream skills so every future run uses it identically.

**Done-rule for the whole loop:** ≥70% scored accuracy on at least 16 of 20 test briefs (companies AND the DM sample), TAM magnitudes realistic per band (broad categories like B2B SaaS ≥10K companies; ultra-niche allowed in the hundreds), total AI Ark spend ≤2,500 credits, and all three skills updated with the final recipe.

## Standing hard rules (inherited — never violate, never re-test)

1. **`lookalike` is PERMANENTLY BANNED** (user directive 2026-07-10). Filters only: `industry` (validated enums), free-text `industries`, `productAndServices`, `naics`/`sic`, `location`, `minEmployees`/`maxEmployees`, founded/revenue/funding ranges.
2. Billing ≈ **1 credit per ROW returned**. Counts = `size:1`. Never size:50 probes. Log every call's rows to the run ledger.
3. `excludeType`/`type` enum values UPPERCASE. Nested requestBody via the MCP tool is SILENTLY IGNORED while billing — never use it. REST `keyword` is tier-gated (401); the MCP `keyword` param works.
4. Results are relevance-sorted and the head over-represents big brands — judge population quality on a DEEP page (offset 3,000+ when the pool allows), not page 1.
5. DM finding = REST `contact.experience.current.title` (SMART mode) + the **mandatory company-ID join post-check** (keep only people whose current-at-target title matches). Flat `title`/`seniority` params are banned for role briefs (~33% precision).
6. Accuracy scoring is ALWAYS delegated to `lilly-lead-score` (companies) and dm-finder-v2's title matcher (DMs) — no inline pattern-matching.
7. Docs source of truth: MCP resource `ark://guide/company-search` and https://docs.ai-ark.com/ (site hides schema behind client-side JS — prefer the MCP resource).

## Budget ledger

Hard ceiling: **2,500 AI Ark credits for the entire loop.** Maintain `RUN-LOG.md` in this skill folder: one line per API call (`step | brief | call shape | rows returned | credits | running total`). Check the running total BEFORE every call; if a call would breach 2,500, stop, report, and end the run regardless of step. Soft alarms at 1,250 (half) and 2,000 — surface them in the next update. Per-brief planning budget: ~100 credits (20 briefs × ~100 = 2,000, leaving ~500 for Step 1/2 probes and retries).

---

## The 7 steps (fixed order — no improvised steps)

### Step 1 — Re-mine the filter surface
Read `ark://guide/company-search` (+ `industry_search` for enum validation, `location_search` for geo strings) and diff against `lilly-tam-methodology-lab/PLAYBOOK-aiark.md`. Produce `FILTER-CATALOGUE.md` in this folder: every usable company_search filter and people-search filter, its type, validated example value, and any new filters the playbook doesn't know about.
- **Done-rule:** `FILTER-CATALOGUE.md` exists, lists ≥10 company filters + the people current-role shape, and every enum-type filter has one validated example.
- **Retry cap:** 2. Probes here spend from the ledger (size:1 only).

### Step 2 — Draft METHODOLOGY v1
Write `METHODOLOGY.md` in this folder — the single recipe both halves will follow:
- **Company mapping recipe:** filter stack order (industry enum → layer naics/sic/productAndServices → keyword self-ID via MCP `keywordMode:WORD`, `keywordSources:NAME,KEYWORD` → location/size), then `size:1` count → `size:10` scored gate (`lilly-lead-score`, hard abort <50%, tighten and re-gate) → deep-page sample to confirm population quality.
- **TAM estimate formula:** `company TAM = total_count × gate precision` (flag that totalElements display-caps at 10,000 — note "10K+" when capped).
- **DM recipe:** for a sample of gated companies, REST current-title search + company-ID join; **DM TAM = company TAM × measured avg on-brief DMs per company** (measured, not assumed ×N).
- **Volume-vs-accuracy dial:** the documented loosen/tighten moves (drop a filter layer for volume; add keyword self-ID or naics for accuracy) with when-to-use rules.
- **Done-rule:** `METHODOLOGY.md` exists with all four sections and no `lookalike` anywhere.
- **Retry cap:** 2.

### Step 3 — Build the 20-brief test set
Write `BRIEFS.json`: 20 briefs in 4 bands of 5 — **broad** (e.g. B2B SaaS US, marketing agencies US+UK), **mid** (e.g. e-commerce agencies DACH, MSPs UK), **niche** (e.g. ITAD providers EU, Amazon PPC agencies), **ultra-niche** (e.g. drone-inspection services AU, veterinary-clinic software). Each entry: brief text, band, DM role set, and an `expected_magnitude` sanity band (broad ≥10,000; mid 2,000–10,000; niche 300–2,000; ultra-niche 50–500 — judgement values, used only as realism checks).
- **Done-rule:** `BRIEFS.json` has 20 entries, 5 per band, each with all four fields. Zero credits spent this step.
- **Retry cap:** 1.

### Step 4 — Run the 20-brief loop (the expensive step)
For each brief, apply METHODOLOGY.md verbatim:
1. `size:1` count → `size:10` gate → score via `lilly-lead-score`.
2. If gate <70%: tighten per the dial and re-gate. **Max 3 filter iterations per brief**, then record the brief as FAILED with its best accuracy + what leaked, and move on.
3. On a passing gate: pull one deep-page `size:10` sample, score it, record blended accuracy; compute TAM estimate.
4. DM half: pick 3 gated companies, run the DM recipe, score titles, record DM accuracy + avg on-brief DMs/company; compute DM TAM.
5. Append a row to `RESULTS.md`: brief | band | iterations | company accuracy | TAM estimate | realistic? (vs band) | DM accuracy | DM TAM | credits.
- **Done-rule (per brief):** a RESULTS row exists with both accuracies and both TAM numbers (FAILED rows count as complete — the loop records failure, it doesn't hide it).
- **Done-rule (step):** all 20 rows present, ledger ≤2,500. In Training Mode ON, pause after **every band of 5** (not every brief) for approval — 4 pauses inside this step.
- **Retry cap:** 3 filter iterations per brief (above); 1 full re-run allowed per brief only if METHODOLOGY.md changed after its first run.

### Step 5 — Consistency verdict + methodology v2
Read RESULTS.md. Pass = ≥16/20 briefs at ≥70% on BOTH accuracies AND every passing brief's TAM inside (or explainably near) its magnitude band. If failing: diagnose the common leak across failed briefs, patch METHODOLOGY.md (v2), and re-run ONLY the failed briefs through Step 4 (their re-run allowance).
- **Done-rule:** verdict PASS recorded at the top of RESULTS.md with the headline numbers.
- **Retry cap:** 2 methodology revisions. If still failing after 2, stop and present the best methodology + honest failure analysis to the user — do not keep burning credits.

### Step 6 — Codify into the three skills
Edit, additively (never delete unrelated content):
- `lilly-tam-mapper/SKILL.md` — replace Stage 3's procedural text with the proven company recipe + TAM formula (keep the lookalike-ban banner).
- `lilly-ai-ark-list-builder/SKILL.md` — same recipe as the skill's canonical flow.
- `lilly-decision-maker-finder-v2/SKILL.md` — add the measured DM-TAM formula + any current-role matcher improvements learned in Step 4.
- **Done-rule:** all three files contain the recipe, agree with each other and METHODOLOGY.md, and contain no `lookalike` usage. The publish-skill hook fires on each write (expected).
- **Retry cap:** 2.

### Step 7 — Report + memory
Final message: verdict, per-band accuracy table, the 20 TAM/DM-TAM estimates, credits spent vs 2,500, what changed in each skill. Save one memory (`project` type) recording the proven methodology headline + where it lives.
- **Done-rule:** report delivered; memory file + MEMORY.md line written.
- **Retry cap:** 1.

---

## Loop mechanics (both modes)

- At every step boundary: check the step's done-rule FIRST. Already passing → announce "Step N already passes, skipping" and move on (in ON mode this still pauses for acknowledgement).
- A step that fails its done-rule after its retry cap → STOP the loop, report exactly what failed and what was tried, and hand to the user. Never silently continue past a failed step.
- Budget breach at any point → STOP immediately (see ledger rules).
- State lives in this folder (`FILTER-CATALOGUE.md`, `METHODOLOGY.md`, `BRIEFS.json`, `RESULTS.md`, `RUN-LOG.md`) so a re-invocation resumes wherever the done-rules say — the skill is safely re-runnable.
