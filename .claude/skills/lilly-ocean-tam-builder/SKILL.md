---
name: lilly-ocean-tam-builder
description: "Build targeted TAM lists via the Ocean.io API (v3/search/companies) for new Smartlead campaigns. Use this skill whenever the user wants to find lookalike companies to an ICP or seed list, generate a prospect list for a new campaign vertical, expand the TAM for an existing campaign, estimate market size, or iterate search filters to reach an 80–90% accuracy match list. Trigger on mentions of Ocean.io, TAM, prospect list, lookalike search, ICP build, 'companies like X', campaign expansion, or any time the user wants a list of matching companies delivered as CSV ready for Lilly-Bot ingestion."
---

# Lilly Ocean TAM Builder

## Purpose

Turn any campaign brief into a high-accuracy, domain-agnostic Target Addressable Market (TAM) list via Ocean.io's `v3/search/companies` endpoint. Iteration is human-driven — the user critiques in plain English, this skill picks and applies the right filter moves.

Output: a CSV of enriched companies (domain, size, industries, tech stack, emails, phones, description) ready to hand off to `lilly-bot` for Smartlead campaign build.

---

## When to Use

Trigger whenever the user wants to:
- Build a TAM for a new campaign / vertical clone
- Find lookalike companies to a seed set
- Estimate market size for an ICP before committing
- Iterate on search filters until results hit an accuracy bar
- Expand geography or tighten size on an existing search

Accept input forms:
- "Build me a TAM for [vertical/ICP]"
- "Find companies like [X]"
- "How big is the market of [Y]"
- "Let's iterate the Ocean search — the last results were too [broad/narrow/wrong]"

---

## API Access

- **Endpoint:** `POST https://api.ocean.io/v3/search/companies`
- **Auth:** `?apiToken=<OCEAN_API_KEY>` query param (key in Claude Desktop config under `mcpServers.ocean.io.env.OCEAN_API_KEY`)
- **Cost:** **1 recurrent credit per call** regardless of result count
- **Daily rate limit:** 1,000 calls/day
- **Preview endpoint (`v3/search/companies/preview`):** enterprise-only — do NOT attempt, it returns "You are not allowed to access this feature"

The MCP server bundled at `~/Downloads/ocean-io-mcp-server/` targets retired v1 endpoints and will 404 — call the API directly via `curl`/Bash instead. **The MCP wrapper's TypeScript types are also outdated** — V3 filter shapes differ; use the Schema Quick Reference below.

---

## Schema Quick Reference

### Discovery endpoints (unauthenticated, free)

Always fetch and cache these at the start of any new run — they prevent 30%+ of trial-and-error API errors:

| Endpoint | Returns |
|---|---|
| `https://api.ocean.io/openapi.json` | Full V3 OpenAPI spec — every filter's correct JSON shape |
| `https://api.ocean.io/v2/data-fields?apiToken=$TOKEN` | Canonical vocabulary for `industries`, `linkedinIndustries`, `technologies`, `regions`, `seniorities`, `departments` |

### V3 filter shapes (the MCP wrapper is wrong about these)

Use these exact shapes inside `companiesFilters`:

