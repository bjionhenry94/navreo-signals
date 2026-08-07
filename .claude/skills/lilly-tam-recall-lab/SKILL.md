---
name: lilly-tam-recall-lab
description: Static orchestration skill that fixes list-building's recall starvation — for each of 30 briefs it finds the HIGHEST-recall Prospeo/AI-Ark shape that still scores ≥70% on-brief, maps its pool (TAM) and volume-beat vs the old tight-shape baseline, proving populous niches yield tens-of-thousands not ~5K. TAM-mapping only: ≤25 rows pulled per shape, never a full list. One fixed step list, each with a checkable done-rule, credit caps, and a Loop Training Mode toggle. Use when the user says "run the recall lab", "fix list-building volume", "maximise recall at 70%", "map the recall-max TAMs", or "/lilly-tam-recall-lab".
---

# lilly-tam-recall-lab

Our "proven" TAM methodology holds ≥70% accuracy but returns unrealistically small pools (B2B SaaS ~5K when the real pool is ~30K) because it over-narrows for precision it doesn't need — `lilly-aiark-methodology-loop` RESULTS law #1 trades −90-95% recall for a precision cushion. This loop optimises the OTHER axis: **among shapes that hold ≥70% on-brief, take the biggest pool.** Two providers only (Prospeo + AI Ark; no Ocean — user 2026-07-13). Static loop — fixed steps, each has a done-rule, Training Mode controls the pauses.

---

## ⚙ Loop Training Mode: **OFF** (flipped by user 2026-07-13)   ← flip this one line to ON to pause at every step

    LOOP_TRAINING_MODE = OFF       # ON = approve every step · OFF = run autonomous

**ON:** pause at EVERY step boundary and wait for explicit approval before continuing. Before starting a step, check its done-rule first — if it already passes, report "Step N already passes, skipping" and move on. Only re-run steps whose done-rule fails. Show what you're about to do (and what it will spend) before doing it.

**OFF:** run all steps end-to-end, no pauses. Done-rule checks, skip-if-passing, and retry caps stay exactly the same — only the pauses go.

**Retry cap (both modes):** each step retries **max 3** times against its done-rule; per-brief shape iterations cap at **3** (matches the prior lab). On cap-hit: record FAILED with the reason, continue to independent steps, surface every FAILED item in the final report. Never silently exceed. Never declare done on a cap-hit.

---

**Spend gate (both modes, non-negotiable):** the only thing spent is API credits. Hard caps **5,000 Prospeo + 5,000 AI Ark** for the whole run. Ledger EVERY billed call in `RUN-LOG.md`. Pool sizes are read from `total_count`/`totalElements` (cheap); samples are **≤25 rows per shape — NEVER a full-list extraction**. `INVALID_FILTERS`/`NO_RESULTS` (Prospeo) are free — use them for enum discovery. At 80% of either cap: pause+report (ON) / stop+report (OFF). A cap-hit before all 30 briefs are mapped = report **FAILED with the exact gap**, never "done". In Training Mode ON, show the intended call + its credit cost before each paid probe.

---

## THE GOAL

A validated recall-maximised methodology that, for each of 30 briefs, reports the **largest company pool (TAM) whose ≤20-row sample still scores ≥70% on-brief** across Prospeo + AI Ark — proving populous niches yield realistic volumes without dropping below 70%.

> Done = **≥24/30 briefs meet their band-appropriate bar** — populous (broad+mid): recall-max pool **≥70% accuracy AND ≥1.5× the old tight-shape baseline**; niche/ultra: **≥70% accuracy OR correctly routed as a structural fail** — with the credit ledger inside caps and every number read independently, not from a provider success flag. Anything less, or a cap-hit, = report the gap honestly; do not declare done.

---

## Ground truth (verified 2026-07-13 — re-verify in Step 1, indexes/enums drift)

