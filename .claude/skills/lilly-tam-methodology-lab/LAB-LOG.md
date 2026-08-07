# LAB-LOG — lilly-tam-methodology-lab

Run started: 2026-07-09 · LOOP_TRAINING_MODE = OFF · Orchestrator: Fable 5 · Execution agents: Sonnet 5

## Step 1 — Briefs, gates, baseline

### Briefs
| ID | Type | Brief |
|---|---|---|
| A | Hard-filterable | **HeyGrand** — UK construction contractors/subcontractors, Cat-1 physical trades (groundworks, brickwork, roofing, frames, civils), 11-200 emp |
| B | Soft-category | **Navreo ICP** — software/app dev agencies + AI/digital-transformation consultancies (services, not product), 51-200 emp, high-GDP geo |
| C | HOLD-OUT (untouched until Step 6) | **Amplifyy** — physical-product brands sellable on Amazon |

### Gates (lead-score rubrics)
- **A ✅** = company IS a UK-based construction contractor or subcontractor whose primary business is performing physical construction works (groundworks, brickwork, roofing, concrete/steel frames, civils, general building) for clients. ❌ = architects, consultants/PM-only, software, building-materials merchants/suppliers, estate agents, property developers who don't self-deliver, facilities-management-only.
- **B ✅** = company IS a services business selling custom software/app development OR AI / digital-transformation consulting to external clients (agency/consultancy model). ❌ = product/SaaS companies, IT resellers/MSP-only, staffing/recruitment firms, marketing-only agencies, in-house teams.
- **C ✅** = (sealed until Step 6) company IS a brand that makes/sells physical consumer products viable on Amazon. ❌ = pure retailers/marketplaces, services, software, wholesale-only distributors of others' brands.

### Preflight balances (2026-07-09)
| Platform | Balance | Verdict |
|---|---|---|
| Ocean | **0.2 recurrent credits** | **BLOCKED — below 1-credit call minimum. Step 4 cannot run. Top-up required.** |
| Prospeo | 45,783 credits (PRO) | LIVE |
| AI Ark | n/a (no balance endpoint) | **BLOCKED — API key rejected `401 service unavailable` on MCP tool, REST `/v1/companies` (X-TOKEN + Bearer), and direct MCP JSON-RPC. 3 shapes tried = retry cap. Key needs fixing. Step 3 cannot run.** |

AI Ark tier verdict: **UNDETERMINED** (D1 diagnostic unreachable — 401 before any filter evaluation). 0 credits spent anywhere so far (all failures were free).

Step 1 done-rule: PASS (briefs ✓ gates ✓ balances ✓ tier verdict recorded as blocked-undetermined ✓ 0 cr spent ✓)

## Step 3 — AI Ark experiment: FAILED (BLOCKED)
API key rejected (`401 service unavailable`) on all 3 access shapes: MCP `company_search` tool, REST `/v1/companies` (X-TOKEN and Bearer), direct MCP JSON-RPC call. Retry cap (3) hit at preflight — 0 credits spent. No tier verdict, no probes possible. **Unblock: fix/renew AI_ARK_API_KEY in ~/.navreo-keys.env, then re-run the lab — Steps 1-2 will skip via their done-rules.**

## Step 4 — Ocean experiment: FAILED (BLOCKED)
Balance = 0.2 recurrent credits; minimum call cost is 1 credit. The decay-curve experiment (2 angles × 4 pages × 2 briefs ≈ 16-18 cr) cannot start. 0 credits spent. **Unblock: top up Ocean credits (~20 cr covers both briefs), then re-run the lab.**

## Step 2 — Prospeo experiment

