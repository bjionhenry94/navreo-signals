# Navreo Default Preset — "Sales Leaders" qualification

This is the original criteria Bjion was using inside Clay before this skill existed. Use it as the default when the user says any of:

- "use the sales-leaders preset"
- "use the Navreo default"
- "same criteria as the 6Sense / Boomerang / ColdIQ / Smartlead-Full / Outplay run"
- "qualify this with the standard ICP"

When using this preset, **still confirm with the user** in Step 0 — summarise it back in 4-6 lines and ask "still this?" before running. Defaults drift; the user may want to tweak the location or avoid-list for this run.

---

## Original Prompt 1 — Role / Location / Company Size qualification

> You're an expert HR manager. Your task is to evaluate the role, location, and
> company size of a potential new hire. You must determine if they fit the
> specified criteria below.
>
> ____
>
> **Role Criteria:**
>
> Head of Sales, Demand Generation, Founding Member, Head of Partnerships, VP
> Sales, Vice President Sales, Sales Director, Director of Sales, Sales Leader,
> Sales Head, Chief Sales Officer, CSO, Chief Revenue Officer, CRO, Chief Growth
> Officer, CGO, Head of Revenue, VP Revenue, Revenue Director, Director Revenue
> Operations, RevOps Director, Head of RevOps, Sales Operations Director, Head of
> GTM, GTM Director, GTM Head, Go-To-Market Lead, Commercial Director, Commercial
> Head, VP Commercial, VP Growth, Growth Director, Head of Growth, VP Global
> Sales, VP Field Sales, Head Enterprise Sales, Head Strategic Sales, Senior
> Director Sales, Global Sales Director, Regional Sales Director, International
> Sales Director, VP Inside Sales, Head Inside Sales, VP Sales Strategy, Sales
> Strategy Director, Head Sales Enablement, Director Sales Enablement, CEO, Chief
> Executive Officer, Business Head, Country Head, Director of Sales Development,
> Market Head, Managing Partner or similar roles, Founder, Co-Founder or any
> sales related roles director and above, Chief Marketing Officer, CMO, VP
> Marketing, Vice President Marketing, Marketing Director, Director of Marketing,
> Senior Marketing Director, Global Marketing Director, Regional Marketing
> Director, Head of Marketing, Head of Global Marketing, Head of Brand, Brand
> Director, Director of Brand, Director of Demand Generation, VP Demand
> Generation, Head of Demand Generation, Director of Growth Marketing, VP Growth
> Marketing, Head of Growth Marketing, Performance Marketing Director, VP
> Performance Marketing, Head of Performance Marketing, Director of Digital
> Marketing, VP Digital Marketing, Head of Digital Marketing, Director of Field
> Marketing, VP Field Marketing, Head of Field Marketing, Director of Product
> Marketing, VP Product Marketing, Head of Product Marketing, Director of
> Marketing Operations, VP Marketing Operations, Head of Marketing Operations,
> Director of Communications, VP Communications, Head of Communications, Director
> of Corporate Marketing, Director of Strategic Marketing, VP Strategic
> Marketing, Head of Strategic Marketing or similar marketing roles director and
> above.
>
> If their title includes multiple roles (e.g., "Co-Founder & CTO"), as long as
> one title meets the criteria, respond "Yes."
>
> If they are a CEO (co-founder, founder, owner, co-owner or similar), their role
> evaluation should always pass.
>
> ____
>
> **Location Criteria:** High salary or high GDP countries
> *(originally "Any Location"; updated mid-conversation to high-GDP preset)*
>
> ____
>
> **Company Size Criteria:**
>
> Anything above 10 unless they're from the United States (but their company must
> be older than 5 years. If they're not, mark as disqualified)

### Clarifications captured during the original run

1. **Company size rule, refined:** Employees > 10 required for everyone. If US-based, company must also be founded > 5 years ago.
2. **Location field for the US check:** company location, not person location.
3. **Missing data → disqualify** (rather than "needs review").
4. **Output format:** export only the "Yes" rows.
5. **High-GDP location preset** = US, CA, UK, IE, AU, NZ, DE, NL, CH, SE, NO, DK, FI, SG, JP, HK, UAE, KSA, IL, plus AT, BE, LU, FR, IT, ES (the OECD + GCC 24-country set).

---

## Original Prompt 2 — Avoid-list / Lead-scoring

> Your task is to identify if the following company should be avoided in sales
> outreach.
>
> Company description of the sender:
>
> These are the other types of businesses which would be classified as a company
> to avoid:
>
> Sales enablement, GTM, go-to-market, cold-outbound, outreach, GTM lead
> generation, outbound prospecting, appointment setting, sales outsourcing, ABM,
> anything sales related, generating revenue, or revenue operations services to
> other companies.
>
> Reply a simple "1 - [Reason]" (if it should be avoided) or "5 - [Reason]" (if
> it should be allowed)
>
> Response guide:
> - If this prompt includes "[insert here]" say "Please edit this column and add
>   companies to avoid"

---

## Equivalent JSON config for `qualify_list.py`

When the user picks the Navreo default preset, run `qualify_list.py` with this config:

