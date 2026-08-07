---
name: lilly-linkedin-page-finder
description: "Discover and verify LinkedIn company pages matching a brief — competitors of a target company, tools/platforms an ICP uses, agencies in a vertical, brands an audience follows, etc. Use this skill whenever the user asks for a list of LinkedIn company pages to scrape followers from, find competitors of a company on LinkedIn, identify SaaS tools or vendors that an ICP would follow, build a list of agencies/influencers to target, find page slugs for a set of named companies, or verify follower counts on a list of LinkedIn pages. Trigger on phrases like 'find me LinkedIn company pages for X', 'find competitors of Y on LinkedIn', 'what tools does my ICP follow', '20 LinkedIn pages to scrape', 'rival agencies between 30K and 100K followers', 'LinkedIn pages of Amazon agencies', 'companies similar to Z on LinkedIn', 'find LinkedIn page slugs for these brands', 'verify follower counts on this list'. Always returns a structured table with rank, company name, LinkedIn slug as a markdown link, follower count, and a one-line positioning/relevance note — formatted to match the output style of the loom-research skill's competitor table for downstream reuse."
---

# Lilly LinkedIn Page Finder

## Purpose

Produce a verified, ranked list of LinkedIn company pages matching the user's brief — typically for follower-scrape outreach campaigns ("we scraped X's followers and reached out"). The brief can be:

- **Competitors** of a target company ("find me 20 rivals to Helium 10 on LinkedIn")
- **Tools** an ICP uses ("Amazon brand owners follow which SaaS tools on LinkedIn?")
- **Agencies / vendors** in a vertical ("find Amazon agencies between 30K-100K followers")
- **Influencers / personal pages** of named-people in a niche
- **Verification** of slugs/counts for a user-supplied list

Output is always a structured table the user can paste into a follower-scrape workflow (PhantomBuster, TexAu, Boomerang, Apify) and onward into Sales Nav, AI Ark, or Smartlead.

---

## When to Use

Trigger on any of:

- "Find me LinkedIn company pages for [X]"
- "Find competitors of [Y] on LinkedIn"
- "What tools does my ICP follow on LinkedIn?"
- "20 LinkedIn pages to scrape"
- "Rival agencies between [N]K and [M]K followers"
- "LinkedIn pages of [niche] agencies"
- "Companies similar to [Z] on LinkedIn"
- "Find LinkedIn page slugs for these brands"
- "Verify follower counts on this list"
- User pastes a list of company names and asks for LinkedIn URLs/follower counts
- User asks for follower-scrape targets

**Do not trigger on:**
- "Research this company in depth" → `loom-research` (does competitors as part of a 6-task pack)
- "Build a Sales Nav URL" → `lilly-sales-nav-builder`
- "Find lookalike *companies* (not pages) for a TAM" → `lilly-ocean-tam-builder`
- "Qualify a CSV of followers" → `lilly-company-followers`

If the user wants Loom research, this skill's output is also the right shape for the loom-research Task 6 competitor table — they're compatible.

---

## Workflow

### Step 0 — Confirm the brief

Send the user this template (or pre-fill from earlier conversation context). Wait for confirmation before searching.

```
I'll find and verify LinkedIn company pages once you confirm:

1. SEARCH TYPE — pick one:
   a) Competitors of a specific company
   b) Tools / SaaS / platforms an ICP uses
   c) Agencies / vendors in a vertical
   d) Influencer / personal LinkedIn pages
   e) Verify a list I'll paste below
   →

2. ANCHOR — depending on type:
   For (a): the target company's name + URL
   For (b): describe the ICP (industry, role, what they care about)
   For (c): the vertical / niche + any geography
   For (d): the niche + persona
   For (e): paste the list of company names or LinkedIn URLs
   →

3. FOLLOWER COUNT RANGE — default 10K-100K. Common ranges:
   - 30K-100K (sweet spot — large enough to scrape volume, niche enough for signal)
   - 10K-50K (mid-tier specialists)
   - 100K+ (broad audiences, lower signal)
   - Any (no limit)
   →

4. HOW MANY PAGES — default 10. Hard limits: typically can verify ~20 in one pass.
   →

5. EXCLUDE — companies you don't want in the result (current clients, your own company, ineligible competitors)
   →
```

