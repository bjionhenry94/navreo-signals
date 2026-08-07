# PLAYBOOK — Ocean.io (MCP `ocean_data_api`)  ·  status: **VALIDATED** (hold-out 80-90%; small-sample caveat)

Measured 2026-07-09 on briefs A + B and hold-out-validated on brief C via the MCP free browse window — **0 credits spent** (19 scored calls). Caveat: per-cell samples are 10 rows (±15pt noise); the B→C cliff is robust across all 3 briefs, fine A-vs-B distinctions are not.

**Entity-flag rule (from the hold-out):** on brand/product briefs add `ecommerce:true` and use product-category-altitude keywords ("skincare brand", not "consumer products brand") — the same entity-type law that rescued Prospeo (its `B2C` flag). Keyword+ecommerce scored 90% on the hold-out.

## 1 · The recipe (firing order)
1. **Free sampling always goes through the MCP, never REST.** First page of any unique filter combo = `creditsUsed: 0` at `num_results ≤ 10`. REST costs 1 cr/call for the identical read. Sample free; pay only to extract.
2. **Lookalike with tier pinning is the primary angle.** Per sub-vertical: 5 near-identical ✅ seeds (from a verified pot) + geo + `companySizes`, sampling each relevance tier separately (`minRelevance`=`maxRelevance`: A/A, B/B, C/C — 3 free calls).
3. **Keyword angle as the volume cross-check:** buyer-type `keywords.anyOf` + `noneOf` noise words + geo + sizes; one free page-1 sample (70% hard brief / 60% soft brief).
4. For construction-style briefs add `noneOf` excludes for manufacturers/suppliers/merchants (same-noun-wrong-business was the dominant noise). **Iteration-measured: Ocean's `noneOf` excludes genuinely work** (+7pts groundworks → 86.7%, +27pts supplements → 76.7%, +11pts B2C → 71.4%) — unlike Prospeo, where excludes reshuffle ranking unpredictably.
5. **Wording morphology matters:** "data consultancy" and "data consulting" are different pools (the "-ing" switch collapsed a Nordic pool to near-zero, "-ancy" restored it byte-for-byte). Probe both forms free before concluding a market is thin.
6. **Don't stack `ecommerce:true` with heavy excludes** — the combination collapsed a pet-brand pool to n=1. Layer one lever at a time, free-probe each.
7. **Lookalike is dead for sub-vertical agency briefs** (e-com growth agencies: 10% at BOTH tiers — same generalist-agency drift as AI Ark). Keyword+flag is the only Ocean angle there.
8. **Ocean is COMPANIES-ONLY — never decision-maker searches.** The `ocean_data_api` MCP exposes people tools (`search_people`, `export_people`, `lookup_person`, `role_changes`) — all BANNED for DM/contact work (sparse people index → false negatives; standing user rule). `employeeFilters` is the one legal use of employee data: it selects COMPANIES and returns companies. DMs go through Prospeo → AI Ark per `lilly-decision-maker-finder-v2`.
9. **Docs-mined filters (2026-07-09, live-validated free):** `employeeFilters.{skills,jobTitleKeywords,seniorities}` — company-selection by employees — scored **100% (10/10) on the dev-agency/AI-DX brief** that lookalike couldn't close (MCP-only; not in Ocean's public REST spec). `locationsCount {from:3}` isolates multi-site organisations (vet-groups probe: real groups surfaced at 40% raw — needs noneOf excludes for universities/retailers). `updatedWithinMonths` can cut the dead-domain tax. `technologies.apps` is a vocabulary TRAP without a `/v2/data-fields` lookup first (Shopify probe: 408K rows @ 0%).
10. **Category-shard sweep (the volume method for fragmented-vocabulary briefs):** 8-16 single-category shards, each its own FREE first-page call; keep shards ≥70%; sum pools with a 20-30% inter-shard overlap haircut (dedupe on domain at extraction). Measured: B2C brands 10/16 shards qualified (~473 net); e-com agencies 6/8 at 90-100%. Zero-hit shard phrasings ("dog toys brand" etc.) are OCEAN INDEX GAPS, not market gaps — cover those categories via Prospeo instead.

## 2 · The probe protocol
- Sampling is FREE but **first-page-only**: `search_after` pagination is hard-blocked at zero balance (rejected pre-charge, no spend risk). Vary the QUERY (tier pin, sub-vertical cluster, keyword shard, geo shard) instead of the page.
- 10 rows per cell, scored via the `lilly-lead-score` gate; each tier's `total` gives the tier-population for volume math.
- Extraction (paginate beyond page 1) is the ONLY paid act — price it from the tier populations before committing (REST ~20 cr per 100-row enriched page per the ocean-tam-builder model).

## 3 · The stop-rule (measured)
- **The decay cliff is B→C, not A→B.** Hard brief: A 80/70% → B 80/70% → C 20/0%. Soft brief (tight seeds): A 70% → B 60% → C 0%.
- **Hard-filterable briefs: extract tiers A+B** (B holds A's precision and carries 3.5-7.5× its volume — A-only forfeits most of the TAM). **Soft-category briefs: extract tier A only.** **Never extract tier C** (unrelated-vertical noise, both briefs).
- Seed verticality holds on Ocean too: tight single-model clusters 70-80%/tier-A vs consulting-flavoured seeds 60% (and 30% at B — no passing tier). Sub-70% tier-A = re-pick seeds, not filters.

## 4 · The numbers
| Brief | Angle | Pop (A/B/C) | Precision (A/B/C) | Stop | Projected ≥70% vol |
|---|---|---|---|---|---|
| A | groundworks cluster | 1,478 / 5,028 / 505 | 80 / 80 / 20% | tier B | ~5,200 |
| A | roofing cluster | 691 / 5,212 / 270 | 70 / 70 / 0% | tier B | ~4,100 |
| A | keywords (pop 989) | page-1 only | 70% | n/a | ~690 |
| B | dev-agency cluster | 1,215 / 2,085 / 3 | 70 / 60 / 0% | tier A | ~850 |
| B | AI/DX cluster | 1,937 / 2,173 / 3 | 60 / 30 / 33% | NONE | 0 |
| B | keywords (pop 548) | page-1 only | 60% | n/a | 0 |
| C hold-out | keywords + ecommerce:true (pop 197) | page-1 only | **90% — PASS** | n/a | ~177 |
| C hold-out | skincare-seed lookalike | 1,248 / 1,746 / 16 | 90 / 80 / 10% | tier B | ~2,500 |

Cross-provider overlap: Ocean ∩ Prospeo ≈ 2-10% both briefs — Ocean adds a third near-disjoint index. Data-quality tax: 1-2 rows/10 (dead domains, wrong-country records) — verification stays mandatory.
**Overturns:** "no usable similarity threshold on Ocean" (tam-mapper decay-recovery preamble) — the MCP exposes A/B/C tiers and they ARE the decay curve; page-depth batching rules (safe/bulk mode) should be re-expressed as tier rules on the MCP path.
