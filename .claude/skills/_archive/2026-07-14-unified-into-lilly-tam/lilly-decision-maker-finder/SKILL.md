---
name: lilly-decision-maker-finder
description: "Find and enrich decision makers at a list of company domains using Prospeo (primary — search + email/phone enrichment) and AI Ark (fallback — people search for low-coverage markets). Use this skill whenever the user gives a list of company domains and wants to surface decision-maker contacts with verified emails — including the natural hand-off step after lilly-ocean-tam-builder Phase 4 or lilly-tam-mapper, populating per-country prospect lists, or filling DMs at a target account list. Trigger on phrases like 'find decision makers at these domains', 'enrich these companies with DMs', 'pull contacts for this list of cos', 'who can we contact at [domains]', 'get me emails for these companies', 'find all the decision makers in [vertical]', or as the natural follow-up after a TAM build. Optionally expands the input domain list first via `lilly-prospeo-list-builder` and/or `lilly-ai-ark-list-builder` (Prospeo first, AI Ark second) to surface additional on-brief companies the original source missed (recall-max classifier/keyword shapes — lookalike features banned) (recommended when the goal is ALL decision-makers in a vertical, not just DMs at a fixed account list). Returns a CSV with verified email + LinkedIn (and optional phone), filtered to brief-relevant titles. Before finishing the run, offers a hand-off to `lilly-email-verification` to pipe Prospeo-source emails through MillionVerifier for a second-layer deliverability check (default yes; AI-Ark-source emails skipped). Never uses Ocean.io's people endpoints (banned)."
---

# Lilly Decision-Maker Finder

## ⚡ 2026-07-14 VERIFIED DM METHOD (live-tested 6 briefs, both providers — supersedes conflicting filter guidance below; evidence `lilly-tam-recall-lab/RESULTS-30.md` DM addendum)