If the user replies in freeform prose, structure it back into the 5 fields and confirm before searching.

### Step 1 — Brainstorm candidate list

Combine LLM knowledge with web search to surface candidates. Order of operations:

**1a. LLM-prior brainstorm.** From training, list 20-40 likely candidates matching the brief. For "Amazon agencies" that's My Amazon Guy, SalesDuo, Pattern, Tinuiti, Acadia, etc. Cast a wide net here — over-collect, under-prune later.

**1b. Web search to expand and validate.** Run `WebSearch` queries in parallel batches. Useful patterns:

- `top {category} {current_year} list` — surfaces published rankings
- `best {category} for {ICP description}` — surfaces curated lists
- `{anchor_company} alternatives` / `{anchor_company} competitors` — for type (a)
- `tools {ICP_role} use {current_year}` — for type (b)
- `top {niche} agencies {country}` — for type (c)

Run independent queries in parallel (multiple `WebSearch` calls in a single turn). Don't search sequentially — wastes context.

**1c. Read 1-2 list articles** with `WebFetch` if the rankings are paywalled-summary in search results. Pick the most authoritative-looking source.

After this step you should have **30-50 candidates**, more than the user asked for. Pruning happens at follower-verification time.

### Step 2 — Verify follower counts and slugs

This is the most expensive part — every candidate needs a follower count check. Strategy:

**2a. Batch parallel queries.** Run `WebSearch` for **5-6 candidates per query** using `OR` operators:

```
"Helium 10" OR "Jungle Scout" OR "SalesDuo" OR "My Amazon Guy" OR "Pattern" LinkedIn followers
```

LinkedIn search results often include follower counts in the snippet. If the snippet doesn't show the count, the URL itself reveals the slug.

**2b. Multiple batches in parallel.** Issue 4-6 batches in a single turn. With 30-50 candidates, that's 6-10 queries — under 1 turn's parallelism budget.

**2c. Disambiguate slug collisions.** Some company names have multiple LinkedIn pages (e.g. "Pattern" has `pattern-hq`, `thisispattern`, `pattern-digital`, ...). Pick the one matching the user's brief — usually verified by checking the page description in search snippets.

**2d. Personal vs company pages.** If the user asked for company pages, prefer `linkedin.com/company/{slug}`. If they explicitly want personal pages (or the niche is influencer-led, like Steven Pope at My Amazon Guy), include `linkedin.com/in/{slug}` with a clear flag.

**2e. Note unverified candidates.** If a candidate's count can't be confirmed via search, drop it — don't fabricate. The diagnostic at the end says "N candidates found, M verified, K dropped (no count)".

### Step 3 — Bucket and rank

Sort by follower count, then bucket:

