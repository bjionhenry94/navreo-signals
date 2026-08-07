---
name: lilly-company-followers
description: "Qualify a list of company-follower prospects (LinkedIn followers, Sales Nav exports, Apollo / Boomerang / 6Sense / ColdIQ / Outplay-style CSVs of people who follow a target company) against per-task qualification criteria. Use this skill whenever the user uploads or attaches a CSV of prospects/leads/followers and asks to qualify, filter, or shortlist them — even if the file format varies (Boomerang, Smartlead-style, Showpad-style, Sales Nav export). Trigger on phrases like 'qualify this list', 'qualify these followers', 'filter this CSV', 'who in this list matches our ICP', 'find the qualified people', 'pull the qualified prospects out of this file'. The skill always asks the user for the qualification criteria first (role / location / size / company-avoid list / sender description), then qualifies — using lilly-personalisation's company-identification confidence ladder (LLM knowledge first, WebFetch only when uncertain) to judge what each company actually does for the in/out call. After producing the qualified list, the skill explicitly asks whether to proceed to email verification & enrichment — never starts that step automatically."
---

# Lilly Company Followers

## Purpose

Take a CSV of prospects (typically LinkedIn followers of a target company, or any Boomerang-style / Sales Navigator-style export) and produce a qualified shortlist of people who match the criteria the user specifies for *this particular task*.

Two things make this skill different from a one-off filter script:

1. **Criteria change every run.** Each upload may target a different ICP, a different sender, a different avoid-list. The skill always asks for the criteria up front — it never assumes defaults from a previous run.

2. **Company-side qualification leans on `lilly-personalisation`'s identification pattern.** Whether a company qualifies (right industry / business model / not a competitor) requires actually knowing what they do. The skill reuses the confidence ladder from `lilly-personalisation` — LLM training knowledge first, WebFetch only when the lead is genuinely unknown — to make the in/out call without burning hours on web research.

The skill stops cleanly after producing the qualified list and **asks the user** whether to continue with email verification / enrichment. It never auto-starts that step, because email verification spends credits on third-party tools (Findymail, ZeroBounce, Apollo, etc.) and the user should always confirm.

---

## When to Use

Trigger on any of:

- "Qualify this list of followers" / "Qualify these prospects"
- "Filter this CSV against our ICP"
- "Pull out the qualified people from this upload"
- "I've got a list of LinkedIn followers — who's worth outreach?"
- User attaches a CSV with columns like `first_name`, `job_title`, `company_name` and asks for filtering of any kind
- Any Boomerang / 6Sense / Apollo / Sales Nav / Showpad-style export with a request to qualify

**Do not trigger on:**
- Smartlead campaign tasks (lead-level personalisation, custom field fills) → that's `lilly-personalisation`
- Smartlead campaign optimisation requests → `lilly-optimiser`
- Building a Sales Nav search URL from scratch → `Lily-Link-Creator`
- Email verification / enrichment alone (after qualification) → `lilly-email-verification`

---

## Workflow

### Step 0 — Ask for the qualification criteria *(always, every run)*

Before doing anything else, send the user **one** message with this template. Pre-fill any fields you can infer from earlier conversation context, and explicitly say which fields you've inferred so the user can correct them.

```
I'll qualify the list once you confirm the criteria for this task. Fill in the
sections below (or just paste a freeform description and I'll structure it).

1. ROLE CRITERIA
   Which titles qualify? (paste a list, or describe by rule — e.g. "Director and
   above in sales/marketing/revenue/growth, plus Founders/CEOs")
   →

2. LOCATION CRITERIA
   Any location? Specific countries? High-GDP preset (US, CA, UK, IE, AU, NZ, DE,
   NL, CH, SE, NO, DK, FI, SG, JP, HK, UAE, KSA, IL, etc.)?
   →
   Match against company location or person location?
   →

3. COMPANY SIZE CRITERIA  (optional — only if the file has employee counts)
   Minimum employee count?  →
   US-based age rule (e.g. "if US, must be 5+ years old")?  →

4. SENDER COMPANY  (one sentence on what YOU sell — used to identify competitors
   we should avoid)
   →

5. AVOID LIST  (categories of companies to skip in outreach)
   Examples: sales enablement, GTM services, cold outbound agencies, lead gen,
   appointment setting, RevOps services, outbound tooling vendors
   →

6. SPECIAL RULES  (optional)
   Anything else — dedup by company, exclude prospects without LinkedIn URL, etc.
   →
```

