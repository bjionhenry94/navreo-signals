# PLAYBOOK — AI Ark `company_search`  ·  status: **SUPERSEDED BY USER DIRECTIVE 2026-07-10**

> ⛔ **The `lookalike` parameter is permanently banned by the user ("once and for all"). AI Ark runs FILTERS-ONLY** — industry enums (via `industry_search`), free-text `industries`, `productAndServices`, `naics`/`sic`, `location`, `minEmployees`/`maxEmployees`, founded/revenue/funding ranges — with a `size:1` count → `size:10` scored gate (hard abort <50%, one filter-tighten retry) before any sized pull. The lookalike recipes and measurements below are retained as historical lab record only. See `feedback_aiark_filters_never_lookalike` (memory) and the lilly-tam-mapper banner.

## (Historical) status: VALIDATED — SERVICES BRIEFS ONLY (measured law, 2026-07-09 iteration)

**Boundary is now a measured law (n=30 per brief, 10 briefs):**
- Services/contractor briefs: **73-100%** — groundworks 100%, prof-services agencies 86.7%, UK construction 90%, roofing 76.7%, SAP consultancies 73.3%. AI Ark is the STRONGEST provider on these.
- Brand/product briefs: **40-50%** even with tight same-category seeds (supplements 50%, pet 43.3%, B2C mixed 40%) — the embedding neighbourhood for brands structurally fills with holdcos, private-label/contract manufacturers, franchise groups. DO NOT run brand briefs on AI Ark; no seed quality fixes this.
- Sub-vertical-within-agencies briefs fail too: e-com growth agencies 20% (embedding latches onto "boutique 11-50 digital agency" style, not the vertical). Data/AI consultancies sit at the 53-57% ceiling.

**Round-2 boundary refinement (2026-07-09, n=25/brief):** the lookalike embedding resolves OPERATIONAL CATEGORIES, not finer distinctions. Passes: freight forwarders 100%, commercial HVAC 100%, MSPs 88% (+ round-1 construction 90-100%, dev agencies 84%). Fails: **organisational-structure distinctions** (multi-site vet groups vs single clinics: 32% even with a tight 5-seed cluster) and **sub-type boundaries inside a profession** (pen-testing vs MSSP vs compliance vs security-product: 52%). Route those brief shapes to Prospeo icp_text + a scoring/triage layer instead.

Measured 2026-07-09 on briefs A + B. 8 paid calls total.
**Billing (documented in qwintiq-list-building, confirmed post-hoc): ~1 credit per ROW returned.** A size:50 probe ≈ 50 credits. Cheap pattern: fire `size:1` first to read `totalElements` (~1 cr), then pull `size:25` for scoring (~25 cr). 25 rows is an accepted probe size — the sample stays representative.

## 1 · The recipe (firing order)
**AI Ark discovery is lookalike-ONLY on this plan.** Per sub-vertical of the brief:
1. Build one **tight seed cluster**: 5 near-identical ✅ companies from an already-verified pot (Prospeo output is ideal — the indexes barely overlap, so seeds transfer cleanly).
2. Fire ONE call: `{"lookalike":"<5 domains comma-separated>","location":"<enum names>","minEmployees":N,"maxEmployees":N,"size":50}` via direct MCP JSON-RPC (`POST https://api.ai-ark.com/v1/mcp?token=$AI_ARK_API_KEY`, tool `company_search`).
3. Repeat with the NEXT sub-vertical's cluster. Clusters are additive (~94% mutually net-new).

**Banned (measured, overturns "filter-first is the foundation" — tam-mapper Stage 3b order):**
- `keyword`/`keywordMode`/`keywordSources` → tier-gated, `401 service unavailable`.
- Filter-first discovery (`industry` enums ± `excludeIndustry`, no lookalike) → FAILED both briefs: 2.0% precision on the soft brief; <50% gate-fail on the hard brief. The industry taxonomy cannot exclude company TYPES (consultancies, suppliers, housing associations all tag as "construction"; product-SaaS tags as "software development").
- There is NO domain-exclude argument — enforce cumulative excludes client-side, always.

## 1.5 · Schema source + docs-mined findings (2026-07-09)
- **The authoritative filter schema is the MCP resource `ark://guide/company-search`** (read free via ReadMcpResourceTool) — the website docs render client-side and hide it. Guide documents: `account.type` enum (privately_held/public_company/non_profit/educational/government_agency), `naics`/`sic`, `productAndServices`, funding filter, `metric` employee/growth filters, nested keyword filter with sources/modes, `foundedYear`/`revenue`/`retailSize` ranges.
- **Measured warnings:** the flat MCP tool params `type`/`excludeType` return `400 request not readable` in every shape tried; passing the guide's nested `requestBody` through the MCP tool is **silently ignored** (returned Tata Group for a UK-groundworks filter — an unfiltered search that still bills). Do NOT use either path until the schema mismatch is resolved with AI Ark support.
- `POST /v1/lists` server-side excludes exist (10 lists × 10K IDs, 24h expiry) — the efficient exclude path for multi-cluster runs. A Credit Retrieval endpoint exists per docs `llms.txt` (slug unresolved). Rate limits: 5/s, 300/min, 18K/hr.

## 2 · The probe protocol
- One cluster = one `size:1` count call (+~1 cr) then one `size:25` scoring call (~25 cr). The 25-row sample is representative — that pair is the verdict. (The lab's original runs used size:50 at ~50 cr before the per-row billing model was confirmed — 25 halves the probe cost with no verdict loss.)
- Post-filter the 50 client-side (HQ country, headcount band, cumulative excludes) before scoring; score survivors via the `lilly-lead-score` gate; first-10 gate ≥5/10 else re-seed once.
- Validate `industry`/`location` enum values with the free `industry_search`/`location_search` tools first; probe billing by logging every paid call.

## 3 · The stop-rule (measured)
- **Seed verticality is the precision dial (26.6-pt swing):** a tight single-model cluster scored 84-86.8%; a looser mixed-model cluster scored 57.4%. If a cluster scores <70%, do NOT retune filters — re-pick tighter seeds (one retry), else that sub-vertical is done.
- Stop adding clusters at the first one <70% (brief B cluster 2 @ 57.4% = ceiling) or when inter-cluster redundancy climbs (baseline ~6% at 2 clusters).

## 4 · The numbers
| Brief | Cluster | totalElements | Precision | Projected vol |
|---|---|---|---|---|
| A | filter-first (control) | 13,501 | FAILED <50% | — |
| A | groundworks/civils seeds | 1,276 | 86.8% | ~1,108 |
| A | roofing/brickwork seeds | 1,544 | 79.6% | ~1,229 |
| B | filter-first (control) | 28,825 | 2.0% | — |
| B | dev-agency seeds | 1,434 | 84.0% | ~1,205 |
| B | AI/DX-consultancy seeds | 1,550 | **57.4% — ceiling** | — |

**Cross-provider law:** AI Ark ∩ Prospeo = 0.75% (B) / 6.4% (A) of returned domains. Running both platforms ≈ doubles the qualified universe per brief. 4 calls per brief bought the verdict both times.