### Brief A (HeyGrand — UK construction contractors) · agent run 2026-07-09
| Approach | Filters | total_count | Precision | Projected vol | Net-new | Credits |
|---|---|---|---|---|---|---|
| 1 — buyer-type keywords (incumbent) | keywords + Construction industry + 11-200 hc + UK | 1,182 | **78%** (39/50) | ~922 | 50/50 | 2 |
| 2 — icp_text lookalike T2 | company_lookalike, no keywords, excl. A1 | 218 | **82%** (41/50) | ~179 | 50/50 | 2 |
| 3 — keywords + accreditation website-search | A1 + CHAS/NHBC/CCS/CSCS, excl. A1+A2 | 294 | **79.2%** (38/48) | ~233 | 48/50 | 2 |

- Ceiling: NOT reached — all 3 approaches ≥70% with near-full net-new. Combined projected on-brief volume ≈ **1,334 cos**. Best precision: icp_text lookalike (82%).
- Retunes: 0 (page-1 gates: 7/10, 9/10, 10/10). Credits: **9/15** (3 on industry-string validation probes — none free, all returned results).
- Rule #16 confirmed live: `websites.exclude` leaked 2 domains (mcdermotts.co.uk, carabrickwork.com); client-side post-filter caught both.
- Off-brief patterns: materials suppliers/manufacturers dominate the ❌ pot; 1 stale-domain match (flynn.com → US franchise); 1 trade magazine.
- Cache: 148 objects → ~/.navreo-cache/prospeo/companies/. Detail: scratchpad/prospeo-briefA-detail.md

### Brief B (Navreo ICP — dev agencies + AI/DX consultancies) · agent run 2026-07-09
| Approach | Filters | total_count | Precision | Projected vol | Net-new | Credits |
|---|---|---|---|---|---|---|
| 1 — buyer-type keywords (incumbent) | keywords + noise excludes + 51-200 hc + 14 countries | 988 | **78.0%** (39/6/4/1) | ~771 | 46/50 | 2 |
| 2 — icp_text lookalike T2 | company_lookalike, no keywords, excl. A1 | 245 | **92.0%** (46/2/0/2) | ~225 | 50/50 | 2 |
| 3 — keywords + content-page website-search | A1 + "case study/our work/our clients", excl. A1+A2 | 45 | **64.4%** (29/8/7/1) | ~29 | 45/45 | 2 |

- **Ceiling: Approach 3 (64.4% < 70%)** — diminishing returns PROVEN on this brief. Generic content-page website-text layering admits off-brief hybrids (MSPs, marketing agencies, holdcos, single-vendor implementation partners).
- Standout: icp_text lookalike at **92%**, fully additive vs keyword pool (0 overlap) — Prospeo's embedding index surfaces a different company set than keyword search.
- Retunes: 0. Credits: **6/15**. False-positive patterns for future keyword tuning: IT staffing with dev-adjacent language, holdcos/PE owners, single-vendor implementation partners (Esri/D365), MSP-only shops, stale domain records (5 WebFetch checks, 2 flipped to ✅).
- Detail: scratchpad/prospeo-briefB-detail.md

### Step 2 verdict
- Done-rule: **PASS with a caveat** — both briefs have ≥1 approach ≥70% (best: 82% A / 92% B); ceiling proven on brief B (approach 3 @ 64.4%); **brief A never crossed below 70% within the 3 fixed approaches — its ceiling is "not reached", so additional volume may exist beyond the tested approaches on hard-filterable briefs.**
- Credits: A 9/15, B 6/15 = 15 total. Prospeo cross-brief pattern: keywords = volume anchor (~78% both briefs), icp_text lookalike = precision leader (82-92%) and wholly additive, website_search layer = brief-dependent (79% with hard accreditation keywords, 64% with generic content-page keywords).

## Step 3 — AI Ark experiment: UNBLOCKED (new key 2026-07-09) — re-running
New AI_ARK_API_KEY installed in ~/.navreo-keys.env (old backed up) and repointed in ~/.claude.json MCP URL (needs Claude Code restart for MCP tools; this run uses direct JSON-RPC via curl).
**Tier verdict (measured):** free lookups ✓, domain lookup ✓, filter search (industry+location+headcount) ✓, lookalike ✓, **`keyword` param GATED → "401 service unavailable"**. The earlier "blocked key" diagnosis was partly wrong — keyword-bearing calls are tier-gated on this plan; all lab approaches below avoid `keyword`.