| Filter | V3 shape | Notes |
|---|---|---|
| `companySizes` | `["11-50","51-200",...]` | Flat array of bucket strings |
| `countries` | `["us","gb",...]` | Flat array, lowercase ISO. **Presence-based** (matches "has presence in", not HQ). **Default to this** for general TAM building. For HQ-strict, use `primaryLocations` instead. |
| `primaryLocations` | `{"includeCountries":[...], "excludeCountries":[...]}` | **HQ-strict** country filter (server-side). Use when exact HQ match is required (e.g. DM-enrichment briefs where DM-at-HQ is mandatory). Cheaper than client-filtering downstream. |
| `otherLocations` | `{"includeCountries":[...], "excludeCountries":[...]}` | Any non-HQ office country. |
| `lookalikeDomains` | `["seed1.com","seed2.com",...]` | **HARD CAP: 10 seeds** (`maxItems: 10`) |
| `excludeDomains` | `["bad1.com",...]` | Flat array |
| `excludeIndustries` | `["Enterprise Software",...]` | Flat array of industry strings |
| `industries` | `{"industries":[...], "mode":"anyOf"}` | V1-style nested shape |
| `industryCategories` | `{"industryCategories":[...], "mode":"anyOf"}` | Top-level taxonomy (~46 categories) |
| `technologies` | `{"apps":{"anyOf":[...]}, "categories":{"anyOf":[...]}}` | V3 nested with `AllAnyNoneFilter` sub-objects |
| `keywords` | `{"anyOf":[...], "allOf":[...], "noneOf":[...]}` | Direct `AllAnyNoneFilter` |
| `mobileAppsFilter` | `{"count":{"from":1,"to":100}, "downloads":{...}, "releaseYear":{...}}` | All sub-fields optional |
| `fundingRound` | `{"raised":{"from":N,"to":N}, "types":["Seed","Series A"], "date":{"from":"YYYY-MM-DD","to":"..."}}` | All optional |
| `fieldsExist` / `fieldsNotExist` | `["mobileApps","emails","logo",...]` | Force fields to be present/absent |
| `companyMatchingMode` | `"precise"` (default) or `"broad"` | Lookalike strictness — `broad` casts wider net |
| `webTraffic` | `{"visits":{"from":N,"to":N}, "views":{...}}` | Filter by traffic ranges |
| `headcountGrowth` | `{"growthRange":{"from":-1.0,"to":3.0}, "months":"Three months", "asPercentage":false}` | Filter by hiring trend |

### `AllAnyNoneFilter` pattern

Several V3 filters (keywords, technologies.apps, technologies.categories, socialMedias.medias) use the same sub-shape:

```json
{
  "anyOf": ["match at least one"],
  "allOf": ["must match all"],
  "noneOf": ["must match none"]
}
```

All three keys are optional — combine as needed.

### Vocabulary lookup (always do this before tech/industry filters)

Tech and industry strings must match Ocean's exact vocabulary, including casing:
- `Appsflyer` ✅ (lowercase 'f') — `AppsFlyer` ❌ rejects
- `Branch` ✅ — `Branch.io` ❌ rejects
- `Singular`, `Kochava` ❌ not in Ocean's vocabulary at all

**Always probe `/v2/data-fields` first.** Save 1 credit per failed attempt.

### Useful per-company response fields

Every search response company object includes:
- `mobileApps` — array of `{link, name}` — App Store + Play Store URLs
- `keywords` — flat array of company-description-derived keywords
- `technologies` + `technologyCategories` — flat arrays
- `industries` + `industryCategories` + `linkedinIndustry`
- `webTraffic` — `{visits, pageViews, pagesPerVisit, bounceRate}`
- `fundingRound` — last raise data
- `departmentSizes` — `[{department, size}]` per-team headcount
- `medias` — LinkedIn / Twitter / FB / IG / YouTube handles

Use `"fields": [...]` in the request body to return only what you need — cuts response size 6x.

---

## The 4-Phase Process

Single-tool scope. This skill builds Ocean TAMs only. Cross-provider expansion (Prospeo + AI Ark) is the orchestrator `lilly-tam`'s job. Decision-maker enrichment is `lilly-tam`'s job. Both are separate skills called after Phase 4 completes.

**Keyword-first priority for buyer-targeting briefs:** when the brief targets a buyer type (e.g. "agencies", "consultancies", "studios"), prioritise keyword + industry + headcount + geo filters over `lookalikeDomains` for the initial Phase 2 sample. The lookalike angle is a useful *supplement* to widen recall later, but should not be the primary because lookalike clusters skew to whichever sub-category dominates the index density (often platforms in ad-tech, dev shops in services). This rule was proven out in the AppLift dry-run 2026-05-01: keyword pass returned 4 net-new pure agencies; lookalike (despite 5 agency seeds) skewed heavily to platforms. See `lilly-tam` Stage 1 for the orchestrated order.



### Phase 0 — Suppression Seed *(before the first paid call)*

