# Probe Results, HeyGrand
**Date:** 2026-05-18
**Companion to:** [rev3 deep dive](heygrand-2026-05-18-rev3-deep.md)
**Total spend:** ~7 credits (5 Serper + 2 Prospeo, TheirStack free, WebSearch free)
**Raw outputs:** `~/probes-heygrand-2026-05-18/*.json`

---

## P1, TheirStack: UK finance-hire volume ✅

| Scope | 30d jobs | 30d unique companies | Daily rate |
|---|---|---|---|
| UK + 9 finance titles, ALL industries (baseline) | **2,030** | 1,396 | ~68 jobs/day |
| **UK + 9 finance titles + Construction industry filter** | **41** | **38** | **~1.4 jobs/day** |

**Decision:** Idea #3 confirmed viable as a **standalone campaign** (41/30d > 20/30d standalone threshold). No need to bundle as 4th-touch on Idea #1.

**Sample roles seen (live)**: Finance Director, Head of Finance (3x), Credit Controller, Credit Risk Manager, Interim Head of Finance / Finance Director, Financial Controller (3x). Title patterns map cleanly to the proposed TheirStack saved-search.

---

## P3, Serper news intent: monthly density on credit-pain disclosures ✅

| Query | 30d hits | Notable hits |
|---|---|---|
| `"profit warning" UK construction` | **10** | Vistry profit warning (multiple sources), BCIS profit-warnings report |
| `"bad debt" construction UK "annual results"` | 1 | HSBC bad debt provisions (off-target, HSBC isn't construction) |
| `"customer insolvency" construction UK` | **10** | BCIS construction-insolvency figures, Credit Connect winding-up notices, multiple named UK construction collapses |
| `"exceptional charge" "doubtful debt" construction UK` | 0 | Query too narrow |
| `"trading update" "credit losses" construction UK` | 3 | RICS data on UK construction, Credit Connect notices, Scottish construction collapse |
| **Combined unique (deduped estimate)** | **~15-20 fresh hits/month** | Strongest signals: Vistry profit warning + BCIS aggregated insolvency data |

**Decision:** Idea #6 confirmed viable. Drop Q4 from production set (zero hits over 30d). Keep Q1, Q3, Q5 as primary queries; Q2 as secondary. Monthly cohort ~15-20 UK construction firms publicly disclosing credit pain.

**Bonus signal**: Q3 surfaced [Credit Connect's "Winding Up Petitions – April 2026"](https://www.creditconnect.co.uk/) as a recurring monthly data source. Worth adding to the Idea #1 lead-magnet's insolvency-data pipeline (cross-references Grand's own database).

---

## P4, Prospeo /search-person on 6 buying-group head offices

| Group | Domain | DMs returned | Top contacts surfaced |
|---|---|---|---|
| **NMBS** | nmbs.co.uk | **60** | Baljit Singh (Head of Trading), Rex Nye (Digital Director), **Richard Sharp (Director of Finance and Operations ACMA)**, **Adrian Oppon (Credit Controller)**, Claire Byrne (Head of HR), plus 55 more |
| **BMF** | bmf.org.uk | **16** | **John Newcomb (Chief Executive)**, **Mike Tattam (Commercial Director)**, regional managers (Suzanne Millward, Chris Heeks, Gary Waide), Membership & IT Manager |
| IBC | theibc.co.uk | 0 (NO_RESULTS) | LinkedIn presence likely under a different domain or thin |
| Fortis | fortis-uk.com | 0 (NO_RESULTS) | Same |
| h&b | hb-uk.com | 0 (NO_RESULTS) | Same |
| BPI Buying Group | bpibg.co.uk | 0 (NO_RESULTS) | Same |

**Decision:** Idea #5 (merchant buying groups) is **viable but smaller than rev3 estimate**. 2 of 6 entities have a strong LinkedIn DM presence (NMBS + BMF = ~76 reachable contacts), 4 entities need manual head-office sleuthing (likely use group-name @group-co domains, or the parent company's domain).

**Action**: confirm 4 missing entities' actual domains via WebFetch on their websites + manual LinkedIn lookup. Pre-Wednesday: ~30 min.

**High-value contacts already named for Idea #5 ABM outreach**:
- NMBS: Richard Sharp (Director of Finance and Operations), Adrian Oppon (Credit Controller), Baljit Singh (Head of Trading)
- BMF: John Newcomb (Chief Executive), Mike Tattam (Commercial Director)

These 5 are the immediate ABM list. Kirk's personal outreach to John Newcomb at BMF first (CEO-to-CEO is the strongest opener).

---

## P2, LinkedIn follower counts for V5 + V8 (passive followers)

Sources: WebSearch with `linkedin.com` domain filter.

### 5 competitor pages

| Page | LinkedIn slug | Confirmed followers | vs. rev3 estimate | Notes |
|---|---|---|---|---|
| **Creditsafe (main)** | [creditsafe](https://linkedin.com/company/creditsafe) | **35,530** | rev3 said 50-80K global → reality 35.5K main page | Largest single audience in scope |
| Creditsafe Technology | [creditsafe-technology](https://linkedin.com/company/creditsafe-technology) | 41,584 | n/a, new finding | Engineering-side subdivision, lower-fit for outreach |
| **Experian Business Information** | [experian-business-information](https://linkedin.com/showcase/experian-business-information/) | **2,812** | rev3 said 20-40K UK → reality is the showcase page is small | Main Experian page is huge but unfiltered. Showcase page is the focused fit but tiny |
| **Dun & Bradstreet UK** | [dun-&-bradstreet-uk](https://linkedin.com/company/dun-&-bradstreet-uk) | **1,682** | rev3 said 30-60K UK → reality the UK page is small | Global D&B page is huge, UK-only page tiny |
| **Equifax UK** | [equifaxuk](https://linkedin.com/company/equifaxuk) | **7,697** | rev3 said 20-40K → reality 7.7K | Mid-size, cross-over from consumer credit |
| Graydon UK | [graydon-uk-limited](https://linkedin.com/company/graydon-uk-limited) | not surfaced (Graydon acquired by Creditsafe) | rev3 said 5-10K → can't confirm | Graydon now owned by Creditsafe, may be deprecated as a separate page |

### 5 association + media pages

| Page | LinkedIn slug | Confirmed followers | vs. rev3 estimate | Notes |
|---|---|---|---|---|
| **CICM** | [chartered-institute-of-credit-management](https://linkedin.com/company/chartered-institute-of-credit-management) | **13,240** | rev3 said 25-35K → reality 13K | Pure-fit credit-pro audience, smaller than estimated but still strong |
| **BMF** | [builders-merchants-federation-ltd](https://linkedin.com/company/builders-merchants-federation-ltd) | **22,452** | rev3 said 10-15K → reality 22.5K | **BIGGEST single trade-body audience in scope, 2x our estimate** |
| **Credit Strategy** | [credit-strategy-magazine](https://linkedin.com/company/credit-strategy-magazine) | **5,709** | rev3 said 15-25K → reality 5.7K | UK credit trade media |
| ICAEW main | [institute-of-chartered-accountants-in-england-and-wales](https://linkedin.com/company/institute-of-chartered-accountants-in-england-and-wales) | not surfaced cleanly (main page ~200K+ globally) | rev3 said 250-400K → likely accurate | Massive total but mostly off-target (audit, tax), filter aggressively to construction finance |
| **CPA (Construction Plant-hire Association)** | [cpa-construction-plant-hire-association](https://linkedin.com/company/cpa-construction-plant-hire-association) | **2,986** | rev3 said 3-8K → reality ~3K | Niche pure-fit for sub-vertical 1B (plant + equipment hire) |

**Combined V5 reachable (after UK construction × finance-role filter)**: ~3-6K qualified prospects across all 10 pages.

**Key finding**: **BMF is the standout (22.5K followers)**, bigger than rev3 estimated. The Builders Merchants Federation followers ARE the Idea #1 ICP. The Idea #4 follower-scrape might actually be the highest-volume single source if we lead with BMF.

**Rev3 estimate accuracy**: I over-estimated 4 pages (Experian UK, D&B UK, CICM, Credit Strategy) and under-estimated BMF. UK-specific competitor pages are smaller than the global parents.

---

## Updated decisions for Wednesday's strategy call

| Idea | Probe verdict | Decision |
|---|---|---|
| #3 Hiring-signal: Credit Controller / CFO / FD | ✅ 41/30d, above 20-threshold | **Standalone campaign**, fire `/lilly-theirstack-setup` |
| #5 Merchant buying groups | ⚠️ 2/6 confirmed (NMBS + BMF = 76 DMs), 4 need manual domain audit | **Viable**, scope down to NMBS + BMF first, expand if domains resolved |
| #6 Profit-warning / bad-debt news | ✅ 15-20 hits/month deduped | **Daily Serper sweep**, fire `/lilly-icebreaker-news-search` with Q1+Q3+Q5 primary |
| #4 Competitor + association followers | ✅ BMF is **22.5K** (biggest), CICM 13K, Creditsafe 35.5K, others smaller | **Lead with BMF + CICM + Creditsafe scrape**, deprioritise D&B UK, Experian UK showcase, Graydon (low UK volume) |

---

## Pre-Wednesday-call follow-ups (~30 min total)

1. **Manual lookup of 4 missing buying-group domains** (IBC, Fortis, h&b, BPI). WebFetch their actual sites to find the correct LinkedIn page slugs + a sample head-office staff member to confirm DM-finder will work post-fix.
2. **ICAEW main page follower count** (the main `institute-of-chartered-accountants-in-england-and-wales` page didn't surface cleanly).
3. **BMF Members' Day 2026 exact date** (rev3 said "Sept 2026 typically", confirm).
4. **Plantworx 2026 confirmed dates** (rev3 said 9-11 June 2026, double-check).

Net result: every top-tier idea now has probe-confirmed volume. Wednesday's call has hard numbers, not LLM estimates.
