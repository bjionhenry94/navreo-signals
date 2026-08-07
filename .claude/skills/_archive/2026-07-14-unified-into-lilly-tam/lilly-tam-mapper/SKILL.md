---
name: lilly-tam-mapper
description: "Orchestrator skill that builds a complete cross-provider TAM by chaining Ocean → Prospeo → AI Ark-filters in cost-ascending order (AI Ark `lookalike` is PERMANENTLY BANNED by the user 2026-07-10 — Stage 3 runs on AI Ark FILTERS only: industry/naics/sic/productAndServices/location/size), with growing exclusion lists, three-pot output (qualified / borderline / off-brief), mandatory WebFetch verification of every sample, and saturation early-stop. Each provider indexes different companies, so combining both maximises TAM coverage while the cumulative exclude list prevents paying for overlap. Use this whenever the user wants to map their full market, find every company in a vertical, build a complete cross-provider prospect list, or expand a TAM beyond a single source. Trigger on phrases like 'map TAM', 'TAM mapper', 'build the full TAM', 'find every company in [vertical]', 'complete prospect list across providers', 'expand the TAM across all providers', 'I want the full picture', 'map our market'. Calls each provider's single-tool skill (lilly-ocean-tam-builder → lilly-prospeo-list-builder → lilly-ai-ark-list-builder), deduplicates by canonical domain, hands off qualified + borderline pots to lilly-decision-maker-finder when the user explicitly asks. Does NOT run DM enrichment itself (separate hand-off step)."
---

# Lilly TAM Mapper

## Purpose

## 🚫 2026-07-10 USER DIRECTIVE — AI Ark: lookalike BANNED, FILTERS are the method (supersedes Stage 3 legacy text and lab update #4)

**AI Ark lookalike searches are permanently banned** — never fire `company_search` with the `lookalike` parameter, regardless of brief type or measured precision. **AI Ark stays in the TAM chain as a FILTERS-ONLY Stage 3** (user clarification 2026-07-10: "we need to use their filters"): `industry` enums (validate via `industry_search` / `ark://reference/industries`), free-text `industries`, `productAndServices`, `naics`/`sic`, `location`, `minEmployees`/`maxEmployees`, founded/revenue/funding ranges. Protocol per search: `size:1` count (~1 cr, per-row billing) → `size:10` scored gate via `lilly-lead-score` (hard abort <50%; one retry layering naics/sic/productAndServices) → explicit user go-ahead → sized pull. Known traps: `keyword` param tier-gated (401); flat `type`/`excludeType` 400; nested requestBody via the MCP tool silently ignored while billing — never use it. AI Ark's other carve-outs (email-finder fallback, current-role DM finding in dm-finder-v2) are unaffected — those are filter-based already. Any `lookalike`-based text below is historical reference only.

## ⚡ 2026-07-14 RECALL-MAX METHODOLOGY (PROVEN, 30-brief lab — supersedes precision-first shape selection everywhere below; full evidence `lilly-tam-recall-lab/RESULTS-30.md`)

The lab measured that precision-first shape building starved recall by 60-85% (B2B SaaS US: 4,711 tight vs 29,804 @ 88% loosest-defensible). **Composite result: 25/30 briefs, median 3.6× volume at the same ≥70% bar.** Every stage of this orchestrator now selects shapes by the RECALL-MAX rule:

1. **Open at the LOOSEST defensible shape** — native classifier alone (Prospeo `company_type.subtypes` or one `company_industry` enum family) + headcount + geo. Never open with narrowing flags (`business_model`, `has_subscription`) — add them only if the gate fails.
2. **≥70% on a ≤25-row sample → try one WIDER rung** (adjacent subtype/enum). Keep widening until a rung fails <70%. **Chosen = the biggest pool that held ≥70%**; the failed rung is the recorded maximality proof. <70% → add exactly ONE narrowing layer, re-gate, max 3 shapes.
3. **Rung viability is GEO-DEPENDENT** — [SaaS,Platform] passes UK (76%), fails US (68%); MSP keywords 80% UK → 16% US. Score every rung in its own geo; never transfer.
4. **Dual-number TAM always:** per-provider pools AND the domain-deduped union. Measure overlap per brief from the samples — near-disjoint FAILS on tight niches (MSP UK measured 20% overlap).
5. **Brand/product briefs are NOT structural fails on Prospeo** — the E-commerce subtype ladder measured 60,769 @ 80% on the DTC brief AI Ark structurally fails (~40-50% ceiling there). Route brand briefs to Prospeo Stage 2, never to AI Ark Stage 3.
6. **Provider-swamp briefs** (US MSPs, US management-consulting — staffing/IT-consulting own the vocabulary on both indexes): no filter shape reaches 70% in 3 iterations. Route: pull the best 55-68% pool small and triage via `lilly-lead-score`, or switch to signal mechanisms. Don't burn iterations.
7. **Prospeo `company_lookalike`/icp_text is BANNED** (user 2026-07-13: all lookalike features decay — every provider). Stage 2 runs classifiers/enums/self-ID keywords only. Any icp_text text below is historical.
8. **Never request emails/contact enrichment in company stages** (user 2026-07-13) — TAM mapping is company-fields-only; enrichment happens only at the explicit DM hand-off.
9. **Gotchas:** Prospeo keyword baskets rerank non-monotonically (a wider basket can SHRINK the pool — treat baskets as probes); "Truck Transportation" is an INVALID Prospeo enum; AI Ark JSON-RPC returns plain JSON, not SSE; index drift is real — re-fire anchor probes each run.
10. **DM hand-off** goes to the VERIFIED method (dm-finder skills, 2026-07-14: Prospeo /search-person = 100% title accuracy with long-tail expansion + Director+ layering + dual-location; 90% bar).

---

Orchestrator skill. Builds a cross-provider TAM by chaining the three single-tool list-builder skills (Ocean → Prospeo → AI Ark) in cost-ascending order, growing the exclusion list across phases so we never pay twice for the same company, verifying each sample via WebFetch before pagination, and producing a three-pot output (qualified / borderline / off-brief). Output feeds the user's hand-off to `lilly-decision-maker-finder`.

The whole point of this skill is **coverage with cost discipline**:
- Each provider indexes different companies. Running all three surfaces cos none would alone.
- The exclude list grows phase-by-phase, so we never pay providers to re-find cos we already have.
- Cheap iteration (re-seed loops, sample-only) over expensive pagination.
- Honest stop conditions: precision floor, saturation signal, soft-category mismatch.

This skill does NOT do decision-maker enrichment. That happens separately, via `lilly-decision-maker-finder`, after the user reviews the TAM and explicitly hands it off.

---

## When to Use

Trigger when the user wants to:
- Build a complete TAM that uses all available providers (not just one).
- Find every company in a vertical / "don't miss anyone".
- Expand a single-source TAM (Ocean-only or Prospeo-only) with cross-index coverage.
- Map their full addressable market before committing to DM enrichment spend.

Accept input forms:
- "Build a TAM mapper for [brief]"
- "Map the TAM for [vertical]"
- "Find every [type of company] across all providers"
- "I want the full picture, not just Ocean"

Skip / don't trigger when the user asks for:
- A single-provider TAM ("just run Ocean", "Prospeo only") → invoke that single-tool skill directly.
- A fixed account list ("here's 50 cos, find DMs") → go straight to `lilly-decision-maker-finder`.
- DM enrichment as the primary deliverable → also `lilly-decision-maker-finder`.

---

## Architecture

```
lilly-tam-mapper  (this skill — orchestrator)
   │
   ├──> [Stage 0.5: Pre-flight saturation probe]   (1 cr — only when input list provided)
   │
   ├──> lilly-ocean-tam-builder       (Stage 1: Ocean lookalike + keyword)
   │       └──> lilly-lead-score      (sample-fit gate, every page 1)
   │
   ├──> lilly-prospeo-list-builder    (Stage 2: Prospeo /search-company)
   │       └──> lilly-lead-score      (sample-fit gate, every page 1)
   │
   ├──> lilly-ai-ark-list-builder     (Stage 3: AI Ark /v1/companies — 3a + 3b)
   │       └──> lilly-lead-score      (sample-fit gate, every page 1)
   │
   ├──> [Stage 3.5: Brand-recognition spot-check]  (catches Tesla-class drift before DM hand-off)
   │
   └──>  USER REVIEW + HAND-OFF
            │
            └──> lilly-decision-maker-finder  (separate skill, manual trigger)
```