Before firing any billed Ocean search, seed the exclusion list from the central Supabase suppression store — this protects standalone runs of this skill the same way `lilly-tam`'s Phase 0 protects orchestrated runs. Use the shared helper `~/.claude/skills/_shared/navreo_db.py`: `navreo_db.check_exclusions(client_id, emails=[...], domains=[...])` for spot-checks, or for full-list seeding query `GET /rest/v1/v_exclusion?client_id=eq.{client}` (plus `client_id=is.null` global rows) via `navreo_db.rest()`. Feed the returned domains into `excludeDomains` on Phase 2 onward. Fails soft: if Supabase is unreachable (`check_exclusions` returns `None` — treat as "check unavailable", never as "no exclusions"), fall back to any hand-curated exclusion CSV and say so in the run summary.

### Phase 1 — Seed Assembly

Gather 4–8 anchor domains that **tightly represent the vertical**. Three rules:

1. **Strong digital footprint required.** Seeds must have active, recently-updated, content-rich websites. Old/thin sites confuse Ocean's crawler and return "bad content" / "crawler failed" / "data gathering started".
2. **Represent the vertical, not past clients.** Previous campaign winners are NOT automatic seeds — they're candidates, but must pass the vertical-representation test. Drop niche outliers even if they responded.
3. **Tight cluster of sub-flavors.** If the vertical has natural sub-flavors (e.g. networking vs. operator), include 1–2 seeds per sub-flavor. Avoid one dominant flavor.

When seeds are needed and the user hasn't given a list, propose them (hyperlinked) in a table with a "what they do" one-liner column. Never use a "why I picked it" column.

### Soft-category brief recipes (apply before Phase 1.5)

For "soft-category" briefs (interior design firms, architecture firms, design / marketing / consulting agencies, etc.), the LinkedIn industry taxonomy is too loose and floods the sample with SaaS / blogs / e-commerce / lifestyle pubs. **Default to EXCLUSIONS rather than tight inclusions** — inclusions over-qualify and miss valid cos with ambiguous tags; exclusions are safer because they only drop confirmed off-brief categories.

| Brief | excludeIndustries |
|---|---|
| Interior design firms | Software, SaaS, Blogging Platforms, Lifestyle |
| Architecture firms | Software, SaaS, Blogging Platforms, Construction (if ID-only) |
| Design agencies | Software, SaaS, Blogging Platforms, E-Commerce |
| Marketing agencies | Software, SaaS, Blogging Platforms |
| Consulting firms | Software, SaaS, Blogging Platforms, Recruiting |

Also default `linkedinIndustries` SOFTLY: e.g., for ID firms try "Design Services" first; if recall too narrow, drop the inclusion filter entirely and rely on exclusions alone. Confirmed 2026-05-04: LinkedIn classifies many EU/AU ID firms as "Design" or "Architecture & Planning" rather than "Design Services", so a strict include cuts recall. Use `linkedinIndustries` inclusion only as a softener, not a hard gate. ~5 wasted credits + 4 turns of fiddling on the Interior Design TAM run before this rule was extracted.

### Phase 1.5 — Filter Confirmation *(required before Phase 2)*

Propose the full filter object in plain English for user confirmation:
- **Countries** (with default regional tier — see Filter Defaults below)
- **Company sizes** (headcount buckets, never revenue)
- Any industry / tech / exclusion filters
- Size of the pull (default 10)

Wait for explicit green-light. Do NOT fire Phase 2 until filters are locked.

**Hard rule: Stage 1 fires exactly 2 isolated angles — `keyword-only` + `lookalike-only`. Never `industries-only`.** Confirmed 2026-05-04 (Run A): industries-only returned 304,462 raw with 0/15 sample precision (pure generic marketing/advertising umbrella). 1 wasted credit. Industry is a narrowing layer, never a standalone angle. If industry-anchored is wanted, pair with `lookalikeDomains` OR `keywords.anyOf` — but never alone.

### Phase 2 — Baseline Pull

