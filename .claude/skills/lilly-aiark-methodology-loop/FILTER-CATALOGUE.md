# AI Ark Filter Catalogue — mined 2026-07-10 (Step 1 output)

Sources: `ark://guide/company-search`, `ark://guide/people-search`, free `industry_search`/`location_search` lookups, diffed against `lilly-tam-methodology-lab/PLAYBOOK-aiark.md`.

## Transport rule (the single most important finding, re-confirmed)

- **MCP tool = FLAT params only.** Passing the guide's nested `requestBody` through the MCP tool is SILENTLY IGNORED while still billing. Company discovery runs on the MCP flat params below.
- **REST = nested shapes.** `POST https://api.ai-ark.com/api/developer-portal/v1/people` (`X-TOKEN: $AI_ARK_API_KEY`, keys in `~/.navreo-keys.env`) accepts the nested guide schema — required for `contact.experience.current.title` (DM finding). Rate limits 5/s, 300/min.
- Billing ≈ 1 credit per row returned on BOTH transports. `size:1` for counts. `totalElements` in the response is the count field.

## Company filters (MCP flat params — validated path)

| Filter | Type | Validated example | Notes |
|---|---|---|---|
| `industry` | enum (921 values) | `software development`, `marketing`, `construction`, `veterinary`, `staffing and recruiting`, `logistics`, `accounting`, `renewable energy` | Validate every value via free `industry_search` first. Matches ANY tag in `industries[]` → over-counts; never use alone. |
| `industries` | free-text advanced | `IT asset disposition` | Only when no enum fits. |
| `excludeIndustry` | enum | `marketing automation` | Same enum set. |
| `location` | enum (5,101 values) | `United States`, `United Kingdom`, `Germany`, `Netherlands`, `Australia`, `Canada` | Single-level tokens; continent = `Northern America`. Free `location_search` validates. |
| `excludeLocation` | enum | `India` | |
| `minEmployees` / `maxEmployees` | int | `11` / `200` | Works on `staff.total`; `minEmployees:1` silently drops unknown-headcount micro-firms. |
| `keyword` + `keywordMode` + `keywordSources` | free text + enums | `keyword:"accounting,bookkeeping,tax"`, `keywordMode:WORD`, `keywordSources:"NAME,KEYWORD"` | WORKS via MCP (validated 2026-05-25, qwintiq run: 10,478→6,731 with junk removed). REST keyword is tier-gated 401. Sources: NAME, KEYWORD, SEO, DESCRIPTION, INDUSTRY. Company `keywords[]` self-ID is the strongest precision lever. |
| `naics` / `sic` | code string | `naics:"541511"` | Free-text codes; layer for precision. |
| `productAndServices` | free-text advanced | `cloud computing` | |
| `type` / `excludeType` | enum | `excludeType:"NON_PROFIT,EDUCATIONAL,GOVERNMENT_AGENCY"` | CONFLICTING evidence: UPPERCASE worked 2026-05-25; lab got 400 on 2026-07-09. Treat as unreliable — try UPPERCASE once, on 400 drop it and filter type client-side. Barely helps anyway (~65 rows of 10K). |
| `minFoundedYear` / `maxFoundedYear` | int | `2015` | |
| `minRevenue` / `maxRevenue` | int USD | `1000000` | |
| `fundingType`, `min/maxTotalFunding`, `min/maxLastFunding`, `min/maxFundingDurationYears`, `fundingNotReceived` | enums/int | `fundingType:"series_a"` | Funding filters confirmed working elsewhere (Prospeo-dead-filters memory: AI Ark funding works). |
| `technology` / `excludeTechnology` | enum (`ark://reference/technologies`) | `shopify` | Useful for tech-defined briefs. |
| `metricEmployee*` / `metricGrowth*` | int + dept CSV + timeframe | growth ≥10% over `twelve` in `sales` | Head-count/growth momentum filters — NEW vs playbook (documented but never validated; probe before relying). |
| `geoLat/geoLng/geoRadius/geoUnit` | numbers | 51.5074/-0.1278/50/km | City-radius targeting — NEW vs playbook. |
| `language` / `excludeLanguage` | enum | `english` | |
| `socialMedia` | enum UPPERCASE | `LINKEDIN` | Proxy for "has LinkedIn page". |
| `lookalike` | — | — | **BANNED. Never pass.** |

Response fields that matter: `totalElements` (display behaviour: treat ≥10,000 as "10K+, may be capped"), `link.domain_ltd` (canonical domain), `location.headquarter.country`, `summary.staff.total` (+ `staff.range` unreliable), `industries[]`, `keywords[]`, `type`.

Head-of-list bias: results are relevance-sorted; big brands/networks dominate page 0. Judge population on a deep page (`page` ≈ 3000/size when the pool allows, else last page).

## People filters (DM finding — REST nested only)

Canonical DM shape (the ONLY approved role-precise path):

```json
{ "page": 0, "size": 25,
  "account": { "domain": { "any": { "include": ["target1.com","target2.com"] } } },
  "contact": { "experience": { "current": { "title": { "any": { "include": {
      "mode": "SMART",
      "content": ["CEO","Chief Executive Officer","Founder","Co-Founder","Owner","Managing Director","President","Head of Sales","VP of Sales","Sales Director","Chief Revenue Officer","Head of Business Development"]
  } } } } } } }
```

- `experience.current` = active positions (use this, not `latest`).
- **Mandatory company-ID join post-check:** keep a person only if a current position (`date.end == null`) at `company.id == person.company.id` matches the role set. Strip `vice president`/`vp` before testing `president`; hard-reject `assistant|executive to|to ceo|recruitment|coordinator|intern|specialist|analyst|associate|representative|shop owner`; VPs qualify only for Sales/BD/CRO/CSO. Dedup by (name, domain).
- Flat `title`/`seniority` (MCP or REST top-level) match WHOLE career history — banned for role briefs (~33% precision).
- Supplementary contact filters available nested: `seniority` enum (c_suite, vp, director, head, owner, founder, partner…), `departmentAndFunction` enum, `location`, `profileBadge`, `skill`, `certification`, education (`school/degree/fieldOfStudy`), duration filters (`currentJob`/`currentCompany`/`total` min/max years — NEW vs playbook, useful for "in seat ≥1 year"), and the full `account.*` block (so DM search can carry the company filter stack directly — company-brief → people in ONE call when domains aren't fixed).

## Diff vs PLAYBOOK-aiark.md (what's new)

1. Playbook's "keyword is tier-gated 401" is REST-only — the MCP flat `keyword` works and is the precision workhorse.
2. Metric (employee-change/growth), geo-radius, education, and duration filters were never in the playbook.
3. People search accepts the full `account.*` filter block — a brief-level DM pull (no fixed domain list) is possible: company filters + current-title in one nested REST call.
4. `type`/`excludeType` evidence conflicts (UPPERCASE-works vs 400) — downgraded to "try once, fall back to client-side".
5. Everything lookalike: historical only, banned.
