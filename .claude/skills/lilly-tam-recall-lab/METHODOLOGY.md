# Recall-Max TAM Methodology v1 — PROVEN 2026-07-13 (25/30 briefs met band bar; RESULTS-30.md)

**New laws measured in the 30-brief run (details in RESULTS-30.md §Measured laws):** rung viability is geo-dependent (score every rung, never transfer across geos); provider-swamp briefs exist (US MSP / US mgmt-consulting → triage route, not filters); the brand-brief ban is AI-Ark-only (Prospeo E-commerce ladder = 60,769 @ 80%); niche overlap can hit 20% (measure per brief); Ark JSON-RPC returns plain JSON not SSE; index drift means anchors re-fire every run.

The optimisation flip: prior labs maximised precision and starved recall (−90-95%). This recipe maximises **pool size subject to accuracy ≥70%**. Same providers, same scoring gate, opposite search direction.

## 0 · The core loop (per brief, per provider)
1. **Start at the LOOSEST defensible shape** — the native classifier alone (subtype / LinkedIn industry enum) + headcount + geo. Nothing else.
2. Read the pool (`total_count` / `totalElements`, ~free) and score ONE ≤25-row sample (1 cr Prospeo / ~rows cr AI Ark).
3. **≥70%? Try one WIDER rung** (add adjacent subtype/enum). Keep widening until a rung fails.
4. **<70%? Add exactly ONE narrowing layer** (self-ID keywords with the industry gate kept ON), re-gate. Max 3 shapes total.
5. **Chosen = the biggest pool that held ≥70%.** The failed wider rung is the proof of maximality. Single-enum briefs where no sane wider rung exists: document proven-loosest instead of burning a probe.

## 1 · Prospeo playbook (recall-max order)
| Brief altitude | Loosest shape to open with |
|---|---|
| Category with native subtype (SaaS, E-commerce, Construction, Logistics, FinTech, Agency) | `company_type.subtypes` ALONE + headcount + geo. **Never open with business_model/has_subscription** — measured cost on B2B SaaS US: those two flags = 4,711 vs 29,804 (−84% recall) for +4pts precision we didn't need. |
| Category with clean LinkedIn industry enum (Staffing, Accounting, Marketing/Advertising, Law) | `company_industry` enum(s) ALONE. |
| Services vertical with no clean classifier (MSPs, freight forwarders, dev shops, solar) | industry enum gate + **self-ID keyword basket** (`include_company_description:true`). The industry-alone rung is fired anyway as the (expected-fail) looser comparison. |
| Niche/ultra (ITAD, SAP, roofing, chandlers) | self-ID keyword basket, geo, headcount only if brief has one. Pools <100 = census. |

**Widening rungs measured (score the rung, never assume):**
- `[SaaS]→[SaaS,Platform]`: **geo-dependent** — UK holds 76%, US fails 68%. Platform pulls job boards/marketplaces; UK index has fewer.
- `[…,Marketplace]` rung: fails everywhere tested (56-poisoned by job boards).
- E-commerce brand briefs: `[E-commerce]→[+Retail]→[+Marketplace]→[+Food & Beverage]` — rungs 2-3 held ≥80% in US (54,791 → 56,950); take the biggest passing rung.
- Industry-axis vs subtype-axis are DIFFERENT ladders — try both when both exist (Construction UK: subtype 4,168@76% vs industry 11,736@60% — subtype won on accuracy, industry rung was the rejected-looser).

**Keyword-basket law (recall edition):** wider baskets do NOT monotonically grow the pool — Prospeo reranks; B6's 8-phrase basket returned FEWER (1,036) than the 5-phrase (1,054). Baskets are a probe, not a dial.

## 2 · AI Ark playbook (recall-max, FILTERS ONLY)
- Open with validated industry enums + the WIDE self-ID synonym set, `keywordSources:"NAME,KEYWORD"` (+`,DESCRIPTION` only on broad-category briefs).
- ONE size:15 gate (totalElements + sample), one retune max. ~1 cr/row — the gate IS the sample.
- `excludeIndustry` only names an OBSERVED leak, never speculative.
- Lookalike remains permanently banned; nested requestBody silently bills — never use.

## 3 · Union (the second recall lever)
Indexes are near-disjoint (0.75-6.4% overlap) → union ≈ additive.
`union = P + A − (sample-overlap-rate × min(P,A))`; dedup actual extracted rows by canonical domain (lowercase, strip www/protocol). Report per-provider pools AND the union.

## 4 · TAM report format (dual number, per brief)
```
Recall-max pool (chosen shape, ≥70%):  N_union  (P: n₁ @ a₁% · A: n₂ @ a₂%)
vs old tight-shape baseline:            ×M multiple
```

## 5 · Structural-fail routes (unchanged, but RETEST brand briefs on Prospeo)
- Brand/product briefs: **no longer auto-routed** — Prospeo `subtypes:[E-commerce,…]` measured 80-92% at 23K-57K on the DTC brief AI Ark structurally failed. Route away from AI Ark only.
- Capability-flooded niches (drone inspection): census + `lilly-lead-score` triage.
- Micro-pools (<20 true cos): census + triage; a passing gate is neither achievable nor needed.

## 5.5 · Lookalike ban — ALL providers (user 2026-07-13)
No embedding/lookalike feature anywhere: AI Ark `lookalike` AND Prospeo `company_lookalike` (`icp_text`, domain modes). Both decay — the embedding neighbourhood drifts off-brief as it widens, so the pool a lookalike reports is not a stable TAM. Discovery = native classifiers + industry enums + self-ID keywords, full stop. (Supersedes the old playbooks' icp_text recipes; strip them at fold-back.)

## 6 · What stays true from the old methodology
- Size the market globally; geo/headcount tiers are post-extraction labels (sharding collapses pools 6.6-11×).
- Keywords say what the company IS; DESCRIPTION poisons niche gates; borderline ⚠️ never counts.
- Excludes are probes, not free precision.
- Score actual rows, never provider counts. ≤25 rows per shape — TAM mapping is not extraction.

*(Numbers table + per-brief worked results: RESULTS-30.md. Ledger: RUN-LOG.md.)*