One call. `size: 50` (buffer — we'll client-filter for HQ). Still 1 credit. Returns:
- `total` — Ocean's raw count (includes non-HQ presences — do not report this directly)
- `companies` — 50 enriched rows
- `searchAfter` — pagination token (save for Phase 4)
- `missingDomains` — any seeds Ocean couldn't index (flag these, consider dropping on next iteration)

**Default mode (presence-based):** Trust Ocean's native `countries` filter. Display the first 10 rows from the raw sample. **Do not** client-filter `primaryCountry` by default — companies with a target-country office are reachable.

**Reporting standard — fixed 3-column format.** Every progress update on TAM size MUST surface these three numbers, never collapsed into a single number:

| Column | Meaning |
|---|---|
| **Verified (sample)** | Qualified hits in the page-1 sample (after manual qualification of the first 10 rows) |
| **Estimated TAM** | `raw_total × sample_precision` (where sample_precision = qualified / qualified+unqualified in the sample) |
| **Pulled (full)** | What's actually been paginated to CSV (0 at Phase 2; updates each page in Phase 4) |

After surfacing the Estimated TAM, ask the user to confirm before paginating to "Pulled (full)". Never report a single number without specifying which column.

**HQ-strict mode (opt-in):** When the brief requires DM-at-HQ (e.g. some DM-enrichment scenarios), use `primaryLocations.includeCountries` server-side (recommended) OR client-filter on `primaryCountry`. Add a fourth column `HQ-TAM estimate = raw_total × (hq_matched / sample_size)`. `hq_tam_estimate` reporting only applies when HQ-strict mode is active.

Display results as a table with:
- `#` | `Domain (hyperlinked)` | `Country` | `Size` | `What they do (≤180 char description)`

Do NOT show the baseline filter JSON in the response. Do NOT surface patterns/observations — just results.

### Phase 3 — Calibration Loop (human-driven)

User critiques results in natural language. Skill interprets and applies the right filter change. Re-run (1 credit). Repeat until the 10 results pass the accuracy bar.

**Use initiative on tweaks — don't show the user a decision-rules cheat sheet.**

Common instruction → action mapping:
| User says | Action |
|---|---|
| "Too many X-type companies" | Tighten with `industries` filter or raise `minScore` |
| "Wrong size" | Adjust `companySizes` bucket list |
| "Focus on [geo]" | Update `countries` |
| "Exclude [size band]" | Remove that bucket from `companySizes` |
| "Too narrow / not enough results" | Lower `minScore`, broaden `companySizes` or seeds |
| "Specific domain keeps showing up" | Add to `excludeDomains` |
| "Replace seed X" | Swap in a new seed that matches the tighter direction |

**Guardrail:** one filter per iteration where possible. Two changes at once = no signal on what moved the needle.

**Country filter = presence-based by default.** Ocean's `countries` filter matches "has presence in", not "HQ'd in". For general TAM building (cold outreach to any target-country office), this is fine — companies with a target-country presence are reachable. **Default: trust the native filter, do not client-filter on `primaryCountry`.** Confirmed 2026-05-04 (Run A): the old HQ-only default dropped ~25-50% of valid results.

**Opt into HQ-strict mode** when the brief requires DM-at-HQ (e.g. specific DM-enrichment briefs):
- Server-side (preferred): use `primaryLocations.includeCountries` filter — see V3 filter shapes table.
- Client-side: filter `.companies[] | select(.company.primaryCountry | IN("us","gb",...))`.

**Standard Phase 2 / iteration call pattern:**
1. Request `size: 50`. Still 1 credit.
2. **Default mode:** report Verified (sample) / Estimated TAM / Pulled (full) — see Phase 2 reporting standard.
3. **HQ-strict mode (opt-in):** add a fourth column `HQ-TAM estimate = raw_total × (hq_matched_count / sample_size)`.
4. Display the first 10 rows.

`hq_tam_estimate` reporting only applies when HQ-strict mode is active.

#### D2C qualification rubric (B2C app campaigns)

For **consumer app TAMs**, Ocean's `industries` filter cannot distinguish D2C apps from B2B SaaS — both can be tagged "FinTech," "EdTech," "Health Care," etc. Manual scoring of the Phase 3 sample is required.

| Test | Pass = D2C |
|---|---|
| Who is the app's end-user? | An individual person — not an employee at-work, business owner, or admin |
| Free to download? | Yes (consumer apps default to free with IAP/subscription/ads) |
| In a target ICP vertical? | Yes |
| **Companion-app rule** | App can be a side-product to a B2B service IF the app itself is consumer-facing (e.g., Experian's consumer credit-monitoring app counts even though Experian is mostly B2B credit-bureau) |
| Disqualifiers | Apps for: merchants (Stripe), team productivity (Asana/Monday), corporate finance (Brex), enterprise admin (PandaDoc), construction firms (Procore), B2B sales reps (Salesforce mobile), SMB owners (Wave) |

**Final qualified TAM formula:**
```
qualified_TAM = raw_total × (hq_matched / sample_size) × (D2C_count / hq_matched)
```

Report all three terms in the Phase 3 result table so the user can see where leakage happens.

#### Industry tag noise (known issues)

| Tag | Catches | Mitigation |
|---|---|---|
| `Gambling` | Restaurants, B&Bs, hotels | Layer `mobileAppsFilter≥1` — kills hospitality with no app |
| `Mobile Payments` | Stripe-class merchant SaaS | Add `excludeIndustries: ["Enterprise Software","Small and Medium Businesses"]` |
| `Personal Finance` | Blogs, content sites, advice services | Layer `mobileAppsFilter≥1` |
| `Cyber Security` | Mostly enterprise SaaS | Use only intersected with consumer keywords (VPN, password manager) |
| `FinTech` | All B2B fintech leaks here | B2B kill list (see Filter Defaults) |
| `Software` / `SaaS` | Catches anything with code | Combine with consumer-vertical keyword filter |

### Phase 4 — Full Extraction

Once filters lock, paginate via `searchAfter` token, `size: 100` per page. Append rows to the vertical's CSV. 1 credit per page.

**Hard cap on lookalike pagination: page 4 (200 cos).** Late lookalike pages drift toward big-brand cos (Tesla-class) that pollute the TAM disproportionately. Confirmed 2026-05-04 (Run A): SaaS-lookalike paginated 7 pages while precision held >50%, but pages 5–8 polluted with Tesla (105 leads), Meltwater (20), Ogilvy (6), Chargebee (5), NetSuite, Lusha. ~157 of 586 enriched leads off-brief. ~150 wasted Prospeo credits + ~42 polluted the Smartlead campaign before manual cleanup.

Rule: stop lookalike pagination at page 4 unless the user explicitly overrides AND the brand-recognition spot-check (in `lilly-tam` Stage 4) has run first. Filter-driven (keyword) searches keep the existing 50% precision-floor rule — they don't have the same drift pattern.

### Cache writes + ledger (mandatory after every paid call)

After **every** billed Ocean call (Phase 2 baseline, each Phase 3 iteration, each Phase 4 page) — not just the final pull:

**Write-back (dual-write):** for each company returned, `navreo_db.put_enrichment("company", domain, "ocean", company_obj, endpoint="v3/search/companies", source_skill="lilly-ocean-tam-builder")` plus `navreo_db.upsert_company(domain, name=company_obj["name"], country=company_obj["primaryCountry"])`, both from the shared helper `~/.claude/skills/_shared/navreo_db.py`. This lets downstream skills (`lilly-icebreaker`, `lilly-tam`, future runs of this skill) read Ocean's enrichment without re-paying for it, and keeps the central `companies` table populated even when this skill runs standalone (outside `lilly-tam`).

**Ledger:** immediately after, `navreo_db.log_provider_usage("ocean", <credits>, endpoint="v3/search/companies", source_id="lilly-ocean-tam-builder")` — 1 credit per call regardless of phase. This is the cost-audit trail, separate from the write-back above; fires even on Phase 3 iterations that get thrown away.

Both fail soft (log and continue) if Supabase is unreachable — never block the run on a cache/ledger write.

### After Phase 4 — Hand-off

Phase 4 produces the Ocean TAM CSV. From here, two distinct hand-offs are available:

**Cross-provider TAM expansion** (Prospeo + AI Ark): use `lilly-tam`. That orchestrator chains Ocean → Prospeo → AI Ark with growing exclusion lists, three-pot output, defensive verification, and saturation detection. Use when the user wants to maximise cross-index coverage of the vertical.

**Decision-maker enrichment**: use `lilly-tam`. That skill owns the canonical Domains→DMs waterfall (Prospeo `/search-person` → client title filter → Prospeo `/bulk-enrich-person` → AI Ark `/v1/people` fallback for thin markets → domain-match filter). Use when the user wants verified emails and titles at this TAM.

Both are separate skill invocations. This skill stops at Phase 4 output.

**Output dir contents per Ocean TAM run:**

| File | Contents |
|---|---|
| `<vertical>-tam.csv` | Full enriched company list (see Output Schema) |
| `<vertical>-spec.json` | Final filter object, seeds, iteration log |

---

## Multi-Tier ICP Pattern *(use when ICP spans 5+ sub-verticals)*

**The problem with one mega-call**: when the ICP brief lists many sub-verticals (e.g., "sports betting + casino + crypto + investments + loans + budgeting + e-learning + kids + fitness + wellness + utilities + neo banking + dating + gaming"), a single lookalike call **always skews** to whichever sub-vertical's seeds have the densest neighbor cloud. Even with rebalanced seeds, the dominant cluster wins.

**Solution**: split into **one Ocean call per sub-vertical**, with 3-5 vertical-specific seeds each. Each is 1 credit. 15 sub-verticals = 15 credits = trivial. Aggregate at the end.

### Per-vertical run shape

For each sub-vertical:
```json
{
  "size": 20,
  "fields": ["domain","name","primaryCountry","companySize","employeeCountOcean",
             "industries","mobileApps","technologies","description","fundingRound"],
  "companiesFilters": {
    "companySizes": [...],
    "countries": [...],
    "lookalikeDomains": [SUB_VERTICAL_SEEDS],         // 5 seeds, vertical-specific
    "mobileAppsFilter": {"count": {"from": 1}},        // optional, per vertical (see decision rule above)
    "excludeIndustries": [B2B_KILL_LIST]               // for B2C campaigns
  }
}
```

### Aggregation

After all per-vertical pulls, compute **per-vertical TAM** using the formula:

```
qualified_TAM = raw_total × (hq_matched / sample_size) × (D2C_count / hq_matched)
```

Then **sum across verticals**, then apply a **15-25% dedupe haircut** (some companies appear in multiple lookalikes, e.g., Robinhood will land in both crypto + investments).

### When to fall back to single-call

- ICP fits 1-3 sub-verticals → single mega-call works fine
- ICP has clear flagship sub-vertical → single call seeded mostly from flagship
- ICP spans 5+ → **always** per-vertical

### Phase 4 cost projection (multi-tier)

For a 15-vertical ICP yielding ~95k pre-dedupe TAM:
- Phase 2 sampling: 15 × 1 = **15 credits**
- Phase 3 iteration (typically 1-2 rerun per weak vertical): **5-10 credits**
- Phase 4 full pagination: 15 verticals × ~5 pages avg × ~20 credits = **~1,500 credits**
- **Total: ~1,520 credits for ~75k qualified deduped companies**

---

## Filter Defaults

### Country tiers

Default tier depends on campaign ICP. Confirm before Phase 2.

| Tier | Countries | Use when |
|---|---|---|
| **Navreo Standard** | `us, gb, de, nl, au, ca, ie` | Default Navreo high-GDP ICP (per memory) |
| **English-only High-GDP** | `us, gb, ca, au, ie, nz` | ICP requires English-first business language |
| **+ Middle East** | above + `ae, sa, qa, bh, kw, om` | Commercial ME where English is common business language |
| **US only** | `us` | US-market campaigns |

### Company size (headcount)

Always prefer headcount over revenue — revenue data in Ocean is unreliable.

| Bucket | Typical use |
|---|---|
| `2-10` | Micro — usually excluded (too small for outbound) |
| `11-50` | Boutique consultancies / small agencies |
| `51-200` | Mid-market services / operators |
| `201-500` | Upper mid-market |
| `501-1000`, `1001-5000`, `5001-10000`, `10000+` | Enterprise (usually out of scope) |

**Default for services/consulting verticals:** `["11-50","51-200","201-500"]`

### Other filters

- `lookalikeDomains` — required, **5 seeds recommended** (hard cap: 10). Use 5 not 3 because crawler-failure rate is ~12% — extras are insurance.
- `minScore` (0.0–1.0) — start unset, add 0.6–0.8 if cluster too diverse
- `industries` shape: `{"industries":[...], "mode":"anyOf"}` — add when specific industries dominate wrongly
- `excludeDomains` — use for specific off-ICP repeaters
- `excludeIndustries` — flat array; use the **B2B kill list** below for any B2C campaign

### B2B kill list (default `excludeIndustries` for any B2C campaign)

D2C campaigns leak Stripe / Brex / Pitchbook / Wave / Asana / Monday / PandaDoc-class B2B SaaS via the `industries` filter (FinTech, Software, etc.). Always add this default exclusion bundle for B2C app/consumer campaigns:

```json
"excludeIndustries": [
  "Enterprise Software", "Enterprise Applications", "Enterprise",
  "Small and Medium Businesses",
  "Recruiting", "Project Management", "Document Management",
  "CRM", "Sales Automation", "Marketing Automation",
  "Human Resources",
  "Big Data", "Business Intelligence", "Information Technology",
  "DevOps", "Consulting", "Professional Services",
  "Management Consulting", "Knowledge Management",
  "Innovation Management", "Business Development", "Outsourcing"
]
```

Do NOT use this list for B2B campaigns (services / consulting / SaaS verticals) — it would kill your ICP.

### `mobileAppsFilter` — when to use

Native filter forcing companies to have ≥1 mobile app. Use for any **B2C app campaign**.

```json
"mobileAppsFilter": {"count": {"from": 1, "to": 100}}
```

⚠️ **Trade-off**: Ocean's mobile-app indexing is uneven across verticals. Adding this filter:
- **Cuts TAM 90%+** in casino, sports betting, banking-branch verticals (Ocean has poor app data here)
- **Minimal cut** in budgeting, fitness, wellness, kids apps, dating, gaming (Ocean indexes well)

Decision rule:
- **App-native verticals** (e.g. dating, gaming, meditation, budgeting) → use `mobileAppsFilter` for clean precision
- **Real-world brand verticals** (e.g. casino, sports betting, retail-with-app, banking) → skip `mobileAppsFilter` and accept noise; manually filter in Phase 3

### `fundingRound` — for funding-gated ICPs

For ICP rules like "20+ employees but raised $5M+ in last 18 months":

```json
"fundingRound": {
  "raised": {"from": 5000000},
  "date": {"from": "2024-10-26"}
}
```

Combine with `companySizes` and let the user know this is OR'd against the size filter at runtime (Ocean ANDs filters, so for OR semantics you may need two separate calls and merge).

---

## Output Schema (CSV)

Single format, every run:

```
domain, company_name, primary_country, company_size, industries, industry_categories,
linkedin_url, year_founded, emails, phones, technologies, mobile_apps,
description, ocean_score, funding_round
```

`mobile_apps` column: pipe-separated `name (link)` pairs — useful for B2C campaigns to verify each company actually ships a consumer app.

`industry_categories` column: top-level (~46) Ocean taxonomy — useful for downstream segmentation in Smartlead/AI Ark.

`funding_round` column: most recent raise as `type|amount|date` (e.g., `Series B|45000000|2025-03-15`).

Feeds directly into `lilly-bot` Smartlead import without reshaping.

---

## Credit Budget Model

Calibrated against real run April 2026:

| Phase | Per-call cost | Notes |
|---|---|---|
| Phase 2 baseline (`size: 50`) | ~1 credit | small calls are cheap |
| Phase 3 iterations (`size: 50`) | ~1 credit each | 4–10 typical |
| Phase 4 full pagination (`size: 100`) | **~20 credits per page** | enriched rows cost more |

**Realistic Phase 4 math:** TAM ÷ 100 × 20 = **~0.20 credits per HQ-matched delivered company**. A 10k-company TAM costs ~2,000 credits; a 20k TAM costs ~4,000.

Always check balance before Phase 4: `curl "https://api.ocean.io/v2/credits/balance?apiToken=$TOKEN"`.

Hard cap at 5,000 credits per run unless user approves more. If TAM > 25k, ask the user before committing.

---

## Guardrails

1. **One-filter-per-iteration** — never change two filters at once.
2. **Seeds are sacred** — if filters can't fix results, the seeds are wrong; rebuild seed list rather than stacking filters.
3. **Log every iteration** — filter spec + TAM total + user's verdict; becomes tuning playbook for adjacent verticals.
4. **Headcount not revenue** — Ocean revenue data is unreliable.
5. **Hyperlink all domains** in tables: `[domain](https://domain)`.
6. **"What they do" one-liners**, never "why picked".
7. **Don't surface patterns** in Phase 3 results — user drives tweaks, skill applies them.
8. **Confirm filters before Phase 2** — Phase 1.5 is not skippable.
9. **Never use the preview endpoint** — it's enterprise-gated and will fail.
10. **Client-filter for strict-HQ country matching** — Ocean's country filter is presence-based.
11. **Vocabulary lookup before tech/industry filters** — fetch `/v2/data-fields` first; tech/industry strings must match Ocean's exact casing or you get 422 errors and waste credits (e.g. `Appsflyer` not `AppsFlyer`).
12. **Always surface `missingDomains`** — Ocean's crawler fails on ~12% of seeds (including brand names like Calm, Coinbase, DraftKings, Stake, Revolut). If 2+ seeds fail, the lookalike is biased toward the survivors — replace failed seeds and re-run.
13. **Use `fields` parameter** — explicitly request only needed fields; cuts response size 6x and improves parsing speed.
14. **B2C campaigns: always use B2B kill list** — `excludeIndustries` with the standard exclusion bundle; otherwise Stripe / Brex / Pitchbook / Wave-class B2B SaaS leak in via "FinTech" / "Software" tags.
15. **B2C campaigns: D2C scoring required** — `industries` filter cannot distinguish D2C from B2B; manual sample classification needed in Phase 3 using the qualification rubric.
16. **Multi-tier ICPs: per-vertical lookalikes** — when ICP spans 5+ sub-verticals, never use a single mega-call; lookalike will skew to densest seed cluster.
17. **5 seeds not 3** — crawler-failure rate is ~12%; always over-provision seeds (max 10 per call).
18. **NEVER use Ocean's people endpoints** — `/v3/search/people`, `/v2/search/people`, `/v2/lookup/people`, `/v2/enrich/person`, `/v2/enrich/people` are **off-limits for decision-maker discovery**. Decision makers come **only** from AI Ark (people search + UI domain upload) and **Prospeo** (email enrichment). Why: Ocean's people index is sparse and inconsistent for non-tech / non-US verticals — using it for disqualification gates produces false negatives (e.g., Inovalabel returned 0 DMs in Ocean despite being a clear-fit Swiss label converter). How to apply: when the user asks to verify or find decision makers at a company, **always** hand off to `lilly-tam` (which uses Prospeo `/search-person` primary + AI Ark `/v1/people` fallback); never call any Ocean people endpoint, even as a quick check.
19. **Suppression seed + write-back + ledger are mandatory, not optional** — Phase 0 seeds exclusions from Supabase (`check_exclusions`), every paid call writes results back via `put_enrichment` + `upsert_company`, and every paid call logs to `log_provider_usage`. Applies even when this skill runs standalone (not via `lilly-tam`) — see "Cache writes + ledger" under Phase 4.

---

## Cloud upload (mandatory)

The finished company CSV from Phase 4 (or Phase 3's qualified sample, if the user stops before full pagination) MUST be uploaded to the central Supabase list store before the run ends — a TAM that only lives on this machine isn't done. Run:

`python3 ~/.claude/skills/_shared/list_upload.py <final.csv> --name "<descriptive list name>" --client "<Client>" [--folder "<Theme>"] --source-skill lilly-ocean-tam-builder --brief "<one-line brief>" --owner "<who asked>"`

Then show the returned `https://navreo-signals.onrender.com/app/lists.html#<id>` link to the user — that link is part of the deliverable, alongside the CSV.

Folder rules: `--client` = the client named in the brief (internal/Navreo pulls → `Navreo`); add `--folder` ONLY when the brief names a campaign theme or segment (e.g. client `Amplifyy`, folder `Beauty`); never deeper than two levels. Re-runs with the same name+client replace that list's rows in place (safe).
