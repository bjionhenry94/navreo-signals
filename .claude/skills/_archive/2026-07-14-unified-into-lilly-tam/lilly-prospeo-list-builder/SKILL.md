---
name: lilly-prospeo-list-builder
description: "Expand a TAM by finding additional on-brief companies via Prospeo's `/search-company` endpoint with company-only filters and exclude-domain logic (RECALL-MAX method 2026-07-14: open at the loosest defensible classifier shape, widen until a rung fails <70%, keep the biggest passing pool; ALL lookalike/icp_text features BANNED — they decay). Supports the full Prospeo filter vocabulary: industry / keywords / headcount / location PLUS the 2026 push: type & business model, AI attributes (uses_ai / has_soc2 / venture_backed / +35 flags), awards & certifications, website traffic (visits + growth + top countries), Google discovery (SEO keywords), key executive events (CEO/CTO/CFO/VP joins+departs), headcount-by-country, products & services, integrations (uses Stripe / Salesforce / etc.), key customers (cos with OpenAI as a customer), operating languages, reverse ICP (cos that sell to VP Sales), website full-text search, company news (funding / launches / layoffs / leadership changes), expanded funding (stage + investors + accelerator), and SIC & NAICS codes. Use this skill whenever the user has an existing company list (e.g. from `lilly-ocean-tam-builder` Phase 4 or a domain list passed to `lilly-decision-maker-finder`) and wants to surface MORE similar companies that the original source missed, OR wants to filter on any of those new Prospeo signals. Prospeo and Ocean index different companies, so combining both maximises TAM coverage. Trigger on phrases like 'expand the TAM', 'find more companies via Prospeo', 'cross-check with Prospeo', 'what did Ocean miss', 'find all the decision makers in [vertical]' (where the input domain list is incomplete), 'find cos that use OpenAI / Stripe / Salesforce', 'find SOC2-compliant cos', 'find recently-funded cos', 'find cos that hired a new CRO', 'find cos with growing web traffic', 'find cos that sell to VP Sales', or as Phase 2 of `lilly-tam-mapper` and the optional Step 0 of `lilly-decision-maker-finder`. Iterates 1 credit per page (25 unique cos), qualifies results in batches, stops when precision drops below 7/10."
---

# Lilly Prospeo List Builder

## Purpose

Expand an existing company list (typically from `lilly-ocean-tam-builder` Phase 4, or as Phase 2 of `lilly-tam-mapper`) by finding MORE on-brief companies via Prospeo's dedicated `/search-company` endpoint. Ocean and Prospeo index different company sets. Running both surfaces companies neither would on its own.

## ⚡ 2026-07-14 RECALL-MAX METHOD (PROVEN, 30-brief lab — supersedes precision-first shape building below; evidence `lilly-tam-recall-lab/RESULTS-30.md`)

Old shapes starved recall 60-85% (B2B SaaS US: 4,711 narrowed vs **29,804 @ 88%** subtypes-alone). The selection rule is now:
1. **Open at the LOOSEST defensible shape:** `company_type.subtypes` alone (SaaS, Agency, Construction, Logistics, FinTech, E-commerce…) or one `company_industry` enum family alone, + headcount + geo. NEVER open with `business_model`/`has_subscription`/keyword narrowing — add ONE layer only if the ≤25-row gate scores <70%.
2. **≥70% → try one WIDER rung** (adjacent subtype/enum). Keep widening until a rung fails; **chosen = biggest pool ≥70%**; record the failed rung as the maximality proof. Max 3 shapes.
3. **Rungs are geo-dependent** ([SaaS,Platform]: UK 76% ✓, US 68% ✗) — score per geo, never transfer.
4. **Keyword baskets rerank non-monotonically** — a WIDER basket can SHRINK the pool (measured twice). Baskets are probes, not dials.
5. **Brand/DTC briefs work here:** the E-commerce→Retail→Marketplace subtype ladder measured 60,769 @ 80% (a brief AI Ark structurally fails). Take the biggest passing rung.
6. **🚫 `company_lookalike` (icp_text and every other mode) is BANNED** — user 2026-07-13, all providers: lookalike features decay. Discovery = classifiers/enums/self-ID keywords only. Ignore any icp_text recipe below (historical).
7. **Never request emails/enrichment from this skill** (user 2026-07-13) — company fields only.
8. Enum trap: "Truck Transportation" is INVALID; probe enums with free INVALID_FILTERS responses. Pass bar for shapes = 70% (recall-max selection), not the old 7/10-and-stop-tightening.

The right endpoint is `/search-company` (NOT `/search-person`). Same X-KEY auth, same 1-credit-per-page cost, returns 25 unique companies per page (no person-deduplication needed). Filter shape is the same `company_*` keyword set used in `/search-person`, minus the `person_*` filters.

`/search-person` is reserved for `lilly-decision-maker-finder`, where person data is the actual deliverable.

---

## When to Use

Trigger when the user wants to:
- Expand an existing TAM beyond the original source.
- Cross-check Ocean.io results against Prospeo's index.
- Run a 2nd-pass expansion with a fresh classifier/keyword shape.
- Add to a live prospect list with newly-surfaced companies.

Accept input forms:
- "Expand the TAM via Prospeo"
- "Find more agencies that Ocean missed"
- "Cross-check this list against Prospeo"
- "Find more like these on Prospeo too" (runs as classifier/keyword shapes — lookalike features are banned)
- Direct hand-off from `lilly-tam-mapper` Stage 2.

