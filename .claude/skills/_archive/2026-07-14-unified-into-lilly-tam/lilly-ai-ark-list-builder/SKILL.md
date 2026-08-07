---
name: lilly-ai-ark-list-builder
description: "AI Ark FILTERS-ONLY company list builder (lookalike remains PERMANENTLY BANNED, user 2026-07-10). Runs the methodology PROVEN on 20 briefs 2026-07-10 (17/20 ≥70% accuracy, ~939 credits — see lilly-aiark-methodology-loop/RESULTS.md): altitude-matched filter stacks (broad = industry enums + excludeIndustry + self-ID keywords on NAME,KEYWORD,DESCRIPTION; niche = self-ID phrases on NAME,KEYWORD only), size:10 scored gate, deep-page blend, dual-number TAM. Use as lilly-tam-mapper Stage 3, or whenever the user wants AI Ark company discovery, an AI Ark TAM count, or cross-index expansion beyond Ocean+Prospeo. Trigger on 'AI Ark list', 'AI Ark TAM', 'expand via AI Ark', 'cross-check against AI Ark'."
---

# Lilly AI Ark List Builder — FILTERS ONLY

## ✅ PROVEN RECIPE (2026-07-10 methodology loop — supersedes everything below; `lookalike` still BANNED)

Validated on 20 briefs broad→ultra-niche: 17/20 hit ≥70% scored accuracy. Full evidence: `~/.claude/skills/lilly-aiark-methodology-loop/{METHODOLOGY,RESULTS}.md`.

**Transport:** MCP flat params only (`mcp__ai-ark__company_search`, or JSON-RPC `POST /v1/mcp?token=…` with `Accept: application/json, text/event-stream`). Nested requestBody via MCP is silently ignored while billing. ~1 credit per ROW returned.

**Shape by brief altitude:**
- **Broad category** (expect ≥10K): `industry` enums (validate free via `industry_search`, pick 2-4) + `excludeIndustry` naming the observed leak + keyword self-ID synonyms `keywordMode:WORD`, `keywordSources:"NAME,KEYWORD,DESCRIPTION"` + `location` + `minEmployees:11,maxEmployees:200`. (Measured: B2B SaaS US 60%→90% by adding excludeIndustry + DESCRIPTION-widened keywords, count held at 14.7K.)
- **Niche/service vertical**: keyword self-ID PHRASES on `keywordSources:"NAME,KEYWORD"` **only — DESCRIPTION poisons niche gates** (client namedrops/capability mentions: measured 10-40% with, 70-80% without) + optional industry enums + location/size (min 5 on ultra-niche).
- Keywords say what the company IS ("roofing contractor", "SAP beratung", "Amazon agency") — never capability tags ("Amazon marketing", "solar", "drone services"). Add local-language phrases on non-English geos ("pistas de padel", "spedition"). Comma values are OR'd.

**Gate sequence (per shape):**
1. `size:10` page 0 (~10 cr; it returns `totalElements` — separate `size:1` only when you might discard on count alone). Score via `lilly-lead-score`. <50% hard abort; <70% tighten ONE layer, re-gate; max 3 iterations.
2. Pool ≥100: ONE deep `size:10` page at ~70% depth, **page ≤950 hard cap** (offset limit ~10K; deeper pages return 0 rows). Pool <100 = census, skip.
3. **Blended accuracy = mean(gate, deep)** — the head is brand-sorted and flatters broad pools (measured 90→60 at depth).

**TAM output — always TWO numbers:** extraction pool = tight-shape `totalElements` × blended accuracy; category estimate = broad-shape count × its measured precision. Flag counts ≥10,000 as display-capped floors.

