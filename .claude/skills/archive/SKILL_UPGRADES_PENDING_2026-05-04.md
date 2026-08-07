# Skill Upgrades — Pending

Temporary tracker for skill upgrades identified during real runs. Each entry is actioned/queued; tick off when the change is merged into the target skill.

---

## Source: Interior Design TAM build (2026-05-04, Bjion)

End-to-end run: TAM mapper → 5,330 cos → DM-finder → 2,295 verified DMs → Smartlead campaign 3278380. Total ~2,757 cr spent, ~10-15 turns of friction from skill-doc gaps. Reflection captured here so the next run is tighter.

### 1. Document `primaryLocations` for HQ-strict geo filter (Ocean v3) — `lilly-ocean-tam-builder`

**Problem:** Skill mentions Ocean's `countries` filter is presence-based ("always client-filter on `primaryCountry`") but doesn't document the dedicated HQ filter `primaryLocations.includeCountries`. I ran two parallel searches (strict-5 vs wide-GDP) and got identical results because both used the presence-based `countries` filter — every co with ANY office in the target country list ranked. Lost a turn on diagnosis.

**Change:** Add to "V3 filter shapes" table:
```
| primaryLocations | {includeCountries:[...], excludeCountries:[...]} | HQ-strict country filter (NOT presence-based). Use this when you need exact HQ match. Cheaper than client-filtering downstream. |
| otherLocations  | same shape | Any non-HQ office country |
```

**Why this matters:** for split-geo briefs (e.g. "1-10 employees only in US/UAE/Spain, 11-50 in wider GDP set") the presence-based `countries` filter cross-contaminates. `primaryLocations` solves it server-side.

---

### 2. Fix Prospeo bulk-enrich response shape doc — `lilly-decision-maker-finder`

**Problem:** Skill's "Reference: Prospeo bulk-enrich response" implies status is at `matched[i].status`. Actual is `matched[i].person.email.status` (and email is at `matched[i].person.email.email`, not `matched[i].person.email` as a string). I parsed wrong, ran 4,500 enrichments, captured 0 verified emails. Prospeo charged the run anyway. Fortunately a re-fire hit cache and was free, but it cost a turn + ~3 min of debugging.

**Change:** Add a worked example to the skill:
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

---

### 3. Multi-level TLD strip pre-flight — `lilly-prospeo-list-builder` + `lilly-decision-maker-finder`

**Problem:** Prospeo rejects domains with multi-level TLDs like `.uk.com`, `.us.com`, `.eu.com` with `INVALID_FILTERS: Subdomains are not supported`. Two batches in my sweep aborted mid-flight because of single offenders (`luckyfox.uk.com`, `massa.us.com`). Required a re-fire after stripping.

**Change:** Add to Step 1 (input prep) in both skills, before the first paid call:
```python
def is_invalid_subdomain(d):
    parts = d.lower().split('.')
    return len(parts) >= 3 and parts[-2] in ('uk','us','eu','gb','de','ca') and parts[-1] == 'com'

# Strip these before any company.websites.include or company.websites.exclude call
domains = [d for d in domains if not is_invalid_subdomain(d)]
```
Surface dropped domains to the user as "N domains stripped (Prospeo rejects multi-level TLDs)".

---

### 4. Smartlead lead schema — `lilly-bot`

**Problem:** Smartlead's `add_leads_to_campaign` API rejects `company` and `title` as top-level fields with `400: "lead_list[i].company is not allowed"`. The MCP wrapper schema (`mcp__smartlead__smartlead_add_leads_to_campaign`) lists both as accepted properties, which is misleading. Two failed pushes before figuring out the actual shape.

**Change:** Add to lilly-bot's Smartlead lead-schema reference:
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
- (any other lead-level merge variables)

Wrong (will 400):
{ "email": "x@y.com", "first_name": "A", "company": "B", "title": "CEO" }

Correct:
{ "email": "x@y.com", "first_name": "A",
  "custom_fields": { "company_name": "B", "title": "CEO", ... } }