Each list-builder is single-tool and standalone. This orchestrator owns:
- Sequencing (cost-ascending: Ocean → Prospeo → AI Ark).
- Cumulative exclusion-list growth between phases.
- **Seeding the exclusion list from Supabase at Phase 0** — before the first provider call, pull the central suppression + contact history via the shared helper `~/.claude/skills/_shared/navreo_db.py`: `navreo_db.check_exclusions(client_id, emails=[...], domains=[...])` for spot-checks, or for full-list seeding query `GET /rest/v1/v_exclusion?client_id=eq.{client}` (plus `client_id=is.null` global rows) with `navreo_db.rest()`. This replaces the old hand-curated CSVs (`marketing_exclusion_domains.csv` etc. — those are already imported into Supabase `suppressions`). Fails soft: if Supabase is unreachable, fall back to the local CSVs and say so in the run summary.
- Three-pot output (`qualified.csv` / `borderline.csv` / `off-brief.csv`).
- Cross-provider domain canonicalisation.
- Saturation detection.
- Hand-off to `lilly-decision-maker-finder` when the user asks.

---

## ⚡ 2026-07-09 Methodology-Lab updates (MEASURED — supersede conflicting text below)

The `lilly-tam-methodology-lab` run (3 briefs + a 10-brief TAM map + volume iteration; playbooks + LAB-LOG in that skill's folder) measured the following. Where anything below in this file conflicts, THESE win:

1. **Entity-type keyword altitude law.** Keywords must say what the company IS at the brief's entity altitude: services briefs = "X agency/contractor/consultancy" phrases; brand/product briefs = product-category + "brand" phrases (the suffix is load-bearing: dropping it collapsed 86%→30%) PLUS the provider's entity flag — Prospeo `company_type:{"business_model":"B2C"}`, Ocean `ecommerce:true`. Buyer-side vocabulary on brand briefs = 32%; category+flag = 83-90%.
2. **Ocean sampling is FREE via the `ocean_data_api` MCP** — first page of any unique filter combo at `num_results≤10` returns `creditsUsed:0`; `search_after` pagination is blocked at low balance. NEVER sample via REST (1 cr/call for the same read). Vary the query (shards, tiers, clusters) to stack free samples; pay only to extract.
3. **Ocean lookalike exposes relevance tiers A/B/C — they ARE the decay curve** (supersedes "no usable similarity threshold" and the page-depth safe/bulk batching rules on the MCP path). Pin per-tier via `minRelevance`=`maxRelevance`. Stop-rule: extract **A+B on hard-filterable briefs** (B holds A's precision at 3.5-7.5× volume), **A-only on soft-category briefs**, **never C** (0-20%).
4. **AI Ark is FILTERS-ONLY — lookalike is BANNED (user directive 2026-07-10, "once and for all"; overrides the lab's lookalike doctrine).** Company discovery on AI Ark uses flat filter params: `industry` (validate enums via `industry_search` / `ark://reference/industries`), `industries` (free-text advanced), `productAndServices`, `naics`/`sic`, `location`, `minEmployees`/`maxEmployees`, founded/revenue/funding ranges. Engineering controls (measured): `keyword` param is tier-gated (401); flat `type`/`excludeType` 400; nested requestBody via the MCP tool is SILENTLY IGNORED while still billing — never use it; industry-enum-only shapes measured 2-50% precision, so EVERY AI Ark search runs a `size:10` scored gate first (hard abort <50%) and layers naics/sic/productAndServices to sharpen before any larger pull. Billing ~1 cr/row — `size:1` for counts.
5. **AI Ark bills ~1 credit per ROW returned.** Probe = `size:1` count (~1 cr) + `size:25-30` scored sample. Never size:50 probes.
6. ~~Prospeo icp_text lookalike~~ — **RETIRED/BANNED 2026-07-13 (user: all Prospeo/AI Ark lookalike features decay).** Its former volume role is covered by the recall-max classifier ladder (see 2026-07-14 banner), which measured strictly bigger pools (subtypes-alone 29,804 vs icp_text-era hundreds).
7. **Prospeo `company_naics` `{"include":[ints]}` is a validated volume lever** — 100% on a 7,786-co consumer-goods pool; but code-dependent (supplement codes → pharma bucket → 0%). Probe page 1 per code family. `company_products_services` matches sellers-not-makers — dead for brand-finding.
8. **Prospeo keyword EXCLUDES reshuffle ranking** and reduced precision on 3 of 6 measured re-probes — treat as a 1-cr hypothesis with the prior filter as fallback, never an assumed fix. (Ocean's `noneOf` excludes DO work: +7 to +27 pts.)
9. **Category-shard sweeps recover volume on fragmented-vocabulary briefs** (8-18 single-category probes, sum only ≥70% shards, 20-30% overlap haircut, domain-level dedupe at extraction). Zero-hit shard phrasings are provider INDEX GAPS — route that category to another provider.
10. **Cross-provider overlap measured at 0.75-6.4%** (all pairs, all briefs) — use a ~5% haircut, and treat the three-provider chain as ~tripling the universe.

11. **NATIVE ENTITY CLASSIFIERS FIRST (docs-mined 2026-07-09).** Before any keyword/icp_text/lookalike approach, check whether the provider has a native filter for the brief's entity type and fire it as approach 0: Prospeo `company_type.subtypes` (27 values incl. SaaS/Agency/Construction/Consulting/Logistics/Marketplace) + `business_model` (8 values) + `has_subscription` — B2B SaaS measured at 8,968 @ ~80%, 20× the icp_text pool; Ocean `ecommerce:true`, `employeeFilters` (by employees' skills/titles — 100% on the dev-agency brief), `locationsCount` (multi-site orgs), `company_founded`-equivalent `yearFounded`. Keywords are now the THIRD approach, not the first.
12. **Docs-mining maintenance rule.** The providers ship filters faster than our skills absorb them (the subtypes classifier sat unused while we built keyword workarounds). Re-mine https://prospeo.io/api-docs, https://docs.ai-ark.com/ (authoritative schema = MCP resource `ark://guide/company-search`, the website hides it behind client-side JS), and https://app.ocean.io/docs quarterly or at the start of any major TAM engagement; diff against the playbooks; validate new entity-classifying filters with 1-page probes before relying on keyword workarounds.

Per-provider recipes with the measured numbers: `lilly-tam-methodology-lab/PLAYBOOK-{ocean,prospeo,aiark}.md`.

---

## Slow TAM build (foundational principle)

**Sample slowly. Never auto-paginate through precision decay.**

Per-provider sample target: **~100 verified rows** before committing to deep pagination (Phase 4 Ocean / 10+ pages AI Ark). The point of the sample build is to *see the precision-decay curve* before spending on the long tail. Lookalike searches in particular decay measurably page-over-page (rule #24): top-ranked rows are tightest matches; deeper pages drift.

**A-grade spot-sample gate (2026-07-10 rule, runs BEFORE any deep pagination):** before committing to deep pagination on any provider, the ~100-row verified sample must score **≥90% brief-fit (an A in `lilly-list-audit` grade bands)**. Below A, **the rest of that source must NOT be pulled** — name what is leaking (the off-brief categories + example rows), tighten the filters, and re-sample until the sample grades A. Only an explicit user override in so many words unblocks a sub-A pull. Origin: the Commercial Roofing campaign shipped on an ungated pull, audited 74% on-ICP, and cost a 973-lead prune from a live campaign. The same gate applies at title level when the pots hand off to `lilly-decision-maker-finder` / `-v2` (both carry it as their Step 2.5 / probe gate).

**Pagination control rule (applies to every stage once pagination has begun): running precision gate.**

After every batch, recompute the running verified-precision (sample-fit %) over the cumulative sample for that provider. Then:

| Running precision | Action |
|---|---|
| **≥90%** | Auto-continue paginating |
| **60-89%** | **HALT. Surface the precision number with the depth-decay pattern. Get explicit user confirmation before paginating further** — the pool has decayed below the A bar the sample was approved at. |
| **<60%** | **HALT — hard floor. Wastage cost outweighs pool value below this; recommend stopping this source, do not paginate further without an explicit override.** |

Why this rule matters: Ocean lookalike precision dropped from 70% (page 1) to 40% (pages 4-6) in the surplus-buyer 2026-05-03 run. Without the halt-and-confirm gate, the orchestrator would silently paginate to Phase 4 on a decaying pool, burning thousands of credits on cos that mostly fail verification. 60% is the empirical floor where pool quality outweighs cleanup cost.

**Lookalike pagination batching (Ocean Stage 1 + AI Ark Stage 3a only):**

Start in **safe mode** (small batches, verify each), then graduate to **bulk mode** only on user authorization.

| Mode | Batch size | When to use |
|---|---|---|
| **Safe (default)** | 20 cos per batch (or lowest provider-accepted size) | Pages 1-3 of any new lookalike search. After each batch, run `lilly-lead-score` to verify and report precision. |
| **Bulk** | 200 cos per batch (4 pages of size:50 fired together) | Only after pages 1-3 in safe mode have hit ≥70% precision **AND** the user explicitly authorises switching to bulk. Then continue at 200-co batches until the 60% halt-gate fires. |

Safe mode protects against wastage on bad seeds before the user has confirmed the cluster is clean. Bulk mode is the throughput mode once confidence is established. **Bulk mode is opt-in by user — never auto-switch.**

Filter-driven searches (Ocean keyword pass, Prospeo `/search-company`, AI Ark Stage 3b) don't apply this batching rule because they don't have lookalike-style depth-decay. Paginate them via the per-skill standard.

**100-row sample target:**

For each provider, the sample-build phase ends when ONE of these triggers:
1. ~100 verified ✅ rows accumulated for that provider (achievable target reached).
2. Running precision drops below 70% AND user does not authorize further pagination.
3. Saturation: ≥80% of returned cos already in cumulative excludes (rule #9).
4. Provider's `total_count` exhausted (Prospeo edge case).

After ANY trigger fires, hand to user: "Stage X provider sample complete (N verified, K% precision, Y credits spent). Continue to deeper pagination, or move to next stage?"

**This per-provider ~100-row sample → hand-to-user pause IS the company-level sample-audit gate: always get explicit go-ahead before deep pagination — never auto-continue silently past it, regardless of precision.** And when the qualified / borderline pots hand off to `lilly-decision-maker-finder` for DM enrichment, the **title-function audit runs there too**: Step 2.5 pulls ~100 DMs, classifies their titles via `lilly-list-audit`, and pauses for go-ahead before any enrichment spend. The sample → audit → pause → full-pull discipline applies at BOTH the company stage (here) and the DM stage (the hand-off).

### Seed verticality — pick seeds that are near-clones of each other

The single biggest precision lever for lookalike searches (Ocean Stage 1 + AI Ark Stage 3a) is **how vertically aligned the seed set is**. The lookalike algorithm clusters around the seed centroid; the tighter the seeds sit on a single sub-vertical, the tighter the returned cluster.

Empirical data from the surplus-buyer 2026-05-03 run:
- **Mixed seeds across 5 sub-verticals (industrial / ITAD / office furniture / mobile / asset recovery):** 30% sample precision. Cluster drifted to "general IT services with hardware lifecycle."
- **Per-sub-vertical tight clusters (5 ITAD seeds OR 5 furniture seeds OR 5 industrial seeds, run separately):** 86-100% sample precision per cluster. Each cluster stayed in its own buyer model.

**Rule for multi-sub-vertical briefs:** ALWAYS run one tight-seed call per sub-vertical, not one mixed-seed mega-call. 5 sub-verticals × 1 sample call each = 5 credits, ~5x better precision than a mixed mega-call. Per-cluster pagination follows the slow-build rule independently.

**How to pick tight seeds:**
1. Within each sub-vertical, all seeds should describe their primary business model in nearly identical language ("ITAD provider", "office furniture liquidator", "industrial machinery dealer who buys").
2. Avoid seeds that span multiple sub-models (e.g., a hybrid ITAD-and-managed-services co; a furniture-and-decor dealer). They drag the cluster centroid into mid-territory.
3. Geographic homogeneity is secondary to model homogeneity, but US-cluster + non-US-cluster sometimes pull tighter than a global-mix cluster.
4. After running the tight call, look at the FIRST page's first 5 results — if they don't all match the seeds' sub-vertical exactly, the seeds aren't tight enough; re-pick from the verified pot.

This is the canonical default for any soft-category brief. Use mixed seeds only when the brief is single-sub-vertical and the user has just provided 5-6 truly homogeneous seeds upfront.

### Precision-decay-recovery protocol (lookalike-based stages)

Neither Ocean nor AI Ark exposes a usable similarity-score threshold (Ocean v3 rejects `minScore`; AI Ark has no score field at all). When lookalike precision decays below 70%, the recovery path is **filter-layering then mode-switching**, iterated up to 3 rounds. **Applies to both Ocean Stage 1 lookalike AND AI Ark Stage 3a lookalike.**

| Round | What to fire | Why |
|---|---|---|
| **Round 1** | **Re-seed** with 5 cleanest near-identical cos from the verified pot — tighter sub-vertical homogeneity than the original seeds | Re-seeding is the cheapest fix. Per the seed-verticality rule, tighter clusters yield tighter results without adding filter noise. Try this BEFORE adding filters. |
| **Round 2** | Re-seeded lookalike + **layer buyer-type keywords** on top | If re-seeding alone didn't recover, narrow the candidate pool with vocabulary-pure buyer-type keywords. Keeps seed signal, adds language gate. |
| **Round 3** | Re-seeded lookalike + keywords + **industry filter** | Tightest layered call. If even this fails, the brief × provider has plateaued. |

**Stop conditions for the recovery protocol:**
- Any round restores precision to ≥60% → continue paginating that round per the slow-build rule.
- All 3 rounds yield <60% → accept the verified pool from earlier pages and move on. The brief-x-provider combination has plateaued.
- Saturation: ≥80% of returned cos already in cumulative excludes → stop, hand to next provider.

**Auto-loosen rule when filter narrows too far:**
If a layered call returns `total_count < 1,000`, the filter is too restrictive — recall is being cut, not just noise. **Auto-suggest loosening BOTH industry and keyword layers** before paginating that round:
- Drop or simplify the keyword layer (e.g., remove subject-matter-specific terms; keep only the strongest buyer-type phrases).
- Broaden the industry list (add 3-5 adjacent industries; e.g., add "Recycling", "Wholesale Trade", "Business Supplies and Equipment" to an IT-only list).
- Re-fire the layered call, target `total_count` in the 1,000-50,000 sweet spot (tight enough to be on-brief, broad enough to capture the real vertical breadth).

A `total < 1,000` after layering on a 14-country high-GDP geo means the brief's actual TAM has been cut to a sub-vertical slice (e.g., industrial-machinery-only when the brief said "machinery, laptops, phones, anything"). Loosening preserves recall while keeping the precision lift the layering provided.

**Cost note:** each round is 1 sample call (1 cr Ocean baseline / ~7 cr Ocean layered / 1 page AI Ark). 3 rounds with possible loosen-retries = 5-15 cr per provider — cheap insurance against burning Phase 4 budget on a decaying pool.

---

## The 4-stage orchestration workflow

### Stage 0: Pre-flight + soft-category gate

**Free preflight (zero credits):**
- Ocean: `GET /v2/credits/balance`, `GET /v2/data-fields` (validate vocabulary).
- Prospeo: `POST /account-information` (balance).
- AI Ark: see Stage 3 (balance endpoint returns 401, diagnostic-call instead).

**Soft-category gate (the up-front question):**
> "Is your brief's primary distinction a dimension data providers can filter on (industry, geography, headcount), or a softer one (services-vs-software, B2B-vs-B2C, hardware-vs-software, agency-vs-platform, app-dev-vs-app-growth)?"

| Answer | Implication |
|---|---|
| Hard-filterable | Standard sample → paginate flow. Lookalike + keyword both work. Expect 50-80% sample precision. |
| Soft-category | Lookalike clustering will skew toward the dominant index density (often platforms in ad-tech, dev shops in services). Plan for 10-30% sample precision on lookalike, re-seed iterations, and possibly pivoting to keyword-driven search. Use **buyer-type keywords** only (rule #11). |

**Gather brief inputs from the user:**
- 5-6 seed domains (for Ocean lookalike + AI Ark lookalike when both are run).
- Country list (default: high-GDP set per `project_navreo_icp_geography`: US, GB, CA, AU, IE, NZ, DE, NL, CH, SE, NO, DK, FI, SG).
- Headcount buckets (default: `["11-50","51-200","201-500"]`).
- Industry filter (Ocean validates via `/v2/data-fields`, Prospeo + AI Ark via probe).
- Buyer-type keywords (e.g. `"app marketing agency"`, `"mobile growth agency"` — never bare subject-matter like `"mobile app marketing"`. See rule #11).
- Soft-category flag (from gate above).

**Auto-exclude tool/SaaS noise for service-provider briefs (rule #23).**

When the brief targets **service providers** (agencies, consultancies, integrators, ID firms, growth shops, etc.) operating in a **tool-heavy vertical** (Amazon ecosystem, e-commerce, ad-tech, mar-tech, sales-tech, dev-tooling), tool/SaaS vendors flood the keyword and lookalike pools because they share the vertical's vocabulary. Auto-prepend the following exclusions to every Stage 1-3 call:

```jsonc
// Ocean: excludeIndustries (additive on top of the standard B2B kill list when relevant)
"excludeIndustries": [
  "Computer Software", "Information Technology", "SaaS",
  "Marketing Automation"   // marketing automation IS a tool itself, not a service category — exclude when brief targets agencies
]

// Ocean / Prospeo / AI Ark: keyword.noneOf (or equivalent negative keyword filter)
"noneOf": [
  "platform", "intelligence", "tool", "SaaS", "software",
  "marketing automation", "automation platform"
]
```

**Important caveat — when NOT to auto-apply:** if the brief's primary target IS a tool / SaaS / platform / marketing-automation category (e.g. "find me marketing automation buyers", "list e-commerce SaaS vendors", "all CDP platforms"), do NOT auto-apply these exclusions — they would block the brief's target. The auto-exclude triggers only when the brief targets **service providers in a tool-heavy vertical**, not when the brief targets the tools themselves.

Decision flow:
1. Is the brief targeting agencies / consultancies / services / integrators? → Auto-apply exclusions.
2. Is the brief targeting platforms / tools / SaaS / marketing automation tech? → Skip exclusions (the noise IS the brief).
3. Ambiguous (e.g. "Amazon companies" without specifying agency vs tool)? → Surface the auto-exclude to the user, ask one clarifying question before locking filters.

**Soft-category brief recipes (rule #28).** Some briefs need brief-type-specific exclusions on top of (or instead of) Rule #23's vertical-aware exclusions. Apply the relevant recipe:

| Brief | excludeIndustries |
|---|---|
| Interior design firms | Software, SaaS, Blogging Platforms, Lifestyle |
| Architecture firms | Software, SaaS, Blogging Platforms, Construction (if ID-only) |
| Design agencies | Software, SaaS, Blogging Platforms, E-Commerce |
| Marketing agencies | Software, SaaS, Blogging Platforms |
| Consulting firms | Software, SaaS, Blogging Platforms, Recruiting |

Default `linkedinIndustries` SOFTLY: try the most specific tag first; if recall too narrow, drop the inclusion filter and rely on exclusions alone. LinkedIn often classifies adjacent firms under different umbrellas (e.g. ID firms tagged "Design" or "Architecture & Planning" rather than "Design Services") — strict includes cut recall.

**Confirm filters with the user before any paid call.** Show the final filter object with auto-exclusions highlighted so the user sees what's been pre-applied.

### Stage 0.5: Pre-flight saturation check (when input list provided)

**Trigger condition:** the user provides an existing company list (CSV, prior TAM, manual seed pool > 50 cos) AND asks to expand it. Skip this stage when the user is starting from scratch with no input list.

**Why this exists:** Amazon-agencies expansion run (2026-05-04) burned 13 credits across Ocean → Prospeo → AI Ark only to surface 38 net-new cos because the input list of 587 was already deeply saturated. A single 1-credit pre-flight probe would have predicted the saturation, surfacing the recommendation to skip the expansion entirely.

**Procedure (1 credit ceiling):**

1. Fire ONE Ocean lookalike call: `size: 50`, 5 seeds picked from input list (most-representative cos), input list as `excludeDomains` (cap unlimited).
2. Compute `overlap_rate = (returned_cos already in input list ∪ canonical_excludes) ÷ returned_cos`.
3. Decision matrix:

| Overlap rate | Implication | Recommendation |
|---|---|---|
| **≥80%** | Input list is well-mapped; cross-provider expansion will yield <30 net-new cos | **Recommend SKIPPING expansion entirely.** Surface the overlap %, projected net-new yield, and projected credit spend. Ask the user to confirm before proceeding to Stage 1. |
| **50-79%** | Moderate saturation; expansion will yield 30-100 net-new cos | Proceed to Stage 1, but warn the user that yield will be modest. Set expectation for find-rate per credit (likely 1-3, not 5+). |
| **<50%** | Input list has significant blind spots; expansion is high-yield | Proceed to Stage 1 normally; expect strong net-new yield. |

**State the recommendation, then offer the choice (CTA pattern):**
> "Pre-flight probe: 88% overlap (44 of 50 sample cos already in your list). Projected net-new from full Stage 1-3 expansion: ~25-40 cos for ~10-15 credits. **Recommend skipping expansion** — your existing list is well-mapped. Confirm skip, or say 'continue' to run anyway."

**Cost ceiling:** 1 Ocean credit. Saves a typical 10-15 credits in over-saturated expansion runs.

### Stage 1: Ocean — delegate to `lilly-ocean-tam-builder`

**2026-07-09 lab overrides for this stage:** sample via the MCP free browse window, never REST (lab update #2); on brand briefs add `ecommerce:true` + category-altitude keywords (#1); lookalike sampling and stop-rules run in relevance-TIER space, not page space (#3); use category shards for fragmented-vocabulary briefs (#9).

Run Ocean's Phase 1 to Phase 3 (sample + iterate + verify). Phase 4 (full pagination) is opt-in and only when sample precision is clean.

**Hard rule: Stage 1 fires exactly 2 isolated angles — `keyword-only` + `lookalike-only`. Never `industries-only` (rule #26).** Confirmed 2026-05-04 (Run A): industries-only returned 304,462 raw with 0/15 sample precision (pure generic marketing/advertising umbrella). 1 wasted credit. Industry is a narrowing layer, never a standalone angle. If industry-anchored is wanted, pair with `lookalikeDomains` OR `keywords.anyOf` — but never alone.

**Keyword-first priority (always run keyword angle BEFORE lookalike):**

1. **Keyword call FIRST** — buyer-type-only keywords (`"app marketing agency"`, `"app growth agency"` etc.) + industry filter (`Marketing Services`, `Advertising Services`, etc.) + headcount + geo. 1 credit per sample. Anchors on WHO the company is — much higher precision for buyer-targeting briefs.
2. **Lookalike call SECOND** (optional) — seed-driven cluster discovery, only run after the keyword pass to fill gaps. 1 credit per sample.

The keyword pass is prioritised because:
- Buyer-type keywords lock onto the actual buyer profile (rule #11b) — no soft-category mismatch.
- Lookalike clusters skew to whichever sub-category dominates the index density (often platforms in ad-tech, dev shops in services). Less reliable as a primary.
- Keyword + industry + headcount + geo defines the brief precisely. Lookalike is just a way to find more cos similar to seeds — useful as a *supplement* to widen recall once the keyword pass establishes the precision baseline.
- Empirically (AppLift dry-run 2026-05-01): keyword pass yielded 4 net-new qualified at 50% precision; lookalike pass yielded 5 (incl 4 user-promoted hybrids) at 50% precision but with platform-cluster bias.

For hard-filterable briefs, the keyword pass alone is usually enough. For soft-category briefs, run both — keyword first, then lookalike to widen recall.

**WebFetch-verify all 10 sample candidates.** Tag ✅ on-brief / ⚠️ borderline / ❌ off-brief / ❓ unreachable.

**Build the three pots:**
- `qualified.csv` — verified ✅ on-brief.
- `borderline.csv` — ⚠️ hybrid, general, not-quite-fit (user-judgment).
- `off-brief.csv` — ❌ confirmed off-brief, kept for traceability and exclusion.

**Hand off to Stage 2:** all 3 pots' domains plus the 5-6 seeds become the cumulative exclude list (53+ domains typically). **Display the rolling TAM table** (see section below) before transitioning.

### Stage 2: Prospeo — delegate to `lilly-prospeo-list-builder`

**2026-07-09 lab overrides for this stage:** fire icp_text lookalike on every services brief as a mandatory second approach (lab update #6); brand briefs = "brand"-suffixed category keywords + B2C flag (#1) and probe `company_naics` (#7); keyword excludes are a hypothesis, not a fix (#8).

`lilly-prospeo-list-builder` calls Prospeo's `/search-company` (NOT `/search-person` for company discovery — see rule #15). One credit per page. The skill handles: filter-shape, buyer-type keywords, the 50% hard-abort gate, the 7/10 iteration rule, defensive client-side exclude filter (rule #16).

**Pass to Prospeo:**
- The cumulative exclude list (capped at Prospeo's 500-domain `websites.exclude`).
- Brief criteria (industry, geo, headcount, buyer-type keywords).
- Default stop precision = 7/10.

**Receive back:**
- New `qualified` rows (tagged `source = "prospeo_company_search"`).
- New `borderline` and `off-brief` rows.
- Iteration log (pages run, precision, credits spent).

**Append to existing pots, deduplicate by canonical domain (rule #3).**

**Saturation check (rule #9):** if Prospeo's net-new rate drops below 25% of returned cos, flag for user before Stage 3 — high overlap means AI Ark probably won't add much either, and you should ask whether to skip it.

**Hand off to Stage 3:** updated cumulative exclude list (typically 70-100+ domains by now). **Update the rolling TAM table** (see section below) — show Prospeo's verified ✅, find-rate, and the cumulative cross-provider qualified TAM before the user decides to fire AI Ark.

### Stage 3: AI Ark — FILTERS ONLY (2026-07-10 user directive; `lookalike` param BANNED — see banner at top)

**✅ PROVEN RECIPE (2026-07-10 methodology loop — 17/20 briefs ≥70% accuracy, ~939 cr; evidence in `lilly-aiark-methodology-loop/{METHODOLOGY,RESULTS}.md`). Supersedes the size:1-first protocol and all 3a/3b lookalike text below (historical only):**

1. **Shape by brief altitude.** Broad category (expect ≥10K): `industry` enums (validate free via `industry_search`) + `excludeIndustry` naming the observed leak + keyword self-ID synonyms WORD on `NAME,KEYWORD,DESCRIPTION` + geo + 11-200. Niche/service vertical: keyword self-ID PHRASES on `NAME,KEYWORD` **only** — DESCRIPTION poisons niche gates (client namedrops/capability mentions: 10-40% with vs 70-80% without, measured). Keywords say what the company IS; never capability tags ("Amazon marketing", "solar", "drone services"); add local-language phrases on non-English geos ("pistas de padel", "SAP beratung").
2. **Gate:** `size:10` page 0 (~10 cr; returns `totalElements`, so a separate `size:1` only when a shape might be discarded on count alone). Score via `lilly-lead-score`; <50% hard abort; <70% tighten one layer and re-gate; max 3 iterations.
3. **Deep blend:** pool ≥100 → one `size:10` page at ~70% depth, **page ≤950 hard cap** (offset limit ~10K — deeper pages return 0 rows/0 cr). Pool <100 = census, skip. Blended accuracy = mean(gate, deep) — the head is brand-sorted and flatters broad pools (90→60 measured).
4. **Dual-number TAM (report both, never one):** extraction pool = tight-shape count × blended accuracy; category estimate = broad-shape count × its measured precision. Counts ≥10,000 are display-capped floors.
5. **Route away, don't iterate:** brand/product briefs (AI Ark ceiling ~40-50% → Prospeo B2C flags / Ocean `ecommerce:true`); capability-flooded niches (the defining activity is a tool of a bigger profession) and micro-pools <20 true cos → census pull + `lilly-lead-score` triage.
6. Sized pulls at ~1 cr/row after user go-ahead; cumulative excludes are client-side (MCP exposes no excludeDomain; `POST /v1/lists` server-side for very large sets). MCP flat params only — nested requestBody via the MCP is silently ignored while billing.

`lilly-ai-ark-list-builder` calls `/v1/companies` in TWO distinct passes that find different cos:

- **Stage 3b — filter-based search (FOUNDATION).** Uses `account.*` filters ONLY (no `lookalikeDomains`). Filter-driven discovery, no precision decay over depth — surfaces a stable pool defined by industry + keywords + headcount + geography. Only viable on **filter-tier keys** — basic-tier silently drops `account.*` and would return global junk (e.g., EY, IBM, PwC for any filter combination).
- **Stage 3a — lookalike-based search (SUPPLEMENT).** Uses `lookalikeDomains` (max 5 seeds). LinkedIn-style seed clustering. Subject to precision-decay-with-depth (rule #24): top pages are tightest, deeper pages drift. Useful as a *recall-widener* on top of 3b's filter foundation.

**Order: 3b first (when filter-tier), then 3a.** Filter-based is the reliable foundation; lookalike is the supplement that catches cos with low seed-similarity that 3b missed. Run sequentially: fire 3b, add returns to cumulative excludes, then fire 3a. Net-new from 3a after 3b is typically 30-60% (cos that don't match the keyword signature but cluster with seeds).

**On basic-tier: skip 3b entirely; run 3a only (Path B).** Confirmed across multiple keys (`8616e6...`, `71f5a79f...`): basic-tier returns 100K+ random global cos for ANY filter combination. The diagnostic is binary — filter-tier key works, basic-tier doesn't. No middle ground.

**Pre-flight: TWO-STAGE diagnostic before any paid full-size call.**

| Diagnostic | What to fire | What it tells you |
|---|---|---|
| **D1 — filter-tier check** | `size:1` with `account.*` filters only (narrow country + headcount + buyer-type keyword, no `lookalikeDomains`) | If `totalElements > 50,000` AND first result doesn't match filter (e.g., DBS Bank for "Singapore + 11-50 + ITAD") → basic-tier, **`account.*` filters silently drop**. Fall through to D2; **skip 3b**. If `totalElements < 1,000` AND first result is brief-relevant → filter-tier valid, **3a uses Path A; 3b is also viable**. |
| **D2 — lookalike-only check** (only if D1 failed) | `size:5` with `lookalikeDomains` (5 cleanest seeds from qualified pot) + permissive `account.location.any.include` | If all 5 results are pure-fit → `lookalikeDomains` is honored on basic-tier. **3a uses Path B; skip 3b.** If random global cos → both filters drop, **ABORT AI Ark entirely**. |

Total diagnostic cost ceiling: 2 AI Ark credits.

**Don't auto-ABORT on D1 failure.** Basic-tier still honors `lookalikeDomains` for Stage 3a. Confirmed 2026-05-03.

**Hard rule on basic-tier (rule #29): if D1 fails, the ONLY working filters are `lookalikeDomains` (max 5 seeds) and `account.location.any.include`. DO NOT probe further.** Specifically: `account.industry.any.include`, `account.headcount.any.include`, `account.keywords.any.include` are silently dropped. Top-level `keywords` and `query` are not recognised. Confirmed across 4 shapes 2026-05-04 (Run B): exhaustive probing wasted 4 credits + 2 turns. The only path forward is firing 3-5 lookalike passes with DIFFERENT seed clusters (US-seeds, UK-seeds, UAE-seeds, AU/SG-seeds — each opens a different cluster) and client-side filtering on HQ + headcount + cumulative excludes.

#### Stage 3a — lookalike-based search

**Path A (filter-tier valid):** `lookalikeDomains` (5 cleanest seeds from qualified pot, no platform-flavoured seeds) + full `account.*` filter layer (industry, geo, headcount, buyer-type keywords). Cumulative excludes capped at 300 — smart-priority subset if over (brand recognition × headcount × web traffic).

**Path B (basic-tier):** `lookalikeDomains` only + permissive `account.location.any.include`. DO NOT pass `account.headcount` or `account.keywords` — silently dropped. After response, **client-side filter**:
- HQ country in target list (read `location.headquarter.country`)
- Headcount in target buckets (read `summary.staff.range.{start,end}` and `summary.staff.total`; NOT `summary.headcount` — doesn't exist)
- Domain not in cumulative excludes (read `link.domain_ltd`)

**Pagination rule for 3a:** apply slow TAM build (see section above). Sample to ~100 verified rows before committing to deeper pagination. Halt-and-confirm if precision drops below 70%.

#### Stage 3b — filter-based search (filter-tier only)

Skip if D1 failed (basic-tier).

Run with `account.*` filters ONLY — no `lookalikeDomains`. Surfaces cos that lookalike clustering missed:
- `account.industry.any.include` — buyer-targeting industry strings (validate via probe, taxonomy-strict)
- `account.location.any.include` — full English country names
- `account.headcount.any.include` — bucket strings ("11-50", "51-200", "201-500")
- `account.keywords.any.include` — buyer-type keywords (rule #11b)
- `account.domain.any.exclude` — cumulative excludes from prior stages + 3a returns (cap 300, smart-priority subset if over)

**Pagination rule for 3b:** same as 3a — slow build to ~100 verified, halt-and-confirm below 70% precision.

**Net-new yield from 3b** = rows that didn't surface in 3a. Often 30-60% of returned cos are net-new (cos with low seed-similarity score that lookalike ranked off the first pages).

**Saturation check (applies to both 3a and 3b):** if a page returns ≥80% domains already in cumulative excludes after client-side filter, stop paginating that sub-stage.

**Append to pots, dedupe by canonical domain. Display rolling TAM table at each sub-stage hand-off (3a → 3b → Stage 3.5).**

### Stage 3.5: Brand-recognition spot-check (mandatory before DM hand-off)

Late lookalike pages drift toward big-brand cos (Tesla-class) that pollute the TAM disproportionately. Run A 2026-05-04: SaaS-lookalike paginated 7 pages while precision held >50%, but pages 5-8 polluted with Tesla (105 leads), Meltwater (20), Ogilvy (6), Chargebee (5), NetSuite, Lusha. ~157 of 586 enriched leads off-brief. ~150 wasted Prospeo credits + ~42 polluted the Smartlead campaign before manual cleanup.

**Procedure (free, ~1 minute):**

1. Surface the **top 30 cos** in the qualified + borderline pots ranked by employee count / web traffic / LinkedIn followers (whichever fields are populated).
2. User reviews the table. Any obvious off-brief big brands (Tesla, Walmart, Microsoft, etc.) get flagged → moved to off-brief pot, added to cumulative excludes.
3. Optionally auto-WebFetch-verify any co with >2,000 employees (the empirical "drift attractor" threshold) for stricter screening.

**Block the DM hand-off until validation passes.** This gate is mandatory; it's free and catches the highest-cost downstream leak.

**Off-brief domain blocklist (rule #30):** maintain `lilly-tam-mapper/off_brief_blocklist.json` — a persistent list of domains that consistently drift into TAMs they shouldn't be in (Tesla, Meltwater, NetSuite, Chargebee, Lusha, Cognism, Belkins, Hawke Media, Patreon, Jasper, Ogilvy, M&C Saatchi Performance, etc.). Auto-prepend to the seed exclude list at Stage 1 start. After each run, prompt: "Any new drift attractors to add to blocklist?"

### Stage 4: Final review + hand-off (manual)

After Stage 3, present the user with the **final rolling TAM table** (per the section below) plus:
- `qualified.csv` count + per-source breakdown (Ocean / Prospeo / AI Ark).
- `borderline.csv` count — **shown separately, never rolled into qualified**.
- `off-brief.csv` count (locked out of enrichment).
- Cumulative credit spend per provider.
- Cost-efficiency: `verified ✅ qualified ÷ total credits = X cos per credit`. Borderlines are NOT in the numerator.

**State the recommendation, then offer the choice (CTA pattern):**
> "Recommend hand qualified + borderline pots to `lilly-decision-maker-finder` for DM enrichment. Confirm or stop here."

Per resolved decisions:
- **Borderline IS included in the DM hand-off** when the user proceeds (decision #1) — but is never counted as "qualified" in headline numbers.
- **Off-brief is never enriched.**
- **No hard credit cap** on Phase 4 if the user explicitly asks for a full pull (decision #2).

`lilly-tam-mapper` itself does NOT enrich DMs. The hand-off is a separate skill invocation.

---

## Rolling TAM estimate (mandatory at each stage boundary)

After every stage's WebFetch verification + pot append, display the running TAM table BEFORE asking the user about next steps. The user reads this to decide whether continuing to the next provider is worth more credits.

**Format (fixed; update at each stage boundary):**

| Stage | Projected total | Verified | Borderline | Off-brief | Sample size | Sample precision | Find-rate per credit | Net-new this stage |
|---|---|---|---|---|---|---|---|---|
| 1 — Ocean | ~15,533 | 7 | 0 | 3 | 50 (sample, 22,190 HQ-projection) | 70% | 7.0 | — |
| 2 — Prospeo | ~70 | ~70 | ~6 | ~13 | 89 (full pull, exhausted) | ~80% | 10.0 | ~70 |
| 3 — AI Ark Path B | ~4,760 | 14 | 6 | 5 | 25 size, 21 post-client-filter | 56% | 14.0 | 14 |
| **Total** | **~20,300** (after ~15% cross-provider overlap haircut) | **~91** | **~12** | **~21** | — | — | — | **~91** |

**Rules:**

1. **Projected total** (col 2 — the headline). Per-provider projection if the user paginated that provider to its ceiling. Total row sums them, minus cross-provider overlap haircut. Calculation per provider:
   - Ocean: `HQ-TAM × sample precision`.
   - Prospeo: `total_count × sample precision` (or actual count if already exhausted).
   - AI Ark: `totalElements × sample precision × dedupe factor` (0.80–0.90; flag that `totalElements` is display-capped at 10,000 and true ceiling may be higher).
   - **Total row haircut:** 10–15% for soft-category briefs (different providers index different cos); 20–30% for tight buyer-type briefs (recognised cos surface in all three).
2. **Verified** = WebFetch-confirmed on-brief. When sample is huge and verification was deferred, mark `(est, X% of N)` and flag the deferral.
3. **Borderline** stays in its own column. NEVER rolled into Verified — borderlines are a separate pot (auto-included on DM hand-off per decision #1) but the headline TAM is verified-only.
4. **Off-brief** covers confirmed off-brief, unreachable, and stale-data rows. Locked out of DM hand-off.
5. **Sample size** is the rows the provider returned (with HQ-projection or `total_count` in parens for context).
6. **Sample precision** = Verified ÷ Sample size — drives the Projected column.
7. **Find-rate per credit** = Verified ÷ credits spent THIS stage. Bench: ≥2.0/credit acceptable, <1.0 means re-think the angle or skip the next provider.
8. **Net-new this stage** = Verified rows that weren't already in cumulative excludes — the real cross-provider yield after dedupe.

**Always report alongside the table:**
- **Cost so far:** total credits spent across all providers, broken down per provider.
- **Saturation signal:** percentage of latest provider's returns that were already in cumulative excludes (rule #9).
- **Projected full-extraction COST** (paginate everything to ceiling) so user can compare projected total vs. credits to get there.

**Don't roll up to one number and skip the per-provider breakdown.** The user needs to see WHERE the wins are coming from to make the next-stage decision.

**3-column communication standard (rule #27):** every progress update on TAM size MUST distinguish three numbers, never collapsed:

| Column | Meaning |
|---|---|
| **Verified (sample)** | Qualified hits in the page-1 sample after `lilly-lead-score` classification |
| **Estimated TAM** | `raw_total × sample_precision` (the Projected total column above) |
| **Pulled (full)** | What's actually been paginated to CSV (0 at sample stage; updates each page) |

Never report a single number without specifying which column. After each provider's sample, surface the **Estimated TAM** explicitly and ask the user to confirm before paginating to "Pulled (full)". Run A 2026-05-04: presenting "110 verified" without column framing led to user pushback (sample-verified ≠ total TAM ≠ full list pulled).

---

## The growing exclusion list mechanic

Track a single canonical `cumulative_excludes` set across all stages. It grows monotonically:

| Stage start | What gets added |
|---|---|
| Stage 1 starts | Original seeds (5-6 domains) |
| Stage 2 starts | + Stage 1 results (qualified + borderline + off-brief) |
| Stage 3 starts | + Stage 2 results |

**Provider exclude caps:**
- Ocean `excludeDomains`: unlimited. No subset needed.
- Prospeo `filters.company.websites.exclude`: 500 domains. Smart-priority subset if exceeded.
- AI Ark `account.domain.any.exclude`: 300 domains. Smart-priority subset if exceeded.

**Smart-priority subset rule** (when over a provider's cap):
1. Rank cumulative excludes by `brand_recognition × headcount × web_traffic` (most-likely-to-resurface first).
2. Send top-N (=cap) to the provider's exclude.
3. Accept overlap on the long tail; dedupe at merge.
4. **Always report the dedupe haircut explicitly** so the user sees the net-new yield.

**Defensive client-side filter (rule #16):** after each provider returns results, ALWAYS post-filter results against the full `cumulative_excludes` set on the client side. Provider exclude flags are unreliable (Prospeo's `websites.exclude` was caught leaking `yodelmobile.com` and `fetch.com` in the AppLift dry-run). The client-side filter is free and catches all leaks.

**Domain canonicalisation (rule #3):** strip `www.`, strip `https://`/`http://`, lowercase. Strict exact-match for dedupe. `applift.co` and `applift.com` are distinct rows unless the user manually merges.

---

## Three-pot output policy

Standard output, every run:

| File | Contents | Goes to DM enrichment? |
|---|---|---|
| `qualified.csv` | Verified ✅ on-brief cos | YES (when user hands off) |
| `borderline.csv` | ⚠️ hybrid / general / not-quite-fit cos that pass user judgment | YES (decision #1: borderline auto-included on hand-off) |
| `off-brief.csv` | ❌ confirmed off-brief, ❓ unreachable, ⚠️ stale-data cos | **NO. Locked out.** Kept only for traceability and to seed future excludes. |

Schema (same across pots):
```
#, domain, name, primary_country, company_size, linkedin_industry, industries,
linkedin_url, verdict, pot, verdict_reason, source, ocean_description
```

`source` values:
- `ocean_lookalike_run<N>`
- `ocean_keyword_run<N>`
- `prospeo_company_search_page<N>`
- `ai_ark_lookalike` / `ai_ark_filter_only`

---

## Sample classification policy — delegate to `lilly-lead-score` (rule #25)

**Every sample-fit gate uses `lilly-lead-score`, not inline pattern-matching.** Each provider's sample (page 1, ~10-25 cos) flows into a single `lilly-lead-score` invocation that returns the verdict table + tally + sample-fit %. The orchestrator then routes on the % per its pagination rule (60% halt-and-confirm gate, 50% hard-abort gate).

**Why this delegation matters:**
- `lilly-lead-score` walks the LLM-first confidence ladder (training knowledge → WebFetch only when uncertain). 60-80% of sampled cos clear from training knowledge in seconds with zero web fetches.
- The previous inline pattern of "WebFetch every candidate" burned context, slowed iteration to minutes per sample, and frequently 403'd on cookie-walled sites.
- Centralising classification in one skill keeps verdict semantics consistent across Ocean / Prospeo / AI Ark samples — the same brief is scored the same way regardless of which provider returned the candidate.

**Invocation pattern (every sample-fit gate):**

```
After provider returns sample:
  1. Pass sample (company names + domains + brief recap) → lilly-lead-score
  2. Receive verdict table + tally (✅/⚠️/❌/❓ per row, with confidence tier)
  3. Append qualified to qualified.csv, borderline to borderline.csv, off-brief to off-brief.csv
  4. Route on sample-fit % per the pagination rule
```

| Phase | Classification path |
|---|---|
| Sample (page 1, ~10-25 cos) | **MANDATORY: pass to `lilly-lead-score`.** Verdict table + sample-fit % returned. |
| Full pull (post-pagination, thousands of cos) | **OPT-IN: pass to `lilly-lead-score` in batches of 25-50.** Quote wall-time first; user can defer to DM enrichment time. |

Verification tags (consistent with `lilly-lead-score` output):
- ✅ on-brief → `qualified` pot
- ⚠️ borderline → `borderline` pot
- ❌ off-brief → `off-brief` pot
- ❓ unknown / unreachable (ECONNREFUSED, 521, empty content, redirected to unrelated host) → `off-brief` pot with explicit `verdict_reason` flag, NOT promoted to enrichment regardless of API description quality

**Stale-data check (rule #17):** treat API descriptions as historic. `lilly-lead-score`'s confidence ladder catches stale data via WebFetch on Medium/Low-confidence rows. The AppLift dry-run caught `fetch.com` described by Prospeo as a London app agency (true 2018, before Dentsu acquisition) when the actual current site is `America's Rewards App` (consumer rewards platform). Verification is non-negotiable.

**Anti-pattern to avoid:** do NOT inline-classify samples by reading API descriptions and pattern-matching against the brief. That collapses the confidence ladder, hides anomalies (product-as-company entries, hardware-led miscategorisations, dead domains), and burns context with WebFetches the LLM didn't actually need. Always delegate to `lilly-lead-score`.

---

## Saturation early-stop (cost-saver)

Compute `net_new_rate = unique_new_domains / total_returned` after each phase.

| Signal | Action |
|---|---|
| Prospeo net-new < 25% | Ask user before firing Stage 3. High overlap means AI Ark probably won't add much. |
| AI Ark page returns ≥80% already-known domains | Stop paginating immediately. TAM-saturation signal. |
| Two consecutive re-seeds can't lift Ocean precision past 50% | Soft-category mismatch. Pivot to keyword-driven OR accept the niche is sparse OR stop. |

Saturation is distinct from precision drop. Both are valid stop conditions; surface honestly rather than burning credits trying to "make it work".

---

## Cost discipline

**Cumulative log at every phase boundary:**
- `credits_spent_so_far`
- `projected_full_run_cost`
- `qualified_per_credit_so_far`

Display this to the user before transitioning between phases. User can pull the brake at any boundary.

**No hard cap on Phase 4 full pull (decision #2):** if the user asks for the full pull, do the full pull. Surface projected cost transparently.

**Calibration from AppLift dry-run (2026-05-01):**

| Provider | Mode | Credits | Net-new qualified | Cos per credit |
|---|---|---|---|---|
| Ocean | Lookalike (run 1) | 1 | 5 (incl user promotions) | 5.0 |
| Ocean | Re-seed lookalike (run 2) | 1 | 1 | 1.0 |
| Ocean | Keyword (run 3) | 1 | 4 | 4.0 |
| Ocean | Keyword broader (run 4) | 1 | 1 | 1.0 |
| Prospeo | `/search-company` filter-only | 2 (1 probe + 1 productive) | 7 | 3.5 |
| AI Ark | Diagnostic (basic-tier abort) | 1 | 0 | n/a |
| **Total** | | **7** | **18** | **2.6** |

Bench: 2.0+ cos/credit is acceptable; below 1.0 means re-think the angle.

---

## Soft-category briefs (special handling)

A "soft-category" brief uses a dimension data providers can't filter on:
- Services vs software
- Agency vs platform  
- App-dev shop vs app-growth agency
- B2B vs B2C
- Hardware vs software

For these briefs:

1. **Expect 10-30% sample precision on lookalike.** The 50% hard-abort gate is likely to fire. Have re-seed iterations planned.
2. **Use buyer-type keywords only (rule #11.b).** `"app marketing agency"` ✅ (anchors on buyer type), `"mobile app marketing"` ❌ alone (anchors on subject matter, catches dev shops + general agencies + platforms).
3. **Default to keyword-driven search before lookalike** when the brief is well-defined.
4. **Verification is the only reliable gate.** No filter combination reliably distinguishes service models in the API taxonomies.
5. **Be honest with the user about TAM size.** Tight buyer-type niches typically have 50-300 cos worldwide in any given size range, not thousands.

6. **Adjacent sub-vertical → parallel seed cluster (rule #31).** When the first lookalike call's sample drifts into a coherent adjacent sub-vertical (≥20% of returns share a tight cluster — e.g. an agency lookalike call returning a stable cluster of platforms like CreatorIQ / Grin / Aspire), **propose splitting into a parallel sub-vertical pot with its own tight-seed cluster** rather than flagging them as off-brief. Compounds with rule #22 (per-sub-vertical tight seed clusters): the platform-drift cos become seeds for a SECOND tight cluster. Track multiple parallel pots (e.g. `qualified_agency.csv`, `qualified_saas.csv`) with cumulative excludes shared across both. Run A 2026-05-04: SaaS platforms surfaced as drift in an agency brief — the better play was treating them as a parallel adjacent pot, not noise.

---

## Hand-off to `lilly-decision-maker-finder`

After Stage 3 completes and the user reviews the TAM, ask:
> "Hand qualified.csv + borderline.csv to `lilly-decision-maker-finder` for DM enrichment? Off-brief stays out."

If yes:
- Pass both `qualified.csv` and `borderline.csv` (decision #1).
- Surface the standard DM-finder hand-off prompts: phone enrichment opt-in (default NO), brief role definition (default standard B2B sales DMs).

If no: leave the TAM as-is. The user can return to it later.

---

## Cloud upload (mandatory)

Every finished TAM pot this skill produces — `qualified.csv` and `borderline.csv` (never `off-brief.csv`, that one stays local) — MUST be uploaded to the central Supabase list store before the run ends. A TAM that only exists on this machine isn't done. Run:

`python3 ~/.claude/skills/_shared/list_upload.py <final.csv> --name "<descriptive list name>" --client "<Client>" [--folder "<Theme>"] --source-skill lilly-tam-mapper --brief "<one-line brief>" --owner "<who asked>"`

Then show the returned `https://navreo-signals.onrender.com/app/lists.html#<id>` link to the user — that link is part of the deliverable, alongside the CSV.

Folder rules: `--client` = the client named in the brief (internal/Navreo pulls → `Navreo`); add `--folder` ONLY when the brief names a campaign theme or segment (e.g. client `Amplifyy`, folder `Beauty`); never deeper than two levels. Re-runs with the same name+client replace that list's rows in place (safe).

---

## Guardrails (the 31 rules)

These are baked-in operational rules. Numbered for cross-reference. Rules 1-18 drawn from the AppLift dry-run (2026-05-01); 19-22 from later refinements; 23-25 from the Amazon-agencies retro (2026-05-04); 26-31 from the Influencer-marketing + Interior Design TAM runs (both 2026-05-04).

1. **Free preflight is mandatory.** `/v2/credits/balance` + `/v2/data-fields` (Ocean), `/account-information` (Prospeo) before any paid call. Cost: 0.
2. **Sample-only by default.** Never paginate to Phase 4 without ≥50% sample precision AND explicit user green-light.
3. **Domain canonicalisation: strict.** Strip `www.`, strip protocol, lowercase. Exact-match dedupe.
4. **Cheap iteration over expensive pagination.** Re-seed loops are 1 credit each. Phase 4 is 50-2000+ credits. Iterate before paginating.
5. **Three pots, always.** `qualified.csv` / `borderline.csv` / `off-brief.csv`. Off-brief NEVER enriched.
6. **WebFetch verification: mandatory on samples, opt-in on full pulls.** Free; catches stale data, false positives, dead domains.
7. **Soft-category gate at the start.** Surface up-front; plan re-seed loops and keyword-pivot if soft.
8. **Keyword-first, lookalike-second order in Ocean.** Run the buyer-type keyword + industry filter pass FIRST (highest precision for buyer-targeting briefs), then optionally chain a lookalike pass to widen recall. Lookalike alone is unreliable for soft-category briefs because it skews to whichever sub-category dominates the index density.
9. **Saturation early-stop.** Net-new < 25% → ask before next provider. AI Ark page ≥80% known → stop paginating.
10. **Cumulative excludes grow monotonically.** Smart-priority subset when over provider caps (Prospeo 500, AI Ark 300).
11. **Keyword acronym false-positive trap.** `"ASO services"` matches "Administrative Services Organization (aso) services". Use fully-spelled phrases. Layer `excludeIndustries` for known false-positive verticals (HR / Outsourcing / Recruiting for ASO=PEO).
12. **Buyer-type vs subject-matter keywords (11b).** Use buyer-type (`"app marketing agency"`) only for buyer-targeting briefs. Subject-matter alone (`"mobile app marketing"`) catches dev shops, general agencies, platforms.
13. **Default no-paginate / hand-off-with-sample.** Most users want 10-30 qualified seeds for Prospeo/AI Ark expansion, not 10K-row Phase 4 extracts. Phase 4 is opt-in.
14. **No hard credit cap on full pulls (decision #2).** Surface projected cost transparently; let the user decide.
15. **Prospeo TAM uses `/search-company`, not `/search-person`.** Higher unique-co recall per credit. `/search-person` is reserved for `lilly-decision-maker-finder`.
16. **Defensive client-side exclude filter.** Provider exclude flags are unreliable (Prospeo `websites.exclude` is leaky). Always post-filter results against `cumulative_excludes` on the client side. Free.
17. **Stale data — always WebFetch-verify.** API descriptions lag reality (acquisitions, brand changes, domain transfers). The AppLift run caught `fetch.com` mis-classified by Prospeo.
18. **AI Ark = TWO separate searches (3a lookalike + 3b filter-only), gated by tier diagnostic.** D1 (`size:1`, `account.*` only) checks filter-tier; D2 (`size:5`, `lookalikeDomains` only) checks lookalike on basic-tier. **Stage 3a runs on ANY tier** — Path A (full filters + lookalike) on filter-tier, Path B (lookalike + client-side filtering) on basic-tier. **Stage 3b only runs on filter-tier** — basic-tier silently drops account.* and would return junk. Both 3a and 3b apply the slow-build pagination control rule (single 60% halt-and-confirm gate). 3b's net-new yield is cos that 3a's lookalike clustering missed (typically 30-60% of returned cos). Never auto-ABORT on D1 failure alone — recover via 3a Path B.

19. **Hyperlink every domain in user-facing tables.** Format `[domain](https://domain)` — the user clicks through to verify. CSV outputs use plain domains for downstream tooling.

20. **CTA pattern: state recommendation, then offer the choice.** At every decision gate (precision below threshold, saturation, post-stage hand-off), don't ask "A or B?" Say "I want to do X. Confirm or pick another." Verdict-led, not menu-led. The user can override the recommendation; the recommendation forces the orchestrator to commit to a position.

21. **Lookalike pagination starts in safe mode (20-co batches, lead-score-verified).** Switch to bulk mode (200-co batches = 4 pages of size:50) only when pages 1-3 hit ≥70% precision AND user authorises. Never auto-switch. Filter-driven searches don't apply this rule.

22. **Per-sub-vertical tight seed clusters beat mixed-seed mega-calls by 3-5x precision.** When the brief spans multiple sub-verticals, fire one tight-seed call per sub-vertical (5 near-identical seeds each). Aggregate results. Do NOT mix seeds across sub-verticals in one call — the cluster centroid drifts and precision collapses to 30%.

23. **Auto-exclude tool/SaaS noise for service-provider briefs in tool-heavy verticals.** When the brief targets agencies / consultancies / integrators / services in a tool-heavy vertical (Amazon, e-commerce, ad-tech, mar-tech), auto-prepend `excludeIndustries: ["Computer Software","Information Technology","SaaS","Marketing Automation"]` and `keyword.noneOf: ["platform","intelligence","tool","SaaS","software","marketing automation","automation platform"]` to every Stage 1-3 call. Marketing automation IS itself a tool. **Caveat:** if the brief's primary target IS a tool/SaaS/platform category, do NOT auto-apply. When ambiguous, surface the auto-exclude and ask one clarifying question before locking filters.

24. **Pre-flight saturation check when input list provided.** If the user provides an existing company list (>50 cos) AND asks to expand it, fire ONE 1-credit Ocean lookalike probe with the input list as `excludeDomains` BEFORE Stage 1. Compute overlap rate. If ≥80% saturated, recommend SKIPPING expansion entirely (Amazon-agencies 2026-05-04 burned 13 credits for only 38 net-new because input list of 587 was already deeply saturated).

25. **Sample classification ALWAYS via `lilly-lead-score`, never inline.** Each provider's sample flows into one `lilly-lead-score` call returning verdict table + sample-fit %. Inline pattern-matching against API descriptions collapses the LLM-first confidence ladder, hides anomalies, burns context, and frequently 403s on cookie-walled sites. `lilly-lead-score` clears 60-80% of typical samples from training knowledge in seconds with zero web fetches.

26. **Stage 1 fires exactly 2 isolated angles — `keyword-only` + `lookalike-only`. Never `industries-only`.** Industries-only returned 304K raw with 0% sample precision (Run A 2026-05-04). Industry is a narrowing layer, never a standalone angle. Pair with `lookalikeDomains` OR `keywords.anyOf` if industry-anchored.

27. **3-column communication standard: Verified (sample) / Estimated TAM / Pulled (full).** Every progress update on TAM size MUST distinguish these three numbers. Never report a single number without specifying which column. After each provider's sample, surface Estimated TAM explicitly and ask the user to confirm before paginating to Pulled (full). User pushed back on "110 verified" without column framing (Run A 2026-05-04).

28. **Soft-category brief recipes: prefer EXCLUSIONS over tight INCLUSIONS for service-provider briefs.** Per-brief `excludeIndustries` map (interior design / architecture / design agencies / marketing agencies / consulting firms — see Stage 0). Inclusions over-qualify and miss valid cos with ambiguous tags; exclusions only drop confirmed off-brief categories. Use `linkedinIndustries` inclusion as a softener, not a hard gate.

29. **AI Ark basic-tier hard rule (REST fallback path ONLY).** Scope clarification: `lilly-ai-ark-list-builder` now uses the MCP `company_search` tool by default; the MCP rejects invalid params at the boundary (typed schema), so the basic-tier silent-drop failure mode this rule documents does NOT apply on the MCP path. **This rule applies ONLY when the skill falls back to the REST `/v1/companies` endpoint** for one niche capability (server-side `account.domain.any.exclude` on huge source TAMs). On the REST-fallback path: if D1 fails, ONLY working filters are `lookalikeDomains` + `account.location.any.include` — STOP probing. `account.industry`, `account.headcount`, `account.keywords` all silently dropped (confirmed across 4 shapes 2026-05-04). Don't chain probe variations to "be exhaustive" — wastes credits + turns. Path forward on REST-fallback: 3-5 lookalike passes with DIFFERENT seed clusters (US / UK / UAE / AU+SG) + client-side filtering on HQ + headcount + cumulative excludes.

30. **Persistent off-brief domain blocklist.** Maintain `lilly-tam-mapper/off_brief_blocklist.json` — list of domains that consistently drift into TAMs they shouldn't (Tesla, Meltwater, NetSuite, Chargebee, Lusha, Cognism, Belkins, Hawke Media, Patreon, Jasper, Ogilvy, M&C Saatchi Performance, etc.). Auto-prepend to seed exclude list at Stage 1 start. After each run, prompt user: "Any new drift attractors to add?"

31. **Adjacent sub-vertical → parallel seed cluster.** When the first lookalike call's sample drifts into a coherent adjacent sub-vertical (≥20% of returns share a tight cluster), propose splitting into a parallel sub-vertical pot with its own tight-seed cluster rather than flagging as off-brief. Track multiple parallel pots (`qualified_X.csv`, `qualified_Y.csv`) with shared cumulative excludes. Compounds with rule #22.

---

## Quick reference — phase-by-phase budget cheatsheet

| Stage | Provider | Sample cost | Full-pagination cost | Trigger to paginate |
|---|---|---|---|---|
| 0.5 | Pre-flight saturation probe (Ocean lookalike) | 1 cr | n/a (one-shot) | Only when input list provided + expansion requested |
| 1 | Ocean (lookalike) | 1 cr | ~20 cr/page × pages | Sample ≥50%, user green-light |
| 1 | Ocean (keyword) | 1 cr | ~20 cr/page × pages | Sample ≥50%, user green-light |
| 2 | Prospeo `/search-company` | 1 cr/page (flat) | 1 cr per additional page | Per-page yield justifies, ≥50% precision |
| 3 | AI Ark `/v1/companies` | 1 cr (diagnostic) + 1 cr (probe) + per-page TBD | per-page measured cost × pages | Tier valid, ≥50% precision |
| 3.5 | Brand-recognition spot-check | Free | n/a (one-shot) | Mandatory before DM hand-off |

Typical AppLift-style soft-category run: **6-10 credits** for 15-25 qualified cos across all three providers. Realistic full-extraction: **50-200 credits** for 100-500 qualified cos.

**Saturation-saved run** (Amazon-agencies 2026-05-04): if Stage 0.5 had been in place, would have saved ~13 credits by surfacing the 88%+ overlap before Stage 1 fired.

---

## See also

- `lilly-ocean-tam-builder/SKILL.md` — Ocean single-tool skill (Phase 1-4, no Phase 4.5/5).
- `lilly-prospeo-list-builder/SKILL.md` — Prospeo `/search-company` single-tool skill.
- `lilly-ai-ark-list-builder/SKILL.md` — AI Ark `/v1/companies` single-tool skill.
- `lilly-lead-score/SKILL.md` — sample classification skill called by every Stage 1-3 sample-fit gate (rule #25).
- `lilly-decision-maker-finder/SKILL.md` — DM enrichment, called separately after TAM mapping.
- `lilly-tam-mapper/off_brief_blocklist.json` — persistent off-brief domain blocklist (rule #30).