**Out-of-scope brief shapes (route away, don't iterate):** brand/product briefs (→ Prospeo B2C / Ocean `ecommerce:true`; AI Ark ceiling ~40-50%); capability-flooded niches (drones-as-surveyor-tool, reefer-as-carrier-capability → census + `lilly-lead-score` triage); micro-pools <20 true cos (census + triage).

Excludes: no `excludeDomain` on MCP — cumulative-exclude filtering is client-side, always.

## ⚡ 2026-07-14 RECALL-MAX ADDENDUM (30-brief lab — layers on the proven recipe above; evidence `lilly-tam-recall-lab/RESULTS-30.md`)

- **Shape selection is now recall-max:** among shapes that hold ≥70%, keep the BIGGEST `totalElements` — start from the WIDEST defensible synonym set + enum stack and only tighten when the gate fails. Record the failed wider variant as the maximality proof. (Old habit of stopping at the first clean tight shape left 3-6× volume on the table — e.g. GC US 30,207 @ 73.3%, Law US 20,151 @ 93.3% with wide sets.)
- **excludeIndustry only names an OBSERVED leak** — never speculative (excludes reshuffle rankings).
- **Transport gotcha:** JSON-RPC responses are PLAIN JSON, not SSE — never pipe through an SSE `data:` filter (45 credits were billed into empty files that way). Company rows: `.result.content[0].text` → JSON with `totalElements` + `.content[]`, name/description under `.summary`, domain under `.link.domain`.
- **Brand/product briefs stay routed away from AI Ark** (~40-50% ceiling confirmed again) — but they are NOT dead briefs: Prospeo's E-commerce subtype ladder measured 60,769 @ 80%. Route there.
- **Provider-swamp briefs** (US MSPs, US management consulting): staffing/IT-consulting own the vocabulary here too (best 33% after retunes) — route to lead-score triage, don't iterate.
- **Never request emails/contact enrichment from this skill** (user 2026-07-13) — company fields only; `email_finder`/`export_single` are out of scope.
- Index drift is real (ITAD/roofing prior shapes didn't reproduce at prior size) — treat every historical count as stale until a fresh gate confirms it.

---

## ⛔ Historical: lookalike ban 2026-07-10

**Never use AI Ark lookalikes.** Everything below is the pre-2026-07-10 document retained for reference; where it conflicts with the proven recipe above, the recipe wins.

---

## Purpose

Expand an existing company list by finding MORE lookalike companies via **AI Ark's `company_search` MCP tool**. Ocean, Prospeo, and AI Ark all index different company sets — running all three surfaces companies none would on its own.

The trick: AI Ark's `company_search` accepts:
- `lookalike` (CSV of LinkedIn URLs or domains) — **native LinkedIn-style lookalike** (similar to Ocean.io)
- Flat account filters (`industry`, `location`, `minEmployees`/`maxEmployees`, `keyword`, `technology`, etc.) — for filter-driven discovery
- `excludeIndustry` / `excludeLocation` / `excludeTechnology` — server-side excludes (but **no excludeDomain** — source-TAM exclusion happens client-side after the call)

This skill complements `lilly-prospeo-list-builder` — both find lookalikes, but pull from different indexes. Run them in sequence to maximise coverage.

**Why the MCP company_search over the REST `/v1/companies` endpoint:**
- Typed schema: the MCP rejects invalid params at the boundary, so there is no "basic-tier silently drops filters" failure mode — the entire prefix/diagnostic check the prior REST version needed is **obsolete**.
- Enum validation via MCP resources (`ark://reference/industries`, `ark://reference/locations`, `ark://reference/technologies`, `ark://reference/languages`) rather than scraping docs.
- Flatter param shape (`industry` CSV, `minEmployees`/`maxEmployees` ints) — no nested `account.*.any.{include,exclude}` JSON to assemble.

**The MCP wraps the REST backend.** Response shape and capability set are identical to the REST `/v1/companies` endpoint — see "Response shape" and "Related REST endpoints" below for the canonical field names. The MCP is a flatter parameter surface; the JSON it returns is the same thing the REST returns.

**One genuine REST-only capability:** the REST endpoint exposes `account.domain.any.exclude` (server-side domain blocklist, capped at ~300 domains in observed practice). The MCP `company_search` does NOT expose `excludeDomain` as a parameter. Source-TAM exclusion on the MCP path happens client-side after the call. If you need server-side exclude of >100s of domains, fall back to REST for that one capability.

---

## When to Use

Trigger when the user wants to:
- Expand an existing TAM beyond Ocean + Prospeo
- Cross-check Prospeo and Ocean results against AI Ark's index
- Run a 2nd or 3rd-pass lookalike using AI Ark's separate company database
- Add to a live prospect list with newly-surfaced companies AI Ark indexes that the others missed

Accept input forms:
- "Expand the TAM via AI Ark"
- "Find more Amazon agencies that AI Ark has but Prospeo doesn't"
- "Cross-check this list against AI Ark"
- "Lookalike to these companies on AI Ark too"
- Direct hand-off from `lilly-tam-mapper` Stage 3 or `lilly-decision-maker-finder` Step 0 (optional list-expansion before DM enrichment)

---

## MCP access

- **MCP server:** `ai-ark` — exposes `company_search`, `people_search`, `email_finder`, `email_finder_results`, `export_single`, `mobile_phone_finder`, `reverse_people_lookup`, `personality_analysis`.
- **Tool name in Claude Code:** `mcp__ai-ark__company_search` (the only one this skill calls).
- **Server URL:** `https://api.ai-ark.com/v1/mcp?token=<AI_ARK_API_KEY>` — auth is in the URL token, not a header. Env-var substitution does NOT expand inside the URL string in `~/.claude.json`, so the literal key gets stored there (file is mode 600 — same handling as the user's other remote MCPs).
- **Configured via the `mcp-remote` bridge** (the user's existing pattern in `~/.claude.json` user-scope). The relevant entry looks like:

  ```json
  "ai-ark": {
    "command": "npx",
    "args": ["-y", "mcp-remote@latest",
             "https://api.ai-ark.com/v1/mcp?token=<KEY>"]
  }
  ```

  `mcp-remote` bridges the remote streamable-HTTP server through stdio so Claude Code's stdio loader can talk to it.
- **Pre-flight:** if `mcp__ai-ark__company_search` is not in the available tool list, the MCP server is not loaded. Either: (a) the entry is missing — add it to `~/.claude.json` under `mcpServers.ai-ark` matching the shape above (the `claude mcp add` CLI is one option, but the user's path is direct config edit since the `claude` binary isn't on their shell PATH); (b) entry exists but Claude Code wasn't restarted after the edit — full quit + reopen required, not just a new conversation; (c) `npx` / Node aren't installed — `node` and `npm` must be on PATH for the `mcp-remote` bridge to spawn. Fall back to `lilly-prospeo-list-builder` if any of these can't be resolved this run.
- **Cost:** AI Ark's billing model for `company_search` is **not documented in the public spec**. Probe at the start of every run by checking the AI Ark dashboard before and after the first `size:5` call — that's the per-page or per-company cost. Update this skill if you learn the model.

---

## The 5-step workflow

### Step 1 — Input

Take from the user (or the calling skill):
- An existing company list — these split into:
  - **Up to ~5 most-representative seeds** → become the `lookalike` CSV (cap unverified; start with 5, back off if the call errors)
  - **Everything else** → becomes the client-side post-processing exclude set
- Brief criteria — what defines a target company (industry, geography, size, technology, keyword)
- Stop precision (default = **7/10 qualified**)
- Page size for qualification batches (default = 25 — `company_search` caps `size` at 100, but qualify only the first 10 unique results from each page)

### Step 1.5 — *(MANDATORY PRE-FLIGHT)* Resolve enum values via MCP resources

Before firing `company_search`, resolve every `industry` / `location` / `technology` value the brief implies. AI Ark's enums are taxonomy-strict — invalid values are rejected.

Read these MCP resources to validate:
- `ark://reference/industries` — 921 canonical industry values
- `ark://reference/locations` — hierarchical (continent / country / state) — pass leaf names only, not the combined path. Note: continent is `Northern America`, NOT `North America`.
- `ark://reference/technologies` — tech-stack keys (use the `key` field exactly)
- `ark://reference/languages` — language values
- `ark://guide/company-search` — full filter guide if you need parameter shape clarification

Do NOT guess values. If the user says "tech," the canonical match is typically 5-20+ industry rows — fetch them all from the resource and pass as a CSV in `industry`.

> **Note:** there is NO basic-vs-filter API-tier check on the MCP path. The typed schema rejects invalid params with a 400 — it cannot silently drop filters the way the REST endpoint did. The whole prior diagnostic-call workflow does not apply here.

### Step 2 — Build the filter

Use flat parameters on `company_search`. The MCP equivalents of the prior REST `account.*` shape:

| Brief intent | MCP parameter | Shape | Notes |
|---|---|---|---|
| Lookalike seeds | `lookalike` | CSV string of LinkedIn URLs or domains | Pick the most representative seeds. LinkedIn URLs give higher accuracy than domains. Cap unverified — start with 5; back off on error. |
| Industry | `industry` | CSV string from `ark://reference/industries` | Multiple: `"health care,software"`. Use exact enum values. |
| Industry (free-text fallback) | `industries` | string | ONLY when desired industry is missing from the enum. Prefer `industry` with enum values. |
| Country / state | `location` | CSV string from `ark://reference/locations` | Pass leaf names only — `"United States,Germany"` not `"Northern America::United States"`. |
| Headcount min | `minEmployees` | integer | Replaces bucket string `"11-50"` → use `minEmployees: 11`. |
| Headcount max | `maxEmployees` | integer | Replaces bucket string `"11-50"` → use `maxEmployees: 50`. Bucket-style ranges become integer pairs. |
| Vertical-specific keywords | `keyword` | CSV string | Multiple: `"amazon,amazon FBA,amazon seller"`. |
| Keyword mode | `keywordMode` | `SMART` (default fuzzy) / `WORD` (whole words) / `STRICT` (exact) | Use `STRICT` when the term is precise (e.g. brand names). |
| Keyword scope | `keywordSources` | CSV of `NAME,KEYWORD,SEO,DESCRIPTION,INDUSTRY` | Default = all sources. |
| Tech stack | `technology` | CSV from `ark://reference/technologies` (use `key` values) | Useful for SaaS-tooling-based ICPs. |
| Industry exclude | `excludeIndustry` | CSV | Server-side exclude. |
| Location exclude | `excludeLocation` | CSV | Server-side exclude. |
| Type exclude | `excludeType` | CSV | E.g. exclude `"educational,non_profit"`. |
| Pagination | `page` (0-based int), `size` (1-100, default 25) | integers | |

**Source-TAM exclusion (post-processing, not a parameter):**

`company_search` has no `excludeDomain` parameter. Exclude the source TAM client-side after each call:

```
fetched_results = company_search(...)
new_results = [r for r in fetched_results if r.domain not in source_tam_domains]
```

There is no 300-domain cap any more — the entire source TAM can be excluded post-fetch with no API constraint. The trade-off is paying for overlap rows that get discarded. For lookalike-driven searches against a 70M-co index this overlap is usually small; report the dedupe haircut explicitly so the user knows the net-new yield.

**MANDATORY: always layer flat filters on top of `lookalike`.** AI Ark's `lookalike` alone is too loose — it pulls cos worldwide regardless of geography, size, or relevance. Without layered filters, page 0 will surface companies in markets and headcounts way outside the brief (Pakistan, India, Bangladesh micro-shops alongside US enterprises). Always include at minimum:
- `location` — target countries
- `minEmployees` / `maxEmployees` — target size range
- `keyword` — vertical-specific terms

The lookalike is a *seed* for clustering; the filters are the *gate* that defines the actual brief. Treat `lookalike` as 30% of the targeting and the filters as the remaining 70%. **Never run with `lookalike` alone.**

**Example call (Amazon-agencies brief):**

```
mcp__ai-ark__company_search({
  page: 0,
  size: 25,
  lookalike: "seed1.com,seed2.com,seed3.com,seed4.com,seed5.com",
  industry: "Marketing & Advertising,E-commerce",
  location: "United States,United Kingdom",
  minEmployees: 11,
  maxEmployees: 200,
  keyword: "amazon,amazon FBA,amazon seller",
  keywordMode: "SMART"
})
```

### Step 3 — Run page-1 + qualify (the iteration loop)

1. Note credit balance via the AI Ark dashboard (no public balance endpoint) **before** the first call.
2. Fire page 0 with `size: 25` (or 100 if cost-per-call is flat — probe to confirm).
3. Note credit balance **after** → cost = `before − after` for one page (likely per-company or per-page).
4. **Filter out source-TAM domains client-side** by `link.domain_ltd` (the canonical bare-domain field — `link.domain` may be a full URL, do NOT match on it).
5. Dedupe remaining results by `link.domain_ltd`.
6. **Surface the TAM headline FIRST** — before qualification rows, report:
   - `totalElements` (total matches AI Ark's index reports — surface even if it caps; see Step "Confirmed quirks")
   - Realistic qualified expansion (`totalElements × precision × (1 − dedupe_haircut)`)
   - Combined source TAM + Prospeo expansion + AI Ark expansion (after merge dedupe)
   - Per-page credit cost (just measured)
7. Take the first 10 unique companies and qualify each:
   - Read `summary.description`, `summary.overview`, `industries[]`, `keywords[]` — those are the qualification-relevant fields.
   - Cross-reference `summary.staff.range.{start,end}` against the brief's headcount band, `location.headquarter.country` against the geography filter, `summary.industry` against the brief.
   - Tag each as **qualified** (matches brief) or **off** (doesn't).
8. **If 7+/10 qualified** → continue. Run page 1, dedupe, qualify, repeat.
9. **If <7/10 qualified** → stop. The filter is too loose. Tighten by:
   - Swapping in tighter `lookalike` seeds
   - Narrowing `keyword` to a more specific term and/or switching `keywordMode` to `WORD` or `STRICT`
   - Tightening the `industry` enum CSV
   - Restricting `minEmployees`/`maxEmployees` band
   - Restart from page 0 with the tighter filter.

### Step 3.4 — *(HARD ABORT GATE)* 50% sample-fit before paginating

After page 0 + WebFetch verification of the first 10 unique-domain candidates, calculate the **on-brief rate**.

- **If ≥50% on-brief** (5+ of 10 verified ICP) → continue to Step 3.5 (verify rest), then paginate per the 7/10 continuation rule
- **If <50% on-brief** (4 or fewer of 10 verified ICP) → **HARD ABORT this search entirely.** Do NOT paginate further. The lookalike+filter pool is fundamentally wrong — full extraction would burn per-page credits on a list where the majority is off-brief, creating massive deliverable cleanup waste downstream.

**What to do on abort:**
1. Report the failure to the user with the actual on-brief rate (e.g., "3/10 verified — pool is 70% off-brief, aborting")
2. Diagnose: are the `lookalike` seeds too generic? Is `keyword` matching too loosely (try `keywordMode: "WORD"` or `"STRICT"`)? Is the country pool too small?
3. Either redesign the filter from scratch with different seeds / tighter keywords, OR conclude that this brief × this market doesn't have a viable AI Ark search and move on (don't force it).

**Why 50% (not 70%):** 70%/7-of-10 is for *iteration continuation* — assumes search is fundamentally sound. 50% is a *fitness gate* — if even half the pool isn't ICP, the search itself is wrong.

### Step 3.45 — *(MANDATORY)* Sample-audit pause: explicit user go-ahead before the full pull

Passing the 50% fitness gate (Step 3.4) and the 7/10 continuation rule is necessary but NOT a licence to auto-paginate the full list — especially here, where AI Ark bills per result returned. **Always present the verified sample to the user and pause for an explicit go-ahead before committing to full pagination / the rest of the spend** — regardless of how clean the sample looks:

1. Show the sample audit: on-brief rate, the qualified / borderline / off-brief split, and example companies per bucket.
2. **Wait for explicit user go-ahead before the full pull.** The user sees what actually surfaced on the first sample (~100), then signs off — or retunes the lookalike seeds / filters and re-samples — before the haystack is paginated. Never silently auto-continue.

This is the company-level half of the gate. When this list feeds a decision-maker pull, the **title-function audit also runs at the DM step**: `lilly-decision-maker-finder` Step 2.5 pulls ~100 DMs, classifies their titles via `lilly-list-audit`, and pauses for go-ahead before any enrichment spend.

### Step 3.5 — *(MANDATORY)* Verify each candidate via WebFetch before enrichment

**Description-field keyword matching is NOT real qualification.** AI Ark's description can mention "label" or "print" while the company is actually a media holding, copy shop, POS display manufacturer, or food packaging firm — all off-brief.

**For every shortlisted candidate, before passing to DM enrichment:**
1. WebFetch the company's website (use the response's domain field) with a brief-specific qualification prompt: "Is this company [brief criteria]? Or are they something else (e.g., commercial printing, media/news, copy shop, POS displays, decorative packaging, food packaging)? Describe in one sentence what they actually do."
2. Mark each as ✅ on-brief / ⚠️ borderline / ❌ off-brief
3. Drop ❌ off-brief cos. Surface ⚠️ borderline cos to the user with the actual website description for a judgment call.
4. Only pass ✅ confirmed-on-brief cos to the next stage.

**Cost rationale:** WebFetch is free; AI Ark `people_search` / `email_finder` bills per DM returned. Skipping verification means burning per-DM credits on an off-brief co's DMs that get thrown away.

**Calibration:** keyword-matched candidate pools have a ~60-70% off-brief rate when the brief involves common words like "label", "print", "tag" (which appear across countless industries). Always verify.

### Step 4 — Track output

For each qualified company, write to a CSV row, mapping from the response shape:

| CSV column | Response field |
|---|---|
| `domain` | `link.domain_ltd` (canonical bare domain — NOT `link.domain`, which can be a full URL) |
| `company_name` | `summary.name` |
| `primary_country` | `location.headquarter.country` |
| `employee_count` | `summary.staff.total` (when present) or `summary.staff.range.start`–`summary.staff.range.end` |
| `industry` | `summary.industry` (single) plus `industries[]` (array of all tagged industries — useful for downstream filtering) |
| `description` | `summary.description` (or `summary.overview` if present and shorter) |
| `linkedin` | `link.linkedin` |
| `source` | literal `"ai_ark_lookalike"` |
| `qualification_round` | the page number on which this co was qualified |

`source = "ai_ark_lookalike"` to distinguish from Ocean / Prospeo rows when the lists merge later.

If chained from `lilly-ocean-tam-builder`, append to the existing TAM CSV with the same column structure as Ocean / Prospeo rows so they merge cleanly.

### Step 5 — Hand off

**When chained from `lilly-tam-mapper` (Stage 3):**
- Updated TAM CSV (Ocean + Prospeo + AI Ark dedupe-merged), with `source` column distinguishing each origin
- Iteration log: pages run, precision per page, credits spent, when filter was tightened
- Surfaced new domains for downstream `lilly-decision-maker-finder`

**When chained from `lilly-decision-maker-finder` (Step 0):**
- Newly-surfaced domain list (deduped against the input domain set)
- Same iteration log
- Caller (`lilly-decision-maker-finder`) merges these onto its input domain list before running Step 1 (Prospeo `/search-person` for DM discovery)

**Standalone:**
- Plain CSV of newly-surfaced domains tagged `ai_ark_lookalike` + iteration log

---

## Cache writes (mandatory after every successful page)

After each `/v1/companies` response that returns ≥1 result, write each company object to the cache so downstream skills (most notably `lilly-icebreaker`, but also future consumers) can read AI Ark's company-level data without paying for a re-fetch.

**Preferred write path (dual-write):** `navreo_db.put_enrichment("company", domain, "ai_ark", company_obj, endpoint="/v1/companies", source_skill="lilly-ai-ark-list-builder")` from the shared helper `~/.claude/skills/_shared/navreo_db.py` — writes the Supabase central cache AND the local mirror below in one call, fails soft to local-only on outage. Also check `navreo_db.get_enrichment("company", domain, provider="ai_ark")` before any paid re-fetch — the central cache may hold entries this machine never fetched.

**Ledger every paid call:** after each billed page, `navreo_db.log_provider_usage("ai_ark", <credits>, endpoint="/v1/companies", source_id="lilly-ai-ark-list-builder")` — this is the cost-audit trail, separate from the cache write above.

**Layout:** `~/.navreo-cache/ai_ark/companies/{canonical-domain}.json`

**Per-file envelope:**
```json
{
  "fetched_at": "2026-05-05T17:25:00Z",
  "endpoint": "/v1/companies",
  "source_skill": "lilly-ai-ark-list-builder",
  "data": { ...the raw AI Ark company object from results[i]... }
}
```

**Write logic** (per company in the response's results array):

```bash
NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
DOMAIN=$(echo "$company_domain" | tr '[:upper:]' '[:lower:]' | sed -E 's|^https?://(www\.)?||;s|/.*$||')

jq -n --argjson co "$company_obj" --arg now "$NOW" \
  '{fetched_at: $now, endpoint: "/v1/companies", source_skill: "lilly-ai-ark-list-builder", data: $co}' \
  > ~/.navreo-cache/ai_ark/companies/${DOMAIN}.json
```

In practice, run as a single jq pipeline over the response — one file per company.

### Cache rules

1. **Last-write-wins** per domain WITHIN AI Ark. Provider trees are isolated (Prospeo writes do NOT touch this tree), so AI Ark and Prospeo can both have a cache file for the same company — the consumer decides which to read first.
2. **Canonical domain key.** Lowercase, strip protocol + `www.`, strip trailing slash and path.
3. **Schema is AI Ark's, not Prospeo's.** AI Ark uses `account.*` / `contact.*` nesting; consumers (e.g. `lilly-icebreaker`) handle the schema mismatch — typically by preferring Prospeo's cache when both exist for the same domain. Don't try to normalise into Prospeo shape at write-time.
4. **Don't write empty data.** Skip `data: null` / `data: {}` rows.
5. **Failure-tolerant.** Cache writes never block the qualification workflow.

---

## Reference: filter values discovery

AI Ark's industry/location/headcount enums are taxonomy-strict. **Validate before firing.**

**Resolve via MCP resources** (preferred over scraping docs):
- `ark://reference/industries` — 921 canonical industry values
- `ark://reference/locations` — hierarchical continent/country/state enum
- `ark://reference/technologies` — each entry has a `key` field; use those exactly
- `ark://reference/languages` — language values
- `ark://guide/company-search` — full filter guide

`headcount` no longer uses bucket strings — it is two integer parameters (`minEmployees`, `maxEmployees`). Map common LinkedIn buckets to int pairs: 1-10 → (1, 10), 11-50 → (11, 50), 51-200 → (51, 200), 201-500 → (201, 500), 501-1000 → (501, 1000), 1001-5000 → (1001, 5000), 5001-10000 → (5001, 10000), 10001+ → (10001, omitted).

---

## Cost calibration (probe before committing)

`company_search`'s billing model is **not in the public docs**. Probe at the start of every run:

1. Note `current_credits` from the AI Ark dashboard.
2. Fire one tiny `size:5` call to `company_search` with valid filters.
3. Note new `current_credits`.
4. **Cost per page = before − after**

Once you know the per-page cost, calibrate the full run. Typical AI Ark cost models seen elsewhere:
- Per-DM (people endpoint): 1 credit per person returned
- Per-company (companies endpoint, hypothesis): 1 credit per company returned, OR flat per-page

If full pagination would burn >100 credits, cap budget upfront — **don't paginate the entire haystack** without confirming with the user.

---

## Confirmed MCP quirks

- **No `excludeDomain` parameter.** Source-TAM exclusion happens client-side after each call. The 300-domain cap from the REST endpoint no longer applies.
- **`industry`/`location`/`technology` are CSV strings**, not arrays. Multiple values: `"health care,software"`. The MCP description warns: "For multiple values use comma-separated strings in a SINGLE call (do NOT make multiple calls)."
- **`location` enum is hierarchical** — continent / country / state. Pass leaf names only. Continent for North America is `Northern America`, NOT `North America`.
- **`headcount` is integer pairs** (`minEmployees`/`maxEmployees`), not bucket strings. Translate from LinkedIn buckets via the table in "Reference: filter values discovery."
- **`industry_search` / `location_search` / `technology_search` tools are referenced in `company_search`'s description but are NOT exposed by the MCP server** as of 2026-05-04. The only enum-resolution path is via MCP resources (`ark://reference/...`). If the description ever references them, ignore — read the resources directly.
- **`size` cap raised to 100** (REST default was 25). Larger pages are fine if cost-per-page is flat, but per-result billing makes 25 the safer default until cost is probed.
- **No tier-silent-drop risk.** The MCP rejects invalid params with a 400; it cannot silently drop filters and return the full index the way the REST basic-tier key did. The diagnostic-call workflow from prior versions of this skill does not apply.

## Guardrails

1. **Always layer flat filters on top of `lookalike`.** Never run with lookalike alone — too loose, surfaces cos worldwide regardless of brief. At minimum: `location`, `minEmployees`/`maxEmployees`, `keyword`.
2. **Always exclude the source TAM domains client-side, by `link.domain_ltd`.** Pull the most representative seeds (~5) for `lookalike`, post-process-filter the rest from each response. NEVER match on `link.domain` — it can be a full URL. Report the dedupe haircut explicitly so the user knows the net-new yield is approximate. (If the source TAM is huge and per-result billing makes overlap painful, fall back to REST `/v1/companies` with `account.domain.any.exclude` — capped at ~300 domains in observed practice.)
3. **Skip people-search / contact filters entirely.** This skill is for company discovery via `company_search`. Use `lilly-decision-maker-finder` for DM discovery (which uses `people_search` + Prospeo).
4. **Always probe credit cost before paginating.** AI Ark billing for `company_search` is not documented — the first call's credit-delta tells you. Don't burn 100+ credits without knowing the per-page cost.
5. **Validate enum values via MCP resources.** AI Ark's enums reject free text — read `ark://reference/...` before firing. The free-text `industries` parameter is a fallback only.
6. **`lookalike` cap is unverified.** Start with ~5 seeds (matches REST behaviour); back off on error. Pick the most representative.
7. **Hard abort at <50% sample-fit.** After page 0 + WebFetch of first 10 unique cos, if fewer than 5 are on-brief ICP → stop pulling, don't paginate. Search is fundamentally wrong; tightening won't recover. **Stop at 7/10 precision** for iteration continuation when the search IS sound.
8. **Lead with the TAM headline, not the qualification table.** The first thing in the page-1 response should be `totalElements`, the realistic qualified expansion, and the per-page credit cost. Qualification rows are supporting evidence — the headline number is what the user needs to make a budget decision.
9. **Source-tag every row.** `source = "ai_ark_lookalike"` so the merged TAM is traceable.
10. **Never use Ocean people endpoints** (banned per `feedback_no_ocean_people_search`).
11. **Run AFTER `lilly-prospeo-list-builder`** when both are needed — Prospeo is flat 1 credit per page (cheap), so test there first; AI Ark is per-call billing of unknown-per-page cost (likely more expensive).
12. **If MCP not configured, fall back or set up.** If `mcp__ai-ark__company_search` isn't in the tool list, the server isn't loaded. Add the `ai-ark` entry to `~/.claude.json` under `mcpServers` using the `mcp-remote` bridge shape shown in "MCP access" above, then full-quit + reopen Claude Code. If the user can't restart, fall back to `lilly-prospeo-list-builder` for this run.
13. **Cache writes are mandatory** (see "Cache writes" section). Every successful `company_search` page writes per-company slices to `~/.navreo-cache/ai_ark/companies/`. Provider-isolated tree (does not collide with Prospeo's). Downstream consumers (`lilly-icebreaker` reads AI Ark cache only when no Prospeo cache exists for that domain) skip re-paying when the data is fresh. Skipping the writes silently breaks the cache contract.
14. **Sample-audit pause before the full pull (MANDATORY, Step 3.45).** Passing the 50% fitness gate is not a licence to auto-paginate — always present the verified sample and pause for explicit user go-ahead before full pagination, regardless of how clean it looks (doubly important here: AI Ark bills per result). When the list feeds a DM pull, the title-audit gate at `lilly-decision-maker-finder` Step 2.5 (pull ~100 DMs → classify via `lilly-list-audit` → pause) applies before enrichment.

---

## Quick reference

| Need | MCP target | Notes |
|---|---|---|
| Find lookalike companies | `mcp__ai-ark__company_search` | `lookalike` CSV + flat account filters; cost TBD per run (probe) |
| Validate industry enum | resource `ark://reference/industries` | 921 entries |
| Validate location enum | resource `ark://reference/locations` | Hierarchical; pass leaf names only |
| Validate technology enum | resource `ark://reference/technologies` | Use the `key` field exactly |
| Validate language enum | resource `ark://reference/languages` | |
| Filter shape reference | resource `ark://guide/company-search` | Full filter guide |
| Check AI Ark balance | AI Ark dashboard (web) | No public balance endpoint on the MCP |
| **Cache write (after every page)** | `~/.navreo-cache/ai_ark/companies/{domain}.json` | free, mandatory per rule #13 |

See also:
- `lilly-prospeo-list-builder/SKILL.md` — the parallel skill for Prospeo's `/search-person` lookalike. Run it FIRST (cheaper); chain this skill after to fill the gap.
- `lilly-decision-maker-finder/SKILL.md` — for DM discovery, uses Prospeo first then AI Ark `people_search` as fallback (separate from this skill, which is company-only).
- `lilly-icebreaker/SKILL.md` — secondary consumer of the AI Ark company cache (Prospeo cache preferred, AI Ark fallback).
- `feedback_prospeo_before_aiark.md` — for DM discovery, Prospeo-first is the canonical rule due to per-page vs per-DM billing. The same logic applies for company discovery: probe Prospeo first, then AI Ark.

---

## Response shape (canonical fields)

The MCP wraps the REST `/v1/companies` endpoint, so the response JSON is identical to what the REST docs publish. Top-level shape:

```
{
  "content": [ <Company>, ... ],
  "totalElements": <int>,        // total matches across all pages
  "totalPages": <int>,
  "size": <int>,                 // page size
  "number": <int>,               // 0-based page number
  "numberOfElements": <int>,     // count in this page
  "first": <bool>, "last": <bool>,
  "pageable": { "pageNumber", "pageSize", "offset", ... }
}
```

Per-company `<Company>` fields actually used by this skill:

| Path | Use |
|---|---|
| `id` | AI-Ark UUID; pass to other AI Ark tools (e.g. `people_search`) for cross-lookup |
| `summary.name` | Company name (CSV `company_name`) |
| `summary.legal_name` | Legal entity (when distinct from `name`) |
| `summary.description` | Long-form description for qualification |
| `summary.overview` | Shorter overview (sometimes more useful than `description`) |
| `summary.industry` | Single primary industry tag |
| `summary.staff.total` | Exact employee count when known |
| `summary.staff.range.{start,end}` | Bucketed headcount range when exact unknown |
| `summary.founded_year` | Founding year |
| `summary.type` | `PUBLIC_COMPANY` / `PRIVATELY_HELD` / `EDUCATIONAL` / etc. |
| `link.domain_ltd` | **Canonical bare root domain — use this for dedup, exclude-matching, CSV `domain` column** |
| `link.domain` | May be a full URL — do NOT use for matching |
| `link.website` | Marketing URL |
| `link.linkedin` | LinkedIn company URL |
| `link.crunchbase`, `link.twitter` | Other social handles |
| `location.headquarter.country` | HQ country (CSV `primary_country`) |
| `location.headquarter.{state,city,street,postal_code}` | Full HQ address |
| `location.locations[]` | All known offices |
| `industries[]` | All tagged industries (richer than `summary.industry`) |
| `keywords[]` | Self-described keywords |
| `technologies[]` | Detected tech stack (each `{name,category}`) |
| `languages[]` | Operating languages |
| `last_updated` | Date of last AI Ark refresh |

When the MCP `company_search` returns, walk `result.content[]` and project these fields onto the CSV row defined in Step 4.

---

## Related REST endpoints (for cross-reference)

The AI Ark MCP exposes 8 tools. Each wraps a REST endpoint. This skill only uses `company_search`; the rest are listed here so the response shape is documented if a future workflow needs them. All are POST `application/json` with `X-TOKEN: $AI_ARK_API_KEY` header (REST) or via the MCP server URL token (MCP).

| MCP tool | REST endpoint | Use case |
|---|---|---|
| `company_search` | `/api/developer-portal/v1/companies` | THIS SKILL — find lookalike companies |
| `people_search` | `/api/developer-portal/v1/people` | Used by `lilly-decision-maker-finder` for DM discovery (fallback after Prospeo). Filters: `account.*` + `contact.*` (seniority, departmentAndFunction, title, skill, location, etc.) |
| `email_finder` | (search + email enrichment combined) | Async — returns `trackId` + `state: PENDING|DONE`. Poll via `email_finder_results`. |
| `email_finder_results` | (paginated results for a `trackId`) | Returns full people-search result with verified emails attached. |
| `export_single` | `/api/developer-portal/v1/people/export/single` | Synchronous single-person export with verified email. Input: `id` (AI Ark person UUID) OR `url` (LinkedIn URL). Returns 404 if no email found. Used for high-value targeted lookups. |
| `mobile_phone_finder` | `/api/developer-portal/v1/people/mobile-phone-finder` | Find mobile phone by `linkedin` URL OR `name + domain` pair. Returns `data: [["+1234567890"]]`. |
| `reverse_people_lookup` | `/api/developer-portal/v1/people/reverse-lookup` | Find a person by their email OR phone number. Returns full person profile. |
| `personality_analysis` | `/api/developer-portal/v1/people/analysis` | DISC + OCEAN (Big Five) + archetype + selling/hiring email-tone advice from a LinkedIn URL. Useful for `lilly-personalisation` enrichment, NOT this skill. |

**Why these are listed here:** if the user ever asks "can the skill grab phone numbers / emails / personality alongside the company list?" — the answer is "yes, via these sister tools" but it would expand scope beyond company discovery. Cross-call with `lilly-decision-maker-finder` (people + email) and `loom-research` (personality) instead.

---

## Cloud upload (mandatory)

The finished `qualified.csv` (and `borderline.csv` when produced) MUST be uploaded to the central Supabase list store before the run ends — a list that only lives on this machine isn't done. Run:

`python3 ~/.claude/skills/_shared/list_upload.py <final.csv> --name "<descriptive list name>" --client "<Client>" [--folder "<Theme>"] --source-skill lilly-ai-ark-list-builder --brief "<one-line brief>" --owner "<who asked>"`

Then show the returned `https://navreo-signals.onrender.com/app/lists.html#<id>` link to the user — that link is part of the deliverable, alongside the CSV.

Folder rules: `--client` = the client named in the brief (internal/Navreo pulls → `Navreo`); add `--folder` ONLY when the brief names a campaign theme or segment (e.g. client `Amplifyy`, folder `Beauty`); never deeper than two levels. Re-runs with the same name+client replace that list's rows in place (safe).