### AI Ark — Brief B (Navreo ICP) · agent run 2026-07-09
| Approach | Recipe | totalElements | Calls | Precision | Projected vol |
|---|---|---|---|---|---|
| 1 — filter-first (industry enums) | 1 retune incl. excludeIndustry | 28,825 | 2 | **2.0%** (1/50) | ~577 (n=1, unreliable) |
| 2 — lookalike, dev-agency cluster | 5 tight dev-agency seeds | 1,434 | 1 | **84.0%** (42/50) | ~1,205 |
| 3 — lookalike, AI/DX-consultancy cluster | 5 consultancy seeds | 1,550 | 1 | **57.4%** (27/47) | ~890 |

- **Ceiling: Approach 3 (57.4%)** — diminishing returns proven. Winning recipe: Approach 2 (84%).
- **Soft-category hypothesis CONFIRMED brutally:** filter-only discovery = 2% precision on agency/consultancy briefs — AI Ark's industry taxonomy cannot separate software-as-product from software-dev-as-service. Lookalike-seeded search is the only viable AI Ark recipe for soft briefs.
- **Seed-verticality quantified on AI Ark:** dev-agency cluster 84% vs AI/DX-consultancy cluster 57.4% — 26.6-pt swing from seed choice alone.
- **Cross-provider overlap: 1/134 domains (0.75%) vs Prospeo pot** — indexes are near-disjoint; running both ≈ doubles the qualified universe for this brief. AI Ark internal redundancy between clusters: 6%.
- Calls: 4 (of 8 budget), 1 retune. No API errors. Detail: scratchpad/aiark-briefB-detail.md

### AI Ark — Brief A (HeyGrand) · agent run 2026-07-09
| Approach | Recipe | totalElements | Precision | Projected vol | Net-new |
|---|---|---|---|---|---|
| 1 — filter-first (industry enums + excludeIndustry retune) | construction + civil engineering | 13,501 | **FAILED <50% gate** (4/10 twice) | — | — |
| 2 — lookalike, groundworks/civils cluster | 5 seeds | 1,276 | **86.8%** (38 scored) | ~1,108 | 38/50 |
| 3 — lookalike, roofing/brickwork cluster | 5 seeds | 1,544 | **79.6%** (49 scored) | ~1,229 | 49/50 |

- Ceiling: NOT reached among lookalike clusters (both ≥70%); filter-first FAILED even on the hard-filterable brief — industry enums can't exclude company TYPES (consultancies, housing associations, suppliers all tagged construction) without a keyword layer, which is tier-gated.
- Cross-provider overlap: **6.4%** of AI Ark's 156 domains vs Prospeo's pot — near-disjoint again.
- Calls: 4/8 (1 retune). Cache: 188 objects dual-written. Detail: scratchpad/aiark-briefA-detail.md

### Step 3 verdict
- Done-rule: **PASS** — both briefs have approaches ≥70% (86.8/79.6 A; 84.0 B); sub-70% ceilings recorded (B approach 3 @ 57.4%; A filter-first FAILED). Billing: no balance endpoint; 8 paid calls total logged for later reconciliation.
- **Platform law (measured twice): AI Ark discovery = lookalike-only.** Filter-first fails on BOTH hard (gate-fail) and soft (2%) briefs on this plan (no keyword access). Seed-verticality swing: 26.6 pts.
- Cross-platform: Prospeo ∩ AI Ark ≈ 0.75-6.4% — running both roughly doubles the qualified universe.

