---
name: lilly-personalisation
description: "Bulk-fill personalisation custom fields on leads inside Smartlead campaigns — supports per-lead inferred fields (Why, Icebreaker, Pain) and bucketed fields (CaseStudy, proof points). Use this skill whenever the user wants to add, backfill, regenerate, or re-bucket lead-level personalisation, rename/correct case-study lines, add hard numbers, or move leads between buckets based on Why-text classification. Trigger when the user mentions filling Why, adding personalisation to a campaign, backfilling custom fields, generating per-lead merge variables, or updating/re-bucketing case studies. NOTE: standard-field hygiene (first_name + company_name normalisation) lives in lilly-qa Step 5d — run it BEFORE this skill so downstream Why/CaseStudy generation references clean {{company_name}} values."
---

# Lilly Personalisation

## Purpose

Bulk-generate and push personalisation custom fields into Smartlead campaigns. Two families of fields, each with its own approach:

**Per-lead inferred fields** — each value is uniquely inferred from company name / website / location / role. Each fragment must feel specific to that target company's ICP and product.
- `Why` — completes the sentence in Loom-style emails:
  > "I recorded a short video for {{company_name}} walking through how we'd **[WHY]**"
- `Icebreaker` — one-line soft opener
- `Pain` — one clause naming the pain the offer solves

**Bucketed fields** — values come from a small hand-crafted library mapped to verticals/business models. The same line is reused across all leads in a bucket.
- `CaseStudy` — vertical-specific proof points paired with a safe generic fallback

**Standard lead fields (`first_name`, `company_name`)** — these render directly in copy via `{{first_name}}` and `{{company_name}}`. Hygiene for them lives in `lilly-qa` Step 5d (cleaning rules + dry-run + push). Run that step **before** this skill so the downstream Why / CaseStudy generation references clean `{{company_name}}` values. See the "Pre-flight: run lilly-qa Step 5d" section below.

The skill can be extended to other custom fields using the same workflow.

---

## When to Use

Trigger whenever the user asks to:
- Fill missing Why fragments on a campaign
- Backfill a custom field across all leads
- Generate per-lead personalisation before launching a campaign
- Regenerate Why values because the offer or angle has changed

Accept input forms:
- "Fill missing Why for campaign 3175137"
- "Do it for: [ID]"
- "Are there any missing Why's for [campaign name]?" (first scan, then offer to fill)

---

## Inputs the User Provides

| Field | Required | Notes |
|---|---|---|
| Campaign ID | **Yes** | Numeric ID, not URL slug |
| API key | Usually | Default to the primary key if not provided. Navreo-titled campaigns on the secondary key `1417c9a6-6fff-433d-8ca4-f0913967a9c4_zto0vlj` per memory |
| Campaign type | Optional | Manufacturer / Distributor / SaaS / Services — inferred from sampling if not given |
| Custom field name | Optional | Defaults to `Why`. Other common ones: `Icebreaker`, `Pain`, `Hook` |

---

## The Why Pattern — Reference

Sampled from 4,000+ live filled fragments across multiple Navreo campaigns. **Always sample 5–10 filled leads in the target campaign first to calibrate** — the exact phrasing varies by offer.

### Structural template

```
[verb-phrase: help your / put your / get your / help your team book meetings with]
[team: sales team / marketing team / team]
[action: connect with / reach / book more meetings with / secure meetings with / put in front of / prioritize outreach to]
[target-ICP: specific buyer type — e.g., procurement managers at commercial construction firms]
[qualifier: actively sourcing / evaluating / specifying / seeking / reviewing / planning]
[product/category]
```

### Variations by campaign type

**Manufacturer / Product**
> "help your team reach the [buyers/contractors] sourcing [product] programs"
> "help your team reach the [OEMs/distributors] sourcing [specialty product] programs"

**Distributor / Wholesale**
> "help your sales team connect with [trade role] actively sourcing [product category]"

**Services / Contractor**
> "help your sales team connect with [decision-maker] actively commissioning [service]"
> "help your sales team connect with [homeowners/property managers] actively sourcing [service]"

**SaaS / Tech**
> "put your team in front of [ICP] actively evaluating [category] platforms"
> "get your team in front of [ICP] actively evaluating [category]"

**GenAI / Services-to-enterprise (the Hard/Soft campaigns)**
> "help your team book more meetings with [buyer] at [ICP companies]"
> "help your team meet more [ICP]"

**Professional Services / Advisory**
> "help your marketing team connect with [decision-makers] at [firm type] actively seeking [category] insights"

### Per-company inference rules

For each lead, infer the Why from:
1. **Company name** — reveals industry
2. **Website domain** — often clarifies (e.g., `.com.br` = Brazil, `roofing` in TLD)
3. **Location** — add geo qualifier if international ("UK homeowners", "Quebec contractors")
4. **Title** — *when available, always factor it in.* Title tells you what this specific person owns inside the company (sales / marketing / commercial / partnerships / operations / founder), and that should shape the Why's verb-phrase and team-noun. A "VP of Sales" deserves "help your sales team connect with…", a "Head of Partnerships" deserves "help your team open conversations with the partners…", a "CEO/Founder" deserves a more strategic frame ("help your team accelerate revenue from…"). The Why should land like it was written for *their* role and responsibilities, not just for their company in general.
5. **Email domain** — if it diverges from the website domain, can hint at a sub-brand or parent group

Knowledge to use:
- Well-known brands: use your trained knowledge directly (Toyota Insurance, Hornby Hobbies, etc.)
- Industry keywords in name: "Roofing" → roofing contractor, "Telecom" → telecom provider
- Unclear names: research the company (website TLD, email domain clues, LinkedIn, general knowledge, or web lookup). Keep investigating until you can name the lead's **product / service category** AND **who buys it**.

### Title-aware Why phrasing — examples

The same company should produce slightly different Whys for different titles. Some examples:

| Lead's title | Verb-phrase / team-noun shift |
|---|---|
| VP/Director/Head of Sales | "help your sales team connect with…" / "put your sales team in front of…" |
| VP/Director/Head of Marketing | "help your marketing team connect with…" / "get your marketing team in front of…" |
| VP/Director/Head of Partnerships / Alliances / BD | "help your team open conversations with the [partner-type] you want to bring on…" |
| Commercial Director / VP Commercial / CCO | "help your commercial team accelerate deals with…" |
| Revenue Director / CRO | "help your revenue team build pipeline with…" |
| CEO / Founder / Managing Director | "help you accelerate revenue from…" / "help your team capture more of the [ICP] market" — more strategic framing, less team-specific |
| Operations / Supply Chain / Procurement (when *they* are the buyer-side) | flip the frame — "help your team connect with [supplier/category] sourcing partners" only when context fits; usually these aren't the right ICP, flag instead |

**If title is missing or generic ("Manager", "Director" with no function, "Owner")** — fall back to the company-level Why without team-noun customisation. Do not invent a title-fit; "help your team connect with…" is a safe neutral default.

### NO UNIVERSAL FALLBACK — CRITICAL

Every Why **must** reference the specific lead's product, service category, buyer type, or business model. A fragment that could apply verbatim to any company is forbidden.

### Identification priority — LLM knowledge first, web fetch only when low confidence

Walk this order for every lead:

**1. LLM training knowledge (default path)** — try to identify the company from name + website domain + email domain + location using only what you already know about industries, brands, market structures, and category players. Most B2B companies in our pool are identifiable this way.

**2. Self-rate your confidence** before writing the Why. Ask honestly: "If I write a Why based purely on what I know about this company, would I bet $100 it's accurate?"

| Confidence | What it looks like | Action |
|---|---|---|
| **High** | You can name a specific product, service line, or business model with no hedging (e.g. "Cirata = WANdisco rebrand → big-data cloud migration"; "Direct365 = UK B2B essentials supplier"; "Raystech = Australian solar wholesaler") | Write the Why from training knowledge. Do NOT call WebFetch. |
| **Medium** | You can place the broad industry but not the specific product line (e.g. "this looks like a German lighting company but I'm not sure if they're consumer or industrial") | One WebFetch on the homepage to confirm. Then write. |
| **Low** | You truly do not know the company and the name + URL give no usable signal (e.g. "Taigle" with no website hits) | WebFetch + WebSearch. If both fail, **always populate the safe fallback Why** (see below) and flag with `confidence = "low_fallback_used"`. NEVER push an empty `Why` field, and NEVER push a Why like "buyers and decision-makers at enterprises actively reviewing partners in your category" (banned generic). |

**Bias toward "High"** — web fetches are slow, often blocked by Cloudflare/403, and waste tokens. If you can write a confident, specific Why from training knowledge, do it. Reserve fetches for genuine unknowns.

### CRITICAL — No-empty-field rule

**Every personalisation field that gets pushed must have a value.** An empty `{{Why}}` or `{{CaseStudy}}` renders as an obviously broken sentence in the email body, which damages deliverability and credibility worse than a slightly generic line ever will.

Apply these fallbacks at write-time, NOT at email-render time:

| Field | When empty | Fallback value |
|---|---|---|
| `Why` | Low-confidence row, identification truly failed | `help your team book more meetings with the buyers you're chasing` |
| `CaseStudy` | No bucket fit identified, agent skipped | The Fallback A line: `Last year we helped over 50 agencies and consultancies drive over $15 million in sales pipeline` |
| Any other custom field | Anything else flagged as empty | A safe generic specific to that field's purpose, OR drop the lead from the upload — never upload empty |

Also flag the row in a parallel `confidence` (or equivalent) column so the user can see which leads got fallbacks and patch them later if desired. Default tag values: `low_fallback_used` (Why), `casestudy_default_used` (CaseStudy).

**Rule of thumb**: A Why fragment that's specific is best, a Why fragment that's safely generic is acceptable, an empty Why is unacceptable. The fallback Why is grammatically clean inside the Loom-style email template (`I recorded a short video for {{company_name}} walking through how we'd help your team book more meetings with the buyers you're chasing`) — it reads as a real sentence even on rows where the lead's exact ICP couldn't be inferred.

### Speed implication — LLM-first means much faster batches

When the agent stays in High-confidence mode and skips WebFetch, batches of 50-100 leads complete in 1-3 minutes instead of 5-10. There's no rate-limit on training knowledge and no Cloudflare blocking. This is why the LLM-first priority isn't just a quality choice — it's also the throughput choice. Batches that previously needed multiple parallel agents to clear can now be done by a single agent in one pass.

Plan batch sizes accordingly: a single agent can comfortably handle 100 leads in one pass when the bias-to-High discipline is followed.

**3. Manual flag if all else fails** — if the company is genuinely unidentifiable after both LLM knowledge and web research, mark `why: null, notes: "could not identify"` and flag the lead. Never substitute a generic Why.

**Banned Why fragments** (any Why matching these exact patterns must be rejected and regenerated):
- "buyers and decision-makers at enterprises actively reviewing partners in your category"
- "decision-makers at your target accounts"
- "enterprises actively sourcing your core offering"
- "partners in your category"
- Anything with the placeholder word "category" that isn't a real named product/service category

The acid test before shipping a Why: **swap the company_name for a competitor's and ask yourself — does the Why still work?** If yes, it's too generic. Rewrite.

### The OTHER failure mode — too specific, paraphrasing their own copy (the AI tell)

There are two ways a Why fails. Too generic is one. The other, just as damaging, is **too specific**: a Why that paraphrases the prospect's own homepage tagline or value proposition back at them. It reads as obviously machine-written, because no human SDR memorises a stranger's marketing copy before reaching out. Examples of the over-specific tell (all real, all rejected):