**Prospeo `/search-person` with the user's canonical method scored 100% title accuracy (150/150 rows). Bar for DM shapes = 90%** (user rule — titles make DM targeting easier, so hold it higher than the 70% company bar). The method:
1. **LLM long-tail title expansion** of the brief's roles (~20-35 variants; include local-language titles — "Geschäftsführer" and "Algemeen directeur" DO match as exact canonical titles, verified 100% on the DE+NL brief) → **qualify** the list, pruning anything not out-and-out close to the brief and anything below Director.
2. **Titles are ALWAYS the primary filter; seniority (Director+) is LAYERED on top. NEVER seniority or department alone** — the "seniority+department fallback for non-English pools" below is RETIRED; use local-language canonical titles instead (canonicalise via free `/search-suggestions` `{"job_title_search": ...}`).
3. **Director-and-above floor, always.** No bare "Director"/"Partner" in role sets — Partner is safe ONLY behind an industry gate (verified: accounting-gated Partner pull = 100%). President is safe on Prospeo (exact match can't hit "Vice President"); on AI Ark add `excludeTitle:"vice president,vp"` when President/CEO sets run (verified 100%).
4. **Location (user rule): target geo = person location AND company location unless told otherwise.** AI Ark: set `location` + `companyLocation` both. Prospeo has NO person-location filter — post-check `person.location` from returned rows and drop off-geo (measured 0-8% leakage: UK firms with US-based MDs).
5. **`/search-person` accepts the recall-max COMPANY shapes directly** (incl. `company_type.subtypes`, `company_industry`, `company_keywords` top-level — verified live) — so a vertical-wide DM pull inherits the proven ≥70% company gate in the same call, no domain list needed. Domain-list mode still works as below for fixed account lists.
6. **AI Ark open person-search is top-up only, never company-gate:** its fuzzy `title` leaks adjacent functions ("Director of Sales *Development*", "Head of Revenue *Ops*" — strip with `excludeTitle`), and its `companyIndustry` gate can leak whole verticals. The production Ark pattern stays the domain-joined pull (100% post-join, 15/15). Gotchas: `people_search` `companyKeyword` = 401 tier-gated, `companyType` = 400; accented titles can break curl payloads — quote-safe or ASCII them.
7. **Never request emails/phones as a side-effect** ([[no-email-requests-unless-needed]]) — search first, sample-audit at the 90% bar, enrich only after the user's explicit go-ahead (Step 3.45/2.5 pauses stand).

## Purpose

Take a list of company domains, return a clean CSV of decision-makers with verified work emails (and optionally verified mobile numbers).

The standard waterfall is **Prospeo-first, AI Ark fallback**:

0. **(Optional) `lilly-prospeo-list-builder`** — expand the input domain list with additional on-brief companies via recall-max classifier/keyword shapes (lookalike features banned). Use when the goal is "ALL decision-makers in vertical X" rather than DMs at a fixed account list. Skip when the input domain list is already authoritative (a curated client list, a finished Ocean Phase 4 export the user is happy with, etc.)
1. **Prospeo `/search-person`** — find people at the target companies (cheap: 1 credit per page regardless of result count)
2. **Client-side title filter** — drop off-brief roles
3. **Prospeo `/bulk-enrich-person`** — verify emails (and phones if asked) for the people found in step 1
4. **AI Ark `/v1/people`** — **fallback only** for companies where Prospeo coverage was thin (typical in non-DACH/Nordic markets — CZ, SK, RO, GR, BG, SI)
5. **Prospeo `/bulk-enrich-person`** again — verify emails for AI Ark finds
6. **Domain-match filter** — drop cross-contaminated emails
7. **Output CSV / xlsx**
8. **(End-of-run hand-off) `lilly-email-verification`** — offer to pipe Prospeo-source emails through MillionVerifier for a second-layer deliverability check (default yes; AI-Ark-source emails skipped because AI Ark's own verification is opaque and the bidirectional-fallback rows have already been through both providers)

**Why Prospeo-first:** Prospeo's search is **flat 1 credit per page (25 results)** regardless of how many DMs come back, while AI Ark **charges per decision-maker returned**. For a typical 30-company list, Prospeo will surface 50-150 people in 2-6 search credits total. AI Ark on the same list returns 200-700 DMs at per-DM billing — far more expensive when used as primary. Use AI Ark only to fill gaps where Prospeo's index is thin.

This skill is the canonical post-TAM DM-enrichment step. It runs after `lilly-ocean-tam-builder` Phase 4 or after `lilly-tam-mapper` (cross-provider TAM). It can also run standalone when the user already has a domain list (from a prior CSV, AI-Ark export, or manual research).

---

## When to Use

Trigger when the user wants to:

- "Find decision makers at these domains"
- "Get me contacts for these companies"
- "Enrich this list of cos with DMs"
- "Who can we email at [list]"
- After completing `lilly-ocean-tam-builder` Phase 4 and needing to fill in DMs
- Build Top 3-per-country style deliverables from a curated company list

Accept input forms:
- Plain list of domains in chat (one per line, or CSV path)
- Path to .txt or .csv with a `domain` / `Website` column
- Direct hand-off from `lilly-ocean-tam-builder` (post-Phase-4 hand-off trigger)

---

## API access (auth + endpoints)

Both keys live in `~/Library/Application Support/Claude/claude_desktop_config.json` under the `email-finders` MCP server's `env` block.

### Prospeo (PRIMARY)
- **Endpoints:**
  - `POST https://api.prospeo.io/search-person` — find people by company website + seniority/department filters
  - `POST https://api.prospeo.io/bulk-enrich-person` — verify emails + optional phones (max 50 per call, **use batches of 10** to avoid INVALID_REQUEST errors)
  - `POST https://api.prospeo.io/account-information` — free, check credit balance
- **Auth:** `X-KEY: <PROSPEO_API_KEY>`
- **Costs:**
  - Search: 1 credit per page (25 results) returning ≥1 result. Free if NO_RESULTS.
  - Enrich (email): 1 credit per verified match. Free on NO_MATCH.
  - Enrich (mobile): 10 credits per verified mobile (only when `enrich_mobile: true`).

### AI Ark (FALLBACK)
- **Endpoint:** `POST https://api.ai-ark.com/api/developer-portal/v1/people`
- **Auth:** `X-TOKEN: <AI_ARK_API_KEY>`
- **Rate:** 5 req/sec, 300/min, 18,000/hr
- **Cost:** AI Ark **bills per decision-maker returned**. Use sparingly — fallback only.

⚠️ **Tier check:** if AI Ark filters return the full ~412M-person index regardless of input, the key is read-only / no-filter tier. Ask user for the FILTER-tier key (separate API key in their AI Ark dashboard). The current working key starts with `838ba1ff...`.

---

## The 7-step workflow (+ optional Step 0)

### Step 0 — *(Optional)* Expand the domain list via `lilly-prospeo-list-builder` and/or `lilly-ai-ark-list-builder`

**Use when:** the goal is "find ALL decision-makers in vertical X" — i.e. you want to maximise DM coverage of a vertical, not just enrich a fixed account list. Common triggers:
- "Find all the decision makers in [vertical]"
- "Don't miss anyone — pull every co in this space"
- Chained from `lilly-tam-mapper` (Ocean + Prospeo + AI Ark lookalike merge)

**Skip when:** the input domain list is authoritative (a curated client account list, a finished Ocean Phase 4 export the user is happy with, a Top-3-per-country brief, etc.) — extra companies would just bloat the deliverable.

**Order:** Always **Prospeo first, AI Ark second** (mirrors the Prospeo-first-AI-Ark-fallback rule in the rest of this skill — Prospeo is flat 1 credit/page, cheap; AI Ark cost-per-page is unknown until probed).

**How:**

1. **`lilly-prospeo-list-builder`** — delegate with the current domain list as the **exclude set** (cap ~100-200 domains, top-N by recognisability) plus brief criteria (industry / country / size / keyword). Default stop precision = 7/10. Cost: typically 5-20 credits.
2. *(optional)* **`lilly-ai-ark-list-builder`** — only run if user wants 2nd-pass coverage beyond Prospeo. Pass:
   - ~~AI Ark `lookalikeDomains` seeds~~ — **BANNED 2026-07-13 (all lookalike features).** AI Ark expansion runs `lilly-ai-ark-list-builder`'s filters-only recipe (industry enums + self-ID keywords)
   - The full source TAM + Prospeo expansion as `account.domain.any.exclude` set
   - Brief criteria (industry / country / size / keyword)
   Cost: probe the per-page cost on call 1 before committing to full pagination.

Each list-builder returns newly-surfaced domains tagged with its source (e.g. `source = "prospeo_company_search"` / `source = "ai_ark_filter_search"`; legacy exports may carry the old `*_lookalike` tags). Merge those onto the original list before running Step 1, deduping on domain.

**MANDATORY between Step 0 and Step 1: WebFetch-verify every newly-surfaced domain against the brief.** API description-text keyword matching is NOT real qualification — keywords like "label", "print", "tag" appear in descriptions of media holdings, copy shops, POS-display manufacturers, food packaging firms, etc. Drop ❌ off-brief cos before passing to DM enrichment. Otherwise you burn 5-30+ credits per company on DMs that get thrown away. (See `lilly-prospeo-list-builder` Step 3.5 + `lilly-ai-ark-list-builder` Step 3.5 for the verification protocol.)

**Always confirm with user before firing Step 0.** If the user already gave a fixed account list and just wants emails, do NOT expand — go straight to Step 1. If running both list-builders, confirm AFTER Prospeo completes whether to also run AI Ark — usually Prospeo alone covers ~70-90% of the gap at much lower cost.

### Step 1 — Input & confirm

Read the domain list (post-Step-0 merge if Step 0 ran).

**Pre-flight: strip multi-level TLD subdomains (rule).** Prospeo rejects domains like `.uk.com`, `.us.com`, `.eu.com` with `INVALID_FILTERS: Subdomains are not supported`. A single offender aborts the entire batch. Strip them BEFORE any `company.websites.include` or `company.websites.exclude` call:

```python
def is_invalid_subdomain(d):
    parts = d.lower().split('.')
    return len(parts) >= 3 and parts[-2] in ('uk','us','eu','gb','de','ca') and parts[-1] == 'com'

domains = [d for d in domains if not is_invalid_subdomain(d)]
```

Surface dropped count: `"N domains stripped (Prospeo rejects multi-level TLDs)"`. Confirmed 2026-05-04: `luckyfox.uk.com`, `massa.us.com` killed two batches mid-sweep before this check existed.

**Streamline check — skip the full A-H menu when caller-args contain a role spec.** If `args` includes role/title keywords ("founder", "owner", "director", "manager", "CEO", "CRO", "VP", etc.), do NOT walk through the full A-H menu below. Instead:
1. Restate the inferred role list in ONE line.
2. Ask: `"Confirm titles below or override:"` + show the curated title list (English) + seniority+department mapping (non-English).
3. User can reply "yes" / "skip Account Manager" / specific override — no need to walk A-H.

The full A-H menu (below) only fires when NO role spec was provided in args (standalone DM-finder runs, not chained from `lilly-tam-mapper` Phase 4).

**MANDATORY before any paid call: confirm the role/title definition with the user.** Never assume the DM target set from the calling skill's hand-off, from the brief description, or from your own inference. Even when the caller passes a "standard B2B sales DMs" hint, the user may have a different target set in mind for this specific campaign (e.g. operations leadership only, finance + IT, technical decision-makers vs commercial). Ask explicitly:

> "Before I fire the search, who do you actually want to target at these companies? Pick from the menu below or specify your own:
> - **A. Top-of-org**: Founder / CEO / COO / President — best for small cos (11-50)
> - **B. Sales leadership**: VP Sales / Sales Director / Head of Sales / CSO / CRO
> - **C. Acquisitions / Procurement leadership**: Head of Acquisitions / Director of Procurement / Chief Procurement Officer
> - **D. Operations leadership**: COO / Operations Director / Head of Operations
> - **E. Finance leadership**: CFO / Finance Director / Head of Finance
> - **F. Marketing leadership**: CMO / Marketing Director / Head of Marketing
> - **G. Technical / IT leadership**: CTO / CIO / IT Director / Head of IT
> - **H. Custom — describe the titles you want**"

The user can pick multiple letters (e.g., "A + B + C"). Show how each option maps to Prospeo's `person_seniority` + `person_department` filters before firing — so the user can sanity-check the filter shape before paying for the probe.

Also confirm:
- Whether to enrich phone numbers (default **NO** — 10x credit cost on Prospeo)
- Number of domains (split into "original" vs "Prospeo-lookalike" if Step 0 ran)

Confirm credit budget estimate before firing:
- Prospeo search: ~1 credit per 25 DMs returned (so 60-domain run typically = 2-6 credits)
- Prospeo email enrich: ~1 credit per verified match (~50-70% match rate)
- Prospeo phone enrich: ~10 credits per verified mobile (~40-50% verified-mobile rate, only if opted in)
- AI Ark fallback: per-DM billed — only used for cos where Prospeo coverage was thin

**Wait for explicit user confirmation on role set + phone opt-in before moving to Step 2.**

#### Size-conditional role filters

When the user wants different roles based on company size (common pattern: top-exec for small cos, mid-management for large cos), **split the domain list by size and run separate searches with separate filters**. Prospeo's `/search-person` applies one filter per call — there's no per-company conditional.

Common pattern (the user's default for buyer-targeting):
- **Small cos (≤200 employees):** top-of-org responds. Seniority = `Founder/Owner` + `C-Suite` + `Vice President` + `Head` + `Director`. Department = `Sales` + `Sales Leader` + `Chief Executive` + `Founder`. Catches Founder/CEO/COO + sales leadership.
- **Large cos (>200 employees):** top exec rarely engages with cold outbound; mid-management is the better entry point. Seniority = `Vice President` + `Head` + `Director` + `Manager`. Department = `Sales` + `Sales Leader`. Drops C-Suite/Founder, keeps sales-leadership ladder including managers.

Map the user's company-size buckets to the two groups:
- Ocean wide buckets: `11-50`, `51-200` → small; `201-500`, `501-1000`, `1001-5000`, `5001-10000`, `10000+` → large
- Prospeo narrow buckets: `1-10`, `11-20`, `21-50`, `51-100`, `101-200` → small; `201-500`, `501-1000`, `1001-2000`, `2001-5000`, `5001-10000`, `10000+` → large
- Unknown/missing size → default to small (most B2B prospect pools skew small)

For each group, fire its own TAM probe + paginate per Step 2-3. The two pools merge cleanly at Step 4 (bulk-enrich).

**Verify "Manager" seniority is valid in Prospeo.** As of 2026-05-03, the documented seniority enum is `Founder/Owner`, `C-Suite`, `Partner`, `Vice President`, `Head`, `Director`. "Manager" may or may not be accepted. Probe with a tiny `size:1` call before paginating; if rejected with INVALID_FILTERS, fall back to `Director` seniority alone for the >200 group (still catches some manager-titled people whose Prospeo seniority normalised up).

### Step 1.5 — Suppression + already-contacted gate (MANDATORY, runs before any paid call)

**Never fire Step 2 (or any Prospeo/AI Ark call) against a domain that's already suppressed or already contacted.** A cost audit found ~30% of DM-enrichment credits going to companies already contacted or on an exclusion list, because this gate didn't exist. Run it after the domain list is finalised (post-Step-0 merge, post-TLD-strip) and before the Step 2 probe.

1. **Exclusion check:** `navreo_db.check_exclusions(client_id, domains=[...all input domains...])` (from `~/.claude/skills/_shared/navreo_db.py`). Returns a list of `{matched_email, matched_domain, reason}` — collect `matched_domain` values into a drop set.
   - **If it returns `None`, Supabase is unreachable — this is "check unavailable", NOT "no exclusions."** Warn the user explicitly: `"⚠️ Exclusion check unavailable (Supabase unreachable) — cannot confirm these domains are clear of suppressions. Proceed anyway, or wait and retry?"` Wait for explicit go-ahead before spending any credits. Never silently treat an unavailable check as a clean bill. **Unattended exception:** when invoked by an unattended orchestrator (e.g. `lilly-theirstack-data-processing` daily run), do NOT block waiting for a human — follow the caller's unattended-safe rule: log the warning into the run summary and proceed WITHOUT dropping anything.
2. **Already-contacted check:** query `contact_history` for `company_domain` matches, batched ~100 domains per call:
   ```python
   for batch in chunks(domains, 100):
       navreo_db.rest(
           "GET", "/rest/v1/contact_history",
           params={"select": "company_domain", "company_domain": f"in.({','.join(batch)})"}
       )
   ```
   Collect the distinct `company_domain` values returned into a second drop set.
3. **Drop both sets from the domain list BEFORE Step 2 fires.** A domain can land in both sets — dedupe when counting.
4. **Report to the user before the Step 2 probe:**
   > "Suppression + contact-history check: **{N} suppressed**, **{M} already contacted**, **{K} proceeding** to enrichment."

Only the surviving `{K}` domains continue into Step 2 (and, if used, Step 0's WebFetch verification stays scoped to the surviving set — no need to re-verify domains this gate already dropped).

### Step 2 — Prospeo `/search-person` (PRIMARY) — probe first, then paginate

**Always run page 1 alone first as a TAM probe.** Read `pagination.total_count` from the response and report the precise TAM to the user *before* paginating further. This costs 1 credit and gives you (and the user) a hard number to budget against — Prospeo doesn't have a free count-only endpoint.

After page 1 returns:

1. Read `pagination.total_count` (= total raw DMs across all pages) and `pagination.total_page`.
2. Estimate verified-email DMs: `total_count × ~60% Prospeo verify rate` (calibration from past runs).
3. Estimate full-enrichment cost:
   - Pagination: `(total_page − 1) × 1` credit (page 1 already done)
   - Bulk-enrich emails: `total_count × 60% × 1` credit per match
   - AI Ark fallback (if any cos return 0 from Prospeo): variable per-DM
   - Phones (if opted in): `verified_emails × 50% × 10` credits
4. Show user a revised budget table and **wait for explicit green-light** before paginating pages 2-N.
5. **Surface per-USEFUL-lead cost** in the budget table (not just total credits). After the brand-recognition gate from `lilly-tam-mapper` Stage 3.5 has run, you have a defensible "off-brief drop rate" estimate (typically ~30%). Project the per-useful-lead cost as `total_credits ÷ (verified_emails × (1 − off_brief_drop_rate))`. Run A 2026-05-04 calibration: 1.54 cr/lead headline became ~1.7 cr/useful-lead after off-brief drop. The user budgets against the latter, not the former.

If `total_count` is wildly bigger or smaller than expected, that's a chance to adjust filters before committing the full spend.

Batch all domains in one call. Prospeo accepts up to 500 domains per `company.websites.include`. **If you have >500 domains, split into multiple calls** — each call's first page is its own probe.

```bash
curl -X POST "https://api.prospeo.io/search-person" \
  -H "X-KEY: $PROSPEO_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "page": 1,
    "filters": {
      "company": {"websites": {"include": ["domain1.com","domain2.com","..."]}},
      "person_job_title": {"include": ["<qualified long-tail title list — ALWAYS present, the primary filter>"], "include_partial_match": true},
      "person_seniority": {"include": ["Founder/Owner","C-Suite","Partner","Vice President","Head","Director"]}
    }
  }'
```

**Filter rules:**
- `company.websites.include`: up to **500 domains** per call. **For larger pools, the skill auto-splits into 500-domain batches in the background — never surface the batching detail to the user (it's an API constraint, not a workflow choice).**
- **PREFERRED for English-dominant pools: `person_job_title.include` with `include_partial_match: true`.** Pass a curated list of canonical leadership titles (CEO, Founder, Managing Director, President, Owner, Head of Sales, VP of Sales, Sales Director, Director of Business Development, Chief Revenue Officer, etc). Partial match catches variants like "Senior Sales Director", "VP of EMEA Sales", "Sales Director - Aerospace". 95%+ Step-3 retention (already title-clean). Empirically delivers **40%+ more verified emails per credit** than the seniority+department combo on English-dominant pools (US/UK/IE/AU/NZ/CA-heavy briefs).
- **~~Seniority+department fallback~~ RETIRED (2026-07-14, user rule: never seniority/department alone).** For non-English pools, put local-language canonical titles IN the title list instead — "geschäftsführer", "algemeen directeur", "directeur" etc. match as exact canonical titles (verified 100% on the DE+NL freight brief). Canonicalise via free `/search-suggestions`. Seniority/department may only LAYER on top of a title list, never replace it.
- `person_seniority` valid values: `Founder/Owner`, `C-Suite`, `Partner`, `Vice President`, `Head`, `Director`, `Manager` — note exact strings (not "VP" / "C-Level" / "Owner" — those reject).
- `person_department` valid values: `Sales`, `Operations`, `Product`, `Chief Executive`, `Founder`, `Sales Leader`, `Operations Executive`. Submit a parent dept and Prospeo auto-includes sub-departments.
- **Never use `person_job_title` strict filter** (without `include_partial_match`) — strict mode rejects most real titles. Always pair `person_job_title.include` with `include_partial_match: true`.

**Pagination:** check `pagination.total_page` in the response. If > 1, paginate via `page` parameter. Each page = 1 credit.

**Usage logging (mandatory after every paid page):** after each `/search-person` call that returns ≥1 result, `navreo_db.log_provider_usage("prospeo", 1, endpoint="/search-person", source_id="lilly-decision-maker-finder")` — 1 credit per page fired (probe page + every paginated page). Skip logging for NO_RESULTS pages (Prospeo doesn't charge for those).

**Response shape:**
```json
{
  "error": false,
  "results": [{"person": {...}, "company": {...}}],
  "pagination": {"current_page": 1, "per_page": 25, "total_page": N, "total_count": N}
}
```

Each `person` has: `person_id`, `first_name`, `last_name`, `full_name`, `linkedin_url`, `current_job_title`, `headline`. **Email and mobile are NOT in search response** — must call `/bulk-enrich-person` next.

### Step 2.5 — Sample-audit gate (MANDATORY before the full pull / enrichment)

The page-1 TAM probe (Step 2) tells you HOW MANY people match. This gate tells you WHETHER THEY'RE THE RIGHT PEOPLE — *before* you pay to paginate and enrich the rest. It exists because fuzzy / loose filters (especially AI Ark, and any broad seniority+department pull) routinely drag in off-brief titles that look fine in the count but are wrong on inspection.

**Always run this before paginating pages 2-N or firing any bulk-enrichment:**

1. **Pull a ~100-person sample.** Prospeo: pages 1-4 (~4 credits at 25/page). AI Ark path: one page of 100. Reuse the people the probe already returned where possible.
2. **Audit the titles** with the `lilly-list-audit` classifier (`classify()` in `lilly-list-audit/scripts/audit_campaign.py`). Set the on-brief bucket(s) to the role set the user confirmed in Step 1 — map the A-H menu to the audit's function labels (e.g. sales-ops / enablement brief → `SALES-SUPPORT`; sales leadership → `SALES-LEADER`; founders → `OWNER/EXEC`). Retarget per `lilly-list-audit`'s `--on-icp` rules.
3. **Present the audit:** on-brief %, the full function mix, and off-brief examples grouped Tier A (adjacent) / Tier B (clearly wrong function) / Tier C (ambiguous) — the `lilly-list-audit` output format. Eyeball a handful of titles first: the classifier is heuristic and *under*-counts on-brief via title precedence (e.g. "Managing Director, Sales Enablement" → OWNER/EXEC), so flag that rather than overstating the off-brief rate.
4. **A-grade gate (HARD STOP): if the sample audits below 90% on-brief (below an A in `lilly-list-audit` grade bands), the rest of the list MUST NOT be pulled.** Do not offer "proceed anyway" as a path — name what is leaking (the off-brief buckets + top example titles), tighten the filters (title excludes, exact-title include-nets, drop the leaking department), and re-sample. Repeat until the sample grades A. Only an explicit user override in so many words ("pull it anyway, I accept the leak") unblocks a sub-A pull. Rationale: the 2026-07-10 Commercial Roofing audit — an unGated pull put ~26% flagged titles into a live campaign; the fix cost a 973-lead prune.
5. **At ≥90%: still pause for explicit user go-ahead before the full pull.** Never auto-proceed. If the user wants to retune the title / seniority filters, adjust and re-sample before committing the full spend.

Hard gate: no full pagination and no bulk-enrichment until (a) the ~100-row sample audits ≥90% on-brief AND (b) the user has seen the sample audit and said go.

### Step 3 — Client-side title filter (brief-relevant only)

After collecting people from Prospeo across all pages, filter to brief-relevant titles. Drop off-brief titles to save enrichment credits.

**KEEP keywords** (multilingual):
```
ceo, coo, cfo, cmo, cpo, cco, cso, cbo, chief, president, founder, owner,
managing director, general manager, geschäftsführer, geschäftsleitung,
direktor, direktur, direktör, dyrektor, reditel, ředitel, jednatel, direttore,
administrerende, daglig leder, toimitusjohtaja,
sales, vertrieb, obchod, vanzari, prodaj, πωλ, myynti,
purchasing, procurement, einkauf, nákup, nabav,
operations, operating, betriebsleiter, produktion, production, manufacturing, supply chain,
product manager, product director, head of product, produkt,
commercial, head of, vp , vice president, manaj, manager, director, responsable, vodja, šef,
business development, key account, account manager, area manager, marketing, executive board
```

**OFF keywords** (drop these even if other keywords match):
```
it manager, it specialist, hr , human resources, graphic designer, intern, junior,
prepre, pre-press, quality control, technician, machine operator, tipograf,
šofer, driver, warehouse, logistik
```

The brief-relevant filter typically retains ~40-70% of Prospeo's seniority+department output.

### Step 4 — Prospeo `/bulk-enrich-person` (verify emails + optional phones)

**Batch size: 10** (not 50). 50-batches sometimes return `INVALID_REQUEST` due to rate-limit/payload-size issues. 10 is reliable.

**Identifier: linkedin_url** (not numeric index). Using `linkedin_url` as the `identifier` field eliminates batch-indexing bugs that caused cross-contaminated emails (e.g., a SOMA person showing a Tiskara Zagreb email). Mapping is then perfect — `match[i].identifier === input linkedin URL`.

**Bidirectional email fallback** (Bjion 2026-04-27): when Prospeo bulk-enrich returns `NO_MATCH` for a person (no verified email found), **fall back to AI Ark `/v1/people` for that person's email** — query AI Ark with the person's LinkedIn URL or name+company. AI Ark sometimes has emails Prospeo doesn't (regional coverage gaps). Likewise, when AI Ark people-search (Step 5) returns a person without an email, **feed that person's LinkedIn URL back to Prospeo `/bulk-enrich-person`**. Both providers index different email caches — bidirectional retry lifts coverage 10-30% on hard markets.

The fallback workflow:
1. Prospeo bulk-enrich first → keep verified emails; flag NO_MATCH list.
2. For NO_MATCH list, query AI Ark (search by linkedin_url or fullname+domain) → keep AI Ark emails.
3. Conversely, when running Step 5 (AI Ark people search for low-coverage cos), every person AI Ark returns without an email → run their linkedin_url through Prospeo bulk-enrich.
4. Domain-match filter (Step 7) applies to both sources equally.

```bash
curl -X POST "https://api.prospeo.io/bulk-enrich-person" \
  -H "X-KEY: $PROSPEO_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "only_verified_email": true,
    "enrich_mobile": false,
    "data": [
      {
        "identifier": "https://www.linkedin.com/in/example",
        "linkedin_url": "https://www.linkedin.com/in/example",
        "first_name": "Jane",
        "last_name": "Doe",
        "company_website": "example.com"
      }
    ]
  }'
```

**`enrich_mobile: true` is opt-in only.** 10 credits per verified mobile. Always confirm with user before enabling. Mobile data is `matched[i].person.mobile.mobile` (international format) when status `VERIFIED`.

Email lives at `matched[i].person.email.email`; canonical company domain at `matched[i].company.domain`.

**Usage logging (mandatory after every batch):** after each `/bulk-enrich-person` call, count `matched[i]` entries with `person.email.status == 'VERIFIED'` (1 credit each) plus, if `enrich_mobile: true`, `mobile.status == 'VERIFIED'` entries (10 credits each) — `navreo_db.log_provider_usage("prospeo", verified_email_count + verified_mobile_count * 10, endpoint="/bulk-enrich-person", source_id="lilly-decision-maker-finder")`. NO_MATCH entries are free and don't count.

#### Bulk-enrich response shape (verified 2026-05-04 — DO NOT MISPARSE)

The skill's previous reference implied status was at `matched[i].status`. **It's not.** Status lives at `matched[i].person.email.status`. Email is at `matched[i].person.email.email` (the `email` object's `email` string), NOT `matched[i].person.email` as a string. Misparse cost in Run B: 4,500 enrichments returned 0 verified emails captured (Prospeo charged the run; re-fire hit cache and was free).

```
matched[i] = {
  "identifier": "https://www.linkedin.com/in/...",
  "person": {
    "person_id": "...",
    "first_name": "...",
    "last_name": "...",
    "linkedin_url": "...",
    "current_job_title": "...",
    "headline": "...",
    "email": {                    ← email is an OBJECT here
      "status": "VERIFIED",       ← status lives here, NOT on matched[i]
      "revealed": true,
      "email": "name@domain.com", ← actual email STRING
      "verification_method": "SMTP",
      "email_mx_provider": "Microsoft"
    },
    "mobile": { ... },           ← when enrich_mobile: true
    "job_history": [...],
    "location": {...}
  },
  "company": {
    "domain": "domain.com",
    ...
  }
}
```

Top-level `not_matched` is a separate array of identifiers (NOT inside `matched` with `status: NO_MATCH`).

#### Error handling and concurrency (Run A 2026-05-04 lesson)

Distinguish error semantics — they are NOT all retryable:

| `error_code` | Meaning | Action |
|---|---|---|
| `"NO_MATCH"` | No verified email found for this person | **FREE and TERMINAL.** Mark all 10 in batch as no-match. **DO NOT retry.** Re-firing wastes turns and never recovers (it's not a rate-limit error). |
| `"Rate limit exceeded"` | Concurrency too high | Only retryable error. Backoff 1.5s. |
| Other `error: true` | Unspecified | Log + skip. |

**Max concurrency for bulk-enrich: 2-3 sequential workers.** 8-way concurrency hit rate limits on 104/195 batches in Run A. Stay at 2-3 to avoid the rate-limit storm.

#### 1-record probe before scaling

Before paginating batches at scale, fire a single bulk-enrich call with 1 DM (the first verified-search result):

```
0. PROBE: 1 DM call.
   Verify the parser correctly extracts:
     - matched[0].person.email.status == 'VERIFIED'
     - matched[0].person.email.email is a string ending in @domain
   If parser fails or returns 0 verified, HALT and inspect raw response before scaling.
   Cost: 1 cr (or 0 if cached). Catches the silent-fail trap that wasted 4,500 records in Run B.
```



### Step 5 — AI Ark fallback (only for low-coverage companies)

**When to fallback:** identify companies where Prospeo returned **fewer DMs than the brief target** (e.g. <3 verified-email DMs per company for a Top-3-per-country deliverable). These are typically Eastern European / Greek / Slovenian markets where Prospeo's index is thin.

If no fallback companies → skip steps 5-6, go straight to Step 7.

**AI Ark response shape (verified 2026-05-04).** Per-person fields nest under `summary` and `link`, not at the top level. The Path A run that extracted `c.get('name')` and `c.get('description')` directly returned empty strings → all 25 cos misclassified as borderline. Use these paths:

| Field | Path |
|---|---|
| Person/company name | `summary.name` |
| Description | `summary.description` (or `summary.overview` / `summary.seo` if present and shorter) |
| Industry | `summary.industry` (single primary tag); `industries[]` for full list |
| Headcount range | `summary.staff.range.{start,end}` |
| Headcount exact | `summary.staff.total` (when known) |
| Domain (canonical bare) | `link.domain_ltd` — **NOT `link.domain`** (which can be a full URL) |
| HQ country | `location.headquarter.country` |
| LinkedIn URL | `link.linkedin` |

```python
# Extraction example
def extract(c):
    return {
        "domain":       c.get("link", {}).get("domain_ltd"),
        "name":         c.get("summary", {}).get("name"),
        "description":  c.get("summary", {}).get("description")
                        or c.get("summary", {}).get("overview", ""),
        "industry":     c.get("summary", {}).get("industry"),
        "staff_min":    c.get("summary", {}).get("staff", {}).get("range", {}).get("start"),
        "staff_max":    c.get("summary", {}).get("staff", {}).get("range", {}).get("end"),
        "country":      c.get("location", {}).get("headquarter", {}).get("country"),
        "linkedin":     c.get("link", {}).get("linkedin"),
    }
```

```bash
curl -X POST "https://api.ai-ark.com/api/developer-portal/v1/people" \
  -H "X-TOKEN: $AI_ARK_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "page": 0,
    "size": 100,
    "account": {"domain": {"any": {"include": [GAP_DOMAINS_HERE]}}},
    "contact": {
      "seniority": {"any": {"include": ["founder","owner","partner","c_suite","vp","director","head"]}}
    }
  }'
```

**AI Ark filter strategy** (cost vs recall trade-off — AI Ark bills per DM returned):
- **Default (broad recall):** seniority-only filter as above. Catches German "Geschäftsführer", Croatian "Direktor", Norwegian "Daglig leder" via AI Ark's normalisation. Use when willing to pay for breadth.
- **Tight (cost-sensitive):** add `contact.experience.current.title.any.include = {"mode": "SMART", "content": [BRIEF_TITLES]}` with brief-specific titles. Lower cost but worse recall on non-English titles. See "Reference: tight title filter" at the bottom for the multilingual title list.

Paginate via `totalPages`. After the fallback pull, re-apply the **client-side title filter** from Step 3 to drop off-brief AI Ark hits.

**Usage logging (mandatory after every page):** AI Ark bills per DM returned — after each `/v1/people` call, `navreo_db.log_provider_usage("ai_ark", len(results_returned_this_page), endpoint="/v1/people", source_id="lilly-decision-maker-finder")`.

### Step 6 — Re-enrich AI Ark finds via Prospeo `/bulk-enrich-person`

Same as Step 4 — batches of 10, `identifier = linkedin_url`. AI Ark returns LinkedIn URLs which feed straight into Prospeo enrichment.

### Step 7 — Domain-match filter (mandatory) + output

Prospeo occasionally returns an email belonging to a different company (cross-contamination — likely from cached enrichment of a person who moved jobs). **Always** filter out emails where the email's domain doesn't match the input company domain.

```python
def email_matches_domain(email, dom):
    em_dom = email.split('@')[-1].lower()
    base = dom.split('.')[0]
    em_base = em_dom.split('.')[0]
    # exact match OR shared TLD-stripped base (e.g. cetisflex.com → cetis.si is acceptable for parent group)
    return em_dom == dom.lower() or em_base == base
```

For known parent/subsidiary pairs, allow either domain (e.g. `gallus-group.com` accepts `heidelberg.com`, `mediehuset-andvord.no` accepts `andvord.no`, `cetisflex.com` accepts `cetis.si`).

**Output CSV columns:** `country, company, website, segment, tier, decision_maker_name, title, linkedin, email, phone, source`.

When chained from `lilly-ocean-tam-builder`, optional xlsx output with:
- `All` tab (every DM)
- 10 per-country tabs
- `Per Market` summary tab (Top 3 / Extended company counts, DMs, emails, phones, segment breakdown)
- Tier coloring: Top 3 = green, Extended = yellow.

---

## Cache writes (mandatory after every successful API call)

After every `/search-person`, `/bulk-enrich-person`, or AI Ark `/v1/people` response that returns ≥1 result, write the per-entity slice to the cache so downstream skills (most notably `lilly-icebreaker`) can read it without paying for a fresh API call.

**Preferred write path (dual-write):** use the shared helper `~/.claude/skills/_shared/navreo_db.py` — `navreo_db.put_enrichment(entity_type, key, provider, payload, endpoint=..., source_skill="lilly-decision-maker-finder")` writes BOTH the Supabase central cache (shared across machines/skills) and the local `~/.navreo-cache` mirror in one call. `entity_type` is `"company"` or `"person"`; `key` is the canonical domain or linkedin slug. Fails soft — a Supabase outage still writes the local mirror. The manual layout below documents the local mirror shape (and is the fallback if the helper is unavailable).

**Cache READS also go Supabase-first:** before treating a domain/person as un-cached, check `navreo_db.get_enrichment(entity_type, key, max_age_days=30)` — the central cache may hold entries this machine never fetched.

**Layout:**
```
~/.navreo-cache/
├── prospeo/
│   ├── companies/{canonical-domain}.json   # e.g. stripe.com.json
│   └── people/{linkedin-slug}.json         # last path segment of linkedin_url
└── ai_ark/
    ├── companies/{canonical-domain}.json
    └── people/{linkedin-slug}.json
```

**Per-file envelope:**
```json
{
  "fetched_at": "2026-05-05T17:25:00Z",
  "endpoint": "/search-person",
  "source_skill": "lilly-decision-maker-finder",
  "data": { ...the raw response slice for THIS entity only... }
}
```

### Cache write — Prospeo `/search-person` (Step 2)

For each `results[i]` in the response:

```bash
NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
DOMAIN=$(echo "$company_domain" | tr '[:upper:]' '[:lower:]' | sed -E 's|^https?://(www\.)?||;s|/.*$||')
LI_SLUG=$(echo "$linkedin_url" | sed -E 's|.*/in/([^/?]+).*|\1|')

jq -n --argjson co "$company_obj" --arg now "$NOW" \
  '{fetched_at: $now, endpoint: "/search-person", source_skill: "lilly-decision-maker-finder", data: $co}' \
  > ~/.navreo-cache/prospeo/companies/${DOMAIN}.json

jq -n --argjson p "$person_obj" --arg now "$NOW" \
  '{fetched_at: $now, endpoint: "/search-person", source_skill: "lilly-decision-maker-finder", data: $p}' \
  > ~/.navreo-cache/prospeo/people/${LI_SLUG}.json
```

In practice, this runs as a Python or jq pipeline over the full response — one company file written per unique domain, one person file written per result.

### Cache write — Prospeo `/bulk-enrich-person` (Step 4)

For each `matched[i]`, MERGE the enriched fields onto the existing person cache file (preserving anything from `/search-person` that enrich didn't return). Simplest pattern: read the existing file, deep-merge the new `data` block, write back.

```bash
EXISTING=$(cat ~/.navreo-cache/prospeo/people/${LI_SLUG}.json 2>/dev/null || echo '{"data":{}}')
jq -n --argjson old "$EXISTING" --argjson new "$enriched_person_obj" --arg now "$NOW" \
  '{fetched_at: $now, endpoint: "/bulk-enrich-person", source_skill: "lilly-decision-maker-finder", data: ($old.data + $new)}' \
  > ~/.navreo-cache/prospeo/people/${LI_SLUG}.json
```

The enrich response also returns a nested `company` object — write/merge that to `~/.navreo-cache/prospeo/companies/{DOMAIN}.json` the same way.

### Cache write — AI Ark `/v1/people` (Step 5)

Same envelope, under `~/.navreo-cache/ai_ark/`. AI Ark's schema is different (account.* / contact.* nesting), so reads are provider-aware — the icebreaker skill prefers Prospeo cache and falls back to AI Ark only if that's all that exists.

```bash
jq -n --argjson p "$ai_ark_person_obj" --arg now "$NOW" \
  '{fetched_at: $now, endpoint: "/v1/people", source_skill: "lilly-decision-maker-finder", data: $p}' \
  > ~/.navreo-cache/ai_ark/people/${LI_SLUG}.json
```

### Cache rules

1. **Last-write-wins** per `(provider, key)`. Never throw away an existing file silently — if a write fails, log it.
2. **Canonical keys.** Domain: lowercase, strip protocol + `www.`, strip trailing slash and path. LinkedIn slug: last path segment of `linkedin_url`, no trailing slash.
3. **Don't write empty data.** If `data: null` or `data: {}`, skip the write — there's nothing to cache.
4. **Failure-tolerant.** Cache writes must never block the main workflow. Wrap in `|| true` if running inline.
5. **Provider isolation.** Prospeo cache and AI Ark cache live in separate trees. Don't merge across providers — the consumer (icebreaker skill) is the right place to decide read order.

---

## Reference: Prospeo `/search-person` shape (PRIMARY)

```json
{
  "page": 1,
  "filters": {
    "company": {"websites": {"include": ["domain1.com","domain2.com"]}},
    "person_seniority": {"include": ["Founder/Owner","C-Suite","Partner","Vice President","Head","Director"]},
    "person_department": {"include": ["Sales","Operations","Product","Chief Executive","Founder","Sales Leader","Operations Executive"]}
  }
}
```

## Reference: AI Ark broad seniority pull (FALLBACK)

```json
{
  "page": 0,
  "size": 100,
  "account": {"domain": {"any": {"include": ["domain1.com"]}}},
  "contact": {
    "seniority": {"any": {"include": ["founder","owner","partner","c_suite","vp","director","head"]}}
  }
}
```

## Reference: AI Ark tight title filter (cost-saver)

```json
{
  "page": 0,
  "size": 100,
  "account": {"domain": {"any": {"include": ["domain1.com"]}}},
  "contact": {
    "experience": {
      "current": {
        "title": {
          "any": {
            "include": {
              "mode": "SMART",
              "content": [
                "ceo","chief executive officer","managing director","general manager","president","owner","founder","co-founder","geschäftsführer","generální ředitel",
                "sales director","head of sales","vp sales","chief sales officer","cso","commercial director","head of commercial","vertriebsleiter","leiter vertrieb","obchodní ředitel","director vanzari",
                "purchasing director","head of purchasing","procurement director","head of procurement","chief procurement officer","einkaufsleiter","leiter einkauf","ředitel nákupu",
                "operations director","head of operations","coo","chief operating officer","betriebsleiter","leiter operations","leiter produktion","production director","head of production","manufacturing director","head of manufacturing","supply chain director","head of supply chain",
                "product director","head of product","chief product officer"
              ]
            }
          }
        }
      }
    }
  }
}
```

## Reference: Prospeo `/bulk-enrich-person` shape

```json
{
  "only_verified_email": true,
  "enrich_mobile": true,
  "data": [
    {
      "identifier": "https://www.linkedin.com/in/jane-doe",
      "linkedin_url": "https://www.linkedin.com/in/jane-doe",
      "first_name": "Jane",
      "last_name": "Doe",
      "company_website": "example.com"
    }
  ]
}
```

---

## Cost calibration (real run, April 2026 — Sihl/Okan PICOFILM, 31 cos / 155 DMs)

Prospeo-first workflow:

| Step | Volume | Credits |
|---|---|---|
| Prospeo `/search-person` (60 domains, paginated to ~3 pages) | ~50-80 DMs surfaced | ~3-6 |
| Prospeo `/bulk-enrich-person` (emails) | 30-50 verified | ~30-50 (1/match) |
| AI Ark fallback (~30 cos with thin Prospeo coverage) | ~700 DMs returned | per-DM billed |
| Prospeo `/bulk-enrich-person` (re-enrich AI Ark finds) | 100-120 verified | ~100-120 (1/match) |
| Prospeo `/bulk-enrich-person` (phones, opt-in) | 72 verified mobiles (46% hit rate) | 637 (10/match) |

**Bottom line:** to deliver a typical Top-3-per-country prospect list (10 markets × 3-5 DMs/co × 3 cos = 90-150 DMs), expect:
- **Prospeo emails:** ~150-200 credits total (search + enrich)
- **AI Ark fallback:** moderate per-DM bill on ~30-50% of companies
- **Prospeo phones (if requested):** +400-800 credits

Confirm with user before enabling phones.

---

## When chained from `lilly-ocean-tam-builder`

Receive: list of HQ-filtered company domains from Phase 4. Plus optionally per-domain segment/tier metadata from a curated input (e.g. PICOFILM v4 prospect list).

Return: enriched DM CSV ready for the user to inspect, plus optionally an xlsx with `All` + per-country + `Per Market` tabs (use openpyxl).

---

## Hand-off — offer to pipe Prospeo-source emails through `lilly-email-verification` (MillionVerifier double-check)

**Always offer this step before finishing the run.** Prospeo's `only_verified_email: true` is an SMTP probe, not a deliverability oracle — catch-all domains, greylisted servers, and stale-but-MX-valid mailboxes can sneak through. MillionVerifier is the second-layer check the Navreo cold-email pipeline already runs on every other source, and the cost (1 MV credit per email, flat) is small compared to the bounce-rate hit on a single bad send.

After the final summary (and BEFORE the HeyReach hand-off below), ask the user:

> "We surfaced **{N_prospeo}** decision-makers with Prospeo-verified emails. Want me to pipe them through `lilly-email-verification` (MillionVerifier) for a second-layer deliverability check? Drops invalid / disposable / unknown, keeps catch-all flagged. ~{N_prospeo} MV credits. Default yes."

Then:
- **If yes** → hand off the verified-email CSV to `lilly-email-verification`. The verification skill auto-detects this is NOT an AI-ARK source (no `AI Ark People ID` column), so it runs MillionVerifier on every row in Stage 1. Stage 2 (find-missing) is a no-op because every row already has an email. The output is the same CSV minus any MV-failed rows, with a `source` column appended (`millionverifier_verified` or carried-through `prospeo`). Drop the MV-failed rows from the deliverable.
- **If no** → end the run with the Prospeo-only verification, write the CSV as normal.

**Always ask, never auto-run** — the user may be on a tight Prospeo + MV credit budget, or trust Prospeo's verification for this run (e.g. a small test batch where MV cost outweighs the bounce-rate risk).

**Scope: Prospeo-source emails only.** Rows whose email came from AI Ark (bidirectional fallback per Guardrail 14 — Prospeo NO_MATCH → AI Ark email lookup) are **exempt** from this hand-off. AI Ark's verification is opaque and the bidirectional flow has already cross-checked both providers; piping them through MV again is unlikely to add value at the cost of more credits. Filter the hand-off input CSV to `source IN ('prospeo', 'ai_ark+prospeo')` — both of those values mean Prospeo enriched the email (the people came from different search providers but the email itself was Prospeo-fetched). Exclude any rows where the email was AI-Ark-fetched.

**Implementation note:** the hand-off input is the same verified-email CSV produced by Step 7 (domain-match-filtered), pre-HeyReach. `lilly-email-verification` reads it, runs MV on the email column, and writes `<basename>_enriched.csv`. The Step-7 CSV is then replaced with the MV-cleaned version for downstream HeyReach hand-off and final deliverable.

---

## Hand-off — offer to push the no-email-found leads to LinkedIn (HeyReach)

**Always offer this step before finishing the run.** This skill produces both verified-email DMs (the kept rows) and a drop pile of DMs whose email couldn't be verified by either Prospeo or AI Ark. Those drop-pile DMs still have a LinkedIn URL and could be reached via LinkedIn DM instead of email — don't let them die silently.

After the final summary, ask the user:

> "We surfaced **{N}** decision-makers without a verified email. Want me to push them to LinkedIn via HeyReach instead? They have LinkedIn URLs, so they'd land in a new HeyReach list ready to feed a LinkedIn campaign."

Then:
- **If yes** → hand off to `lilly-heyreach-upload`. Pass the no-email DM rows (preserving LinkedIn URL, first name, last name, company name, title, country, segment / tier metadata). The skill handles list creation, custom-field generation, and the upload.
- **If no** → end the run, write the verified-email CSV as normal.

Never auto-push without confirmation — the user may not have a LinkedIn campaign set up for the brief, or the no-email DMs may be intentional discards. Always ask.

**Implementation note:** the no-email pile is the set of search-step results that survived the title filter (Step 3) but didn't get a verified email from Prospeo `/bulk-enrich-person` (Step 4) OR AI Ark person lookup (Step 5) OR the bidirectional fallback (Guardrail 14). Carry those rows through to a parallel "no-email" output that the hand-off can consume. Don't drop them from intermediate state.

---

## Cloud upload (mandatory)

The finished, verified-email DM CSV MUST be uploaded to the central Supabase list store before the run ends — it must never live only on this machine. Run:

`python3 ~/.claude/skills/_shared/list_upload.py <final.csv> --name "<descriptive list name>" --client "<Client>" [--folder "<Theme>"] --source-skill lilly-decision-maker-finder --brief "<one-line brief>" --owner "<who asked>"`

Then show the returned `https://navreo-signals.onrender.com/app/lists.html#<id>` link to the user — that link is part of the deliverable, alongside the CSV.

Folder rules: `--client` = the client named in the brief (internal/Navreo pulls → `Navreo`); add `--folder` ONLY when the brief names a campaign theme or segment (e.g. client `Amplifyy`, folder `Beauty`); never deeper than two levels. Re-runs with the same name+client replace that list's rows in place (safe).

---

## Output schema

CSV columns (ordered as below):

```
country, company, website, segment, tier, decision_maker_name, title, linkedin, email, phone, source
```

- `country` — full name (Switzerland not CH)
- `tier` — `Top 3` / `Extended` (when chained from lilly-ocean-tam-builder); else blank
- `segment` — strict brief category (e.g. `Industrial Tag & Label Manufacturer`, `Industrial Identification / Barcode / Security Specialist`, `Industrial Printing & Identification Solution Provider`) — caller's responsibility to map
- `linkedin` — full LinkedIn URL
- `email` — verified by Prospeo with `only_verified_email: true`
- `phone` — verified mobile (international format) when `enrich_mobile: true` was set; else blank
- `source` — `prospeo` (search-then-enrich) or `ai_ark+prospeo` (fallback then enrich)

---

## Guardrails

1. **Never use Ocean.io's people endpoints** (`/v3/search/people`, `/v2/search/people`, `/v2/lookup/people`, `/v2/enrich/person`, `/v2/enrich/people`). Banned per `feedback_no_ocean_people_search` memory — Ocean's people index is sparse and produces false negatives.
2. **Always Prospeo first, AI Ark fallback.** Prospeo search is flat 1 credit per page; AI Ark bills per DM returned. Going AI Ark-first on a 30-co list can 10x your costs vs Prospeo-first.
3. **Prefer `person_job_title.include` + `include_partial_match: true`** with a curated leadership-title list for English-dominant pools (US/UK/IE/AU/NZ/CA). Falls back to `person_seniority` + `person_department` for non-English-dominant pools (DE/NL/Nordic/Eastern-European). Never use `person_job_title` strict alone (without `include_partial_match`) — strict rejects most real titles. The skill auto-splits domain lists at the 500-domain Prospeo cap behind the scenes; never surface batching details to the user.
4. **Prospeo bulk-enrich batches: 10, not 50.** 50 sometimes fails `INVALID_REQUEST`. 10 is reliable.
5. **`identifier = linkedin_url`** in bulk-enrich payloads. Avoids batch-indexing bugs that caused cross-contaminated emails.
6. **Domain-match filter is mandatory.** Drop emails where `email.split('@')[-1]` doesn't match the input company's domain (modulo known parent/subsidiary pairs).
7. **Phone enrichment is opt-in.** 10 credits per verified mobile vs 1 per email. Always confirm with user.
8. **AI Ark filter-tier key required** for the fallback step. If filters silently return the full 412M-person index, ask user for the search-tier key.
9. **Use full words in deliverables.** "Companies" not "cos", "Decision Makers" not "DMs" — per Bjion's preference.
10. **Surface unfilled gaps honestly.** If a market's domains return 0 verified-email DMs even after AI Ark fallback, say so — don't pad with off-brief alternatives.
11. **Document the workflow used in the deliverable.** Include the credits spent, hit rate, and any markets where coverage was thin.
12. **Always TAM-probe before paginating.** First Prospeo `/search-person` call (page 1, 1 credit) returns `pagination.total_count` for the entire filtered TAM. Show this to the user as a precise budget input + revised cost estimate, then wait for explicit green-light before paginating pages 2-N. Prospeo has no free count-only endpoint — every search call returning ≥1 result costs 1 credit per page — but the page-1 probe is by far the cheapest way to lock down the spend before committing.
13. **Offer Step 0 (list expansion) when the goal is "all DMs in vertical X".** If the user's intent is vertical-wide DM coverage (not a fixed account list), proactively offer to chain `lilly-prospeo-list-builder` first (cheap — flat 1 credit/page) and optionally `lilly-ai-ark-list-builder` second (per-page cost TBD per run, more expensive) to surface additional on-brief companies the input source missed (recall-max shapes; lookalike banned). Always Prospeo first, AI Ark as 2nd-pass option. Skip silently when the input is clearly authoritative (curated client list, user-finalised TAM, Top-3 brief). Always confirm before firing — extra companies can bloat a deliverable that was meant to be tight.
14. **Bidirectional email fallback Prospeo↔AI Ark.** When either provider returns a person without a verified email, retry the lookup against the other provider before giving up. Prospeo NO_MATCH → AI Ark email lookup; AI Ark person-without-email → Prospeo bulk-enrich. Both providers cache different email datasets (regional + temporal coverage gaps). Bidirectional retry lifts verified-email coverage 10-30% on hard markets at minimal extra cost (Prospeo enrich is 1 credit/match, AI Ark people lookup is per-DM-returned but you're only re-running the gap subset).
15. **Cache writes are mandatory** (see "Cache writes" section). Every successful Prospeo `/search-person`, `/bulk-enrich-person`, and AI Ark `/v1/people` response writes per-entity slices to `~/.navreo-cache/{prospeo,ai_ark}/{companies,people}/`. Downstream skills (`lilly-icebreaker` today, others later) read this cache to avoid paying for the same data twice. Skipping the writes silently breaks the cache contract.
16. **Always offer the `lilly-email-verification` hand-off before finishing.** Prospeo's `only_verified_email: true` is a single SMTP probe — catch-all / greylisted / stale-MX rows can sneak through. The hand-off runs MillionVerifier on Prospeo-source emails (`source IN ('prospeo', 'ai_ark+prospeo')`) for a second-layer deliverability check. Default yes; flat 1 MV credit per email. AI-Ark-source emails (from the bidirectional NO_MATCH fallback) are exempt — verification is opaque and double-checking adds cost without obvious value. The hand-off runs BEFORE the HeyReach no-email hand-off so any MV-dropped rows can also be offered to LinkedIn.
17. **Sample-audit gate before any full pull (MANDATORY, Step 2.5).** After the page-1 TAM probe, pull a ~100-person sample, run the `lilly-list-audit` classifier on the titles, present the function mix + on-brief % (with the Tier A/B/C off-brief breakdown), and ALWAYS pause for explicit user go-ahead before paginating or enriching the full set. Never auto-proceed, regardless of score. The point: the user pulls ~100 first, sees who's actually showing up, and signs off before the whole list is committed to spend.
18. **Suppression + already-contacted gate before any paid call (MANDATORY, Step 1.5).** Batch-check all input domains against `navreo_db.check_exclusions(client_id, domains=[...])` and `contact_history` (via `navreo_db.rest`) BEFORE Step 2 fires. Drop matches, report N suppressed / M already-contacted / K proceeding. If `check_exclusions` returns `None`, treat it as "check unavailable" — warn the user and wait for explicit go-ahead, never proceed silently as if there were no exclusions. This closed a ~30%-of-credits leak where enrichment ran against companies already contacted or suppressed.
19. **Log every paid call.** After every Prospeo `/search-person`, `/bulk-enrich-person`, and AI Ark `/v1/people` call, `navreo_db.log_provider_usage(provider, credits, endpoint=..., source_id="lilly-decision-maker-finder")`. This is the spend ledger the cost audits read from — skipping it hides real spend.

---

## Quick reference

| Need | Endpoint | Auth | Cost |
|---|---|---|---|
| **Find people (PRIMARY)** | `POST api.prospeo.io/search-person` | `X-KEY` | 1 / page (25 results) |
| Verify emails | `POST api.prospeo.io/bulk-enrich-person` (`only_verified_email: true`) | `X-KEY` | 1 / match |
| Verify phones | `POST api.prospeo.io/bulk-enrich-person` (`enrich_mobile: true`) | `X-KEY` | 10 / verified mobile |
| **Find people (FALLBACK)** | `POST api.ai-ark.com/api/developer-portal/v1/people` | `X-TOKEN` | per DM returned |
| Check Prospeo balance | `POST api.prospeo.io/account-information` | `X-KEY` | free |
| **Cache write (after every fetch)** | `~/.navreo-cache/{prospeo,ai_ark}/{companies,people}/{key}.json` | n/a | free, mandatory |
| **MV double-check (end-of-run hand-off)** | `lilly-email-verification` on Prospeo-source emails | n/a | 1 MV credit / email, flat |

See also: `reference_dm_finder_apis.md` (memory) for full schema details; `feedback_no_ocean_people_search.md` for the Ocean people-search ban rationale; `lilly-icebreaker/SKILL.md` for the cache consumer; `lilly-email-verification/SKILL.md` for the MillionVerifier hand-off contract.


## Upload gate (MANDATORY)

Before ANY lead push into a Smartlead campaign that results from this skill (`add_leads_to_campaign` or equivalent), hand off to `lilly-upload-gate` and let it run to a green gate: every enabled check PASS or explicitly OVERRIDDEN per-flag, and the audit row written to `list_upload_qa_runs` BEFORE the first add-leads call. Never upload around the gate.
