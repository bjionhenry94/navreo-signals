# Skill Updates Backlog

Pending fixes/improvements to skills, captured during real runs. Apply in batches when iterating on skill files.

---

## Source runs (both 2026-05-04)

- **Run A — Influencer-marketing TAM** (`lilly-tam-mapper` end-to-end)
- **Run B — Interior Design TAM** (mapper → DM-finder → Smartlead campaign 3278380; 5,330 cos → 2,295 verified DMs; ~2,757 cr)

14 unique items consolidated from 19 across both runs (5 deduped).

---

## Implementation order (priority — highest leverage first)

Items where BOTH runs flagged the same thing get top priority (highest confidence).

1. ⏳ **Smartlead lead schema** (#1) — BOTH runs; affects every campaign push; pure doc fix
2. ⏳ **Prospeo bulk-enrich hardening** (#2) — silent failure mode; misparsed 4,500 records in Run B; biggest cost-saver
3. ⏳ **Drift-control bundle** (#3 + #4 + #5) — brand-recog gate + Ocean p4 cap + blocklist; ~150 cr wasted in Run A; ship together
4. ⏳ **AI Ark documentation** (#6) — basic-tier filter rules + response shape under `summary.*`; saves 4-5 cr + 2 turns
5. ⏳ **Soft-category exclusion-bias recipes** (#7) — 5 cr + 4 turns saved per soft brief
6. ⏳ **Multi-level TLD strip** (#8) — 1-2 turns saved mid-sweep
7. ⏳ **Ocean V3 geography filter doc** (#9) — `primaryLocations` (HQ-strict) + presence-based default
8. ⏳ **Stage 1 = exactly 2 angles** (#10) — never industries-only
9. ⏳ **SaaS sub-vertical parallel pot** (#11) — split when ≥20% drift is coherent adjacent
10. ⏳ **3-column comms standard** (#12) — Verified / Estimated / Pulled
11. ⏳ **Pre-flight DM cost projection** (#13) — per-USEFUL-lead cost surfacing
12. ⏳ **Streamline dual-skill role confirmation** (#14) — UX polish

Mark with ✅ as each is merged into the target skill file.

---

## Items

### 1. Smartlead canonical lead schema — `lilly-bot`

**Source:** Run A first `add_leads_to_campaign` failed with `"company" is not allowed`. Run B got `400: "lead_list[i].company is not allowed"` plus `title` rejected at top-level — two failed pushes. The MCP wrapper schema (`mcp__smartlead__smartlead_add_leads_to_campaign`) lists `company` and `title` as accepted, which is misleading.

**Change:** Add canonical lead-schema reference to `lilly-bot`:

```
ALLOWED top-level fields:
- email (required)
- first_name
- last_name
- phone_number   (NOT "phone")

EVERYTHING ELSE goes in custom_fields:
- company_name (NOT "company" — both top-level "company" AND "company_name" are rejected)
- title
- website
- country
- linkedin
- segment
- LinkedinURL, company_domain, etc.

Wrong (will 400):
{ "email": "x@y.com", "first_name": "A", "company": "B", "title": "CEO" }

Correct:
{ "email": "x@y.com", "first_name": "A",
  "custom_fields": { "company_name": "B", "title": "CEO", ... } }
```

**Hard rule:** always send 1 test lead first to confirm schema, then batch the rest.

Also: separately request that the MCP wrapper's tool schema be tightened to match the actual API.

---

### 2. Prospeo bulk-enrich hardening — `lilly-decision-maker-finder`

Three issues found across both runs; ship as one hardening pass.

#### 2a. Response shape doc fix

**Source (Run B):** Skill's "Reference: Prospeo bulk-enrich response" implies status is at `matched[i].status`. Actual is `matched[i].person.email.status` (and email is at `matched[i].person.email.email`, not `matched[i].person.email` as a string). Misparsed 4,500 enrichments → 0 verified emails captured. Re-fire hit cache and was free, but cost a turn + ~3 min debugging.

**Change:** Add worked example:

```
matched[i] structure (verified-on-2026-05-04):
{
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
      "email": "name@domain.com", ← actual email string
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

Plus: top-level `not_matched` is a separate array of identifiers (NOT inside `matched` with `status: NO_MATCH`).

#### 2b. NO_MATCH ≠ rate-limit; concurrency 2-3 max

**Source (Run A):** Treated `error_code: "NO_MATCH"` as retryable, re-fired same batches 4 times. NO_MATCH is FREE and TERMINAL. Plus 8-way concurrency hit rate limits on 104/195 batches.

**Change:** In Step 4, explicitly distinguish:
- `error_code: "NO_MATCH"` → free, terminal, mark all 10 in batch as no-match, do NOT retry.
- `error_code: "Rate limit exceeded"` → only retryable error. Backoff 1.5s.
- Other `error: true` → log + skip.

Max concurrency for bulk-enrich: **2–3 sequential workers** (8-way breaks).

#### 2c. 1-record probe before scaling

**Source (Run B):** Bulk-enrich response-shape misparse went undetected for 4,500 records. A 1-record probe at the start would have surfaced it.

**Change:** Add to Step 4 — before paginating batches:

```
0. PROBE: fire a single bulk-enrich call with 1 DM (the first verified-search result).
   Verify the parser correctly extracts:
     - matched[0].person.email.status == 'VERIFIED'
     - matched[0].person.email.email is a string ending in @domain
   If parser fails or returns 0 verified, HALT and inspect raw response before scaling.
   Cost: 1 cr (or 0 if cached). Skips the silent-fail trap.
```

---

### 3. Brand-recognition pre-DM-enrichment gate — `lilly-tam-mapper`

**Source (Run A):** Ocean Phase 4 SaaS-lookalike paginated 7 pages while precision held >50%, but late pages (5–8) drifted into big-brand cos: Tesla (105 leads), Meltwater (20), Ogilvy (6), Chargebee (5), NetSuite, Lusha, etc. ~157 of 586 enriched leads were off-brief. ~150 Prospeo credits wasted. ~42 polluted the Smartlead campaign before manual cleanup.

**Change:**
- Add new **Stage 4 — Robust Validation** (between Stage 3 results and DM hand-off): mandatory **brand-recognition spot-check**. Surface top 30 cos in qualified+borderline pots ranked by employee count / web traffic / LinkedIn followers. User reviews; obvious off-brief brands (Tesla, Walmart, Microsoft) get flagged → off-brief pot.
- Or auto-WebFetch-verify any co in TAM with >2,000 employees (the "drift attractor" threshold).
- Block DM hand-off until validation passes.

---

### 4. Cap Ocean Phase 4 lookalike pagination at page 4 — `lilly-ocean-tam-builder`

**Source (Run A):** SaaS-lookalike precision held >50% through page 7 — but pool QUALITY decayed by brand-size, not just hit-rate. The 40% off-brief at deep pages concentrated in big tech brands that pollute disproportionately.

**Change:**
- In Phase 4, **hard cap lookalike pagination at page 4 (200 cos)** unless user explicitly overrides AND brand-recognition verify (#3) runs first.
- Filter-driven (keyword) searches keep existing 50% precision-floor rule — they don't have the same drift pattern.

---

### 5. Persistent off-brief domain blocklist — `lilly-tam-mapper`

**Source (Run A):** Same recurring pattern across runs — Tesla, Meltwater, NetSuite, Chargebee, Lusha, Cognism, Belkins, Hawke Media, Patreon all drift into TAMs they shouldn't be in.

**Change:**
- Add `lilly-tam-mapper/off_brief_blocklist.json` — persistent list of domains that consistently drift.
- Auto-exclude from every TAM build (added to seed exclude list at Stage 1 start).
- After each run, prompt: "Any new drift attractors to add to blocklist?" — accumulates over time.
- Seed list: tesla.com, meltwater.com, netsuite.com, chargebee.com, lusha.com, cognism.com, belkins.io, hawkemedia.com, patreon.com, jasper.ai, ogilvy.com, mcsaatchiperformance.com.

---

### 6. AI Ark documentation pass — `lilly-ai-ark-list-builder` + `lilly-tam-mapper` + `lilly-decision-maker-finder`

Two issues found across both runs; ship as one doc pass.

#### 6a. Basic-tier hard rule — stop probing

**Source (Run B):** Skill memory says basic-tier drops `account.*` filters but doesn't strongly tell future-Claude to STOP probing. Ran D1 (filter-tier check, failed → basic-tier confirmed), then later when re-asked, ran 4 more keyword probe variations to be exhaustive — all confirmed silently dropped (totalElements=17.2M, top results Amazon/Walmart/McDonalds across all shapes). 4 wasted credits + 2 wasted turns.

**Change:** Add to Step 2 (diagnostic):

```
HARD RULE on basic-tier: if D1 fails, the ONLY working filters are:
  - lookalikeDomains (max 5 seeds)
  - account.location.any.include (geo)

DO NOT probe further. Specifically:
  - account.industry.any.include → silently dropped
  - account.headcount.any.include → silently dropped
  - account.keywords.any.include → silently dropped (confirmed across 4 shapes 2026-05-04)
  - top-level "keywords" → not recognised
  - top-level "query" → not recognised

Only path forward on basic-tier:
  - Fire 3-5 lookalike passes with DIFFERENT seed clusters (US-seeds, UK-seeds, UAE-seeds, AU/SG-seeds)
  - Each pass opens a different cluster (lookalike clusters skew to seed nationality)
  - Client-side filter results on HQ + headcount + cumulative excludes
```

#### 6b. Response shape — fields nested under `summary`

**Source (Run A):** First AI Ark Path B run extracted `c.get('name')` and `c.get('description')` directly — both empty, all 25 cos classified as borderline. Correct paths nest under `summary`.

**Change:** Update reference sections with complete response shape:

- `summary.name`, `summary.description` (or `summary.seo`), `summary.industry`
- `summary.staff.range.{start,end}`, `summary.staff.total`
- `link.domain_ltd`
- `location.headquarter.country`

Add a Python "extraction example" helper.

---

### 7. Soft-category exclusion-bias recipes — `lilly-tam-mapper` + `lilly-ocean-tam-builder`

**Source (Run B):** "Interior design" brief flooded with SaaS / blogs / e-commerce / magazines on first sample (only 25 → 5 looked like real ID firms). Required iterative tightening with `linkedinIndustries: ["Design Services"]` + `excludeIndustries: ["Software", "SaaS", "Blogging Platforms", "Lifestyle"]`. ~5 wasted credits + 4 turns of fiddling.

**Change:** Add brief→filter recipe map to Stage 0:

```
Soft-category brief recipes (default to EXCLUSIONS rather than tight inclusions
— inclusions over-qualify and miss valid cos with ambiguous tags;
exclusions are safer because they only drop confirmed off-brief categories):

| Brief                           | excludeIndustries                                              |
|---------------------------------|----------------------------------------------------------------|
| Interior design firms           | Software, SaaS, Blogging Platforms, Lifestyle                  |
| Architecture firms              | Software, SaaS, Blogging Platforms, Construction (if ID-only)  |
| Design agencies                 | Software, SaaS, Blogging Platforms, E-Commerce                 |
| Marketing agencies              | Software, SaaS, Blogging Platforms                             |
| Consulting firms                | Software, SaaS, Blogging Platforms, Recruiting                 |

Also default `linkedinIndustries` SOFTLY (e.g., for ID firms try
"Design Services" first; if recall too narrow, drop the linkedinIndustries
filter and rely on excludeIndustries alone — confirmed 2026-05-04 that
LinkedIn classifies many EU/AU ID firms as "Design" or "Architecture &
Planning" rather than "Design Services", so a strict include cuts recall).
```

**Bjion's note:** "Inclusion filter over-qualifies, but exclusions feel safer that's fine." Action: prefer exclusions; use linkedinIndustries inclusion only as a softener, not a hard gate.

---

### 8. Multi-level TLD strip pre-flight — `lilly-prospeo-list-builder` + `lilly-decision-maker-finder`

**Source (Run B):** Prospeo rejects domains with multi-level TLDs like `.uk.com`, `.us.com`, `.eu.com` with `INVALID_FILTERS: Subdomains are not supported`. Two batches in sweep aborted mid-flight on single offenders (`luckyfox.uk.com`, `massa.us.com`). Required re-fire after stripping.

**Change:** Add to Step 1 (input prep) in both skills, before first paid call:

```python
def is_invalid_subdomain(d):
    parts = d.lower().split('.')
    return len(parts) >= 3 and parts[-2] in ('uk','us','eu','gb','de','ca') and parts[-1] == 'com'

# Strip these before any company.websites.include or company.websites.exclude call
domains = [d for d in domains if not is_invalid_subdomain(d)]
```

Surface dropped domains as "N domains stripped (Prospeo rejects multi-level TLDs)".

---

### 9. Ocean V3 geography — `primaryLocations` + presence-based default — `lilly-ocean-tam-builder`

Two complementary fixes — ship together.

#### 9a. Default to presence-based `countries`

**Source (Run A):** Skill defaulted to client-side `primaryCountry` filter (HQ-only), dropping ~25-50% of results. User clarified Ocean's native presence-based `countries` filter is enough.

**Change:** Flip the default in Phase 2/3: trust Ocean's native presence-based `countries` filter. HQ-only client-filter becomes **opt-in** for explicit HQ-targeting briefs (DM-enrichment where DM-at-HQ is a hard requirement). Update `hq_tam_estimate` reporting: only project HQ-rate when HQ-filter is active.

#### 9b. Document `primaryLocations` for HQ-strict

**Source (Run B):** Skill mentions presence-based filter but doesn't document the dedicated HQ filter `primaryLocations.includeCountries`. Ran two parallel searches (strict-5 vs wide-GDP) and got identical results because both used presence-based `countries`. Lost a turn on diagnosis.

**Change:** Add to "V3 filter shapes" table:

```
| primaryLocations | {includeCountries:[...], excludeCountries:[...]} | HQ-strict country filter (NOT presence-based). Use this when you need exact HQ match. Cheaper than client-filtering downstream. |
| otherLocations  | same shape | Any non-HQ office country |
```

For split-geo briefs (e.g. "1-10 employees only in US/UAE/Spain, 11-50 in wider GDP set") the presence-based `countries` filter cross-contaminates. `primaryLocations` solves it server-side.

---

### 10. Stage 1 = exactly 2 angles, never 3 — skip industries-only — `lilly-tam-mapper` + `lilly-ocean-tam-builder`

**Source (Run A):** First Stage 1 fired three isolated angles. Industries-only returned **304,462 raw with 0/15 = 0% sample precision** — pure generic marketing/advertising umbrella. 1 wasted credit.

**Change:** In `lilly-tam-mapper` Stage 1 + `lilly-ocean-tam-builder` Phase 1.5, **hard rule**: Stage 1 fires exactly 2 isolated angles — `keyword-only` + `lookalike-only`. Never `industries-only`.

Industry is a **narrowing layer**, never a standalone angle. If industry-anchored is wanted, pair with `lookalikeDomains` OR `keywords.anyOf` — but never alone.

---

### 11. SaaS / platform sub-vertical as separate seed cluster on soft-category briefs — `lilly-tam-mapper`

**Source (Run A):** When agency lookalike call drifted toward SaaS platforms (CreatorIQ, Grin, Aspire, etc.), user pointed out SaaS is actually a viable adjacent pot — better treated as parallel pot than off-brief.

**Change:** In Stage 1, after first lookalike call's sample is classified, if ≥20% of returns are a coherent adjacent sub-vertical, **propose splitting into a parallel sub-vertical pot with its own tight-seed cluster** rather than flagging them as off-brief.

Compounds with rule #22 (per-sub-vertical tight seed clusters): platform-drift cos become seeds for a SECOND tight cluster.

Track multiple parallel pots (e.g. `qualified_agency.csv`, `qualified_saas.csv`) with cumulative excludes shared across both.

---

### 12. Strict 3-column communication standard — `lilly-tam-mapper` + `lilly-ocean-tam-builder`

**Source (Run A):** During Stage 1 I presented "110 verified" without clearly framing it as a sample. User pushed back: sample-verified ≠ total TAM ≠ full list pulled.

**Change:** Every progress update must use the **fixed 3-column format**:
1. **Verified (sample)** — what's been classified from sampled pages.
2. **Estimated TAM** — raw `total_count` × sample precision.
3. **Pulled (full)** — what's actually been paginated.

Never collapse the columns. Never report a single number without specifying which.

After each provider's sample, surface the **Estimated TAM** explicitly and ask the user to confirm before paginating to "Pulled (full)".

Process unchanged — safe-mode 20-co batches, halt at <50% precision. Only framing changes.

---

### 13. Pre-flight DM enrichment cost projection + per-lead cost surfacing — `lilly-decision-maker-finder`

**Source (Run A):** Projected ~1,247 cr but actual was ~720 cr (lower verify rate than expected). Per-lead cost was 1.54 cr/lead (~30% off-brief, so true effective cost ~1.7 cr/useful-lead).

**Change:** After Prospeo TAM probe, surface:
- Projected verified emails (TAM × verify rate)
- Projected total credits (search + enrich)
- Projected **per-USEFUL-lead cost** (after expected off-brief drop) — only meaningful if #3 brand-recognition gate has been run.

---

### 14. Streamline dual-skill role confirmation — `lilly-decision-maker-finder`

**Source (Run B):** When `lilly-tam-mapper` hands off to `lilly-decision-maker-finder` with role specs in the args, the DM-finder skill MANDATES a fresh full-menu role question from the user. Duplicate ask — user already provided the role list once. Adds a turn + cognitive load.

**Change:** Modify Step 1 (Input & confirm) — when `args` contains a role list:

```
1. Detect role spec in caller args (look for "founder", "owner", "director", "manager", etc.)
2. Restate the inferred role list in ONE line
3. Ask: "Confirm titles below or override:" + show curated title list (English) + seniority+department (non-English)
4. User can reply "yes" / "skip Account Manager" / specific override — no need to walk full A-H menu
```

Full A-H menu only fires when no role spec was provided in args (standalone DM-finder runs).

---

## Skipped recommendations (do not action)

- **Step 3 title filter tightening** (Run B) — assignment-specific (interior design firms vs other service businesses use different off-keyword sets); handled per-brief with existing OFF_KW list as starting point.
- **Default `size: 5000` on Ocean** (Run B) — current default of 50 is fine for sampling; user prefers explicit pagination control over one-shot full pull.
- **Saturation halt by industry-tag drift** (Run B) — current saturation logic (net-new rate < 25%) is sufficient.