- "help your team connect with eye-care practices adopting objective vision diagnostics" (lifted from a medical-device site's own copy)
- "help your team book demos with sales leaders ramping reps faster with AI coaching" (their product page, reworded)
- "help your team book calls with founders past $1M that need a real marketing leader" (their ICP statement, paraphrased)

**Second acid test: read the Why next to the prospect's homepage. If it sounds like you scraped their value prop and handed it back, it's too specific — rewrite it the way a person would actually describe who they sell to.** Plain beats clever:

- eye-care device maker → "help your team get in front of more eye-care practices"
- AI sales-coaching tool → "help your team book more demos with sales teams"
- fractional-CMO consultancy → "help your team sign more founder-led B2B companies"

The target is "who does this company sell to, in the words a human would use" — buyer type + their world (ecommerce brands, recruiters' hiring clients, public-sector teams, etc.) — NOT a restatement of the prospect's own positioning. Mild generality in plain language is more human and more credible than hyper-specific jargon echoed from their site. The sweet spot sits between the two acid tests: specific enough that the buyer is named, plain enough that it never sounds like their own copy.

### Banned words / style

- **Never** use "help your team with outreach" (too vague)
- **Never** start with "reach out to" (wrong voice)
- **Never** use "mid-market" — banned phrase, replace with specific size descriptors or drop entirely
- **Never** use the word "category" as a placeholder for an unknown product ("partners in your category" / "your category of platforms") — name the actual category
- Avoid em dashes — use regular hyphens only
- Each fragment should read like **one clause**, not a sentence
- Keep under ~150 characters
- No trailing period — it flows into the email copy

---

## The CaseStudy Pattern — Bucketed, Not Per-Lead

Some personalisation fields work better as a **small library of hand-crafted lines mapped to verticals**, rather than unique per-lead inference. The canonical example is `CaseStudy`. Same logic applies to proof-point fields, offer-framing fields, or any merge tag where you have a finite set of strong real case studies to reuse.

### When to use bucket-based vs per-lead

| Approach | Use when |
|---|---|
| Per-lead inference (Why, Icebreaker, Pain) | Each line must feel specific to THIS company |
| Bucketed (CaseStudy, proof points, offer variants) | A small set of real, hard-won case studies is re-used across leads in the same vertical |

### Case-study line structure

Pattern for vertical-specific lines:

```
We helped [BRAND NAME], a [ACCURATE DESCRIPTOR], [VERB + HARD NUMBER OUTCOME]
```

Winning examples (current Navreo library):

- `We helped SIHL, a 350-year-old wholesale manufacturer, add $1.6 million to their sales pipeline`
- `We helped TrAIDe, a distributor, secure 6-figure and 7-figure partnerships`
- `We helped TalentStream, a recruitment company, eliminate manual prospecting entirely`
- `We helped Pathos PR, a UK PR agency, add 33% to their total revenue`

Pattern for generic fallback lines (no strong vertical match):

Two flavours — a name-drop proof line (preferred when the named brands will feel credible to the lead's category) and an aggregate-outcome line (for niche verticals where name-drops might feel mismatched).

```
We've booked meetings for our clients with companies like [BRAND1], [BRAND2], [BRAND3] and [BRAND4]
```

or

```
Last year we helped over [N] [businesses/agencies/consultancies] drive over [$XM] in [sales pipeline/revenue]
```

- `We've booked meetings for our clients with companies like Logitech, HubSpot and BNP Paribas` (generic fallback example — pick 3 dynamically from the approved pool, weighted to the lead's target-account universe)
- `Last year we helped over 50 agencies and consultancies drive over $15 million in sales pipeline` (agency-tilted fallback)

**Pick the 3 name-drops dynamically per lead — do NOT rely on pre-baked variants.** For every lead that lands in Fallback B, Claude must pick 3 brands from the approved pool below that most resemble the **lead's own target accounts / ICP** — name-drops are aspirational FOR THE LEAD, so they should look like the kind of accounts the lead themselves wants to book meetings with. Cycle the selection across the campaign — don't send every lead the same 3-brand combo. The pool is limited to real brands we've received responses from in `#asteri-navreo-notification-channel`; refresh as new name-brand replies come in.

### Non-negotiables for case-study lines

- **Name the brand** where possible (SIHL, TrAIDe) — specificity builds credibility over "a manufacturer" / "a recruitment company"
- **Describe accurately** — the descriptor must match what the **lead** does, not what the reference customer did. If TrAIDe is your distributor case study, the line goes to leads who are distributors; the descriptor inside the line must read "distributor" so it lands as "yes this is relevant to me"
- **Hard numbers over vague claims** — "$1.6 million" beats "millions"; "33%" beats "significantly"; "50 clients" beats "many". If the real number is public, use it
- **No em dashes, no trailing period** — the line flows into the email body or P.S.
- **One sentence, one idea** — don't cram multiple wins into one line
- **Max 3 name-drops per line** — when using the name-drop pattern (e.g. "We've booked meetings for our clients with companies like X, Y and Z"), never list more than three brands. Beyond three reads as a brag-list and dilutes credibility. Pick the three with the strongest sector spread for the line's target bucket.
- **Name-drops must be aspirational FOR THE LEAD** — the brands listed should be companies the **lead would want to book meetings with themselves** (their target accounts / ideal customer profile), NOT brands the lead is similar to or competes with.
- **No perfect fit? Use the biggest credible brand we have, as long as it's remotely relevant** to the lead's universe. A loosely relevant Samsung still carries more weight than a perfectly-vertical no-name.

### CaseStudy assignment — derive the bucket FROM THE WHY, not from the raw company name

Once a lead has a high-quality, specific Why, the Why text is the strongest signal of business model and target-account universe. Always classify CaseStudy from the Why text rather than re-running an industry classifier on the company name. The Why already encodes the inference; reusing it keeps Why and CaseStudy aligned.

How: read the Why's noun phrases (the buyer type and the product/service category) and map them to a bucket via the Why-text classifier in "Classifying Leads into Buckets — Use the Why Field". Don't fall back to the rule-based name classifier — that was the legacy path before LLM-first Whys made the Why text reliably specific.

### CaseStudy assignment priority — ALWAYS prefer a hand-crafted brand line over a name-drop fallback

When picking a CaseStudy line for a lead, walk this hierarchy in order:

1. **Vertical-specific hand-crafted line first** — if the lead matches one of our existing branded case studies (SIHL = manufacturer, TrAIDe = distributor, TalentStream = recruitment, Tech Reserve = tech outsourcing, Pathos PR = UK PR agency, Superhuman Sales = lead-gen agency), USE THAT. A real brand + real outcome + accurate descriptor always beats a name-drop fallback. *(Note: media-focused marketing agencies previously landed on a Revenews line; that bucket has been retired — those leads now land on Fallback A.)*
2. **Vertical-tailored name-drop fallback** — if the lead's vertical isn't covered by a hand-crafted line (e.g. banking, insurance, healthcare, hospitality, construction, logistics, energy, capital/lending, legal, real estate, SaaS), use a name-drop line tailored to that vertical's buying universe.
3. **Generic name-drop fallback** — if the lead's vertical doesn't fit any tailored fallback either, use the most permissive Fallback B line (universal brand mix).

The hand-crafted case studies are the strongest credibility play we have — never replace them with a name-drop just because name-drops are easier to template. Name-drops are the safety net for verticals we haven't built a real case study for yet.

### Current Navreo CaseStudy library (living reference)

| Bucket | Target vertical | Line |
|---|---|---|
| SIHL | Wholesale manufacturer | `We helped SIHL, a 350-year-old wholesale manufacturer, add $1.6 million to their sales pipeline` |
| TrAIDe | Distributor | `We helped TrAIDe, a distributor, secure 6-figure and 7-figure partnerships` |
| TalentStream | Recruitment | `We helped TalentStream, a recruitment company, eliminate manual prospecting entirely` |
| Tech Reserve | Tech outsourcing | `We helped a tech outsourcing firm do the work of 10 full-time recruiters` |
| Pathos PR | UK PR agency | `We helped Pathos PR, a UK PR agency, add 33% to their total revenue` |
| Superhuman Sales | Lead-gen agency | `We helped a lead-gen agency lift their response rates across the board` |
| Fallback A | Agency/consultancy (generic) | `Last year we helped over 50 agencies and consultancies drive over $15 million in sales pipeline` |
| Fallback B | Any lead without a matching hand-crafted branded case study | `We've booked meetings for our clients with companies like [B1], [B2] and [B3]` — pick 3 brands per lead at generation time from the approved pool below, weighted to the lead's target-account universe |

**Approved name-drop pool — 57 brands, no tiers.** Every brand below has actually responded to a Navreo campaign (sourced from `#asteri-navreo-notification-channel`). All mentions are defensible if challenged.

**There is no hierarchy among these brands.** Don't pick on "recognisability" — pick on **fit with the lead's target-account universe**. A category-perfect match (e.g. Cera Care for a lead selling to UK home-care providers) lands harder inside the lead's world than a famous-but-irrelevant generalist (Logitech). Every lead deserves a triplet personalised to their universe; none should land on a default mix.

The brands are grouped below by category-fit description so you can scan for matches quickly. Use any of the 57 freely as long as the fit reasoning is sound.

### Brand pool — broad / cross-vertical fits

Use when the lead's buyer universe is broad, generalist, SaaS-GTM, enterprise-finance, or consumer.

| Brand | What they're recognised for | Fits when lead sells to… |
|---|---|---|
| Logitech | Global consumer/business tech peripherals — NASDAQ-listed | Consumer brands, marketplaces, hardware buyers, generalist audiences |
| HubSpot | Global CRM / marketing SaaS — household name in B2B software | SaaS, GTM teams, marketers, sales-led orgs, generalist audiences |
| BNP Paribas | Top-tier European bank (parent of Arval) | Finance, insurance, enterprise, professional services |
| Pegasystems | NASDAQ-listed enterprise workflow / BPM software | Enterprise IT, finance, insurance, pro-services buyers |
| AlphaSense | Market-intelligence SaaS, ~$4B valuation | Finance, consulting, strategy teams, research-heavy buyers |
| Clay | Hot GTM / sales-enrichment tool — recognisable in sales circles | SaaS, GTM, sales-ops, RevOps audiences |
| Entrata | Major US property-management SaaS | Real estate, property, vertical-SaaS buyers |
| Brenntag | World's largest chemical distributor — DAX-listed | Industrial, manufacturing, distribution, chemicals, logistics |
| TaskRabbit | IKEA-owned consumer gig marketplace | Consumer services, home services, marketplaces, lifestyle |
| Toptal | Global freelance talent marketplace | Agencies, consultancies, services firms, talent buyers |

### Brand pool — vertical / category-specific fits

Use whenever the lead's buyer universe matches the brand's category. These land harder inside their category than any generalist would. **No bias against using them** — fit is the only criterion.

| Brand | Category | Fits when lead sells to… |
|---|---|---|
| Ivey MBA | Top Canadian business school (Ivey at Western) | Executive education, MBA programs, alumni networks |
| Visma | Largest Nordic ERP / accounting SaaS | Nordic SMB software, ERP, accounting |
| BCA Research | Leading macro investment research | Asset managers, hedge funds, macro-research buyers |
| Procurify | Established procurement SaaS | Finance / procurement / ops teams |
| SafetyWing | Global health insurance for remote workers | Remote-first, nomad, distributed workforce |
| Arval | Fleet management (BNP Paribas Group) | Corporate fleet, mobility, leasing |
| Georgian Partners | Canadian growth-equity / tech investor | VC / PE LPs, growth-stage SaaS |
| euNetworks | European bandwidth / fibre operator | Telecom, data centre, hyperscale infra |
| Aptive Pest Control | Large US pest-control chain | Home services, residential services |
| Solink | Video analytics for retail / multi-location | Retail, QSR, multi-site operators |
| Flashbots | Core crypto / MEV infrastructure | Crypto, DeFi, on-chain finance |
| Ondo Finance | On-chain tokenised treasuries | Tokenisation, DeFi, crypto-native finance |
| Cera Care | UK home-care technology | UK healthcare, elder care, home health |
| FYI Doctors | Canadian optometry chain | Eyecare, optometry, healthcare retail |
| Vivisol | Italian home healthcare / respiratory | European home healthcare, respiratory, medtech |
| Ecolomondo | Canadian cleantech / tyre recycling | Cleantech, circular economy, recycling |
| XPV Water Partners | Water-focused growth equity | Water tech, utility infra, cleantech |
| The Yield Lab | Agritech / foodtech VC | Agtech, foodtech, sustainable ag |
| Sampford Advisors | Mid-market tech M&A advisor | M&A advisory, tech investment banking |
| Makers | UK coding bootcamp | Dev bootcamps, tech hiring, training |

### Brand pool — niche-specific fits

Real respondents from less-recognised verticals. Use them whenever the lead unmistakably sits in that niche — there's no "default skip" for these. If a niche brand is the strongest fit for the lead's universe, it wins.

3rd Wave · AssetFlo · Avance Services · Beacon Software · ChatBar AI · Coach Built · CRCE · ERA Partners · Experience First · Fairing Group · FindItParts · GL Group · In-Hand City · Intellistack · Klu Part · Maverix PE · Monarch Landscape · Netos · Northlane Capital · One Review · PestCo · Runtime Entertainment · Sickbird Production · Three.vc · Try Otter · Visa Concord Group · Vortex Pix

When picking from this group, internally name (one sentence) why this brand is a stronger fit for the lead than every brand in the broad and category groups. If you can't, the lead probably belongs in one of the other groups.

### How Claude picks 3 brands at generation time

1. Read the lead's Why (or company/website if Why is sparse) and infer the lead's **target-account universe** — the kinds of companies the lead wants to book meetings with.
2. **Scan all 57 brands**. Pick the 3 whose buyer universe most overlaps the lead's. No group is "preferred" — fit is the only criterion.
3. **Category-perfect matches always beat generalist near-misses.** A lead selling to fleet operators → Arval, not Logitech. A lead selling to UK home-care → Cera Care, not HubSpot. A lead selling to crypto-native finance → Flashbots / Ondo Finance, not BNP Paribas.
4. **Mix groups freely** in one triplet — `HubSpot` + `BCA Research` + `Arval` for a lead selling research/data into financial-services fleet buyers is a legitimate combo. The triplet should look like a buyer universe to the lead, not like a Tier list.
5. **Cycle combos across the campaign** — rotate so different leads see different 3-brand sets. A campaign where every lead sees `Logitech, HubSpot, BNP Paribas` is the failure mode; the picker has stopped personalising.
6. **No "default mix"** even for ambiguous universes. If the Why is genuinely vague, infer harder from company name + domain + title before picking. If still vague, pick 3 that hint at multiple plausible universes (e.g. one SaaS, one finance, one consumer) so at least one resonates — never the same triplet across many leads.
7. Always exactly 3. Never 2, never 4. Never two from the same narrow category in one triplet (e.g. don't pair `Flashbots` + `Ondo Finance` together — one crypto name is enough; pair the second with a brand that broadens the universe).
8. **Diversity audit at end of run**: in any campaign with >500 `fallback_b` leads, the unique-triplet count should be at least ~30% of total `fallback_b` rows. Lower than that means the picker repeated combos too often — do a rebalancing pass.

**When the user asks for updates** (add a brand name, correct a descriptor, swap in a hard number), treat as a bulk rename — see "Renaming / re-bucketing" below.

---

## Classifying Leads into Buckets — Use the Why Field

When deciding which CaseStudy line to assign each lead, the `Why` field is your strongest signal. Why has already been inferred per-company, so it encodes the lead's business model — use that rather than re-deriving from company name.

### Two-set classifier pattern

Build two pattern sets for each target bucket:

**Positive patterns** — phrases in the Why that signal "this lead is in the target vertical":

```python
DISTRIBUTOR = [
    'distribution partner', 'import and export', 'import and trading',
    'wholesale and distribution', 'trading partners', 'brand-distribution',
    'fmcg-distribution', 'food-import', 'fresh-produce import',
    'speciality green-coffee', 'actively sourcing Italian wine',
    'wine importers and distributors actively', 'international fashion buyers actively',
    # ... extend from samples
]
```

**Exclusion patterns** — phrases that look like the target but aren't (always test exclusions first, they're the stronger signal):

```python
NOT_DISTRIBUTOR = [
    'sourcing strategy and consulting',          # consultancy
    'needing corporate and commercial legal',    # law firm
    'shippers actively sourcing',                # logistics, not distributor
    'actively scoping M&A',                      # M&A advisor
    'evaluating US market-entry',                # market-entry consultancy
    'sourcing executive-search',                 # recruitment
    # ... extend from samples
]
```

### Classification logic

```python
def classify(why):
    w = (why or '').lower()
    # Exclusions first — stronger signal than positives
    if any(p in w for p in NOT_TARGET_PATTERNS):
        return 'not_target'
    if any(p in w for p in TARGET_PATTERNS):
        return 'target'
    return 'unknown'  # safe fallback to generic bucket
```

### Multi-pass refinement workflow

Hand-written patterns never nail classification on the first pass. Expect 3-4 iterations:

1. **First pass** — seed positive/exclusion patterns from domain knowledge + sample Whys
2. **Verify counts** — print classification distribution (`target / not_target / unknown`). If unknown > ~60% of the pool, patterns are too narrow
3. **Sample candidates** — random sample 25 from the `target` pile, read them as if you were the prospect receiving the case study — any false positives?
4. **Peek at unknowns** — cluster unclassified Whys by trailing phrase to spot missed patterns:
   ```python
   from collections import Counter
   tails = Counter(w[-60:].strip() for w in unknowns_whys)
   # Print top 30 — clusters reveal the missed patterns
   ```
5. **Extend patterns, re-run** — add the newly-spotted positives/exclusions
6. **Plateau check** — stop when adding patterns no longer moves the distribution meaningfully. Expect ~20-25% of a broad fallback pool to reclassify into a specific vertical

### Always err toward the safe fallback

If a Why is genuinely ambiguous, leave the lead in the generic fallback bucket. A permissive "$15M pipeline for 50 businesses" line is always credible. A wrong vertical-specific case study actively damages credibility ("we helped SIHL, a manufacturer" landing on a law firm is worse than no case study at all).

---

## Renaming / Re-bucketing Workflow

When the user asks to change the CaseStudy library — add a brand name, correct a descriptor (e.g. "TrAIDe is actually a distributor, not an export consultancy"), add a hard number ("put $1.6M instead of 'millions'"), or re-classify leads between buckets — follow this workflow:

### A. Renaming a case-study line (no bucket changes)

1. Run full end-to-end scan to confirm current state
2. Build a simple `OLD → NEW` mapping (one per line being renamed)
3. For each lead whose CaseStudy matches an old line, queue a payload with the new value
4. Push in batches of **200** (fixed-value updates don't need per-lead inference so larger batches are fine)
5. Re-scan to verify the distribution moved as expected

### B. Re-bucketing leads between buckets (business-model reclassification)

1. Run full end-to-end scan to get current `email → CaseStudy + Why` state
2. For the source bucket(s) to reduce (e.g. a too-generic Fallback), apply the Why-text classifier (see "Classifying Leads into Buckets" above)
3. Sample-check the candidates before pushing
4. Push in batches of 200 with the new bucket's case-study line
5. Re-scan and report the new distribution

### C. Stop mid-run if the user corrects a descriptor

If the user interrupts with a correction while batch files are already built but before the first POST ("TrAIDe is a distributor, not an export consultancy"):

1. **Do not push the old batches** — discard them
2. Rebuild the mapping with the corrected descriptor
3. Regenerate all batch payload files
4. Re-run validation (lead count, banned words, em dashes)
5. Push the corrected batches

Never patch partial pushes with a second correction pass — the API upserts, so the second push overrides, but the log becomes noisy and the user's mental model gets harder to verify.

---

## Pre-flight: run lilly-qa Step 5d to clean `first_name` and `company_name`

`{{first_name}}` and `{{company_name}}` render directly in every email body, and the downstream `Why` / `CaseStudy` fields generated by this skill reference `{{company_name}}` in their phrasing. Dirty inputs propagate: `recorded a video for Acme Corp Inc.` reads like a contract; `help your team source eco-friendly textile suppliers for Acme Corp Inc.` reads twice as bad.

**Action**: before running any per-lead generation pass, run `lilly-qa` Step 5d (`scripts/check_lead_field_hygiene.py`). It detects missing values + dirty patterns (legal suffixes, profession tails, ALL-CAPS, auto-hyperlinking TLDs, URLs in company field, etc.), dry-runs the proposed diff, and pushes cleaned values back to Smartlead after explicit user confirmation.

The cleaning logic (`clean_first_name`, `clean_company_name`, full rule tables) used to live here; it has been moved to the QA skill so the gate sits in one place. See `~/.claude/skills/lilly-qa/references/lead-field-hygiene.md` for the rule details and `~/.claude/skills/lilly-qa/scripts/check_lead_field_hygiene.py` for the executable.

> Related skill: `lilly-updates-leads` handles general lead-data bulk fixes (from CSVs, normalising across campaigns). Use `lilly-qa` Step 5d for inline pre-flight cleaning of a single campaign before Why/CaseStudy generation. Use `lilly-updates-leads` for standalone data-quality passes from CSVs.

### Skip rule

Skip the pre-flight cleaning step only when:
- The leads were imported from a known-clean source within this conversation (e.g. a freshly-exported CSV that was already normalised by `lilly-updates-leads`).
- The campaign copy contains neither `{{first_name}}` nor `{{company_name}}` (rare).

When in doubt, run it — detection is fast and free, and a dirty `{{company_name}}` will propagate into every Why fragment generated by this skill.

---

## Workflow

### Step 0 — Confirm the offer with the user *(do this every run, before anything else)*

Before generating a single Why, lock down what we're actually selling on this campaign. The Why is the bridge between the lead's world and the offer; getting it right requires knowing both sides.

Ask the user (concise — single message, 3-4 questions max):

1. **What is the offer?** One-sentence pitch. ("We help X book meetings with Y" / "We sell Z to A")
2. **Who is the offer's buyer?** The ICP — the kind of company/role our offer is meant to put the *lead* in front of. (NOT the lead themselves — the people the lead wants to sell to / partner with / hire from.)
3. **Any specific angle this campaign is leading with?** (Hard offer / soft offer / event-led / case-study-led / category-shift / etc.)
4. **Anything off-limits?** Topics, claims, or framings to avoid (regulatory sensitivities, banned competitors mentioned, etc.)

Why this matters: the Why fragment completes the sentence *"I recorded a short video for {{company_name}} walking through how we'd **[WHY]**"*. If the offer is "we help agencies book demos with enterprise SaaS buyers" but the Why says "help your team source eco-friendly textile suppliers", the email is incoherent. Confirming the offer is what keeps every per-lead Why aligned with the same north star.

If the user has already shared the offer earlier in the conversation, summarise it back in one line and ask "still this?" rather than re-interrogating. The point is alignment, not a re-survey.

**Skip rule:** the only time to skip this step is when the user has explicitly said "use the existing campaign's voice — sample filled Whys and match them" (i.e. you're filling gaps in an already-tuned campaign rather than launching a new angle). In that case, Step 1 below is the calibration, not Step 0.

### Step 0.5 — Read the email copy *(MANDATORY before generating any per-lead field that renders in body copy — `Why`, `Icebreaker`, `Pain`, `Hook`, etc.)*

A fragment generated in isolation will tonally and grammatically clash with the email body it lands in. Before generating any per-lead inferred field, fetch the actual campaign copy and use it as literal context for every generation.

#### Fetch the sequence

```bash
curl -s "https://server.smartlead.ai/api/v1/campaigns/{ID}/sequences?api_key={KEY}"
```

Returns an array of sequence steps. Each step has `subject`, `email_body`, `seq_number`, etc. Most icebreakers/Whys live in `seq_number: 1` (email-1) but check every step that contains the merge variable — follow-ups sometimes re-render `{{Icebreaker}}` too.

#### For each merge variable to be generated

1. **Locate every occurrence** of `{{VariableName}}` across all sequence steps' `email_body`.
2. **Extract the carrier sentence** — the sentence containing the merge variable. This is the literal context the generation must complete grammatically.
   - **Why example carrier:** `I recorded a short video for {{company_name}} walking through how we'd {{Why}}.` Generated text must finish that sentence cleanly with a verb-phrase.
   - **Icebreaker example carrier:** `Hi {{first_name}}, {{Icebreaker}} I recorded a short video for {{company_name}}…` Generated text must be a complete sentence that hands off into the next sentence without a tonal jolt.
3. **Extract surrounding context** — the sentence immediately before and after the carrier. The generated line must read coherently with both.
4. **Echo back to the user before generating** — paste the email-1 body back with each merge variable highlighted in **bold** and confirm: *"This is the copy I'll be writing into. Same as what you have in mind?"* Catches stale copy, wrong campaign, or unexpected merge variables before any generation cost is incurred.
5. **Include the carrier + surrounding context in EVERY generation prompt** for that field. Without it, the LLM guesses tone and grammatical shape; with it, every line lands cleanly.

#### Suggesting body tweaks (optional output)

While reading, if a transition will fight every generated line (e.g. icebreaker followed by `I recorded a short video for…` reads stiffly because the second sentence opens "I" right after the icebreaker), surface the friction as a **suggestion** — never auto-apply:

> *"The transition from `{{Icebreaker}}` to `I recorded a short video…` will read stiffly because the second sentence opens with 'I' immediately after the icebreaker lands. Two options: (a) change the next sentence to `So I recorded a short video…` or `Just recorded a short video…` for a softer hand-off, or (b) accept the slight stiffness and generate around the current copy. Which?"*

The skill SUGGESTS, the user decides. If they want the body change applied, route to `lilly-bot` (handles sequence edits). Don't edit copy from `lilly-personalisation` — different skill, different concern.

#### Skip rule

Only skip Step 0.5 if the user has already pasted email-1 copy into this conversation AND explicitly said *"use the copy I just gave you, don't re-fetch."* Otherwise always fetch fresh — the copy might have been edited since the user last saw it.

#### Why this matters specifically for `Icebreaker`

The icebreaker is the SECOND thing the prospect reads (after the greeting). It sets tone and topical frame for everything after. An icebreaker generated without seeing the body can:
- Use a punctuation hand-off that breaks (line ends in a period when the body expects a comma continuation)
- Reference a topic that contradicts the body's pitch (e.g. "noticed you're using Salesforce" when the email pitches a Salesforce-replacement)
- Be tonally mismatched (warm-fuzzy icebreaker + clinical body, or vice versa)
- Open with "I-language" right before a body sentence that also starts with "I"

Step 0.5 prevents all four. The downstream `lilly-qa` Step 5c-b coherence check is the safety net — but you save that check (and the user) work by getting it right at generation time.

### Step 1 — Sample existing filled fragments

Before writing anything, fetch a few pages and find 5–10 filled samples:

```bash
for offset in 0 500 1000 1500 2000; do
  curl -s "https://server.smartlead.ai/api/v1/campaigns/{ID}/leads?api_key={KEY}&offset=${offset}&limit=100" > p_${offset}.json &
done
wait
```

Then filter Python-side for `custom_fields.Why` where `len(why) >= 10`. Show the user 5 examples so they can confirm the pattern before the skill proceeds at scale.

### Step 2 — Full campaign scan (denominator)

Fetch **all** pages in parallel to get the true missing count:

```bash
for offset in $(seq 0 100 {total+100}); do
  curl -s "{leads_url}&offset=${offset}&limit=100" > p_${offset}.json &
done
wait
```

Report: `Total: X | Filled: Y | Missing: Z` before any writes.

### Step 3 — Batch fill (100 leads per batch)

For each batch:
1. Slice the next 100 missing leads from `missing.json`
2. Generate a unique Why per lead (never copy-paste the same fragment across unrelated companies). **Every generation prompt must include the carrier sentence + surrounding context from Step 0.5** — without it, lines won't grammatically complete the body sentence they're inserted into.
3. Write payload to a file:

```json
{
  "lead_list": [
    {"email": "...", "custom_fields": {"Why": "..."}},
    ...
  ]
}
```

4. POST via heredoc/file-based curl (shell escaping is too fragile otherwise):

```bash
curl -s -X POST "https://server.smartlead.ai/api/v1/campaigns/{ID}/leads?api_key={KEY}" \
  -H "Content-Type: application/json" \
  -d @/tmp/campaign_{ID}/batch{N}.json \
  --max-time 60 --retry 2
```

5. Parse response:
   - `upload_count` — total accepted
   - `already_added_to_campaign` — confirmed updates (most leads land here because they already exist)
   - `block_count` — BLOCKED/suppressed leads, will not be updated (expected)
   - `invalid_email_count` — should be 0

### Step 4 — Report running total

After each batch:

```
Batch {N} complete. Running total: {done}/{total_missing} ({%}).
  Pushed: 100  Updated: {97-100}  Blocked: {0-3}
  Remaining missing: ~{X}
```

### Step 5 — Stop condition

Continue until a full end-to-end scan returns **only BLOCKED leads** unfilled. Those are permanently suppressed by Smartlead and cannot be updated — the cumulative `block_count` should exactly match the residual unfilled count.

Verify:

```python
unfilled = [l for l in all_leads if len(why or '') < 10]
blocked_only = all(l['status'] == 'BLOCKED' for l in unfilled)
```

If `blocked_only` is True → **done**. Report final tally and tear down any cron loop.

---

## Autonomous Progression Pattern

For long campaigns (1,000+ leads), set up the `/loop 3m keep going` pattern so each "keep going" iteration processes the next 100:

```
/loop 3m keep going
```

Creates a cron (`*/3 * * * *`) that re-fires "keep going" every 3 minutes, keeping the cache warm and letting the user walk away. **Tear down with `CronDelete` when scan returns BLOCKED-only.**

Batch size **100** hits the sweet spot: large enough to make progress, small enough for Smartlead's API + our context window.

---

## Common Pitfalls

| Problem | Fix |
|---|---|
| Exit code 56 on POST | Network hiccup — retry with `--max-time 60 --retry 2` |
| Cloudflare 1010 blocking | Use curl (not Python urllib) — curl's default UA passes through |
| `"settings.update" not allowed` | Don't include `settings` object with `update:true` — just use `lead_list` |
| Duplicate Why across companies | Never batch-paste the same fragment to unrelated leads — always infer per company |
| User asks "why did the upload say 96 updated not 100?" | `block_count: 4` — these are BLOCKED leads, expected dead-lead behaviour |
| Sequence fetch returns empty on a Navreo campaign | Wrong API key — try the Navreo secondary key `1417c9a6-...zto0vlj` |
| Em dashes creeping in | Replace all `—` with `-` or ` - ` before pushing — **also scan case-study lines**, not just Whys |
| Generated icebreaker doesn't grammatically flow into the next sentence in the email body | You skipped Step 0.5 (read the email copy). Always fetch the sequence first, extract the carrier sentence, and feed it into every generation prompt — without it, lines are written blind |
| Generated line is tonally fine on its own but reads stiffly inside the email | Same root cause — Step 0.5 wasn't done OR the carrier-sentence context wasn't passed through to every generation call. Fix at Step 0.5, regenerate, don't try to patch downstream |
| User wants a body tweak suggested by Step 0.5 to be applied | Don't apply from `lilly-personalisation`. Surface the suggestion, let the user accept, then route to `lilly-bot` for the actual sequence edit |
| "mid-market" in generated Whys | Banned phrase — replace with specific size descriptor or drop entirely; run a post-fill scan to catch stragglers |
| CaseStudy bucket descriptor is wrong for the lead's vertical | The line's descriptor must match what **the lead** does (TrAIDe = distributor → lands on distributor leads). Correct the library, then bulk-rename affected leads |
| "millions" / "significantly" / vague claims in case studies | Use hard numbers — $1.6M, 33%, 50 clients. Weak claims damage credibility at the P.S. position |
| User corrects a descriptor mid-run after batches are built | Stop pushing, discard the prepared batches, rebuild with the corrected descriptor, re-run validation, then push (see "Stop mid-run" in Re-bucketing Workflow) |
| Over-aggressive classifier moves too many leads into a vertical bucket | Error toward safe fallback. Sample 25 random candidates before pushing; if any feel like a wrong fit, tighten the positive patterns and extend the exclusion list |
| `Hi JOHN,` / `Hi ,` / `recorded a video for Acme Corp Inc....` in sent email | Standard-field hygiene wasn't run pre-flight. Run `lilly-qa` Step 5d (`scripts/check_lead_field_hygiene.py`) before generating Why/CaseStudy — it covers shouting, empty values, legal suffixes, profession tails, auto-hyperlinking TLDs, and URLs in `company_name` |
| Why references the dirty company name | Same root cause — Step 5d wasn't run. Re-run it now, then regenerate Why for the affected leads |

---

## Output Format

After completion, summarise as:

| Metric | Value |
|---|---|
| Campaign ID | {id} |
| Total leads | {n} |
| Started missing | {start_missing} |
| Filled by this run | {filled_in_run} |
| Unfillable (BLOCKED) | {blocked} |
| Final filled | {final_filled}/{n} ({%}) |
| Batches pushed | {n_batches} |

---

## Extending to Other Custom Fields

Pick the right pattern depending on whether the field is per-lead or bucketed:

### Per-lead inferred fields (follow the Why Pattern)

Each value is unique per lead, inferred from company/website/location/role.

1. **Filter expression**: `custom_fields.{FieldName}` instead of `custom_fields.Why`
2. **Pattern library**: sample existing filled values to learn the expected voice
3. **Payload key**: `"custom_fields": {"{FieldName}": "..."}`

Common alternatives:
- **Icebreaker** — one-line soft opener (e.g., "Apologies if this isn't relevant, wasn't sure who handles this at {{company_name}}")
- **Pain** — one clause naming the pain the offer solves
- **Hook** — relevant signal tied to the lead (hiring, funding, news)

Before filling a new field type, always ask the user for 3–5 examples of the voice they want, or sample 10+ existing filled leads in the campaign.

### Bucketed fields (follow the CaseStudy Pattern)

Each value is one of a small hand-crafted set mapped to verticals.

1. **Get the library from the user** — ask for the full list of bucket → line mappings with a descriptor for each
2. **Classify leads into buckets** — use the Why-text classifier (see "Classifying Leads into Buckets"); fall back to a generic "safe" bucket when ambiguous
3. **Push per-bucket fixed values** — batch size 200 works well because no per-lead inference is needed
4. **Verify distribution** — sample 25 random leads per bucket to sanity-check the descriptor lands well

Common alternatives:
- **ProofPoint** / **SocialProof** — named reference-customer line, similar to CaseStudy
- **OfferFraming** — vertical-specific offer language (e.g. "30 demos/month" for SaaS vs "$500K pipeline" for enterprise services)
- **ProductAngle** — which of several products/services to lead with based on the lead's vertical

### Pre-flight cleaning (run lilly-qa Step 5d)

Before generating any new per-lead or bucketed field, run `lilly-qa` Step 5d to clean `first_name` and `company_name`. The cleaner dry-runs the proposed diff, asks for explicit confirmation, then pushes corrected values via the Smartlead API. Once that's done, every downstream Why / CaseStudy / Icebreaker generated by this skill references clean `{{company_name}}` automatically. See the "Pre-flight: run lilly-qa Step 5d" section above for the rationale.

---

## Reference: Default API Keys

- **Primary**: `a8f9359c-b334-4120-9dc5-e36880040492_nzb0cg5`
- **Navreo secondary**: `1417c9a6-6fff-433d-8ca4-f0913967a9c4_zto0vlj` (Navreo-titled campaigns only)

Never hardcode these in committed code — prompt the user or read from env/settings.
