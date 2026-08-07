# PLAYBOOK — Prospeo `/search-company`  ·  status: **VALIDATED** (hold-out 83% after 1 revision)

Measured 2026-07-09 on brief A (UK construction contractors, hard-filterable) and brief B (dev agencies + AI/DX consultancies, soft-category); hold-out-validated on brief C (Amplifyy physical-product brands) after one revision. 24 credits total.

## 0.4 · NATIVE ENTITY CLASSIFIERS — fire these FIRST (docs-mined + live-validated 2026-07-09)
Prospeo has native entity-type filters that replace the keyword-altitude workaround as the opening move:
- **`company_type.subtypes.include`** — 27 live-confirmed values: AI/ML, Agency, Construction, Consulting, Data/Analytics, E-commerce, Education, FinTech, Food & Beverage, Franchise, Government, Hardware, HealthTech, Hospitality, Insurance, Legal, Logistics, Manufacturing, Marketplace, Media/Publisher, Non-Profit, Platform, Professional Services, Real Estate, Retail, **SaaS**, Telecommunications.
- **`company_type.business_model`** — b2b, b2b2c, b2c, d2c, franchise, government, marketplace, non_profit (we had only ever used B2C).
- **`company_type.has_subscription`** (bool).
- Measured on the B2B SaaS brief: subtypes SaaS + b2b + has_subscription + headcount = **8,968 @ ~80%** vs icp_text 455 @ 100% and keywords 10,652 @ 50% — **20× the precise pool**. Native+icp_text together over-anchors to a sub-niche (278) — use native alone for volume, icp_text as a separate additive approach.
- **New firing order: 1) native subtype/business-model filter → 2) icp_text (services) or category keywords+flag (brands) → 3) keyword page.** Keywords drop to third.
- Other docs-mined levers now available (shapes in `docs-prospeo-inventory.md`): `company_revenue` (bucket ladder), `company_headcount_growth` (hiring velocity), `company_job_posting_hiring_for` (native hiring signal), `company_headcount_by_department`, `company_founded` `{min,max}` (the recency lever brief 2 needed!), `company_technology`. `company_intent` remains dead (INTERNAL_ERROR).

## 0.3 · Round-2 refinements (2026-07-09, 10-brief validation)
- **icp_text is the PRIMARY lever on services briefs, keywords secondary** — icp_text went 100/100/100/70% (SaaS, MSPs, HVAC, freight) while the paired keyword pages collapsed to 0-50% on the same briefs. Keywords fail wherever STAFFING/RECRUITING firms share the vocabulary ("accounting firm", "managed IT services", "IT support" → placement-agency swamp). Fire icp_text first; keyword page second; keep whichever clears 70%.
- **NAICS: narrow codes only.** 561720 janitorial ≈ 100%; 311920 coffee → generic food-mfg 0%; 541940 veterinary → labs/wholesalers 30%. Probe page-1 per code and expect broad-mapping codes to fail.
- **Serve-qualifier briefs ("X firms FOR e-com clients") have NO filter lever** — entity keywords score 0-25% (recruiter swamp), icp_text finds perfect entities but loses the clientele qualifier. The qualifier must be a scoring/WebFetch triage layer on an entity-correct pool.
- **Index-void categories exist** (cold-plunge brands: ≤6 rows on every provider): when all three providers return near-zero on a real market, the route is manual/web research, not more filter permutations.

## 0.2 · Volume levers (measured 2026-07-09, iteration 4)
- **icp_text is also the sub-vertical volume lever on services briefs** — fired at e-com growth agencies it scored **100% on a 334-co pool** where keywords alone found ~34-740. Fire it on EVERY services brief, always.
- **`company_naics` validated:** `{"include":[int,...]}` top-level, ints only, 3- and 6-digit codes mix freely. Semantic fit is code-dependent: general consumer-goods codes (325620/339920/337/316/332215) scored **100% on a 7,786-co pool** (best volume lever ever measured on a brand brief); supplement codes (325411 etc.) scored **0%** — NAICS buckets supplements with pharma. Probe each code family's page 1 before trusting.
- **`company_products_services` is DEAD for brand-finding:** `{"products_include":[...]}` validates but matches "offers/sells this" — returns retailers and franchises, not brand owners (0% on pet brands).
- **Category sharding:** brand vocabulary fragments across product categories; wide "brand"-suffixed baskets (10-18 phrases, NO excludes) recover volume single-phrase baskets miss (e-com agencies 338→740; pets 8→30).