- **Keys:** `~/.navreo-keys.env` → `PROSPEO_API_KEY`, `AI_ARK_API_KEY`.
- **Prospeo** `POST https://api.prospeo.io/search-company`, `-H "X-KEY: $PROSPEO_API_KEY"`, body `{"page":1,"size":25,"filters":{…}}`. Response `{error, free, pagination.total_count, results[].company{name,domain,industry,description,employee_range,…}}`. **1 credit/page**; `size` is fixed at 25; `INVALID_FILTERS`/`NO_RESULTS` are FREE. Native classifiers (all top-level under `filters`): `company_type.subtypes.include` (27 values incl SaaS, Agency, Consulting, Construction, Logistics, FinTech, E-commerce…), `company_type.business_model` (b2b/b2c/…), `company_type.has_subscription`; `company_attributes` (~40 bool flags incl `b2b`, `uses_ai`, `has_soc2`); `company_industry.include` (**strict LinkedIn strings** — "Marketing Services","Advertising Services" work; "Marketing" → INVALID_FILTERS); `company_headcount_range` buckets `["11-20","21-50","51-100","101-200",…]`; `company_location_search.include` (full English country names).
- **PROVEN probes (reproduce these ± index drift):** B2B SaaS US 11-200 → `subtypes:["SaaS"]` alone = **29,804 @ ~88%**; `+business_model:b2b +has_subscription` = 4,711 @ ~92%. Marketing agencies US+UK 11-200 → `company_industry:["Marketing Services","Advertising Services"]` alone = **28,345 @ ~76%**; `∩ subtypes:["Agency"]` = 13,513 @ ~92%; `subtypes:["Agency"]` alone = 57,415 (too broad — all agency types). **Recall-max correctly prefers the looser shape that still clears 70%.**
- **AI Ark** FILTERS-ONLY — `lookalike` is **permanently banned** (user "once and for all"). `mcp__ai-ark__company_search` with `industry` enums (validate via `mcp__ai-ark__industry_search`) + `excludeIndustry` + altitude-matched self-ID keyword synonyms on `NAME,KEYWORD` (add `DESCRIPTION` for broad briefs only — it poisons niche gates). **~1 credit/ROW.** Fire `size:1` for `totalElements`, then `size:10-20` for the sample. Offset cap ~10K → page **≤950** (deeper = 0 rows). Nested `requestBody` via MCP is **silently ignored while still billing** — never use it. No domain-exclude arg → dedup client-side.
- **Baselines to beat** live in `~/.claude/skills/lilly-aiark-methodology-loop/RESULTS.md` (B2B SaaS ~11,100; Marketing agencies ~10,200; per-brief tight-shape numbers). The 20 briefs live in that skill's `BRIEFS.json`.
- **Standing laws (honor, don't rediscover):** size the market GLOBALLY then apply geo/headcount as POST-extraction labels — never separate per-tier filter queries (sharding collapsed a pool 6.6-11×, `feedback_tam_tier_is_postlabel_not_filter`); keyword phrases say what the company IS, not buyer vocabulary; indexes near-disjoint (0.75-6.4% overlap) so Prospeo ∪ AI Ark ≈ additive; excludes are NOT free precision (reduced it in 3/6 Prospeo re-probes) — probe each, keep prior shape as fallback.
- **Structural-fail shapes (route away, don't chase iterations):** brand/product briefs (AI Ark ~40-50% ceiling → Prospeo B2C flags); capability-flooded niches (defining activity is a tool of a bigger profession); micro-pools <20 drowned by adjacent vocabulary (census + `lilly-lead-score` triage). Flag + route + **exclude from the volume denominator**.
- **Scoring:** `lilly-lead-score` semantics on the returned rows (name/domain/industry/description); precision = ✅ ÷ scored; borderline ⚠️ never counts; **≥70% = pass**.
- **Unknown until Step 1:** the 10 new populous briefs (draft for user veto); current AI Ark `industry` enum spellings; whether index drift moved the two proven anchors.

---

## THE STEPS

### Step 1 — Re-verify ground truth + build the 30-brief set
Load the 20 briefs from `lilly-aiark-methodology-loop/BRIEFS.json`. Draft **10 new populous/broad briefs** (big B2B categories × large geos — e.g. B2B SaaS UK, IT/MSP US, digital agencies AU, recruitment agencies UK, e-commerce brands… avoid known structural-fail shapes) and, in Training Mode ON, get user veto. Re-fire the two PROVEN anchor probes (1 Prospeo credit) to confirm index drift hasn't broken them. Write `BRIEFS-30.json`.
- **Done-rule:** `BRIEFS-30.json` holds exactly 30 briefs each with `{id, band, brief, dm_roles, expected_magnitude, tight_baseline}` (baseline copied from prior RESULTS or `null` for the 10 new); AND the B2B-SaaS anchor probe returns `subtypes:["SaaS"]` total_count within ±25% of 29,804 (else record drift and update the anchor before proceeding).

### Step 2 — Per brief: run the recall recipe, keep the biggest ≥70% shape
For each brief, pick the path by altitude: **(A) Classifier-first** where a native subtype/industry fits — lead with the LOOSEST defensible shape (`subtypes` alone, or `company_industry` LinkedIn-enum alone) + headcount + geo; if the ≤20-row sample scores <70%, add exactly ONE narrowing layer and re-gate; among all shapes ≥70% keep the BIGGEST pool. **(B) Broad-net subtractive** where no clean native subtype exists (MSPs, cold-chain, SAP consultancies) — broadest defensible net, then add excludes as 1-credit probes to lift precision to ≥70% from below, keeping the prior shape as fallback. Read `total_count`/`totalElements` for the pool; pull ≤20-25 rows; score via `lilly-lead-score`. Log every billed call + credits to `RUN-LOG.md`. Max 3 shape iterations/brief.
- **Done-rule:** each brief has, in `RUN-LOG.md`, ≥2 scored shapes (the chosen recall-max one + at least one comparison — a looser shape that scored <70% OR the proven-loosest), the chosen shape's pool size, its sampled accuracy ≥70% (or the brief flagged structural-fail with its route), and no shape pulled >25 rows.

### Step 3 — Union the two providers per brief
Where both Prospeo and AI Ark returned a ≥70% shape, dedup by **canonical domain** (lowercase, strip `www.`/protocol) and report the union pool = |Prospeo ∪ AI Ark|, not a sum. Where only one ran, that IS the pool.
- **Done-rule:** every brief row in `RESULTS-30.md` shows per-provider pool + the deduped union number, and a spot-check of one union brief confirms overlapping domains were removed (union < Prospeo + AI Ark by the observed overlap).

### Step 4 — Baseline compare + band-bar pass/fail
For each brief compute `× multiple = recall-max union pool ÷ tight_baseline`. Apply the band bar: populous (broad+mid) needs ≥70% acc AND ≥1.5× baseline; niche/ultra needs ≥70% acc OR correct structural-fail routing. For the 10 new briefs with `null` baseline, fire ONE tight self-ID-keyword shape as the baseline probe.
- **Done-rule:** every brief row carries `{recall-max pool, sampled acc, tight_baseline, ×multiple, band, PASS/FAIL/ROUTED}`; structural-fail briefs are marked ROUTED and excluded from the volume denominator.

### Step 5 — Write RESULTS-30.md + METHODOLOGY.md, compute the composite
Assemble `RESULTS-30.md` (the full per-brief table + credit totals) and `METHODOLOGY.md` (the locked recall-max recipe: the altitude decision tree, per-provider loosest-defensible shapes, the ≤20-row gate, union logic, dual-number TAM). Hand-re-score a **random 5 briefs** to confirm the automated scores match within ±1 row.
- **Done-rule (lettered):** (a) `RESULTS-30.md` has all 30 rows; (b) composite pass = **≥24/30** meet their band bar; (c) hand-re-score of 5 random briefs matches automated ±1 row; (d) `RUN-LOG.md` totals show Prospeo ≤5,000 AND AI Ark ≤5,000; (e) `METHODOLOGY.md` states the recipe with the two proven anchors as worked examples. Any of (a)-(e) failing = report the gap, not done.

### Step 6 — Fold-back (HELD — user sign-off required, NOT run inside the loop)
Do NOT edit `lilly-tam-mapper` / `lilly-prospeo-list-builder` / `lilly-ai-ark-list-builder` inside this loop. After the user signs off on `RESULTS-30.md`, fold the locked recipe in as a separate action.
- **Done-rule:** the final report ends with an explicit "AWAITING SIGN-OFF to fold into production skills" line and zero production-skill files were modified by this run.

---

## Final report (always, both modes)

One summary: steps passed/skipped/FAILED; the composite **N/30** with the band-bar breakdown; the headline per-brief numbers (recall-max pool, accuracy, baseline, ×multiple) for the populous briefs; total credits spent (Prospeo / AI Ark) vs the 5,000 caps; artifact paths (`BRIEFS-30.json`, `RUN-LOG.md`, `RESULTS-30.md`, `METHODOLOGY.md`); every ROUTED structural-fail brief; and the "AWAITING SIGN-OFF" fold-back line. Name the real numbers — "a summary" is not a spec.

## Hard don'ts

- **Never pull a full list.** Max 25 rows per shape — this is TAM mapping, not extraction (user 2026-07-13).
- **Never exceed 5,000 Prospeo or 5,000 AI Ark credits**; ledger every billed call; a cap-hit is FAILED-with-gap, never done.
- **Never use ANY lookalike feature on EITHER provider** (user 2026-07-13: "they both suffer from decay") — AI Ark `lookalike` (and its nested `requestBody`, silently ignored while billing) AND Prospeo `company_lookalike`/`icp_text` are all banned. Filters, classifiers, and self-ID keywords only.
- **Never request emails or contact enrichment** (user 2026-07-13): no AI Ark `email_finder`/`people_search`/`export_single`, no Prospeo email endpoints — TAM mapping needs company fields only; email reveal is paid weight this lab never uses.
- **Never shard geo/headcount at the filter level** — size globally, tier as post-labels.
- **Never score off a provider count or success flag** — score the actual returned rows; borderline never counts.
- **Never chase a structural-fail shape** (brand/capability-flooded/micro-pool) past its route — flag and exclude from the denominator.
- **Never edit production skills inside this loop** — fold-back waits for user sign-off (Step 6).
- **Never exceed a retry/iteration cap or report done while any done-rule fails** — surface the gap.
