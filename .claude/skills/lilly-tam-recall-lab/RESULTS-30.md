# RESULTS — 30-brief recall-max TAM lab · 2026-07-13 · Training Mode OFF

## VERDICT: ✅ COMPOSITE PASS — 25/30 briefs meet their band bar (bar: ≥24/30)
- **21 PASS + 4 correctly ROUTED + 5 honest FAILs**
- Credits: **Prospeo ≈88 / 5,000 · AI Ark ≈860 / 5,000** (full ledger in RUN-LOG.md; includes 45 Ark cr lost to an SSE-parse mistake, ledgered)
- Every accuracy number scored from actual returned rows (name/domain/industry/description), lilly-lead-score semantics, ⚠️ never counts. Hand-re-score of 5 briefs: 2 exact matches, 2 fail-list-confirmed, 1 frame-sensitive (B27, confirmed under the brief's OR-wording). Zero lookalike calls, zero email requests, no shape pulled >25 rows.

## The headline: recall was starving. Populous briefs at ≥70% accuracy:

| # | Brief | Band | Prospeo chosen | AI Ark chosen | **Recall-max union** | Old baseline | **×** | Verdict |
|---|---|---|---|---|---|---|---|---|
| 1 | B2B SaaS US | broad | 29,804 @ 88% | 5,632 @ 93.3% | **~35,100** | 11,100 | **3.2×** | ✅ PASS |
| 2 | Marketing agencies US+UK | broad | 28,345 @ 76% | 8,243 @ 80% | **~36,300** | 10,200 | **3.6×** | ✅ PASS |
| 3 | Dev shops Europe | broad | 4,009 @ 76% | none ≥70% | 4,009 | 880 | **4.6×** | ✅ PASS |
| 4 | E-comm/DTC brands US | broad | 60,769 @ 80% | routed (brand ban) | **60,769** | prior = FAIL | **brief unlocked** | ✅ PASS |
| 5 | Construction GCs UK | broad | 4,168 @ 76% | 3,398 @ 73.3% | ~7,400 | 1,560 | **4.7×** | ✅ PASS |
| 6 | MSPs UK | mid | 1,054 @ 80% | 1,023 @ 73.3% | ~1,872 (20% sample overlap!) | 1,500 | 1.25× | ❌ FAIL (volume) |
| 7 | Freight DE+NL | mid | 827 @ 80% | 1,530 @ 93.3% | ~2,300 | 590 | **3.9×** | ✅ PASS |
| 8 | Staffing AU | mid | 834 @ 96% | 1,235 @ 80% | ~2,050 | 790 | **2.6×** | ✅ PASS |
| 9 | Accounting CA | mid | 848 @ 88% | 554 @ 86.7% | ~1,390 | 540 | **2.6×** | ✅ PASS |
| 10 | Solar installers US | mid | 376 @ 72% | 350 @ 80% | ~715 | 380 | 1.9× | ✅ PASS |
| 11 | ITAD US+UK | niche | none ≥70% (3 iters) | none ≥70% (3 iters) | — | 175 | — | ❌ FAIL |
| 12 | Amazon agencies | niche | none | 199 @ 80% | 199 | 110 | 1.8× | ✅ PASS |
| 13 | SAP consultancies DACH | niche | none | 82 @ 73.3% | 82 | 66 | 1.2× | ✅ PASS (acc bar) |
| 14 | Commercial roofing UK | niche | none | 31 @ 86.7% | 31 | 83 | 0.4× | ✅ PASS (acc bar) |
| 15 | Cold-chain US | niche | none | 1,552 @ 73.3% | **1,552** | 63 | **24.6×** | ✅ PASS |
| 16 | Drone inspection AU | ultra | census 265 @ 8% | — | — | — | — | 🔀 ROUTED (capability-flooded → census + lead-score triage) |
| 17 | Vet PM software US+UK | ultra | census 25 @ 48% | none | — | 12 | — | 🔀 ROUTED (micro-pool → census + triage) |
| 18 | Padel builders EU | ultra | census fail | — | — | — | — | 🔀 ROUTED (micro-pool) |
| 19 | Ship chandlers NL+BE | ultra | 107 @ 36% | none | — | 10 | — | 🔀 ROUTED (micro-pool) |
| 20 | Equestrian construction UK+IE | ultra | none | 51 @ 90% | 51 | 8 | **6.4×** | ✅ PASS |
| 21 | B2B SaaS UK | broad | 7,492 @ 76% | 518 @ 86.7% | ~8,000 | 1,027 | **7.8×** | ✅ PASS |
| 22 | MSPs US | broad | none (3 iters, best 56%) | none (3 iters, best 33%) | — | 2,361 | — | ❌ FAIL |
| 23 | Digital agencies AU | mid | 2,411 @ 80% | 87 @ 73.3% | ~2,490 | 339 | **7.3×** | ✅ PASS |
| 24 | Recruitment agencies UK | broad | 5,433 @ 88% | 6,065 @ 73.3% | **~10,900** | 2,918 | **3.7×** | ✅ PASS |
| 25 | Management consulting US | broad | none (3 iters, best 44%) | none | — | 715 | — | ❌ FAIL |
| 26 | Freight/logistics US | broad | 2,365 @ 72% ⚠borderline | none | 2,365 | 829 | **2.9×** | ✅ PASS (borderline — 18✅/25; one-row sensitivity disclosed) |
| 27 | Commercial GCs US | broad | 25,979 @ 76% | 30,207 @ 73.3% | **~54,100** | 8,976 | **6.0×** | ✅ PASS |
| 28 | CPA firms US | broad | 4,186 @ 72% | none | 4,186 | 4,076 | 1.03× | ❌ FAIL (volume) |
| 29 | FinTech UK | mid | 275 @ 80% | 1,606 @ 73.3% | ~1,850 | 572 | **3.2×** | ✅ PASS |
| 30 | Law firms US | broad | 8,656 @ 76% | 20,151 @ 93.3% | **~28,100** | 6,677 | **4.2×** | ✅ PASS |

Union = P + A − measured-sample-overlap estimate (overlap 0 in most samples; B6 measured 20% — see law 6). Dual numbers always reported.

## Band pass rates
- Broad: 11/13 (fails: B22 MSP US, B25 consulting US, B28 CPA US volume; B26 borderline-pass)… **10 clean + 1 borderline**
- Mid: 6/7 (fail: B6 MSP UK on volume)
- Niche: 4/5 (fail: B11 ITAD)
- Ultra: 5/5 (1 pass + 4 correctly routed)

## Measured laws (new this run)
1. **The recall flip works.** Median volume multiple on passing populous briefs ≈ **3.6×**, at 72-96% accuracy. The old methodology's precision cushion (85-95%) was paid for with 60-85% of the market.
2. **Loosest-defensible-first, widen-until-fail:** every chosen shape needs the failed wider rung recorded (B1: +Platform 68% ✗; B21: +Marketplace 56% ✗; B5/B27: industry-alone 60%/48% ✗). Where no sane wider rung exists, document proven-loosest.
3. **Rung viability is GEO-DEPENDENT:** [SaaS,Platform] passes UK (76%), fails US (68%). MSP keywords pass UK (80%), collapse US (16%). Never transfer a rung across geos unscored.
4. **Provider-swamp briefs exist:** US MSP / US management-consulting vocabulary is owned by staffing+IT-consulting firms on BOTH indexes — no filter shape reaches 70% within 3 iterations. These need a scoring/triage layer (lead-score pass over the 56-68% pool), not more filter permutations.
5. **The brand-brief ban is AI-Ark-only:** Prospeo E-commerce subtype ladder = 60,769 @ 80% on the DTC brief AI Ark structurally fails. Retest "structural fails" per provider before routing away.
6. **Near-disjoint weakens on tight niches:** B6 MSP UK sample overlap 20% (Centerprise/Xeretec/Probrand in both). Measure overlap per brief; never assume 0.75-6.4%.
7. **Prospeo enum traps:** "Truck Transportation" is INVALID (free error); keyword baskets rerank non-monotonically (wider basket shrank B6 1,054→1,036 and B29 275→123). Ark JSON-RPC responses are plain JSON (not SSE) — parse accordingly (45 cr lost to sed-filtering, ledgered).
8. **Index drift is real:** ITAD (prior 249 @ 70%) and roofing UK (prior 119 @ 70%) did not reproduce at prior size; roofing re-passed at 31 @ 86.7%, ITAD failed outright. Anchors must be re-fired every run (Step 1 does).

## The 5 honest FAILs and their routes
- **B6 MSPs UK** — accuracy fine (80/73%), union 1.25× < 1.5×. Route: accept the 1,872 pool (it IS the recall-max at 70%) or add a third source.
- **B11 ITAD** — both providers flood (distributors/TPM/nonprofits). Route: census pull at best shape + lead-score triage.
- **B22 MSPs US / B25 Management consulting US** — provider-swamp (law 4). Route: pull the 56-68% pool ≤ a few hundred rows and triage with lilly-lead-score; or signal-based mechanisms instead of static lists.
- **B28 CPA firms US** — accuracy 72% but recall-max ≈ baseline (1.03×); the old shape was already near the index ceiling. Route: accept pool as-is; volume gain must come from a third source, not this index.

## AWAITING SIGN-OFF to fold into production skills
Fold-back targets: `lilly-tam-mapper` (recall-max Stage order + dual-number TAM), `lilly-prospeo-list-builder` (loosest-first ladder, subtype openers, strip icp_text per lookalike ban), `lilly-ai-ark-list-builder` (recall-max keyword sets, plain-JSON parse note). NO production skill was modified during this run.

---

# DM ADDENDUM — decision-maker accuracy verification · 2026-07-13/14 · bar = 90%

Method (user's canonical): LLM long-tail title expansion → qualify to Director+ (no bare Director; Partner only behind an industry gate) → title-list-PRIMARY search with seniority layered → location = person AND company geo.

## Title-level accuracy (the 90% bar)
| Brief | Prospeo (25-row) | Prospeo DM-TAM | AI Ark open-search (15-row) | Ark DM-TAM |
|---|---|---|---|---|
| B1 SaaS US sales leaders | **100%** | 14,352 | 86.7% (fuzzy leaks: "Sales Development", "Revenue Ops") | 46,129† |
| B2 Agency leaders US+UK | **100%** | 16,690 | 93.3% | 24,843 |
| B7 Freight DE+NL (local-lang) | **100%** (Geschäftsführer/Algemeen directeur match!) | 422 | 86.7% titles; companyIndustry gate LEAKED | 1,996† |
| B9 Accounting partners CA | **100%** | 1,285 | 100% | 1,570 |
| B24 Recruitment leaders UK | **100%** | 3,024 | 93.3% | 3,319 |
| B27 GC leaders US | **100%** (exact-match kills President trap) | 16,803 | 100% (excludeTitle "vice president" — the documented law works) | 41,059† |
| **Aggregate** | **150/150 = 100%** | | avg 93.3% | †open-search counts include company-gate leak — treat as ceiling |

## Verdict: ≥90% bar MET
- **Prospeo `/search-person` = the DM primary: 100% title accuracy across all 6 briefs.** Exact canonical-title matching is structurally noise-free; recall comes from the long-tail expansion (canonicalise via free /search-suggestions). Accepts the recall-max company shapes (incl. company_type.subtypes) directly — DM search inherits the proven company gate.
- **AI Ark = top-up, TWO legal patterns:** (1) domain-joined pull at known companies (prior lab: 100% post-join, 15/15) — the production pattern for dm-finder; (2) open search ONLY with excludeTitle strips (fuzzy title matching leaks adjacent functions: 86.7% raw → ~100% with excludes, proven on B27). Open companyIndustry gate can leak whole wrong verticals (B7) — never trust it for company-fit; join to the company pot instead.
- **Location law confirmed:** person+company dual-set on Ark = 100% geo. Prospeo has no person-location filter — post-check caught 0-8% off-geo leaders (UK firms with US-based MDs) → keep the post-check as a standing step.
- **Traps neutralised:** Partner behind industry gate = safe (B9 100%); President exact-match (Prospeo) or VP-exclude (Ark) = safe (B27 100%).
- Gotchas: people_search `companyKeyword` = 401 tier-gated, `companyType` = 400; accented titles can kill curl payloads (quote-safe or ASCII them).
- Cost: ~7 Prospeo + ~90 AI Ark credits. Zero email/enrichment calls.

Grand totals for the whole lab: **Prospeo ≈95 / 5,000 · AI Ark ≈950 / 5,000.**