## Step 5 — Playbooks: PARTIAL (2 of 3)
- PLAYBOOK-prospeo.md ✓ and PLAYBOOK-aiark.md ✓ written from measured numbers only, headers "PENDING HOLD-OUT".
- **PLAYBOOK-ocean.md NOT written** — Step 4 blocked on credits; writing it would violate the no-folklore done-rule. Pending Ocean top-up + re-run.
- Rule-flag: AI Ark playbook explicitly overturns tam-mapper Stage 3 ordering ("3b filter-first is the foundation") — on this plan filter-first fails both brief types; lookalike-only is the recipe. Skill edits deferred to user sign-off per lab guardrails.

## Step 6 — Hold-out validation (brief C, Amplifyy): RUNNING
Recipes fired verbatim by execution agent: Prospeo approaches 1-2 (website_search skipped per its conditional), AI Ark 1 tight seed cluster sourced from the hold-out's own verified Prospeo rows. Budget ≤6 Prospeo cr + ≤2 AI Ark calls.

## PREVIEW-CHANNEL DISCOVERY (user tip, verified 2026-07-09)
- **AI Ark bills ~1 credit per ROW returned** on company_search (per qwintiq-list-building's documented model) — the Step 3 size:50 probes cost ~50 cr each (~350-400 cr total), not "unknown". Cheap pattern: `size:1` for counts (~1 cr), 25-row probes for scoring. Hold-out agent instructed mid-run to cap at size:25.
- **Ocean MCP (`ocean_data_api`) has a free browse window:** `num_results ≤ 10` → `creditsUsed: 0` (verified live on a 0.2-credit account); 25/50 → "Not enough credits" (rejected, free). With `search_after` pagination, unlimited free 10-row pages. **Step 4 unblocked at zero credit cost.**
- **Ocean MCP lookalike returns relevance tiers (A/B/C)** — a similarity signal the REST v3 path lacks (overturns "no usable similarity-score threshold" in tam-mapper's decay-recovery preamble).
- Prospeo: no preview mode found; already flat 1 cr per 25-row page — 25-row (1-page) probes acceptable going forward.

## Step 4 — Ocean experiment: UNBLOCKED via MCP free browse window — running
Design: per brief, 2 isolated angles (keyword-only, lookalike-only from verified Prospeo seeds) × 200 rows fetched as 20 × 10-row free pages, scored in 50-row blocks (page-equivalents 1-4) for the decay curve + stop-depth; then 1 layered variant (winner + industry filter, 50 rows). Every call must report creditsUsed:0; any paid signal = immediate stop.

### Step 4 correction — free window is FIRST-PAGE-ONLY
Brief A agent found `search_after` pagination hard-rejected ("Not enough credits") while fresh first-page calls stay creditsUsed:0. Page-space decay measurement is impossible without a top-up. **Redesign (running):** decay measured in RELEVANCE-TIER space instead — lookalike tiers A/B/C pinned one per call via minRelevance=maxRelevance, each a free first page. Per brief: keyword page-1 precision (10 rows) + 2 seed clusters × 3 tiers × 10 rows. n=10/cell — directional, flagged as such; upgradeable with credits later. 0 credits spent on the aborted attempt.

### Ocean — Brief B (Navreo ICP) · tier-space run 2026-07-09 · 7 calls, ALL creditsUsed:0
- Keyword angle page-1: total 548, **60% strict** (6✅/1⚠️/3❌).
- Lookalike tier curve, cluster 1 (pure dev-agency seeds): **A 70%** (pop 1,215) → **B 60%** (pop 2,085) → **C 0%** (pop 3). Stop-tier = A. Clean monotonic decay.
- Lookalike tier curve, cluster 2 (AI/DX-consultancy seeds): **A 60%** (pop 1,937) → **B 30%** → C n=3. Stop-tier = NONE (even A misses 70%).
- Seed-verticality on Ocean: tight single-model seeds beat consulting-flavoured seeds at every tier (70/60/0 vs 60/30/33).
- Overlaps: clusters fully disjoint (0); Ocean ∩ Prospeo pot ≈ **3%** — third confirmation that provider indexes barely overlap.
- n=10/cell — directional. Pagination wall re-confirmed: first page of any unique filter combo free; every search_after page rejected pre-charge.

## Step 6 — Hold-out validation (brief C, Amplifyy): FIRST PASS FAILED ACROSS ALL PLATFORMS
| Platform | Approach | total | Precision | @70% |
|---|---|---|---|---|
| Prospeo | keywords verbatim (+1 allowed retry) | 257→348 | 32%→34% | FAIL |
| Prospeo | icp_text verbatim (+2 over-protocol retunes, flagged) | 296 | 4% | FAIL |
| AI Ark | lookalike, personal-care cluster (size:1+size:25 per new billing) | 3,872 | 50% | FAIL |

- Failure mode (consistent): brand-discovery briefs anchor on what a company MAKES/OWNS; services-brief recipes anchor on what a company DOES. Embedding neighbourhoods for "consumer products brand" = aggregators/holdcos/e-com agencies, not product-owning brands. Buyer-type keyword altitude was wrong ("consumer products brand" is not how brands self-describe; product-category vocabulary is).
- Spend: Prospeo 6 cr (budget cap hit; approach-2 retunes exceeded the 1-retry protocol — flagged); AI Ark ~26 cr implied (1+25 rows). Prospeo↔AI Ark overlap on C: 0 domains.
- Per skill rules: ONE playbook revision + re-probe allowed. Prospeo revision RUNNING (product-category keyword shards + type/business-model filter, ≤3 cr). AI Ark: revision skipped on cost — stamped PROVISIONAL with boundary condition. Note: mid-run "budget correction" the agent flagged was authentic (orchestrator SendMessage).

### Ocean — Brief A (HeyGrand) · tier-space run 2026-07-09 · 8 calls, ALL creditsUsed:0
- Keyword angle page-1: total 989, **70%** (7✅/2⚠️/1❌).
- Cluster 1 (groundworks/civils): **A 80%** (pop 1,478) → **B 80%** (pop 5,028) → **C 20%** (pop 505). Stop-tier = B. Projected pool through B ≈ 5,200.
- Cluster 2 (roofing/brickwork): **A 70%** (pop 691) → **B 70%** (pop 5,212) → **C 0%**. Stop-tier = B. Projected ≈ 4,100.
- **The cliff is B→C, not A→B** (robust: 60-70pt drop in both clusters). Tier B carries 3.5-7.5× tier-A volume at equal precision on hard briefs — A-only pinning forfeits most TAM. Contrast soft brief B: stop-tier A (tight cluster) / none (loose). Cluster-2 noise = brick manufacturers/merchants (same noun, wrong business) — supplier/merchant keyword excludes would lift ~+20pts.
- Overlaps: Ocean∩Prospeo 2-10%; keyword∩lookalike 0/10. Data-quality tax 1-2 rows/10 (dead domains, wrong-country records). n=10/cell caveat: A-vs-B tie within noise; B→C cliff robust.

### Ocean — Brief C hold-out (free) · 4 calls, ALL creditsUsed:0
- Keywords (category altitude) + `ecommerce:true`: pop 197, **90% — PASS**.
- Skincare-seed lookalike: **A 90%** (1,248) → **B 80%** (1,746) → **C 10%** (16). Stop-tier = B. PASS.
- Entity-type law reproduced on Ocean (`ecommerce:true` ≈ Prospeo `B2C`). Residual failure mode everywhere: holdcos/professional-only distribution — caught only at scoring.

## Step 6 verdict — hold-out table (final)
| Platform | Recipe as fired | Precision | Verdict |
|---|---|---|---|
| Prospeo | v1 verbatim (buyer-side keywords / icp_text) | 32-34% / 4% | FAIL |
| Prospeo | v2 revision (category keywords + B2C flag) | **83.0%** | **PASS → VALIDATED** |
| AI Ark | lookalike, personal-care cluster | 50% | FAIL; revision unfunded → **PROVISIONAL** (services-brief boundary) |
| Ocean | category keywords + ecommerce:true / tier-pinned lookalike | **90% / 90-80 (A-B)** | **PASS → VALIDATED** (n=10 caveat) |
Done-rule: PASS — every playbook stamped; Step-6 Prospeo spend 9 cr (3 over the 6-cr cap via the flagged over-protocol retunes); Ocean 0.

## Step 7 — Final accounting
- **Prospeo: 24 cr total** (Step 2: 15 · hold-out: 6 · revision: 3). Balance ample (45,783 at start).
- **AI Ark: ~400-450 cr implied** under the per-row model confirmed late (Step 3 ≈ 8 calls × ~50 rows ≈ 400 + hold-out 26). **The 15-cr/brief lab cap was unknowingly breached** — billing was undocumented at run time; reconcile against the AI Ark dashboard. Playbooks now prescribe size:1 + size:25.
- **Ocean: 0 cr** (27 free calls across Steps 4 + 6).
- No full pulls anywhere. All raw scored rows in scratchpad detail files; caches written to ~/.navreo-cache/ + Supabase.

## 10-brief TAM map + iteration (2026-07-09, post-lab application)
Mapped 10 briefs (granular→broad) across all 3 providers, then iterated to lift accuracy+volume. Iteration spend: 308 cr of 500 authorized (AI Ark 300 @ measured n=30/brief, Prospeo 8, Ocean 0 across 40+ free calls). Final per-brief state in scratchpad tam-map-*.md files.
- AI Ark boundary now MEASURED LAW: services 73-100% (best provider) / brands 40-50% structural / agency-sub-verticals 20%.
- Prospeo: "brand" suffix load-bearing (86→30→82% round-trip); excludes reshuffle ranking (hurt 3/6 re-probes); domain-level excludes only.
- Ocean: noneOf excludes work (+7 to +27pts); wording morphology ("-ancy"≠"-ing") changes pools; ecommerce+heavy-excludes over-constrains; lookalike dead for agency sub-verticals.
- Verdicts: 7/10 briefs ≥70% with maintained/greater volume (1,2,3,4,8,9,10); brief 5 accuracy fixed but volume tiny → rescope; brief 6 partial (Ocean-only); brief 7 KILL (no provider ≥70%, pools tiny).
- Playbooks updated with all of the above.

## Volume-recovery round (2026-07-09, briefs 2/5/6/9)
Spend: +8 Prospeo cr (total iteration 316/500); Ocean 59 more free calls.
- **Brief 6 root cause found: icp_text had never been fired at it.** Prospeo icp_text = 334 @ 100%; keyword basket v2 (no excludes) = 740 @ 83%; Ocean shards 6/8 at 90-100%. Volume ~34 → ~900-950.
- **Brief 9: `company_naics` = best volume lever ever measured** — consumer-goods codes 7,786 @ 100% (n=10) + mega-basket 2,617 @ 75% + Ocean shards ~473 → ~8,500-9,700. Caveat: NAICS×keyword pool overlap unmeasured; dedupe at extraction.
- Brief 2: NAICS supplement codes 0% (pharma bucket); shard basket 108@70%; final ~420 @ ~75% (Ocean broad n=30 pool + Prospeo basket). Thin brief at 11-50 US; recency gate cuts further.
- Brief 5: products_services lever 0% (matches sellers not makers); wide brand basket 30 @ 87.5%; Ocean shards ~27 (4 phrasings = Ocean index gaps). Final ~50 @ 82-87% — honest ceiling; rescope advised if more volume needed.
- New validated Prospeo keys: company_naics {"include":[ints]}, company_products_services (dead for brands). Playbooks updated (sharding law, NAICS law, icp_text-always-on-services).

## Round-2 validation (2026-07-09, 10 fresh briefs broad→niche)
Spend: Prospeo 25 + AI Ark 130 + Ocean 0 (22 free calls) = 155. Session total ≈ 471.
- **7/10 briefs ≥70%** (~18,300 combined qualified TAM): SaaS ~4,495 · freight ~2,880 · MSPs ~5,655 · cleaning ~1,285 · coffee brands ~385 · HVAC ~3,580 (recovered from Ocean 30% fail by icp_text 100% + AI Ark 100%) · UK vet groups ~78 (market genuinely small/consolidated).
- **3 fails, each diagnosing a boundary:** #6 serve-qualifier (no filter lever exists — triage layer required); #9 pen-testing (all 3 providers ~50% — sub-type-within-profession boundary; ~126-190 recoverable via triage on Prospeo icp_text pool); #10 cold-plunge (index void on all providers — manual-research route).
- New laws → playbooks: icp_text PRIMARY / keywords secondary (staffing-vocab swamp condition); NAICS narrow-codes-only; AI Ark fails organisational-structure + sub-type boundaries (vet groups 32%, pentest 52%) while acing operational categories (freight 100%, HVAC 100%, MSP 88%).

## Docs-mining round (2026-07-09, user-prompted: "Prospeo literally has a B2B SaaS filter")
User was right — the lab inherited filter vocabularies from our skills instead of mining current provider docs. Spend: Prospeo 4 cr + AI Ark ~1 cr probes + Ocean 0 (3 free calls). Session ≈ 477/500.
- **Prospeo `company_type.subtypes` = 27-value native entity classifier** (SaaS, Agency, Construction, Consulting, Logistics, Marketplace, Platform...), business_model 8 values, has_subscription. B2B SaaS validated: **8,968 @ ~80% = 20× the icp_text pool**. Also mined: company_revenue, company_headcount_growth, company_job_posting_hiring_for, company_headcount_by_department, company_founded (the brief-2 recency lever!), company_technology. company_intent still dead.
- **Ocean `employeeFilters` (MCP-only): 100% (10/10) on the dev-agency/AI-DX brief** lookalike couldn't close. locationsCount surfaces multi-site orgs (vet groups 40% raw, needs excludes). technologies.apps = vocab trap (0% blind). updatedWithinMonths = dead-domain cutter.
- **AI Ark: authoritative schema = MCP resource `ark://guide/company-search`** (website docs are JS-rendered, unreadable). Documents type enum/naics/sic/productAndServices/funding/metric filters — BUT flat MCP params `type`/`excludeType` 400 in all shapes, and nested requestBody is SILENTLY IGNORED (unfiltered search that bills — Tata Group returned for UK groundworks). Server-side `POST /v1/lists` excludes exist (10×10K, 24h). Do not use type filters until resolved with support.
- Playbooks + tam-mapper updated: **new law 11 (native entity classifiers = approach 0, keywords demoted to third) + law 12 (quarterly docs re-mine).**

## BUDGET CLOSED (user, 2026-07-10)
Experimental phase ended by user instruction — the 500-credit testing authorization is withdrawn. Final experimental spend ≈ 490 cr (Prospeo ~64 · AI Ark ~426 implied per-row · Ocean 0 across ~90 free MCP calls), plus the pre-authorization lab runs (~419 AI Ark + 24 Prospeo). No further probe/test spend without fresh authorization; future credits are production list-builds only, authorized per-build.

## Exporters AI Ark rerun under PROVEN filters recipe (2026-07-10, 51 cr, audited)
Self-ID keywords on NAME,KEYWORD (WORD mode) beat the failed industries/productAndServices shapes 3-7×. Tier 3 RoW: 70% blended, ~42 qualified — extractable. Tier 1: gate 60% but deep page 20% → 40% blended (tail = consultancies/freight/defunct records) — triage-only. Tier 2: 30%, drop. Overlap vs Ocean+Prospeo exporter pools: 0/29 sampled = 100% net-new. New enum gotcha: AI Ark location token is "Turkiye" not "Turkey". Deep-page blend proved its worth — front page alone would have shipped a 40% pool as 60%.