```

Also: separately request that the MCP wrapper's tool schema be tightened to match the actual API.

---

### 5. AI Ark basic-tier — hard rule, skip exhaustive keyword probe — `lilly-ai-ark-list-builder` + `lilly-tam-mapper`

**Problem:** Skill memory says basic-tier drops `account.*` filters but doesn't strongly tell future-Claude to STOP probing. I ran D1 (filter-tier check, failed → basic-tier confirmed), then later when re-asked, ran 4 more keyword probe variations to be exhaustive — all confirmed silently dropped (totalElements=17.2M, top results Amazon/Walmart/McDonalds across all shapes). 4 wasted credits + 2 wasted turns.

**Change:** Add a hard rule to Step 2 (diagnostic) in `lilly-ai-ark-list-builder`:
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

---

### 6. Streamline dual-skill role confirmation — `lilly-decision-maker-finder`

**Problem:** When `lilly-tam-mapper` hands off to `lilly-decision-maker-finder` with role specs in the args, the DM-finder skill MANDATES a fresh full-menu role question from the user. Duplicate ask — user already provided the role list once. Adds a turn + cognitive load.

**Change:** Modify Step 1 (Input & confirm) — when `args` contains a role list:
```
1. Detect role spec in caller args (look for "founder", "owner", "director", "manager", etc.)
2. Restate the inferred role list in ONE line
3. Ask: "Confirm titles below or override:" + show the curated title list (English) + seniority+department (non-English)
4. User can reply "yes" / "skip Account Manager" / specific override — no need to walk the full A-H menu
```
The full A-H menu only fires when no role spec was provided in args (standalone DM-finder runs).

---

### 7. Soft-category pre-prescription with exclusion bias — `lilly-tam-mapper` + `lilly-ocean-tam-builder`

**Problem:** "Interior design" brief flooded with SaaS / blogs / e-commerce / magazines on first sample (only 25 → 5 looked like real ID firms). Required iterative tightening with `linkedinIndustries: ["Design Services"]` + `excludeIndustries: ["Software", "SaaS", "Blogging Platforms", "Lifestyle"]`. ~5 wasted credits + 4 turns of fiddling. Skill mentions "soft-category" gate generically but doesn't pre-prescribe the recipe.

**Change:** Add a brief→filter recipe map to `lilly-tam-mapper` Stage 0:
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

**Bjion's note (2026-05-04):** "Inclusion filter over-qualifies, but exclusions feel safer that's fine." Action: prefer exclusions; use linkedinIndustries inclusion only as a softener, not a hard gate.

---

### 8. 1-record bulk-enrich probe before bulk run — `lilly-decision-maker-finder`

**Problem:** Bulk-enrich response-shape misparse went undetected for 4,500 records (see item 2). A 1-record probe at the start would have surfaced the shape mismatch before scaling.

**Change:** Add to Step 4 (Prospeo bulk-enrich) — before paginating batches:
```
0. PROBE: fire a single bulk-enrich call with 1 DM (the first verified-search result).
   Verify the parser correctly extracts:
     - matched[0].person.email.status == 'VERIFIED'
     - matched[0].person.email.email is a string ending in @domain
   If parser fails or returns 0 verified, HALT and inspect raw response before scaling.
   Cost: 1 cr (or 0 if cached). Skips the silent-fail trap.
```

---

## Skipped recommendations (do not action)

- **Step 3 title filter tightening** — assignment-specific (interior design firms vs other service businesses use different off-keyword sets). Will be handled per-brief with the existing OFF_KW list as starting point.
- **Default `size: 5000` on Ocean** — current default of 50 is fine for sampling; user prefers explicit pagination control over one-shot full pull.
- **Saturation halt by industry-tag drift** — current saturation logic (net-new rate < 25%) is sufficient.

---

## Implementation order (priority — highest leverage first)

1. ⏳ Smartlead lead schema doc (item 4) — affects every campaign push, easiest win
2. ⏳ Prospeo bulk-enrich response shape (item 2) — silent failure mode, hardest to debug if hit
3. ⏳ AI Ark basic-tier hard rule (item 5) — saves 4-5 cr per run + 1-2 turns
4. ⏳ TLD strip pre-flight (item 3) — saves 1-2 turns mid-sweep
5. ⏳ `primaryLocations` doc (item 1) — saves 1 turn on geo-split briefs
6. ⏳ Soft-category exclusion-bias recipes (item 7) — saves 4-5 cr + iteration on soft briefs
7. ⏳ 1-record bulk-enrich probe (item 8) — defensive, low-effort
8. ⏳ Streamline dual-skill role confirm (item 6) — UX polish, minor

Mark with ✅ as each is merged into the target skill file.