---

## API access

- **Endpoint:** `POST https://api.prospeo.io/search-company`
- **Auth:** `X-KEY: <PROSPEO_API_KEY>` (in `mcpServers.email-finders.env`)
- **Cost:** **1 credit per page** that returns ≥1 result. Free on `NO_RESULTS` or `INVALID_FILTERS`.

---

## The 5-step workflow

### Step 1 — Input

Take from the user (or the calling skill):
- An existing company list (the "anchor" — Ocean TAM, prior research file, etc.). These become the **excludes**.
- **Baseline brief criteria:** industry, geography, headcount, buyer-type keywords.
- **(2026 push) Optional extended-filter criteria** — any of the following narrows the search powerfully and is worth surfacing during intake:
  - **Compliance / attributes:** SOC2 / GDPR / HIPAA / venture-backed / publicly traded / uses-AI / has-API / has-Chrome-extension / has-marketplace / etc. → `company_attributes`
  - **Customer-list intent:** "cos with [Brand] as a customer" → `company_key_customers`
  - **Tech-stack mention:** "cos using Stripe / Salesforce / Segment / etc." → `company_integrations`
  - **Recent exec change:** "cos that hired a new CRO / VP Sales / CMO in last 90d" → `company_key_execs`
  - **Recent funding:** "Seed/Series A/B in last 90d", "investors include [X]", "was in [accelerator]" → `company_funding`
  - **Recent news:** "recently funded / launched / partnered / expanded / had layoffs / IPO'd / changed leadership" → `company_news`
  - **Awards / certifications:** "Inc 5000", "Deloitte Fast 500", "SOC 2 certified", etc. → `company_awards`
  - **Traffic profile:** "cos with 10K+ monthly visits", "cos with traffic growing 20%+", "cos with US traffic share above 50%" → `company_website_traffic`
  - **Headcount-by-country:** "10-50 employees in Germany", "100+ in US AND 20+ in UK" → `company_headcount_by_location`
  - **Reverse ICP (who they sell to):** "cos that sell to VP Sales", "cos targeting mid-market HR" → `company_icp`
  - **Products / services offered:** "cos offering CRM / Design Consulting / etc." → `company_products_services`
  - **SEO keyword intent:** "cos that rank for 'sales engagement platform'" → `company_google_discovery`
  - **Website-text search:** "cos whose website mentions 'pricing' on the homepage", "cos with a security page" → `company_website_search`
  - **Operating languages:** "cos that operate in French + German" → `company_operating_languages`
  - **SIC / NAICS codes:** "cos in NAICS 541512" → `company_naics` / `company_sics`
  - ~~ICP-text lookalike~~ — **BANNED 2026-07-13 (all lookalike features, all providers — decay).** "Find cos similar to X" requests run as native classifier + self-ID keyword shapes instead.