- **Tier 1 — In range** (matches user's range exactly)
- **Tier 2 — Above range** ("flag but skip" if user requested narrow range)
- **Tier 3 — Below range** ("near-miss" — include only if Tier 1 is short of target count)

If Tier 1 has fewer pages than the user asked for, fill from Tier 3 (nearest first) and label them clearly as below-threshold rather than padding with random irrelevant names.

### Step 4 — Produce the table

Output as a markdown table matching this exact column structure (so it's reusable for the `loom-research` skill's Task 6):

```
| # | Competitor | LinkedIn | Followers | Positioning / Relevance |
|---|---|---|---|---|
| 1 | **{Name}** | [linkedin.com/company/{slug}](https://www.linkedin.com/company/{slug}) | {count} | {one-line why-it-matters} |
```

Notes on formatting:
- Render LinkedIn as a markdown link with the path-only label (`linkedin.com/company/{slug}`) — not bare URL or full https://.
- Bold the company name in the second column.
- Follower counts: format with thousands separators (`50,230` not `50230`).
- Positioning: ONE line — what they do, why they're relevant, and any flag (size tier, geography, sub-threshold).
- Personal pages: use `linkedin.com/in/{slug}` and label "(personal)" in positioning.

After the main table, add up to two optional supplementary tables:

```
## Tier 2 — Above range (flagged but excluded)

[same column structure, only if Tier 2 has ≥3 entries]

## Tier 3 — Near-miss (below range)

[same column structure — include only entries used to fill Tier 1 short]
```

Finish with a `**Sources:**` section listing every URL used as markdown links.

---

## Common Pitfalls

| Problem | Fix |
|---|---|
| LLM brainstorm produces names without verifying they exist on LinkedIn | Always run Step 2 verification — never output a slug you haven't seen confirmed in a search result. |
| Search snippets don't show follower count for some candidates | Issue a second targeted query: `"{exact company name}" LinkedIn followers count`. If still no count, drop. |
| User asks for "competitors" but a tool/SaaS keeps appearing | Tools' follower bases ARE the user's ICP, so they're often a better scrape target than direct rival agencies. Include with a clear "tool/platform" tag in Positioning rather than excluding. |
| Personal LinkedIn pages have huge followings (e.g. founder-led companies) | If relevant to the niche (Amazon-creator culture), list separately under "Bonus personal pages" — don't mix into the main company table, since the URL pattern (`/in/`) and scrape mechanics differ. |
| Company name collisions on LinkedIn | Always verify the slug matches the description in the search snippet before including. "Pattern" alone is ambiguous; "Pattern (Amazon accelerator)" → `pattern-hq`. |
| User asks for 20 in a 30K-100K range and only 12 verify in range | Surface that constraint honestly: "Pure-niche specialists are typically sub-30K — here are 12 in range plus 8 strong near-misses (15-30K) to round out 20." Don't pad with irrelevant 30K+ companies. |
| Search returns 2024-era data | Web search now defaults to current year — explicitly include `{current_year}` in queries to get fresh follower counts. |

---

## Examples of good briefs

**Good — competitor scrape for Amplifyy outreach:**
```
SEARCH TYPE: c (Agencies in a vertical)
ANCHOR: Amazon brand-management agencies, US-led
RANGE: 30K-100K
COUNT: 20
EXCLUDE: Amplifyy itself, Pattern (already at 120K)
```

**Good — tool ecosystem for ICP discovery:**
```
SEARCH TYPE: b (Tools / SaaS)
ANCHOR: Founders of 11-50 employee Shopify DTC brands, beauty/skincare
RANGE: any
COUNT: 15
EXCLUDE: nothing
```

**Bad — too vague:**
```
"Find me some LinkedIn pages"
```

For a vague brief, ask the 5 confirmation questions before searching.

---

## Composes with

| If the user then asks… | Hand off to |
|---|---|
| "Now scrape these followers" | External tool (PhantomBuster / TexAu / Boomerang / Apify) — not a Lilly skill |
| "Qualify the scraped followers against my ICP" | `lilly-company-followers` |
| "Build a Sales Nav search to find people at these companies instead" | `lilly-sales-nav-builder` |
| "Now find lookalike *companies* (not just LinkedIn pages)" | `lilly-ocean-tam-builder` |
| "Now make a Loom research pack on the top company in this list" | `loom-research` |
| "Verify and enrich emails for these prospects" | `lilly-email-verification` |
| "Build a Smartlead campaign targeting these companies' followers" | `lilly-bot` |

---

## Style rules

- Always render LinkedIn URLs as markdown links with path-only label.
- Always include follower counts — never output a row without a verified number.
- Sort by follower count, descending.
- One sentence per Positioning cell — dense and factual, no fluff.
- When in-range candidates fall short, surface the constraint explicitly rather than padding.
- For named brands the user already knows (e.g. "Helium 10"), skip the over-explanation and just confirm the LinkedIn slug + count.