```json
{
  "role_criteria": {
    "titles": [
      "Head of Sales", "VP Sales", "Vice President Sales", "Sales Director",
      "Director of Sales", "Sales Leader", "Sales Head", "Chief Sales Officer",
      "CSO", "Chief Revenue Officer", "CRO", "Chief Growth Officer", "CGO",
      "Head of Revenue", "VP Revenue", "Revenue Director", "RevOps Director",
      "Head of RevOps", "Sales Operations Director", "Head of GTM",
      "GTM Director", "GTM Head", "Go-To-Market Lead", "Commercial Director",
      "Commercial Head", "VP Commercial", "VP Growth", "Growth Director",
      "Head of Growth", "VP Global Sales", "VP Field Sales",
      "Head Enterprise Sales", "Head Strategic Sales", "Senior Director Sales",
      "Global Sales Director", "Regional Sales Director",
      "International Sales Director", "VP Inside Sales", "Head Inside Sales",
      "VP Sales Strategy", "Sales Strategy Director", "Head Sales Enablement",
      "Director Sales Enablement", "CEO", "Chief Executive Officer",
      "Business Head", "Country Head", "Director of Sales Development",
      "Market Head", "Managing Partner", "Founder", "Co-Founder",
      "Founding Member", "Head of Partnerships", "Head of Demand Generation",
      "Demand Generation",
      "Chief Marketing Officer", "CMO", "VP Marketing",
      "Vice President Marketing", "Marketing Director", "Director of Marketing",
      "Senior Marketing Director", "Global Marketing Director",
      "Regional Marketing Director", "Head of Marketing",
      "Head of Global Marketing", "Head of Brand", "Brand Director",
      "Director of Brand", "Director of Demand Generation",
      "VP Demand Generation", "Director of Growth Marketing",
      "VP Growth Marketing", "Head of Growth Marketing",
      "Performance Marketing Director", "VP Performance Marketing",
      "Head of Performance Marketing", "Director of Digital Marketing",
      "VP Digital Marketing", "Head of Digital Marketing",
      "Director of Field Marketing", "VP Field Marketing",
      "Head of Field Marketing", "Director of Product Marketing",
      "VP Product Marketing", "Head of Product Marketing",
      "Director of Marketing Operations", "VP Marketing Operations",
      "Head of Marketing Operations", "Director of Communications",
      "VP Communications", "Head of Communications",
      "Director of Corporate Marketing", "Director of Strategic Marketing",
      "VP Strategic Marketing", "Head of Strategic Marketing"
    ],
    "founder_tier_always_passes": true
  },
  "location_criteria": {
    "mode": "high_gdp_preset",
    "match_field": "company"
  },
  "size_criteria": {
    "min_employees": 11,
    "us_min_age_years": 5,
    "skip_if_missing": false
  },
  "avoid_list": {
    "sender_description": "Navreo runs outbound sales campaigns for B2B companies — Smartlead infrastructure, copy, and booked meetings.",
    "categories": [
      "sales enablement", "gtm services", "go-to-market services",
      "cold outbound", "cold email", "cold calling",
      "lead generation", "leadgen", "appointment setting",
      "sales outsourcing", "outsourced sales",
      "demand generation agency", "abm services",
      "account-based marketing services",
      "outbound agency", "outbound prospecting", "prospecting service",
      "pipeline generation", "sales consulting", "sales consultancy",
      "sales agency", "revenue operations services", "revops services",
      "outreach agency", "outreach platform",
      "fractional cmo", "fractional cro", "fractional sales leader",
      "sdr as a service", "bdr as a service"
    ],
    "brand_names": [
      "Smartlead", "Apollo", "Clay", "Outreach.io", "Instantly", "Lemlist",
      "Salesloft", "Gong", "Reply.io", "Lavender", "Smartwriter", "Hyperise",
      "Belkins", "Cience", "Operatix", "MarketStar", "Pearl Lemon",
      "INFUSE", "Anteriad", "TechTarget", "Demand AI", "Madison Logic",
      "Showpad", "Highspot", "Seismic", "Mindtickle"
    ]
  },
  "output": { "dedupe_by_company": false }
}
```

Drop this into a file (e.g. `/tmp/navreo_default_config.json`) and run:

```bash
python3 .claude/skills/lilly-company-followers/scripts/qualify_list.py \
    --input <path-to-csv> \
    --config /tmp/navreo_default_config.json
```

---

## When to deviate from this preset

The preset is calibrated to **outbound services for B2B companies, broad sales/marketing leadership ICP**. Reach for a different config if any of these are true for the upload:

- The campaign targets a narrower function (e.g. only Marketing leaders, only Founders) — drop the unused titles
- The sender's pitch isn't outbound-services — rebuild the avoid-list around the actual competitor set
- The list is regional (e.g. all Australia) — switch `location_criteria.mode` to `"allowlist"` with the explicit country list
- The list is from a known-clean source where the ICP and avoid-list were already enforced upstream — relax to a role-only check (set `mode: "any"` and clear the avoid-list categories)

When in doubt, send the full Step-0 template with the preset values pre-filled and let the user override individual sections.