Wait for the user's response before scanning a single row. If they paste a freeform criteria description, structure it back into the 6 fields above and ask them to confirm before proceeding. Misalignment on criteria is the single biggest cause of bad qualified lists; **never skip this step**, even if the user previously qualified a similar file.

**Skip rule:** the only valid skip is when the user says something like *"use the same criteria as the last upload"* in the same conversation. In that case, summarise the criteria back in 4-6 lines and ask "still this?" before running.

### Step 1 — Inspect the file & report capability

Read the first 5 rows of the CSV and detect which qualifying signals are present in the columns. The pipeline at `scripts/qualify_list.py` does this automatically and prints a capability report.

Capability report tells the user **which criteria can actually be enforced** vs. **which had to be skipped** because the data isn't in the file. This avoids the silent failure of "I qualified it" when in fact half the rules couldn't apply.

Common file types and their typical capabilities:

| File type | Has employees? | Has industry? | Has description? | Has company location? |
|---|---|---|---|---|
| Boomerang/6Sense (full LinkedIn enrich) | ✓ | ✓ | ✓ | ✓ |
| Apollo export | ✓ | ✓ | partial | ✓ |
| Sales Nav export | partial | ✓ | ✗ | ✓ |
| Showpad-style follower list | ✗ | ✗ | ✗ | ✗ (only person city) |
| Raw LinkedIn follower scrape | ✗ | ✗ | ✗ | ✗ |

When the file is thin (Showpad / raw scrape), the role check still works perfectly, the avoid-list scan works on company name + domain only (lower precision), and size/age/location filters get skipped — the skill must say so explicitly.

### Step 2 — Qualify per row

Per row, walk these checks **in this order** (cheapest first, expensive company-identification last):

#### 2a. Role check — title-only, deterministic