## 0.1 · Iteration-measured caveats (2026-07-09)
- **The "brand" suffix is load-bearing:** dropping it from category phrases collapsed pet brands 86%→30%; restoring it recovered 82%. Never bare-noun a brand brief.
- **Keyword EXCLUDES are not free precision** — they reshuffle Prospeo's ranking and measurably REDUCED precision on 3 of 6 re-probes (groundworks 50→30%, B2C 70→50%). Treat excludes as a hypothesis to probe (1 cr), never a guaranteed fix; keep the previous filter shape as the fallback.
- **Domain-level dedupe/excludes only** — two same-name-different-domain collisions caught live; name-based matching is unsafe.

## 0 · Keyword altitude law (from the hold-out failure→pass)
**Match keyword vocabulary to the brief's ENTITY TYPE, not the buyer's vocabulary for it.**
- Services briefs (contractors, agencies, consultancies): phrases for what the company DOES — "groundworks contractor", "software development agency". (78% A, 78% B.)
- Brand/product briefs: product-category + "brand" — "cookware brand", "skincare brand" — PLUS the entity-type filter `company_type: {"business_model":"B2C"}` (validated live). Buyer-side vocabulary ("consumer products brand") scored 32-34%; category altitude + B2C scored **83%**.
- Known residual on brand briefs: house-of-brands holdcos slip the B2C filter — caught only at scoring.

## 1 · The recipe (firing order)
1. **Entity-type keywords** (the volume anchor): `company_keywords.include` = 4-6 phrases at the correct altitude (rule 0) + entity-type/industry filter + headcount + geo + `exclude` noise words (services: "platform","SaaS","staffing","recruitment"; brands: "agency","aggregator","distributor","wholesale","marketplace"). Expect ~78-83% precision and the largest `total_count`.
2. **icp_text lookalike — SERVICES BRIEFS ONLY:** `company_lookalike: {icp_text: "<one-sentence ICP>", minimum_tier: "T2"}` + headcount + geo, NO keywords, approach-1 domains in `websites.exclude`. Expect 82-92% precision, ~20-25% additional volume, near-zero overlap with the keyword pool. **On brand-discovery briefs this approach scored 4%** (embedding neighbourhoods = aggregators/holdcos/e-com agencies) — skip it there.
3. **`company_website_search` layer — conditional:** ONLY when the brief has hard credential vocabulary (accreditations/certifications — CHAS/NHBC gave 79%). Generic content-page keywords ("case study","our work") drop precision to 64% — never use them as a third approach.

## 2 · The probe protocol
- One approach = one 50-row probe = 2 pages = **2 credits** (size fixed at 25/page). 50 rows IS representative of the pool — no deeper sampling needed. Budget mode: a single 25-row page (1 cr) is an acceptable probe when credits are tight; no preview/free mode exists on this endpoint (`INVALID_FILTERS`/`NO_RESULTS` responses are free, use them for enum discovery).
- Page-1 gate: verify first 10 unique domains; <5/10 ✅ → retune once, else the approach fails.
- Score all 50 via the `lilly-lead-score` gate. Precision = ✅ ÷ all scored; borderline ⚠️ never counts.
- Budget 1-3 extra credits for industry-string validation probes (they return results, so they bill — 3 cr burned on brief A).

## 3 · The stop-rule (measured)
- Stop adding approaches at the **first one <70% precise or with zero net-new** (brief B: approach 3 @ 64.4% = ceiling). Note: on hard-filterable briefs all 3 approaches held ≥70% (brief A) — the ceiling there is un-found; more volume may exist past the standard sequence.
- Always client-side post-filter against cumulative excludes: `websites.exclude` confirmed leaky live (2 leaks/98 excludes).

## 4 · The numbers
| Brief | Approach | total_count | Precision | Projected on-brief vol | Credits |
|---|---|---|---|---|---|
| A | keywords | 1,182 | 78% | ~922 | 2 |
| A | icp_text T2 | 218 | 82% | ~179 | 2 |
| A | + accreditation website-search | 294 | 79.2% | ~233 | 2 |
| B | keywords | 988 | 78.0% | ~771 | 2 |
| B | icp_text T2 | 245 | 92.0% | ~225 | 2 |
| B | + content-page website-search | 45 | **64.4% — ceiling** | ~29 | 2 |
| C hold-out | buyer-side keywords (verbatim v1) | 348 | 32-34% — FAIL | — | 3 |
| C hold-out | icp_text (verbatim v1) | 296 | 4% — FAIL | — | 3 |
| C hold-out | **category keywords + B2C (revision)** | 468 | **83.0%** — PASS | ~388 | 3 |

Cost-efficiency: ~6-9 credits per brief buys the full methodology verdict; combined projected on-brief volume ≈ 1,334 (A) / ~1,000 (B) at ≥70%.
Recurring false positives to pre-exclude in keywords: staffing firms with dev-adjacent language, holdcos/PE owners, single-vendor implementation partners, MSPs, materials suppliers/manufacturers (construction), stale-domain records (~2-4%/50 — WebFetch flips some back to ✅).
