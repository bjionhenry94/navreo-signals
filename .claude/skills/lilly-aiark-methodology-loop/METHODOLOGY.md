# AI Ark Methodology v2 — PROVEN 2026-07-10 (17/20 briefs ≥70%, ~939 credits)

The single recipe for AI Ark company mapping AND decision-maker finding. v1 drafted from docs; v2 is what the 20-brief test measured. This file is the source the three production skills were codified from.

## 0 · Transport + billing (non-negotiable)
- Companies: MCP flat params (`company_search` via MCP tool or JSON-RPC `POST /v1/mcp?token=…` with `Accept: application/json, text/event-stream`). Nested requestBody via MCP is silently ignored while billing.
- DMs: REST `POST https://api.ai-ark.com/api/developer-portal/v1/people` (`X-TOKEN`), nested body.
- ~1 credit per row returned, both transports. `lookalike` permanently banned.

## 1 · Company mapping recipe

**Shape by brief altitude:**

| Altitude | Filter stack |
|---|---|
| **Broad category** (expected ≥10K) | industry enums (validated, 2-4) + `excludeIndustry` naming the observed leak + keyword self-ID synonyms, `keywordMode:WORD`, `keywordSources:"NAME,KEYWORD,DESCRIPTION"` + location + 11-200 size |
| **Niche/service vertical** | industry enums (optional) + keyword self-ID PHRASES, `keywordSources:"NAME,KEYWORD"` **only — never DESCRIPTION** (client namedrops + capability mentions poison niche gates: measured 10-40% with, 70-80% without) + location + size (relax min to 5 on ultra-niche) |

**Keyword rules (the precision dial):**
- Phrases must say what the company IS ("roofing contractor", "SAP beratung", "Amazon agency") — never capability/market tags ("Amazon marketing", "solar", "drone services", "installation").
- Add local-language self-ID phrases for non-English geos ("pistas de padel", "Geschäftsführer", "spedition").
- Comma-separated values are OR'd. WORD mode handles multi-word phrases.

**Gate sequence:**
1. `size:10` page 0 gate (~10 cr — it returns `totalElements`, so no separate size:1 unless you might discard on count alone). Score via `lilly-lead-score` semantics. **<50% hard abort** the shape; <70% tighten ONE layer and re-gate; max 3 iterations per brief, then record FAILED.
2. Pool ≥100: ONE deep `size:10` page at ~70% depth, **capped at page ≤950** (offset limit ~10,000 — deeper pages return 0 rows). Pool <100 = census, skip.
3. **Blended accuracy = mean(gate, deep).** The head is brand-sorted and flatters broad pools (90→60 measured); tight shapes hold (90→100).

## 2 · TAM estimate — always TWO numbers
```
Extraction pool  = tight-shape totalElements × blended accuracy
Category estimate = broad-shape totalElements × that shape's measured precision
```
Report both. totalElements ≥10,000 → flag as display-capped floor. Never a raw count alone.

## 3 · DM recipe (100% post-join precision, 15/15 briefs)
1. 3 gated companies → REST nested pull, `size:25`:
   `account.domain.any.include` + `contact.experience.current.title.any.include` `{mode:SMART, content:[role variants]}` and, when CEO/President in set, `…title.any.exclude` `{mode:SMART, content:["Vice President","VP"]}` (cuts billed noise — 8/20 rows on one brief were VPs matched via "President").
2. **Company-ID join post-check (mandatory):** keep only people with a current position (`date.end == null`) at `company.id == person.company.id` whose title matches the role set. Strip `vice president|vp` before testing `president`; hard-reject `assistant|executive to|to ceo|office of|recruitment|coordinator|intern|specialist|analyst|associate|representative|retired`; VPs only for Sales/BD/CRO/CSO; dedup (name, domain).
3. **Role-set design:** never bare "Director" or "Partner" (functional directors / equity consultants explode the match — measured on construction + consultancies). Use Managing Director, Managing Partner, Owner, C-titles; add local-language titles (Geschäftsführer, Directeur).
   **Director-and-above floor (user rule 2026-07-11):** every pull filters Director+ — the title list spans the full Director+ ladder for the brief's function; below-Director titles never enter the include list and the post-check rejects anything below the floor.
   **Never seniority/department in isolation (user rule 2026-07-11):** the nested current-title content list is always the primary filter; `seniority`/`departmentAndFunction` only layer on top to narrow, never fire alone or as a substitute.
4. `avg_dms_per_co` = kept ÷ 3. Measured anchors: SMB services 1-2 · logistics/dev 2-3 · construction 3-6 · accounting 7-10 · thin niches can be <1 (ITAD 0.7 — widen sample or roles).
```
DM TAM = company TAM × avg_dms_per_co (measured, never assumed)
```

## 4 · Volume-vs-accuracy dial
| Leak | Move |
|---|---|
| Wrong entity type (IT-services in SaaS, distributors in brands) | `excludeIndustry` the leak's primary tag |
| Namedrop/capability rows on niche brief | Drop DESCRIPTION from keywordSources; drop generic tags |
| Accuracy fine, volume ≪ band | Broad-shape category count for the second TAM number; add synonym/local-language phrases |
| Deep ≪ gate | Head-heavy pool: keep blended number, don't paginate past where quality held |
| DM noise billed | Add nested title exclude; tighten content list, never seniority/department |

## 5 · Out-of-scope brief shapes (route elsewhere, don't burn iterations)
1. **Brand/product briefs** → Prospeo B2C flags / Ocean `ecommerce:true` (AI Ark ceiling ~40-50%).
2. **Capability-flooded niches** (the defining activity is a tool of a bigger profession — drones/surveyors, reefer/carriers) → pull the census shape and triage via `lilly-lead-score`, or route to Prospeo icp_text.
3. **Micro-pools (<20 true cos) with vocabulary-sharing noise** → census pull + manual/LLM triage; a passing gate is not achievable and not needed.
