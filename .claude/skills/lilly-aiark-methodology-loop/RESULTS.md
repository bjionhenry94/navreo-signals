# RESULTS — 20-brief AI Ark methodology test · 2026-07-10

## VERDICT: ✅ PASS — 17/20 briefs ≥70% on BOTH company and DM accuracy
- Credits spent: ~939 of 2,500 (ledger in RUN-LOG.md)
- DM post-join accuracy: **100% on all 15 briefs measured** (the company-ID join + matcher is the whole story)
- Company accuracy across passing briefs: avg ~80% (range 70-95%)
- 3 fails are STRUCTURAL brief shapes (identity not expressible as filters), documented below — route those to Prospeo/Ocean per existing laws.
- Methodology v2 (METHODOLOGY.md) reflects everything measured; v2 re-runs flipped B12 and B15 from fail to pass.

## Per-brief results

| # | Brief | Band | It | Co acc (gate/deep/blend) | AI Ark TAM (tight shape) | Category est (broad shape) | Band-realistic? | DM acc | DMs/co | DM TAM |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | B2B SaaS US | broad | 3 | 90/60/**75%** | 14,758×.75 ≈ **11,100** | 43K raw | ✓ ≥10K | 100% | 2.7 | ~30,000 |
| 2 | Marketing agencies US+UK | broad | 3 | 90/80/**85%** | 11,955×.85 ≈ **10,200** | 36K raw | ✓ | 100% | 1.3 | ~13,600 |
| 3 | Dev shops Europe | broad | 3 | 90/70/**80%** | 1,098×.8 ≈ **880** | ~4.6K | ✗ explainable (keyword-recall bound) | 100% | 2.0 | ~1,800 |
| 4 | DTC consumer brands US | broad | 3 | best **40%** — **FAIL** | — | — | — | — | — | — |
| 5 | UK construction GCs | broad | 2 | 90/100/**95%** | 1,641×.95 ≈ **1,560** | 15,255×.45 ≈ 6,900 | ~ near-band | 100% | 5.7 | ~8,900 |
| 6 | MSPs UK | mid | 1 | 90/100/**95%** | 1,583×.95 ≈ **1,500** | 8,601 raw | ✓ via category | 100% | 1.3 | ~2,000 |
| 7 | Freight DE+NL | mid | 1 | 70/70/**70%** | 844×.7 ≈ **590** | 4,069 raw | ✓ via category | 100% | 3.0 | ~1,800 |
| 8 | Staffing AU | mid | 1 | 80/100/**90%** | 880×.9 ≈ **790** | 1,403 raw | ~ | 100% | 1.7 | ~1,300 |
| 9 | Accounting CA | mid | 1 | 90/80/**85%** | 631×.85 ≈ **540** | 976 raw | ~ | 100% | 6.7 (partners) | ~3,600 |
| 10 | Solar installers US | mid | 3 | 70/90/**80%** | 476×.8 ≈ **380** | 1,878 | ~ | 100% | 1.3 | ~500 |
| 11 | ITAD US+UK | niche | 2 | 70/70/**70%** | 249×.7 ≈ **175** | — | ~ just under 300 | 100% | 0.7 (thin!) | ~120 |
| 12 | Amazon agencies US+UK+DE | niche | 3+v2 | 80/70/**75%** | 146×.75 ≈ **110** | — | ~ | 100% | 1.3 | ~145 |
| 13 | SAP consultancies DACH | niche | 2 | 90/90/**90%** | 73×.9 ≈ **66** | 388×.6 ≈ 233 | ✗ under, provider-bound | 100% | 4.0 | ~265 |
| 14 | Commercial roofing UK | niche | 2 | 70/70/**70%** | 119×.7 ≈ **83** | — | ✗ under, provider-bound | 100% | 3.3 | ~275 |
| 15 | Cold-chain logistics US | niche | 3+v2 | 80/60/**70%** | 90×.7 ≈ **63** | 627 | ✗ under | 100% | 1.3 | ~82 |
| 16 | Drone inspection AU | ultra | 3 | best **40%** — **FAIL** | — | — | — | — | — | — |
| 17 | Vet PM software US+UK | ultra | 2 | **90%** (census, 13) | ≈ **12** | 61 | ~ | 100% | 1.7 | ~20 |
| 18 | Padel builders EU | ultra | 3+v2 | best **60%** — **FAIL** | (~9 true builders exist) | — | — | — | — | — |
| 19 | Ship chandlers NL+BE | ultra | 1 | **80%** (census, 13) | ≈ **10** | — | ~ | 100% | 1.3 | ~13 |
| 20 | Equestrian construction UK+IE | ultra | 1 | **80%** (census, 10) | ≈ **8** | — | ~ | 100% | 1.0 | ~8 |

Band pass rates: broad 4/5 · mid 5/5 · niche 5/5 (after v2) · ultra 3/5.

## The 3 structural fails (do NOT retry on AI Ark — route elsewhere)
1. **Brand/product briefs** (B4, best 40%): distributors/contract-mfrs/private-label share every filterable trait with brands. Confirms the 2026-07-09 lab law. Route to Prospeo B2C flags / Ocean ecommerce:true.
2. **Capability-flooded niches** (B16 drones 40%): when the niche's defining activity is a TOOL used by a bigger profession (surveyors with drones), keyword self-ID cannot separate identity from capability.
3. **Micro-pools drowned by adjacent vocabulary** (B18 padel 60%): the true pool (~9-15 cos) is smaller than the vocabulary-sharing noise (clubs, equipment brands). Pull the census shape and hand to `lilly-lead-score` triage instead of chasing a passing gate.

## Measured laws (all folded into METHODOLOGY.md v2)
1. Industry-enum-only = 10-60% precision. Keyword WORD NAME,KEYWORD-only = precision at −90-95% recall. **Broad briefs: industry + excludeIndustry + self-ID synonyms on NAME,KEYWORD,DESCRIPTION. Niche briefs: NAME,KEYWORD ONLY** (DESCRIPTION matches client namedrops + capability mentions and poisons niche gates: B12 10%, B14 20%, B15 40% with DESCRIPTION → 70-80% without).
2. Never use generic capability tags as keywords ("Amazon marketing", "solar", "drone services", "installation") — entity phrases only; add local-language self-ID phrases for non-English geos ("pistas de padel", "SAP beratung", "spedition").
3. **Offset cap ~10,000**: pages past it return 0 rows (0 credits). Deep-sample at page ≤950 (size 10). Pools <100 = census; skip the deep sample.
4. The size:10 gate returns totalElements — a separate size:1 pre-count is only worth firing when a shape might be discarded on count alone (ultra-niche zero-pool checks, broad-shape category counts).
5. Blend gate+deep accuracy; the head is brand/staff-sorted and overstates quality on broad pools (B1 90→60 at depth) but holds on tight niche shapes (B5 90→100).
6. **Dual-number TAM**: tight-shape extraction pool (count × blended accuracy) AND broad-shape category estimate (broad count × its measured precision). Never present one number.
7. DM current-role + company-ID join = **100% post-join precision in 15/15 briefs**, keep-rate 33-80% of billed rows. Add nested title `exclude` ["Vice President","VP"] when President/CEO sets are used (8/20 billed rows on B10 were VPs matched via "President"). Never bare "Director"/"Partner" in role sets (functional-director/equity-consultant explosion); use Managing/Owner-scoped variants. Thin niches can yield <1 on-brief DM/co (ITAD 0.7) — calibrate on 3 cos, widen if thin.
8. DM TAM = company TAM × measured avg on-brief DMs/co (never an assumed ×N). Measured anchors: SMB services 1-2, logistics/dev shops 2-3, construction 3-6, accounting firms 7-10.