- Stop precision (default = **7/10 qualified**).
- Page-size for qualification batches (default = 10 — `size:25` is fixed on `/search-company` regardless of what's requested; qualify the first 10 results from each page).

**Pre-flight: strip multi-level TLD subdomains.** Prospeo rejects domains like `.uk.com`, `.us.com`, `.eu.com` with `INVALID_FILTERS: Subdomains are not supported`. A single offender aborts the entire batch (confirmed 2026-05-04: `luckyfox.uk.com`, `massa.us.com` killed two batches mid-sweep). Strip them from the anchor list BEFORE any `company.websites.include` or `company.websites.exclude` call:

```python
def is_invalid_subdomain(d):
    parts = d.lower().split('.')
    return len(parts) >= 3 and parts[-2] in ('uk','us','eu','gb','de','ca') and parts[-1] == 'com'

domains = [d for d in domains if not is_invalid_subdomain(d)]
```

Surface dropped count to the user: `"N domains stripped (Prospeo rejects multi-level TLDs)"`.

### Step 2 — Build the filter

**CRITICAL: filter shape uses TOP-LEVEL keys for industry / keywords / headcount / location** (not nested under `filters.company`). Confirmed via `/search-company` probes 2026-05-01. The nested `filters.company.industries` shape is silently ignored — calls succeed but the filter has no effect.

Only `websites` (include/exclude) belongs nested under `filters.company`.

Skip `person_*` filters entirely. This is a company-discovery endpoint.

```bash
curl -X POST "https://api.prospeo.io/search-company" \
  -H "X-KEY: $PROSPEO_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "page": 1,
    "size": 25,
    "filters": {
      "company": {"websites": {"exclude": [<existing TAM domains, max 500>]}},
      "company_keywords": {"include": ["<buyer-type phrase 1>","<buyer-type phrase 2>"], "include_company_description": true},
      "company_industry": {"include": ["<exact LinkedIn industry string>"]},
      "company_headcount_range": ["11-20","21-50","51-100","101-200"],
      "company_location_search": {"include": ["United States","United Kingdom"]}
    }
  }'
```

**Filter rules:**

| Filter | Position | Shape | Notes |
|---|---|---|---|
| `websites.exclude` | nested under `filters.company` | `{"exclude": [...]}` | Cap 500 domains. If TAM bigger, prioritise top-N most recognisable. **Provider exclude is leaky — always client-side filter results too (rule #16).** |
| `company_keywords` | top-level | `{"include": [...], "include_company_description": true}` | `include_company_description: true` matches against company description text. Best for buyer-type filtering. **Use buyer-type phrases only (rule #11b)** — see Step 2.5. |
| `company_industry` | top-level | `{"include": ["Marketing Services","Advertising Services",...]}` | **Strict enum — exact LinkedIn industry strings only.** "Marketing & Advertising" / "Marketing and Advertising" / "Marketing" all return INVALID_FILTERS. Confirmed working: "Marketing Services", "Advertising Services". Probe one at a time to validate. |
| `company_headcount_range` | top-level | `["11-20","21-50",...]` | Buckets: `1-10, 11-20, 21-50, 51-100, 101-200, 201-500, 501-1000, 1001-2000, 2001-5000, 5001-10000, 10000+` |
| `company_location_search` | top-level | `{"include": ["United States","United Kingdom"]}` | Full English country names. Validate via `POST /search-suggestions` with `{"location_search":"<prefix>"}`. |

**Validation:**
- **Industry strings:** `/search-suggestions` does NOT expose industry validation. Probe by firing tiny `size:2` calls. `INVALID_FILTERS` = wrong string (free). `total_count: N` = valid (1 credit).
- **Cost of probing:** invalid filters return `INVALID_FILTERS` for free. `NO_RESULTS` (filter combination matches zero cos) is also free — useful for shape validation without spend.
- **`size` parameter is fixed at 25 on `/search-company`.** Setting `size: 2` does not reduce the per-page payload. Plan credit budgets around 25-per-page.

---

### Step 2.1 — Extended filter reference (2026 push, validated 2026-05-19)

In addition to the 5 baseline filters above, `/search-company` accepts the full Prospeo SearchFilter vocabulary. Every filter below was probed live on 2026-05-19 and confirmed working unless marked otherwise. All shapes are top-level under `filters` (NOT nested under `filters.company`) except `company.websites` / `company.names` / `company.company_oids`.

| Filter key | Position | Shape | Notes / enum |
|---|---|---|---|
| `company_type` | top-level | `{"status": "Private"\|"Public"\|"Non Profit"\|"Other", "business_model": "...", "is_retail": bool, "is_marketplace": bool, "is_mainly_ai": bool, "is_mainly_crypto": bool, "multi_product": bool, "has_free_tier": bool, "is_self_serve": bool, "is_sales_led": bool, "has_usage_pricing": bool, "has_subscription": bool, "has_enterprise_plan": bool, "has_public_pricing": bool, "subtypes": {...}}` | `status` enum confirmed via probe. `subtypes` uses `CompanySubtypeInclude` schema (27 categories per marketing — probe to discover values). |
| `company_attributes` | top-level | Object of ~40 boolean flags. Each is `true` / `false` / null. | Full key list: `b2b`, `demo`, `freetrial`, `downloadable`, `mobileapps`, `onlinereviews`, `pricing`, `uses_ai`, `has_api`, `has_chrome_extension`, `has_sso`, `has_uptime_guarantee`, `has_open_source`, `has_marketplace`, `has_blog`, `has_podcast`, `has_community_forum`, `has_knowledge_base`, `has_academy`, `has_affiliate_program`, `has_case_studies`, `has_testimonials`, `has_phone_support`, `has_email_support`, `has_chat_support`, `has_ticket_support`, `has_social_support`, `has_soc2`, `has_iso27001`, `has_gdpr`, `has_hipaa`, `has_ccpa`, `has_pci_dss`, `has_esg_reports`, `has_physical_offices`, `is_venture_backed`, `is_publicly_traded`. Also: `other_compliance: [strings, max 50]`, `compliance_match_mode: "EXACT"\|"CONTAINS"`, `data_residency: "<string, max 50>"`. Confirmed: `{"uses_ai": true}` returned 336,188 cos. |
| `company_awards` | top-level | `{"include": [strings, max 50], "match_mode": "EXACT"\|"CONTAINS"}` | Include-only, no exclude. `EXACT` = full pipe-delimited entry match (default); `CONTAINS` = substring inside any entry. Examples: `"Inc 5000"`, `"SOC 2"`, `"Deloitte Technology Fast 500"`. |
| `company_funding` | top-level | `{"stage": ["Series A","Seed",...], "funding_date": 30\|60\|90\|180\|270\|365, "last_funding": {"min":"...","max":"..."}, "total_funding": {"min":"...","max":"..."}, "investors": [strings, max 10], "was_in_accelerator": bool, "accelerator_name": "<string, max 100>"}` | `stage` enum: `Series unknown`, `Pre seed`, `Seed`, `Series A`, `Series B`, `Series C`, `Series D`, `Series E-J`, `Grant`, `Angel`, `Private equity`, `Debt financing`, `Non equity assistance`, `Post IPO equity`, `Undisclosed`, `Post IPO debt`, `Product crowdfunding`, `Equity crowdfunding`, `Corporate round`, `Convertible note`, `Secondary market`, `Initial coin offering`, `Post IPO secondary`. `funding_date` is days lookback. `min`/`max` enum: `<100K`, `100K`, `500K`, `1M`, `5M`, `10M`, `25M`, `50M`, `100M`, `250M`, `500M`, `1B`, `5B`, `10B+`. |
| `company_google_discovery` | top-level | `{"seo_keywords": [strings, max 100, each max 100 chars]}` | LLM-generated keyword index (not real SERP data). Routes to OpenSearch. |
| `company_headcount_by_location` | top-level | `{"entries": [{"country": "<full name>", "min_headcount": int, "max_headcount": int}, ...max 10]}` | Per-country headcount range. Use full English country names (validate via `/search-suggestions`). At least one entry required. |
| `company_icp` (Reverse ICP) | top-level | `{"titles_include": [strings], "titles_exclude": [strings], "company_sizes": ["micro"\|"smb"\|"midmarket"\|"enterprise"\|"large_enterprise"], "industries": [strings], "geographic_markets": [strings], "geographic_scope": "<string>", "departments": {"include": [strings], "match_mode": "any"\|"all", "other": [strings]}}` | "Find cos that SELL TO X." **WARNING:** `company_sizes` uses a DIFFERENT enum from `company_headcount_range` (5 buckets, not 11). Mixing them is a common footgun. |
| `company_integrations` | top-level | `{"include": [strings, max 20], "exclude": [strings, max 10]}` | Integrations mentioned on website (Salesforce, Stripe, Segment, HubSpot, etc.). Pipe-delimited backing column. |
| `company_intent` | ❌ FORBIDDEN | n/a | `INVALID_FILTERS: Forbidden filters found: company_intent`. UI-only. Do not include in any payload. |
| `company_key_customers` | top-level | `{"include": [strings, max 100]}` | Include-only. "Find cos whose customer list mentions [Brand]." Example: `["OpenAI"]` finds every company claiming OpenAI as a customer. |
| `company_key_execs` | top-level | `{"event_types": [strings], "timeframe_days": int}` (default 90) | 24-event enum: `CEO Departed`, `CEO Appointed`, `CTO Departed`, `CTO Appointed`, `CFO Departed`, `CFO Appointed`, `COO Departed`, `COO Appointed`, `CMO Departed`, `CMO Appointed`, `CRO Departed`, `CRO Appointed`, `VP of Sales Departed`, `VP of Sales Appointed`, `VP of Marketing Departed`, `VP of Marketing Appointed`, `VP of Engineering Departed`, `VP of Engineering Appointed`, `Any C-Level Departed`, `Any C-Level Appointed`, `Any VP Departed`, `Any VP Appointed`, `Any Director Departed`, `Any Director Appointed`. Powerful intent signal — e.g. "CRO Appointed in last 60 days". |
| `company_keywords` | top-level | `{"include": [strings], "exclude": [strings], "include_all": bool (default false), "search_everywhere": bool (default true), "sources": ["specialties"\|"social_media_description"\|"seo_description"\|"ai_description"\|"products_services"\|"website_pages"], "include_company_description": bool, "include_company_description_seo": bool}` | **Revamped** in 2026 push — now searches across 6 configurable text sources. When `search_everywhere: true` (default), all 6 sources scanned. Old `include_company_description` field still accepted for back-compat. Buyer-type rule (Step 2.5) still applies. |
| `company_lookalike` | ❌ **BANNED 2026-07-13** (all lookalike features, all shapes — decay; see rule #17) | n/a | Historical: **icp_text mode was the only working mode on this endpoint.** `domain` and `company_oids` modes return `INTERNAL_ERROR`. Submit a natural-language ICP description (e.g. `"B2B SaaS sales engagement platform"`) — backend embeds + kNN. Tier `T3` = wider, `T1` = tightest. |
| `company_naics` | top-level | `{"include": [int], "exclude": [int], "include_all": bool}` | Standalone NAICS classification (separated from `company_industry` in 2026 push). Integer codes only (e.g. `541512` = computer systems design). |
| `company_news` | top-level | `{"keywords": [strings], "categories": [strings], "timeframe_days": int}` (default 90) | 10-category enum: `Funding & Investment`, `Mergers & Acquisitions`, `Product Launch`, `Partnership`, `Expansion`, `Layoffs & Restructuring`, `IPO`, `Leadership Change`, `Legal & Regulatory`, `Awards & Recognition`. `keywords` is free-text. **Replaces V7 Serper news search at the LIST layer** for many briefs. |
| `company_operating_languages` | top-level | `{"include": [strings, max 10]}` | Pipe-delimited language column. Example: `["english","french"]` = OR across the two. |
| `company_products_services` | top-level | `{"products_include": [strings, max 20], "products_exclude": [strings, max 10], "products_match_all": bool, "service_tags_include": [strings, max 20], "service_tags_exclude": [strings, max 10], "service_tags_match_all": bool}` | Two parallel sets — `products_*` (what they make) and `service_tags_*` (what they offer). Backed by OpenSearch `company_text` index. |
| `company_sics` | top-level | `{"include": [int], "exclude": [int], "include_all": bool}` | Standalone SIC classification. Integer codes only (e.g. `7372` = prepackaged software). |
| `company_website_search` | top-level | `{"include_keywords": [strings, max 10], "exclude_keywords": [strings, max 10], "match_mode": "any"\|"all", "page_scope": ["homepage"\|"product"\|"blog"\|"careers"\|"about", max 5], "url_contains": "<string, max 200>", "has_persona_pages": bool, "has_industry_pages": bool, "has_solution_pages": bool, "has_careers_page": bool, "has_status_page": bool, "has_sla_page": bool, "has_developer_docs_page": bool, "has_investor_page": bool, "has_security_page": bool, "has_comparison_pages": bool}` | Full-text crawl search with 10 page-type boolean flags. Backed by OpenSearch. |
| `company_website_traffic` | top-level | `{"min_monthly_visits": int (0..100M), "max_monthly_visits": int, "visit_change": {"period": "monthly"\|"quarterly"\|"yearly", "min_change": -100..10000, "max_change": -100..10000}, "top_countries": [strings], "min_country_pct": 0..100, "max_country_pct": 0..100}` | Traffic volume + growth/decline + audience-country mix. `visit_change` is percent change (e.g. `min_change: 20` = traffic up at least 20%). |

**Validation cost summary (probed 2026-05-19):** the full 19-filter validation sweep cost **2 credits total** across 10 probes. INVALID_FILTERS and NO_RESULTS responses are both free — use them aggressively when discovering enum values for a new brief.

### Step 2.5 — Buyer-type vs subject-matter keywords (rule #11b)

The buyer-type vs subject-matter distinction is critical for keyword selection. Confirmed in the AppLift dry-run (2026-05-01): broad subject-matter keywords drag in dev shops, general agencies, and platforms; buyer-type keywords stay precise.

| Keyword class | Example | Behaviour |
|---|---|---|
| **Buyer-type** ✅ | `"app marketing agency"`, `"app growth agency"`, `"mobile growth agency"`, `"ASO agency"` *(careful with acronyms — see rule #11)* | Anchors on WHO the company is. The word `"agency"` / `"consultancy"` / `"studio"` does the work. |
| **Subject-matter** ❌ alone | `"mobile app marketing"`, `"user acquisition"`, `"app store optimization"` *(alone, no "agency")* | Anchors on WHAT they do. Catches dev shops, general agencies, platforms — anyone who *mentions* the topic. |

Rule: when targeting a buyer type, only use buyer-type keywords. Subject-matter words are valid only when fused into a buyer-type phrase (`"mobile user acquisition agency"` ✅).

**Acronym false-positive trap (rule #11):** `"ASO services"` will substring-match "Administrative Services Organization (aso) services" inside HR/PEO descriptions. Use fully-spelled phrases (`"app store optimization services"`) or layer `excludeIndustries: ["Human Resources","Outsourcing","Staffing and Recruiting"]`.

### Step 3 — Run page-1 + qualify (the iteration loop)

1. Fire page 1 with `size: 25`. Cost: 1 credit.
2. Read `pagination.total_count` (companies, not persons — confirmed for `/search-company`).
3. **Surface the TAM headline FIRST.** `total_count` × 1 credit = full extraction cost. Show this before qualification rows.
4. Take the first 10 unique companies and qualify each: read description, tag y/n.
5. **If 7+/10 qualified** → continue. Run page 2, qualify, repeat.
6. **If <7/10 qualified** → stop. Filter is too loose. Tighten by:
   - Narrowing `company_keywords` to a more specific buyer-type term.
   - Tightening `company_industry` to fewer canonical strings.
   - Tightening `company_headcount_range` (drop the largest bucket).
   - Adding `excludeIndustries` for off-brief categories.
   - Resume from page 1 with the tighter filter.

### Step 3.4 — *(HARD ABORT GATE)* 50% sample-fit before paginating

After page 1 + WebFetch verification of the first 10 unique-domain candidates, calculate the **on-brief rate**.

- **If ≥50% on-brief** (5+ of 10 verified ICP) → continue to Step 3.5 and paginate per the 7/10 continuation rule.
- **If <50% on-brief** (4 or fewer of 10 verified ICP) → **HARD ABORT this search entirely.** Do NOT paginate further. The filter pool is fundamentally wrong. Full extraction would burn 10-50 credits on a list where the majority is off-brief.

**On abort:**
1. Report the failure to the user with the actual on-brief rate (e.g., "3/10 verified — pool is 70% off-brief, aborting").
2. Diagnose: is the keyword too generic? Is the industry filter wrong? Is the country pool too small for the niche?
3. Either redesign the filter from scratch with tighter keywords / different industry / different angle, OR conclude that this brief × this market doesn't have a viable Prospeo search and move on.

**Why 50% (not 70%):** the 70%/7-of-10 rule is for *iteration continuation* — assumes the search is fundamentally sound. The 50% rule is a *fitness gate* — if even half the pool isn't ICP, the search itself is wrong, and tightening filters won't recover it.

### Step 3.45 — *(MANDATORY)* Sample-audit pause: explicit user go-ahead before the full pull

Passing the 50% fitness gate (Step 3.4) and the 7/10 continuation rule is necessary but NOT a licence to auto-paginate the full list. **Always present the verified sample to the user and pause for an explicit go-ahead before committing to full pagination / the rest of the spend** — regardless of how clean the sample looks:

1. Show the sample audit: on-brief rate, the qualified / borderline / off-brief split, and example companies per bucket.
2. **Wait for explicit user go-ahead before the full pull.** The user sees what actually surfaced on the first sample (~100), then signs off — or retunes filters and re-samples — before the haystack is paginated. Never silently auto-continue.

This is the company-level half of the gate. When this list feeds a decision-maker pull, the **title-function audit also runs at the DM step**: `lilly-decision-maker-finder` Step 2.5 pulls ~100 DMs, classifies their titles via `lilly-list-audit`, and pauses for go-ahead before any enrichment spend.

### Step 3.5 — *(MANDATORY)* Verify each candidate via WebFetch before enrichment

**API description matching is NOT real qualification.** Two failure modes confirmed in the AppLift dry-run (2026-05-01):
1. **Stale data (rule #17):** Prospeo described `fetch.com` as "global agency, London/NY/SF/LA/Tokyo/Singapore/HK" — accurate for Fetch the agency in 2018, before they were absorbed by Dentsu. Today `fetch.com` is `America's Rewards App` (consumer rewards platform — completely different company).
2. **Soft-category mismatch:** descriptions can match keywords like `"mobile app marketing"` while the company is actually a dev shop, general agency, or platform.

**For every shortlisted candidate, before passing to DM enrichment:**
1. WebFetch the company's website with a brief-specific qualification prompt: "Is this company [brief criteria]? Or are they something else (dev shop, platform, general agency, dead/hijacked domain)? Quote one phrase. Tag: AGENCY (app-focused) / HYBRID / PLATFORM / OFF-BRIEF / unreachable."
2. Mark each as ✅ on-brief / ⚠️ borderline / ❌ off-brief / ❓ unreachable.
3. Drop ❌ off-brief. Surface ⚠️ borderline to user judgment. Tag ❓ unreachable as "needs live verification" — never auto-promoted.
4. Only ✅ confirmed-on-brief cos pass to enrichment.

**Cost rationale:** WebFetch is free. DM enrichment is 1-30+ credits per company. Skipping verification means burning credits on cos that get dropped.

### Step 3.6 — *(MANDATORY)* Defensive client-side exclude filter (rule #16)

Provider `websites.exclude` is unreliable. Confirmed today: `yodelmobile.com` and `fetch.com` were in our `filters.company.websites.exclude` payload (verified before sending), Prospeo returned them anyway. Likely cause: companies have multiple stored websites and the filter only matches against one of them.

**After every page returns, post-filter results client-side:**
```python
exclude_set = {d.lower() for d in cumulative_excludes}
clean = [r for r in results if (r.get('company',{}).get('domain') or '').lower() not in exclude_set]
leaked = [r for r in results if (r.get('company',{}).get('domain') or '').lower() in exclude_set]
# Log leaked count — useful signal for filter health
```

Cost: 0. Catches Prospeo's leaks.

### Step 4 — Track output (three pots)

For each verified company, write to ONE of three CSVs:

| File | Verdict | Goes to DM enrichment? |
|---|---|---|
| `qualified.csv` | ✅ on-brief | YES (when caller hands off) |
| `borderline.csv` | ⚠️ user judgment | YES (auto-included on hand-off per resolved decision #1) |
| `off-brief.csv` | ❌ confirmed off-brief, ❓ unreachable, stale-data, hijacked | **NO. Locked out.** |

Schema:
```
#, domain, company_name, primary_country, employee_size, industries, description,
verdict, pot, verdict_reason, source, qualification_round
```

`source = "prospeo_company_search"` to distinguish from Ocean-sourced rows.

If chained from `lilly-tam-mapper`, append to the existing pots so they merge cleanly across providers.

### Step 5 — Hand off

**When chained from `lilly-tam-mapper` (Stage 2):**
- Updated three pots (Ocean + Prospeo merged).
- Iteration log: pages run, precision per page, credits spent, when filter was tightened, leaked-exclude count.
- Surfaced new domains for the cumulative_excludes set passed to Stage 3 (AI Ark).

**When chained from `lilly-decision-maker-finder` (Step 0):**
- Newly-surfaced domain list (deduped against the input domain set).
- Same iteration log.
- Caller merges these onto its input domain list before running Step 1 (Prospeo `/search-person` for DM discovery).

**Standalone:**
- Three-pot CSVs tagged `prospeo_company_search` + iteration log.

---

## Cache writes (mandatory after every successful page)

After each `/search-company` response that returns ≥1 result, write each company object to the cache so downstream skills (`lilly-icebreaker`, future skills) can read funding / job_postings / technology / employee_count without paying for a re-fetch.

**Preferred write path (dual-write):** `navreo_db.put_enrichment("company", domain, "prospeo", company_obj, endpoint="/search-company", source_skill="lilly-prospeo-list-builder")` from the shared helper `~/.claude/skills/_shared/navreo_db.py` — writes the Supabase central cache AND the local mirror below in one call, fails soft to local-only on outage. Also check `navreo_db.get_enrichment("company", domain)` before any paid re-fetch — the central cache may hold entries this machine never fetched.

**Ledger every paid call:** after each billed `/search-company` page, `navreo_db.log_provider_usage("prospeo", <credits>, endpoint="/search-company", source_id="lilly-prospeo-list-builder")` — this is the cost-audit trail, separate from the cache write above.

**Layout:** `~/.navreo-cache/prospeo/companies/{canonical-domain}.json`

**Per-file envelope:**
```json
{
  "fetched_at": "2026-05-05T17:25:00Z",
  "endpoint": "/search-company",
  "source_skill": "lilly-prospeo-list-builder",
  "data": { ...the raw company object from results[i]... }
}
```

**Write logic** (per company in `results[]`):

```bash
NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
DOMAIN=$(echo "$company_domain" | tr '[:upper:]' '[:lower:]' | sed -E 's|^https?://(www\.)?||;s|/.*$||')

jq -n --argjson co "$company_obj" --arg now "$NOW" \
  '{fetched_at: $now, endpoint: "/search-company", source_skill: "lilly-prospeo-list-builder", data: $co}' \
  > ~/.navreo-cache/prospeo/companies/${DOMAIN}.json
```

In practice, run this as a single jq pipeline over the full response — one file per company in `results[]`.

### Cache rules

1. **Last-write-wins** per domain. If `lilly-decision-maker-finder` later calls `/search-person` against the same domain, its newer write overwrites this one — that's correct, since `/search-person`'s nested company object is identical-or-richer.
2. **Canonical domain key.** Lowercase, strip protocol + `www.`, strip trailing slash and path.
3. **Don't write empty data.** Skip `data: null` / `data: {}` rows.
4. **Failure-tolerant.** Cache writes never block the main qualification workflow. Wrap in `|| true` if running inline.
5. **No people from this endpoint.** `/search-company` only returns companies — only `~/.navreo-cache/prospeo/companies/` is touched.

---

## Reference: filter values discovery

Prospeo's industry/location enums are taxonomy-strict. **Validate before firing.**

- **Location candidates:** `POST /search-suggestions` with `{"location_search": "United"}` → returns up to 10 country/zone matches. Free.
- **Industry candidates:** `/search-suggestions` does NOT expose industry validation (the `company_industry_search` key is rejected). Two ways to find valid strings:
  1. Probe by firing tiny `size:2` calls — `INVALID_FILTERS` = invalid (free), `total_count: N` returned = valid (1 credit).
  2. Pull the SearchFilter schema from `https://api.prospeo.io/openapi.json` (free) — though the industry enum itself isn't enumerated in the spec.
- **Confirmed valid industry strings**: `Marketing Services`, `Advertising Services`. **Confirmed invalid:** `Marketing & Advertising`, `Marketing and Advertising`, `Marketing`.
- **Job-title candidates:** `POST /search-suggestions` with `{"job_title_search": "sales"}` — returns up to 25 normalised titles. Free. *(Used by `lilly-decision-maker-finder`, not this skill.)*

---

## Cost calibration

- 1 credit per page (25 unique companies)
- Realistic iteration: 1-15 pages before precision drops or `total_count` is exhausted.
- **Typical full expansion run: 1-15 credits** — cheap enough to be a routine TAM-doubling step.

**AppLift dry-run (2026-05-01):**
- 1 credit (failed-shape probe → INVALID_FILTERS, free in theory but registered)
- 1 credit (productive `/search-company` call — 12 unique cos returned, `total_count: 12`, `total_page: 1`, full TAM in one credit)
- 7 qualified after WebFetch verification + client-side exclude filter (caught 2 leaked excludes)

**Bench: 3.5 cos per credit on tight buyer-type briefs.** Higher-recall briefs (e.g. broader industry) typically deliver 5-10 cos per credit.

If `total_count` after page 1 is >5,000, cap credit budget upfront — don't paginate the entire haystack without confirmation.

---

## Why `/search-company`, not `/search-person`

Confirmed today (2026-05-01):

| | `/search-person` (with company-only filters) | `/search-company` (THIS skill) |
|---|---|---|
| Cost per page | 1 credit | 1 credit |
| Per-page returns | 25 person rows | 25 unique companies |
| Unique cos per page (after dedupe) | 3-15 (varies wildly by niche density) | 25 |
| In tight niches (few big cos dominate) | 3 cos / page (8.3 persons each — wasted payload) | 25 cos / page |
| Filter shape | Same `company_*` keys | Same `company_*` keys |

`/search-person` was the historical workaround when this skill assumed `/search-company` had a different shape. Probing today (2026-05-01) confirmed `/search-company` accepts the identical `company_*` filter shape with `{"include": [...]}` wrappers. The switch is pure recall improvement at the same credit cost.

`/search-person` is still the right endpoint for `lilly-decision-maker-finder`, where person data is the deliverable.

---

## Guardrails

1. **Always exclude the source TAM domains** via `filters.company.websites.exclude` UP TO the measured cap of 500. Don't self-impose a smaller limit. If source TAM > 500, three options:
   - **(default) Smart-prioritised single-pass:** rank by "likelihood to resurface" (high web traffic + ≥50 headcount + brand recognition), exclude top-500, accept overlap on the rest, dedupe at merge.
   - **Multi-pass rotating excludes:** run Prospeo N = `ceil(source_tam / 500)` times, each with a different 500-domain subset.
   - **Adaptive page-by-page exclusion:** swap surfaced overlap cos into the exclude set between pages.
   Default to single-pass with smart-prioritised excludes unless brief calls for maximum coverage.
2. **Use `/search-company`, not `/search-person`,** for company discovery.
3. **Use top-level filter keys, NOT nested under `filters.company`.** `company_industry`, `company_keywords`, `company_headcount_range`, `company_location_search` go at the root of `filters`. Only `websites` belongs nested under `filters.company`.
4. **Validate filter values before firing.** Locations + job titles via `/search-suggestions` (free). Industries by tiny `size:2` probe calls — `INVALID_FILTERS` = bad string (free), `total_count: N` returned = valid (1 credit).
5. **Hard abort at <50% sample-fit.** After page 1 + WebFetch verification of the first 10, if fewer than 5 are on-brief ICP → stop pulling, don't paginate. **Stop at 7/10 precision** for iteration continuation when the search IS sound.
6. **Lead with the TAM headline, not the qualification table.** First thing in the response: `total_count`, realistic qualified expansion (`total_count × precision`), combined source+expansion total.
7. **Three pots — `qualified.csv` / `borderline.csv` / `off-brief.csv`.** Off-brief NEVER goes to DM enrichment.
8. **Buyer-type keywords only** for buyer-targeting briefs. Subject-matter keywords (alone) catch dev shops + general agencies + platforms.
9. **Acronym false-positive mitigation:** prefer fully-spelled phrases (`"app store optimization services"` not `"ASO services"`). Add `excludeIndustries` for known false-positive verticals.
10. **Defensive client-side exclude filter (rule #16) is mandatory.** Provider `websites.exclude` is leaky. Post-filter results against the cumulative exclude set. Free.
11. **WebFetch verification of every candidate (rule #17) is mandatory** before DM enrichment. API descriptions lag reality (acquisitions, brand changes, domain transfers).
12. **Source-tag every row** as `source = "prospeo_company_search"` for traceability across providers.
13. **Never use Ocean people endpoints** (banned per `feedback_no_ocean_people_search`).
14. **1 credit per page = 1 iteration cost.** Don't conflate iterations with credit count.
15. **Cache writes are mandatory** (see "Cache writes" section). Every successful `/search-company` page writes per-company slices to `~/.navreo-cache/prospeo/companies/`. Downstream consumers (`lilly-icebreaker` reads funding / job_postings / technology / employee_count from this cache) skip re-paying when the data is fresh. Skipping the writes silently breaks the cache contract.
16. **`company_intent` is forbidden on this endpoint.** Confirmed 2026-05-19: the legacy `/search-company` API returns `INVALID_FILTERS: Forbidden filters found: company_intent`. Coresignal intent data is Prospeo-UI-only. Never include `company_intent` in any payload, and if a user asks for "intent-based" filtering, redirect them to (a) the Prospeo UI for an export, or (b) hiring-signal (`company_key_execs`) + funding-signal (`company_funding`) + news-signal (`company_news`) as proxies — all three are accessible via this endpoint.
17. **`company_lookalike` is BANNED in every mode (user 2026-07-13 — all lookalike features on all providers decay).** Never include it in any payload. When the user asks for "companies similar to X", translate the ask into native classifier shapes (`company_type.subtypes` / `company_industry`) + self-ID keywords per the RECALL-MAX method at the top of this skill. (Historical note: icp_text was the only working mode; domain/company_oids modes returned INTERNAL_ERROR.)
18. **`company_icp.company_sizes` uses a DIFFERENT enum from `company_headcount_range`.** The Reverse-ICP filter (cos that sell to X) buckets sizes into 5 LLM-categorical labels: `micro`, `smb`, `midmarket`, `enterprise`, `large_enterprise`. The headcount filter (cos OF a certain headcount) uses 11 explicit ranges: `1-10`, `11-20`, ..., `10000+`. Mixing them returns `INVALID_FILTERS`. Footgun caught 2026-05-19.
19. **Sample-audit pause before the full pull (MANDATORY, Step 3.45).** Passing the 50% fitness gate is not a licence to auto-paginate — always present the verified sample and pause for explicit user go-ahead before full pagination, regardless of how clean it looks. When the list feeds a DM pull, the title-audit gate at `lilly-decision-maker-finder` Step 2.5 (pull ~100 DMs → classify via `lilly-list-audit` → pause) applies before enrichment.

---

## Quick reference

| Need | Endpoint | Auth | Cost |
|---|---|---|---|
| Find on-brief companies (recall-max shapes) | `POST api.prospeo.io/search-company` (this skill) | `X-KEY` | 1 / page (25 unique cos) |
| Find decision-makers | `POST api.prospeo.io/search-person` (used by `lilly-decision-maker-finder`) | `X-KEY` | 1 / page |
| Validate industry/location values | `POST api.prospeo.io/search-suggestions` | `X-KEY` | free |
| Check Prospeo balance | `POST api.prospeo.io/account-information` | `X-KEY` | free |
| **Cache write (after every page)** | `~/.navreo-cache/prospeo/companies/{domain}.json` | n/a | free, mandatory |

See also:
- `lilly-tam-mapper/SKILL.md` — orchestrator that calls this skill as Stage 2.
- `lilly-decision-maker-finder/SKILL.md` — uses `/search-person` for DM discovery, not this skill.
- `lilly-ai-ark-list-builder/SKILL.md` — parallel skill for AI Ark cross-index expansion. Run AFTER this one (cheaper baseline).
- `lilly-icebreaker/SKILL.md` — primary consumer of the company-data cache.

---

## Cloud upload (mandatory)

The finished `qualified.csv` (and `borderline.csv` when produced) MUST be uploaded to the central Supabase list store before the run ends — a list that only lives on this machine isn't done. Run:

`python3 ~/.claude/skills/_shared/list_upload.py <final.csv> --name "<descriptive list name>" --client "<Client>" [--folder "<Theme>"] --source-skill lilly-prospeo-list-builder --brief "<one-line brief>" --owner "<who asked>"`

Then show the returned `https://navreo-signals.onrender.com/app/lists.html#<id>` link to the user — that link is part of the deliverable, alongside the CSV.

Folder rules: `--client` = the client named in the brief (internal/Navreo pulls → `Navreo`); add `--folder` ONLY when the brief names a campaign theme or segment (e.g. client `Amplifyy`, folder `Beauty`); never deeper than two levels. Re-runs with the same name+client replace that list's rows in place (safe).