Apply the user's role criteria to `job_title` using:
- Direct phrase match (titles in the user's explicit list win first)
- Senior-prefix + qualifying-domain combination (Chief/VP/Head of/Director + sales/marketing/revenue/etc.)
- Founder/CEO tier always passes (Founder, Co-Founder, CEO, Owner, Managing Partner, etc.)
- Junior-prefix exclusions reject Manager/Analyst/Specialist/Coordinator-level titles even if they contain a domain word

Skip the rest of the checks for any row that fails the role test — title is fast and disqualifies most of the file.

#### 2b. Location, size, age — structural filters from CSV columns

Only apply the filters whose data is present. Report which were skipped.

#### 2c. Company qualification — uses lilly-personalisation's confidence ladder

For rows that survive the structural filters, decide whether the **company** qualifies. This is the in/out call: does this company match the ICP (e.g. "B2B SaaS"), and is it not on the avoid-list (e.g. "doesn't sell sales enablement to other companies")?

Walk the **same confidence ladder used in `lilly-personalisation`** for identifying what a company does:

| Confidence | What it looks like | Action |
|---|---|---|
| **High** — you can name the specific product/service/business model from training knowledge alone | "PixelSurge = e-commerce design agency"; "Fibonacci Agency = marketing services for finance"; "Stratnova = IT staffing" | Use that knowledge to score in/out. **No web fetch.** |
| **Medium** — you can place the broad industry but not the specific product line | "TechTides Global — sounds like IT consulting but not sure if they're a service provider or product" | One WebFetch on the homepage. Then score. |
| **Low** — name + domain give no usable signal | "Taigle" with no brand recognition and no clear domain | WebFetch + WebSearch. If still unclear, mark as `unknown — flag for manual review` rather than guessing. |

**Bias toward High.** If the user supplied LinkedIn description / industry / specialities text in the CSV, that's effectively a free pre-fetched company description — use it. If the file is thin (Showpad-style), most companies still resolve at High confidence from name + domain alone (e.g. `pdf.com → PDF Solutions, semiconductor/chip-design SaaS`).

For each company, produce two judgments:

1. **Does this company match the ICP positively?** (yes / no / unknown)
2. **Is this company on the avoid-list?** (yes — skip; no — keep; unknown — keep but flag)

Both must clear: a company that's a perfect ICP match but is also a competitor is `1 - avoid`. A company that's not on the avoid-list but isn't an ICP match is `1 - off-ICP`.

#### 2d. Score the row

Output for each row that survived role + structural filters:
- `5 - meets ICP, no avoid signals` — qualified
- `1 - [reason]` — disqualified (with the specific reason: "off-ICP", "competitor: lead-gen agency", "competitor: sales enablement vendor", etc.)

### Step 3 — Output the qualified list

Write a Final Outreach List CSV with all original columns + a `Lead Score` column showing `5 - [reason]` for the surviving rows. The pipeline at `scripts/qualify_list.py` handles this directly.

Filename convention: `<original-stem> - Final Outreach List.csv` next to the input file.

Print a summary back to the user:

```
Input:        <path>
Rows:         N

Criteria applied:
  ✓ role criteria
  ✓ location criteria (using <column>)
  ✓ company size (min N)
  ✓ avoid-list scan
Criteria skipped (data unavailable):
  ✗ <criteria> — <reason>

Disqualification breakdown:
  Role-fail:    X
  Loc-fail:     X
  Size-fail:    X
  Age-fail:     X
  Avoided:      X
Qualified:    Y
Find rate:    Y/N (P%)

Output:       <path>
```

### Step 4 — Ask about email verification, do not start it

Once the qualified list is written, end the run with **a clear question**, not an action:

```
The qualified list is ready (Y rows at P% find rate) — see <path>.

Next step would be email verification & enrichment for these Y prospects. That spends
credits on whichever provider you use (Findymail / ZeroBounce / Apollo / etc.) and
takes a few minutes per 1k rows.

Do you want me to start that now? If yes — which provider, and is the API key in
the usual place or do you want to share it again?
```

**Do not auto-start verification.** This is a hard rule. The user owns the spend decision and the provider choice. Wait for explicit confirmation. If the user says yes, hand off to the `lilly-email-verification` skill rather than running it inline.

---

## Company Qualification — Worked Examples

### Example 1 — Showpad follower list, rich enough to skip the web

Lead: `Christophe Begue, VP of Corporate Strategic Marketing, PDF Solutions, pdf.com, San Francisco`

- **Role check:** "VP of Corporate Strategic Marketing" — senior prefix (VP) + qualifying domain (Marketing) → ✓
- **Company identification (High confidence):** PDF Solutions is a NASDAQ-listed semiconductor yield-management software vendor — Bjion's training knowledge has this directly. No WebFetch needed.
- **ICP check:** SaaS / enterprise software → matches generic "B2B SaaS" ICP if the user specified one
- **Avoid check:** PDF Solutions doesn't sell sales enablement, GTM services, or any avoid-list category → not on avoid-list
- **Score:** `5 - meets ICP, no avoid signals`

### Example 2 — Avoid-list hit on company name alone

Lead: `John Smith, Sales Director, Smartlead, smartlead.ai`

- **Role check:** "Sales Director" → ✓
- **Company identification (High):** Smartlead is a cold-email infrastructure SaaS — a direct competitor / outbound tooling vendor.
- **Avoid check:** Hits the "outbound tooling vendor" entry on the avoid-list → ✗
- **Score:** `1 - competitor: outbound tooling vendor`

No need to WebFetch — Smartlead is recognisable from name and domain alone.

### Example 3 — Medium confidence, one WebFetch resolves it

Lead: `Anna Lee, Head of Growth, TechTides Global, techtidesglobal.com`

- **Role check:** "Head of Growth" → senior prefix + qualifying domain → ✓
- **Company identification (Medium):** "TechTides Global" — sounds like an IT services or consulting firm but the name is vague. WebFetch homepage:
  - Homepage says "We help enterprises modernise their data infrastructure" → IT services / consulting
- **ICP check:** Service provider, not a product company → matches if ICP includes services firms
- **Avoid check:** Not in any avoid category → ✓
- **Score:** `5 - meets ICP (IT services), no avoid signals`

### Example 4 — Low confidence, can't resolve, flag

Lead: `Maria Rodriguez, CEO, Taigle, taigle.io`

- **Role check:** "CEO" — founder tier → ✓
- **Company identification (Low):** Name doesn't trigger any training knowledge. WebFetch returns Cloudflare 403. WebSearch returns no clear results.
- **Score:** `unknown - could not identify company; flag for manual review` (still kept in the qualified list, with the flag in the reason field, so the user can decide).

Don't push a generic "looks fine" verdict on companies you can't identify. The reason field gives the user the choice to manually triage these or drop them.

---

## Speed Notes

The lilly-personalisation skill notes that a single agent can comfortably qualify 100 leads in 1-3 minutes when bias-to-High is followed. The same applies here — most company calls are decidable from name + domain + (LinkedIn description if available) without ever calling out.

For files >2k rows, batch the qualification rather than trying to evaluate every row inline:

1. Run the deterministic pipeline (`scripts/qualify_list.py`) for role + structural filters and the keyword-based avoid scan. This handles 99% of rows that hit explicit avoid-list categories.
2. Only the residue — rows where the keyword scan came back clean but the company is still ambiguous — needs LLM-based ICP/avoid judgment. That residue is typically <5% of the qualified pool.

---

## Recipes

Composable patterns the pipeline doesn't natively express in a single config. Use these when the user's request matches.

### Recipe 1 — Tiered country-size rules

**When to use**: User wants different `min_employees` thresholds based on country economic tier, or wants to hard-block specific countries entirely.

Example phrasing: *"Block India / Pakistan-type companies entirely. If it's a low-GDP / low-salary country, min size 100. Otherwise min 10."*

**Workflow**:

1. **Pre-bucket script** (one-off Python) — read the input CSV, drop rows whose trailing country segment matches the hard-block list, route remaining rows into `bucket_high_gdp.csv` and `bucket_low_gdp.csv` based on country lookup. **Match both full names and ISO-2 codes** (Boomerang/Apollo often use ISO-2). **Treat unknown / missing locations as high-GDP** — the role + avoid filters still gate the row, so being permissive here recovers leads rather than losing them.
2. **Two configs** — `config_high_gdp.json` with `min_employees: 10`, `config_low_gdp.json` with `min_employees: 100`. Both share role + avoid + age rules. Set `location_criteria.mode: "any"` in both (already pre-filtered).
3. **Run `qualify_list.py` twice** (parallelisable — independent inputs/outputs).
4. **Concat** the two `Final Outreach List.csv` files into one. Add a `Size Tier` column marking the bucket each row came from for downstream debugging.

See `references/country_tiers_preset.md` for the country lists, ISO-2 mappings, and a working `preprocess.py` outline.

### Recipe 2 — Pre-dedup against existing Smartlead audience

**When to use**: User wants to re-qualify a list to *find leads previously missed*, and they already have leads from this list (or overlapping lists) in active Smartlead campaigns. Common for follower-of-competitor plays where multiple campaigns share follower bases.

Example phrasing: *"Subtract the leads already in Smartlead before qualifying"* / *"Find any prospects that were qualified out before that shouldn't have been."*

**Workflow**:

1. **Build the exclusion list** — extract emails from the relevant Smartlead campaigns via `list_leads_by_campaign` (paginate via `offset`/`limit`; dedup by lowercased email). For 30+ campaigns or 30k+ leads, the MCP tool's per-call token budget overflows — fetch via direct HTTPS to `https://server.smartlead.ai/api/v1/campaigns/{id}/leads` with the API key from the MCP env, using a rate-limited concurrent fetcher (8 workers, 180 req/min cap to stay under the 200/min account limit). Output a single `exclusion_list.csv`.
2. **Pre-dedup** in the same preprocess step that handles Recipe 1 (or a separate one if no country tiering is needed): drop rows whose lowercased + trimmed email matches the exclusion set.
3. **Run `qualify_list.py`** on the deduped output as usual.

Surface the dedup step in Step 0's criteria confirmation if the user framed the task as a re-qualification — they expect it but won't always say so.

### Combining the two

The Boomerang re-qualification run (Apr 2026) combined both recipes: build Smartlead exclusion (48 campaigns, 31,621 unique emails) → email-dedup → country pre-bucket (hard-block 5 countries + 2 size buckets) → 2× `qualify_list.py` → concat. End-to-end on a 369k-row input: ~5 minutes for the qualifier itself; the Smartlead extract was the long pole (~20 minutes).

The patched range-aware size parser nearly doubled the qualified pool (11,032 → 21,442) by recovering rows previously dropped on `11-50` / `201-500` / `10001+` size strings. Always run the full pipeline once and check the disqualification reason histogram before reporting — a high "size not numeric" or "missing title" count is the signal that the input has a format quirk worth handling before trusting the output.

---

## Files in This Skill

- `scripts/qualify_list.py` — generalised parameterised pipeline. Reads a CSV + JSON config, auto-detects column schema, applies role / location / size / age / avoid-list filters, prints capability report, writes Final Outreach List. Size parser handles plain integers, range strings (`11-50`), and `N+` formats by extracting the first integer as the lower bound. **Always use this rather than rolling row-by-row qualification by hand**, except for the small residue of LLM-judged company calls.
- `references/criteria_template.md` — the 6-field template the skill sends in Step 0. Reference this verbatim when asking the user for criteria.
- `references/company_qualification.md` — extended notes on running the confidence ladder for ICP/avoid calls (lifted and adapted from `lilly-personalisation`).
- `references/navreo_default_preset.md` — the original Navreo sales-leaders qualification + avoid-list (the prompts Bjion was using in Clay before this skill existed). Use as a default when the user says "use the sales-leaders preset" or "same as the 6Sense / Boomerang run."
- `references/country_tiers_preset.md` — country lists and ISO-2 mappings for the 3-tier hard-block / low-GDP / high-GDP recipe used in Recipe 1.

---

## Output Format

After completion, summarise as:

| Metric | Value |
|---|---|
| Input file | `<path>` |
| Rows in | N |
| Role-fail | X |
| Location-fail | X |
| Size-fail | X |
| Age-fail | X |
| Avoided (competitor / off-ICP) | X |
| **Qualified** | **Y** |
| **Find rate** | **Y / N = P%** |
| Output file | `<path>` |
| Criteria skipped due to missing data | `[list]` |

Then the email-verification offer (see Step 4).

---

## Common Pitfalls

| Problem | Fix |
|---|---|
| Auto-starting email verification after qualification | **Don't.** Always ask. The user owns the spend decision. |
| Running on a thin file (no employees / industry / description) without warning the user | The capability report must explicitly list which criteria got skipped. Silent skipping = silent miscalibration. |
| Web-fetching every company at Medium confidence | Bias to High. Most B2B companies are identifiable from name + domain. Reserve fetches for genuine unknowns. |
| Pushing a generic "looks fine" verdict on Low-confidence companies | Mark them `unknown — flag for manual review` and let the user decide. Never invent a verdict. |
| Re-using last run's criteria without confirming | Step 0 is mandatory every run. The only allowed shortcut is "same as last time" + a 4-line summary the user explicitly confirms. |
| Avoid-list misses on description/specialties when the file is thin | Tell the user up front: "this file has no LinkedIn descriptions, so the avoid-scan only sees company name + domain — precision will be lower for non-obvious competitors. Consider running the qualified list back through your usual website-check step (Claigent/Clay) before outreach." |
| Wrong column for location filter | Default to company location if available; only fall back to person location when company location isn't in the file. Tell the user which one was used. |
| Treating "Director" without a domain word as qualified | "Director" alone doesn't carry function — needs a sales/marketing/revenue/growth modifier nearby. Same for "Vice President" / "Head" / "Managing Director". |
| Em dashes / smart quotes in the user-supplied criteria leaking into regexes | Normalise the user's criteria text (lowercase, strip smart quotes, normalise whitespace) before compiling patterns. |
| Range-format employee counts being dropped as "size not numeric" | LinkedIn enrichments (Boomerang / Apollo / Sales Nav) store size as `11-50`, `201-500`, `10001+` — not plain integers. `qualify_list.py` now extracts the first integer and treats it as the lower bound. If the run report shows a high `size: size not numeric` count, the column has an unexpected format (text labels, decimals, "Self-employed") — inspect a sample before trusting the qualified set. The Boomerang re-qual run lost 25,604 rows on the first pass before this was patched. |
| Boomerang location uses ISO-2 codes with a "Primary" suffix | The trailing segment of `Linkedin Company Location` is often `IN`, `GB`, `BR`, `DE`, `US` — not the full country name — and is often preceded by a literal "Primary" tag. When pre-bucketing or hard-blocking by country, parse the trailing segment for **both** full names **and** ISO-2 codes, skipping "Primary"/empty segments. The first preprocess in the Boomerang re-qual leaked 12,897 India rows into high-GDP before this was caught. Always sanity-check hard-block counts against expectations. |
| `min_employees` is a single value — can't express tiered country rules | The config takes one `min_employees`. For "min 10 in high-GDP, min 100 in low-GDP, hard-block India/Pakistan-type" — pre-bucket the input by country, run `qualify_list.py` once per bucket with bucket-specific configs, then concat. See `references/country_tiers_preset.md` and Recipe 1 below. |
| Forgetting to subtract the existing Smartlead audience when "re-qualifying" | When the goal is *"find leads we missed before"*, the user almost always wants to drop leads already in active Smartlead campaigns first. Build the exclusion email set via `list_leads_by_campaign` (across all relevant campaigns), email-dedup the input before qualifying. Surface this in Step 0's criteria confirmation if the request is framed as a re-qual — users expect it without always asking. See Recipe 2 below. |

---

## Reference: How This Composes With Other Lilly Skills

| If the user asks… | Use this skill | Then potentially hand off to… |
|---|---|---|
| "Qualify this CSV of followers" | **lilly-company-followers** (this skill) | `lilly-email-verification` (next step) → `lilly-personalisation` (when pushing into Smartlead) |
| "Generate Why fragments for these leads" | `lilly-personalisation` | — |
| "Why is this campaign underperforming?" | `lilly-optimiser` | — |
| "Build me a Sales Nav search for [criteria]" | `Lily-Link-Creator` | export to follower-scrape → **lilly-company-followers** |
| "Verify these emails / find missing emails" | `lilly-email-verification` | — |
| "Build me a TAM" | `lilly-ocean-tam-builder` | export → **lilly-company-followers** |
| "Write the campaign copy" | `lilly-copywriter` | — |
| "LinkedIn / connection-request copy" | `lilly-linkedin-copywriter` | — |
