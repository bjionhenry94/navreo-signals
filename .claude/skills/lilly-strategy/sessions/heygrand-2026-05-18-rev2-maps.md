# Campaign Maps, Grand HQ (HeyGrand), rev2
**Date:** 2026-05-18
**Companion to:** [heygrand-2026-05-18-rev2.md](heygrand-2026-05-18-rev2.md) (shortlist + scoring)
**Purpose:** Concrete blueprints per idea, ready for Wednesday call review then build-skill firing.

Each map covers: audience filter spec, target persona, volume math, subject-line + opener seeds, magnet delivery flow, sequencing, build chain (literal commands), blockers, credit budget, launch-readiness ETA.

---

# Idea #1, Insolvency-list bait, builders merchants first

**Score:** 25/25. **Mechanism:** Targeted list (V1.A) × Grand insolvency data (M1).

## Audience filter spec

Input file: `CH_Cat1_Master_2026-05-15.csv` (Kirk's 88K UK construction master).

```
WHERE tier IN ('T2', 'T3')
  AND mcr_in_email_campaign != 'yes'
  AND mcr_in_linkedin_campaign != 'yes'
  AND sub_vertical = 'Builders Merchants'
  AND postcode_region IN ('M', 'BL', 'OL', 'WA', 'SK')   -- Greater Manchester pilot, replace post-call
```

## Persona enrichment

Persona 1 (primary, all sizes):
- Chief / Head of / Director / Manager / Controller of: Finance, Credit
- Accountant, Billing, Collections, Accounts Receivable, AR

Persona 2 (T3 only):
- Managing Director, General Manager, Owner, Director

Exclusions: "Account Manager" (client-facing, not credit decision-maker, per Navreo memory rule).

## Volume math

| Stage | Estimate | Source |
|---|---|---|
| Master list | 88,000 | Kirk's CH_Cat1_Master file |
| T2/T3 only | ~62,000 | Assume ~70% T2/T3 split (T1 ~5%, T4 ~25%) |
| MCR-excluded | ~58,000 | 4K MCR minus T1/T4 overlap |
| Builders merchants sub-vertical | ~18,000 | Assume 30% of Cat 1 by density (manufacturers + plant hire share remainder) |
| Greater Manchester pilot region | ~1,500-2,500 | ~10-15% of UK builders merchant TAM |
| DM enriched (Persona 1 + 2, avg 2 DMs/co) | ~3,000-5,000 | Prospeo primary, AI Ark fallback |
| Verified email rate ~55% (UK SMB tier) | ~1,650-2,750 verified contacts | AI Ark verification |
| Daily send capacity (10K/mo current → 40K/mo target) | ~330-1,300 sends/day during pilot | Existing Instantly + new domains |

Pilot region launches with ~1,650-2,750 inboxes. At 2-email sequence + sub-vertical-rollout cadence, pilot exhausts in ~10-14 days. Expansion to remaining UK regions thereafter.

## Subject-line + opener seeds (for `/lilly-copywriter`)

Subject candidates (target one variant per sub-vertical for A/B tracking):
- `"{builders_merchant_in_recipient_region} in admin this week"` (specific named co + region trigger curiosity)
- `"Manchester merchants insolvent this week, your list"`
- `"This week's bad-debt risks in {region}"`
- `"3 merchants on your beat just went into admin"`

Opener concept (~30-40 words, for Lilly to draft):
> Hi {firstname}, you've probably heard {specific_named_co} just went into administration last week, painful for everyone they owed money to. We pulled together this week's list across {region}, 7 firms in total. Want it?

Follow-up CTA: "Reply 'list' and I'll send it over. No catch, no demo ask."

## Magnet delivery flow

```
Recipient replies "list" or similar positive
    ↓
Auto-reply (Instantly) sends a Calendly-free link to a gated landing page
    ↓
Landing page collects: recipient's email confirmation + region + sub-vertical preference (pre-filled from CRM)
    ↓
Backend triggers Grand DB query:
    SELECT name, postcode, sic_code, last_filed_status
    FROM grand_companies
    WHERE postcode_region = {recipient_region}
      AND sic_code IN ({recipient_subvertical_buyer_codes})
      AND status_tag IN ('In Administration', 'In Insolvency', 'CVA')
      AND status_tag_date >= NOW() - INTERVAL '7 days'
    ↓
CSV emailed to recipient within 5 minutes
    ↓
Auto-reply 2 (24hrs later): "Did the list make sense? Here's how we flagged 4 of those firms 48-72hrs before CreditSafe did, want a 15min walkthrough?"
```

Engineering work for Kirk: build the per-region query as a callable endpoint. ~1-2 days dev effort, can ship a manual CSV-pull fallback for week 1.

## Sequencing

| Day | Touch | Channel | Content |
|---|---|---|---|
| 0 | Email 1 | Instantly | Bait subject + opener + region-specific reference to 1 named insolvency |
| +3 | Email 2 (if no reply) | Instantly | "Here's the second batch, plus 3 firms with profile downgrades this week" (different named insolvencies, fresh value) |
| +7 | LinkedIn connection (if no reply) | HeyReach | Same hook in 100-char LinkedIn DM, signed by Aiste for T3 / Kirk for T2 |
| +14 | Email 3 (if no reply, ~30% drop-off acceptable) | Instantly | Soft case study from peer + offer "free 30-day risk audit on your top 10 customers" |

## Build chain (literal commands when Kirk approves)

```
# Step 1: Triangulation, run once, blocking
python3 ~/scripts/triangulate_mcr_against_master.py \
  --master CH_Cat1_Master_2026-05-15.csv \
  --mcr MCR_Sellers_For_CH_Triangulation_2026-05-15.csv \
  --output CH_Cat1_Master_triangulated.csv

# Step 2: Filter to builders merchants × Greater Manchester pilot
# (Spreadsheet filter, no script)

# Step 3: DM enrichment
/lilly-decision-maker-finder
  Input: filtered builders-merchants subset CSV
  Personas: Persona 1 + Persona 2 (T3 only)
  Title exclusions: "Account Manager"
  Geo: GB
  Skip step-0 list expansion (88K is authoritative)

# Step 4: Email verification
/lilly-email-verification
  Input: enriched DM CSV
  Primary: AI Ark
  Fallback: Prospeo enrich-person

# Step 5a: Push verified to Instantly
# (Manual import to Instantly campaign for now, until Bjion has Instantly API access)

# Step 5b: Push no-email-found to HeyReach
/lilly-heyreach-upload
  Input: verified DM CSV (no_email_found rows only)
  List name: heygrand-cat1-bm-manchester-2026q2-linkedin
  Sender: Aiste (T3) or Kirk (T2)

# Step 6: Copy generation
/lilly-copywriter
  Brief: "HeyGrand Idea #1 Insolvency-list bait, builders merchants Manchester, see campaign map"
```

## Blockers / dependencies

| Blocker | Owner | ETA |
|---|---|---|
| Triangulation script vs. 2,900 unmatched MCR rows | Bjion + Claude Code | 1 day |
| Grand insolvency-list endpoint (or manual CSV pull) | Kirk's eng team | 1-2 days |
| Sender capacity (need ~30K/mo from this campaign alone if pilot expands) | `porkbun-domain-ideator` + warm-up | 14-21 days |
| Bounce-rate investigation on existing Instantly mailboxes | Renato | 1-2 days |
| Geo pilot decision (Greater Manchester vs. West Midlands vs. London) | Wednesday call | 2 days |

## Credit budget (pilot, Greater Manchester only)

| Item | Cost |
|---|---|
| DM enrichment (~1,500-2,500 cos × Persona 1+2) | ~150-250 Prospeo credits |
| Email verification (~3,000-5,000 contacts) | ~50-100 AI Ark credits + ~50 Prospeo (fallback) |
| Copy generation | 0 (LLM only via lilly-copywriter) |
| **Pilot total** | **~250-400 credits** |

## Launch-readiness ETA

5-7 days from green light, gated by triangulation + Grand endpoint readiness + initial DM enrichment batch.

---

# Idea #2, Trade-credit bait + personalised video, full Cat 1

**Score:** 22/25. **Mechanism:** Targeted list (V1, full Cat 1) × bait-and-switch (M6).

## Audience filter spec

```
WHERE tier IN ('T2', 'T3')
  AND mcr_in_email_campaign != 'yes'
  AND mcr_in_linkedin_campaign != 'yes'
  AND id NOT IN (already_used_by_idea_1)
  AND sub_vertical IN ('Plant & Equipment Hire', 'Construction Manufacturers', 'PPE Distributors',
                       'Chemicals & Coatings', 'Tool Dealers', 'Electrical Wholesalers')
```

(Builders merchants already covered by Idea #1, so this picks up the other 5 sub-verticals.)

## Persona enrichment

Same as Idea #1 (Persona 1 primary, Persona 2 for T3, exclude "Account Manager").

## Volume math

| Stage | Estimate |
|---|---|
| Cat 1 minus builders merchants minus MCR minus Idea #1 cohort | ~40,000-45,000 cos |
| T2/T3 only | ~28,000-32,000 |
| DM enriched (avg 2 DMs/co) | ~50,000-65,000 |
| Verified email rate ~55% | ~28,000-36,000 verified contacts |

Large, sustainable cohort. Roll out one sub-vertical per week to keep copy A/B clean.

## Subject-line + opener seeds

Subject (Kirk's currently-winning pattern, scale up):
- `"Quick one about trade credit"` (Kirk's tested winner)
- `"Trade credit account application"` (more explicit bait)
- `"Application for trade credit, your process"` (T2-flavoured)
- `"Hello, trade credit query"` (minimum-effort opener)

Opener concept:
> Hi {firstname}, hoping you can point me in the right direction. We're looking to set up trade credit with {recipient_company_name}, what's your usual process?

This is bait-and-switch: recipient assumes Grand is a builder applying for credit. The conversion lever is the video reply, not the email.

## Magnet delivery flow

```
Recipient replies positively ("happy to send you our application form" / "our process is...")
    ↓
Manual review by Kirk: positive lead flagged in Slack
    ↓
Kirk approves video trigger
    ↓
Pitchlane or escript generates per-recipient video:
    - Base video: Kirk recording 2-3min walkthrough of Grand
    - Per-recipient swap: opening "Hi {firstname}" + on-screen mention of {recipient_company_name}
    - Optional: opening frame shows recipient's actual website (Pitchlane feature)
    ↓
Auto-reply 2: "Hi {firstname}, before we fill out your form, wanted to tell you why we use Grand instead of CreditSafe to vet our customers, 2min video here: {pitchlane_link}"
    ↓
On video play: Calendly link in chat / £500 free-credit offer if T3 self-serve
    ↓
On Calendly book: T2 demo with Kirk
```

## Sequencing

| Day | Touch | Content |
|---|---|---|
| 0 | Email 1 | Trade-credit bait |
| +3 | Email 2 (no reply) | Softer follow-up: "Did you have a chance to look at our application?" |
| +7 | LinkedIn DM (no reply) | "Hi {firstname}, just nudging you about a trade credit account, OK to start the process?" |
| +14 | Email 3 (no reply) | Pivot to the platform: "By the way, since we're chasing credit accounts, we built a tool that flags when your existing customers go into trouble before CreditSafe does, want to see?" |

## Build chain

```
/lilly-decision-maker-finder
/lilly-email-verification
# Push to Instantly (different campaign from Idea #1)
/lilly-copywriter (trade-credit bait variant)

# Video pipeline, one-time setup:
1. Kirk records 3min base video
2. Pitchlane or escript account setup (subscription)
3. Manual reply-trigger workflow until automated
```

## Blockers / dependencies

- Kirk records the base video (~30min total inc. retakes)
- Pitchlane / escript subscription decision (~$200/mo, Renato to pick)
- Manual reply-flagging workflow in Instantly (Slack webhook)
- Same TAM-pipeline blockers as Idea #1 (triangulation, sender capacity)

## Credit budget (per sub-vertical wave, ~6,000 cos)

| Item | Cost |
|---|---|
| DM enrichment | ~600 Prospeo credits per wave |
| Email verification | ~200 AI Ark + ~100 Prospeo per wave |
| Pitchlane / escript | ~$200/mo flat |
| **Per-wave total** | **~900 credits + $200/mo tool** |

## Launch-readiness ETA

10-14 days from green light (gated by base-video recording + Pitchlane setup, then same TAM pipeline as #1).

---

# Idea #3, Newly-hired Credit Controller / CFO / FD signal

**Score:** 22/25. **Mechanism:** Hiring signal via TheirStack (V2.A + V2.B) × M3 risk-audit + M4 credits.

## Audience filter spec, TheirStack saved-search

```
Posted_date: last 60 days, rolling
Job_location_country: GB
Company SIC codes: Cat 1 construction (from Kirk's 88K master, SIC list)
Job title patterns (operational set, T3-weighted):
  - "Credit Controller"
  - "Senior Credit Controller"
  - "Credit Manager"
  - "Accounts Receivable Manager"
  - "Collections Manager"
Job title patterns (strategic set, T2-weighted):
  - "CFO"
  - "Chief Financial Officer"
  - "Head of Finance"
  - "Finance Director"
  - "Financial Controller"
Negative title filter:
  - "intern", "apprentice", "trainee", "junior", "assistant"
```

## Persona enrichment

The new hire IS the lead (no DM-finder step on most rows). Optional secondary enrichment: pull the hiring manager (CFO if the new hire is Credit Controller, MD if the new hire is CFO).

## Volume math

| Stage | Estimate (needs TheirStack probe) |
|---|---|
| UK construction × all finance hiring titles, last 60d | ~80-180 jobs estimated |
| Per month rolling | ~40-90 jobs / month |
| Unique companies (some post multiple roles) | ~30-65 cos / month |
| DM enriched (the new hire + 1 secondary contact) | ~60-130 contacts / month |
| Verified email rate ~60% (LinkedIn-sourced higher than CH-sourced) | ~36-78 verified / month |

Lean monthly volume, ~25-50 fresh sends per week. Suitable as a dedicated boutique campaign, not as a primary volume driver. Should bundle with weekly Idea #1 send for combined cadence.

## Subject-line + opener seeds

Subject (anchored to the role-change but NOT mentioning the hire per Navreo `skip_angles` rule):
- `"30-day risk audit on your top customers"`
- `"3 customers worth checking on your ledger"`
- `"Free credit-control audit, no catch"`

Opener concept (role-anchored, zero post reference per icebreaker rule):
> Hi {firstname}, I work with credit teams at builders merchants like {peer_company} who run a clean ledger but want a faster early-warning on customer risk. Worth 15min to walk through your top 10 customers together?

## Magnet delivery flow

```
Reply "yes" or "interested"
    ↓
Kirk's team manually pulls Grand DB risk-grades on recipient's top 10 customers (recipient supplies the list, or we infer from Grand's existing data on the recipient's trade relationships)
    ↓
Output: 1-pager showing each customer's current risk + 30-day trend + comparison to CreditSafe's last-known status
    ↓
Delivered as PDF email attachment + 30min Zoom walkthrough
    ↓
At end of Zoom: £500 credits unlocked + onboarding flow
```

## Sequencing

| Day | Touch | Content |
|---|---|---|
| 0 | Email 1 | Audit pitch (role-anchored, no hire reference) |
| +4 | Email 2 (no reply) | Variant CTA: "If 15min is too much, want the 1-pager template we use?" |
| +10 | LinkedIn DM (no reply) | Soft prompt + audit offer |
| +21 | Email 3 (no reply) | Cross-pollinate with Idea #1 insolvency list as a passive opener |

## Build chain

```
# Phase 1: Probe (free, run before Wednesday)
/lilly-theirstack-setup
  Mode: Phase 2 free-preview only
  Title patterns: see audience filter
  Confirm: 30-day TAM ≥ 20 jobs?

# Phase 2: If TAM ≥ 20, full setup
/lilly-theirstack-setup
  Mode: full provisioning
  Brief: see "audience filter" + "magnet flow" + "sequencing" above
  Icebreaker config: skip_angles=["Hiring", "You joined"]   ← per Navreo memory rule
  Output destination: Make.com scenario → Sheet → Instantly (or HeyReach for no-email)

# Phase 3: Daily ops
/lilly-theirstack-data-processing
  Run daily, idempotent
```

## Blockers / dependencies

- TheirStack volume probe (free, ~10min)
- Risk-audit 1-pager template (Kirk's CS team designs, ~2-3 hrs)
- Manual reply review flow (Kirk owns)

## Credit budget

| Item | Cost |
|---|---|
| TheirStack subscription (existing Navreo plan) | 0 |
| DM enrichment (~50 cos / month, avg 2 DMs) | ~50-100 Prospeo / month |
| Email verification | ~30 AI Ark / month |
| **Monthly recurring** | **~80-130 credits / month** |

## Launch-readiness ETA

7-10 days from green light, gated by probe + audit-template build.

---

# Idea #4, Competitor LinkedIn followers (CreditSafe + Experian + D&B + Graydon)

**Score:** 21/25. **Mechanism:** Passive followers (V5.A-C) × M5 head-to-head report.

## Audience filter spec, Trigify saved-searches

```
Tracked LinkedIn pages:
  - linkedin.com/company/creditsafe
  - linkedin.com/company/experian-business
  - linkedin.com/company/dun-and-bradstreet
  - linkedin.com/company/graydon

Engagement type: follower (NOT post-engagement, per Kirk red flag)
Geo filter (applied post-scrape): GB
Title filter (applied post-scrape):
  - Persona 1 titles (Credit Controller, Credit Manager, Head of Credit, CFO, Head of Finance, FD, AR Manager)
Company filter (applied post-scrape):
  - SIC codes intersection with Kirk's 88K Cat 1 list (or recipient claims construction sector)
```

Note: Trigify (or any LinkedIn follower-scrape tool) returns 100% of followers paginated; the filters above are Navreo-side post-processing via `lilly-company-followers`.

## Volume math (needs LinkedIn follower-count lookup probe)

| Page | Estimated total followers | UK construction finance filter (~1-3%) |
|---|---|---|
| CreditSafe UK | ~30,000-50,000 | ~300-1,500 |
| Experian Business UK | ~50,000-100,000 | ~500-3,000 |
| Dun & Bradstreet UK | ~30,000-50,000 | ~300-1,500 |
| Graydon UK | ~5,000-10,000 | ~50-300 |
| **Combined unique** | ~100,000-180,000 | **~1,000-5,000 qualified** |

Probe needed: actual follower counts via `/lilly-linkedin-page-finder`.

## Persona

Persona 1 only (we KNOW these followers care about credit-intelligence tooling; less need to fish with Persona 2).

## Subject-line + opener seeds

Subject (competitor-aware):
- `"CreditSafe vs Grand on 3 of your customers"`
- `"Free side-by-side, your top 3 trade-credit risks"`
- `"What CreditSafe missed on {a_named_recent_insolvency}"`

Opener concept:
> Hi {firstname}, I noticed you follow CreditSafe on LinkedIn. Quick offer, we'll pull a free side-by-side of CreditSafe's data vs ours on any 3 customers you pick. We flag risk 48-72hrs faster on average, often by weeks. Worth a look?

## Magnet delivery flow

```
Reply with 3 named customer companies
    ↓
Kirk's analyst (or automated query if endpoint exists) pulls:
  - CreditSafe current grade (if Grand has access to compare)
  - Grand current grade
  - Grand 30-day trend
  - Last 6 events (signals, filings, news) per customer
    ↓
1-page side-by-side PDF, branded
    ↓
Email delivery + 15min Zoom offer
    ↓
On Zoom: walkthrough + £500 credits to onboard
```

## Sequencing

Same 4-touch cadence as Idea #3, with copy variants emphasising the competitor comparison angle.

## Build chain

```
# Phase 1: Probe (free, manual LinkedIn follower-count lookup)
/lilly-linkedin-page-finder
  Verify follower counts on 4 pages above
  Output: confirmed counts + recommended scrape order

# Phase 2: Follower scrape (Trigify or equivalent, outside Lilly skill chain)
# Run Trigify (or Phantombuster) follower-list export per page
# Combine, dedupe by LinkedIn URL

# Phase 3: Qualification
/lilly-company-followers
  Input: combined follower CSV
  Qualification criteria:
    - Geo = GB
    - Title in Persona 1
    - Company SIC in Cat 1 construction (intersect with Kirk's 88K master to confirm)
  Output: qualified list

# Phase 4: DM enrichment (some followers will already have public email on profile)
/lilly-decision-maker-finder
  Mode: enrich-only (no list expansion)
  Input: qualified list with LinkedIn URLs

# Phase 5: Email verification + push
/lilly-email-verification
# Push to Instantly + HeyReach
```

## Blockers / dependencies

- Trigify subscription seat (Renato to set up)
- 1-2 days of Trigify scrape time per page (rate-limited)
- Manual analyst pull for the head-to-head 1-pager (until automated)
- LinkedIn follower-count probe (free, 5min, can do now)

## Credit budget

| Item | Cost |
|---|---|
| Trigify scrape (per page) | ~10-30 credits per page × 4 pages = ~40-120 credits |
| DM enrichment | ~200-500 Prospeo |
| Email verification | ~100-200 AI Ark |
| **One-time setup** | **~350-820 credits** |

## Launch-readiness ETA

14-21 days from green light. Trigify scrape is the longest pole.

---

# Idea #5, Merchant buying groups (NMBS, IBC, Fortis, h&b)

**Score:** 20/25. **Mechanism:** Concentrated B2B network (V1.H) × M10 custom group-credit-policy template.

## Audience filter spec

Manual list of UK merchant buying-group head offices. Known entities:

| Group | Members (approx) | LinkedIn | Notes |
|---|---|---|---|
| [NMBS (National Merchant Buying Society)](https://www.nmbs.co.uk/) | ~720 member firms | linkedin.com/company/nmbs | Largest UK builders-merchant co-op |
| [The IBC](https://www.theibc.co.uk/) | ~140 member firms | linkedin.com/company/the-independent-builders-merchants-consortium | Tier above NMBS by avg member size |
| [Fortis](https://www.fortis-uk.com/) | ~150 member firms | linkedin.com/company/fortisuk | National network |
| [h&b](https://www.hb-uk.com/) | ~750 member firms | linkedin.com/company/h-and-b | Decorative + DIY-leaning, broader catalogue |
| [BPI (British Plumbing Industries) Buying Group](https://www.bpibg.co.uk/) | ~60 member firms | n/a | Niche, plumbing |
| [BMF (Builders Merchants Federation)](https://www.bmf.org.uk/) | ~720 member firms | linkedin.com/company/builders-merchants-federation | Industry body, includes most buying groups + standalone merchants |

Targets: ~6 head-office entities, Group Credit Manager + Head of Finance + MD per entity.

## Persona enrichment

- Group Credit Manager
- Group Head of Credit
- Group Finance Director
- Group CFO
- Group MD (decision-maker on member-platform endorsements)
- Head of Member Services (gatekeeper for endorsing tools to members)

## Volume math

| Stage | Estimate |
|---|---|
| Target head-office entities | 6 |
| Target persons per entity | 4-6 |
| Total target prospects | ~24-36 |
| Verified email rate (executive-level) | ~70% |
| Reachable contacts | ~17-25 |

Tiny list. Treat as ABM. The PRIZE is a member-endorsement, which would unlock thousands of NMBS / IBC / Fortis / h&b members in one move.

## Subject-line + opener seeds

Subject (group-aware):
- `"NMBS members, this week's worst credit risks"`
- `"A standard credit-policy template for your 720 members"`
- `"Group-wide credit visibility, NMBS pilot proposal"`

Opener concept (Kirk-signed, T1/T2-flavoured):
> Hi {firstname}, NMBS members face a shared problem: each one runs their own credit policy + each one gets blind-sided by the same insolvent customers. We've built a credit-intelligence platform that flags customer risk 48-72hrs faster than CreditSafe. Would you have 20min to walk through a group-wide pilot we'd propose at no cost to NMBS?

## Magnet delivery flow

```
Reply positive
    ↓
Kirk personally takes the call (T1 motion, exec-to-exec)
    ↓
Deliverable: bespoke group-credit-policy template (1-page PDF) + a free group-level dashboard mockup showing aggregated risk across N member firms
    ↓
Ask: group endorses Grand to all members + Grand pays a referral fee per member converted
```

## Sequencing

Bespoke per entity. Email 1 personalised by Kirk + Bjion. LinkedIn DM at +5d. Phone follow-up at +10d (Kirk's mobile). No mass-sequence; this is exec-to-exec ABM.

## Build chain

```
# Phase 1: Confirm entities + Group Credit Manager presence (free)
/lilly-linkedin-page-finder
  Pages: NMBS, IBC, Fortis, h&b, BPI BG, BMF
  Verify follower counts + active Group Credit Manager LinkedIn presence

# Phase 2: DM enrichment
/lilly-decision-maker-finder
  Domain list: nmbs.co.uk, theibc.co.uk, fortis-uk.com, hb-uk.com, bpibg.co.uk, bmf.org.uk
  Personas: Group titles above
  Mode: enrich-only

# Phase 3: Email verification
/lilly-email-verification

# Phase 4: Manual exec-to-exec outreach via Instantly + LinkedIn + phone
# Kirk + Bjion own this list, no mass-sequencing
```

## Blockers / dependencies

- Group-credit-policy template design (1-2 days Kirk + Bjion collaboration)
- Group-dashboard mockup (Kirk's eng or design team, ~3-5 days)
- Kirk's calendar availability for exec calls (allow 2-4 calls in next 30 days)

## Credit budget

| Item | Cost |
|---|---|
| DM enrichment (6 cos × ~5 personas) | ~30 Prospeo |
| Email verification | ~10 AI Ark |
| **One-time** | **~40 credits** |

Ultra-cheap on credits; expensive on Kirk's time.

## Launch-readiness ETA

3-5 days from green light. Smallest, fastest blueprint of the lot.

---

# Idea #6, Profit-warning / bad-debt-disclosure news intent

**Score:** 20/25. **Mechanism:** News intent (V7.E) × M5 head-to-head report.

## Audience filter spec, Serper query template

```
Query 1: "profit warning" UK construction site:companieshouse.gov.uk OR site:gov.uk OR site:proactiveinvestors.co.uk
Query 2: "bad debt" OR "doubtful debt" construction site:investegate.co.uk
Query 3: "exceptional charge" customer insolvency construction UK
Query 4: "credit losses" interim results UK builders merchant
Query 5: site:gov.uk "regulated information service" construction insolvent customer
Filter window: last 30 days
```

Outputs: list of UK Cat 1 construction firms that have publicly disclosed bad-debt charges, profit warnings tied to customer insolvency, or exceptional credit-loss provisions in their last reporting cycle.

## Volume math

| Source | Monthly estimate |
|---|---|
| Public profit warnings (LSE-listed, AIM, regulated) | 5-15 / month UK-wide construction |
| Annual report disclosures (Companies House filings text-indexed) | 20-40 / month (one-off picks, varies by season) |
| Industry-press coverage (Construction News, Building) | 10-20 / month |
| **Unique cos after dedup** | **~15-30 / month** |

Small monthly cohort, but every prospect is a HOT lead. Each has just been publicly burned by a CreditSafe miss.

## Persona enrichment

- CFO (priority, signed the disclosure)
- Head of Finance / Finance Director
- Head of Credit / Credit Manager (closest to the pain)

## Subject-line + opener seeds

Subject (oblique, NEVER mentions the bad-debt event directly, too sensitive):
- `"Credit-intelligence for {company_name}'s top 50 customers"`
- `"3 customer-risk insights we'd flag for you"`
- `"How we'd protect against a repeat of {industry_term}"`

Opener concept:
> Hi {firstname}, we're a credit-intelligence platform built for finance teams at construction firms. Quick offer, we'll run a free risk-screen on the top 50 customers of {company_name}. Most teams discover 2-3 names they didn't realise had downgraded. Want it?

CRITICAL: don't reference the specific profit warning. Highlighting their public pain feels intrusive; offering the SOLUTION is welcome.

## Magnet delivery flow

Same as Idea #4 head-to-head report, scaled up: 50 customers risk-screened instead of 3.

## Sequencing

Same 4-touch cadence as Idea #3.

## Build chain

```
# Phase 1: Probe Serper query density (cheap, ~10 credits)
/lilly-icebreaker-news-search
  Mode: test against the 5 query templates above
  Confirm: ≥10 unique cos / month?

# Phase 2: Daily Serper sweep
/lilly-icebreaker-news-search
  Mode: rolling daily sweep
  Filter: stale-cutoff 30d
  Output: new cos / day to enrich

# Phase 3-5: same as Idea #3
```

## Blockers / dependencies

- Serper query template testing (10min)
- Risk-screen on 50 customers requires recipient to share their AR ledger or top-customer list (sensitive; needs Kirk's positioning)

## Credit budget

| Item | Cost |
|---|---|
| Serper sweep (daily, ~50 cos/month) | ~50-100 Serper / month |
| DM enrichment | ~30-60 Prospeo / month |
| Email verification | ~20 AI Ark / month |
| **Monthly recurring** | **~100-180 credits / month** |

## Launch-readiness ETA

7-10 days from green light. Serper query refinement is the slow part.

---

# Ideas #7-#10, brief maps

### Idea #7, Multi-finance-role hire signal (firms hiring 2+ finance roles in 90d)

**Mechanism:** TheirStack aggregation (V2.D) × M3 risk-audit.

- Same TheirStack saved-search as Idea #3 BUT post-filter to companies with ≥2 distinct finance roles posted within 90 days.
- Expected volume: ~5-15 cos / month (function build-out is rare but high-signal).
- Build chain: bundle on top of Idea #3 TheirStack feed. Custom aggregation logic in `lilly-theirstack-data-processing` (~1hr dev).
- Credit budget: same as Idea #3 (no incremental cost).

### Idea #8, CICM followers + member directory scrape

**Mechanism:** Passive followers (V5.E) + manual scrape × M10 credit-policy template + M4 credits.

- Audience: [CICM company page](https://linkedin.com/company/chartered-institute-of-credit-management) followers + members listed in CICM's [Knowledge Hub](https://www.cicm.com/) directory.
- Volume probe: CICM has ~30K LinkedIn followers; member directory ~9K active certified credit professionals.
- UK construction filter narrows to ~500-1,500 qualified prospects.
- Build chain: Trigify scrape + manual CICM directory CSV download (publicly available to members; Kirk holds CICM membership? if not, ~£200/yr).
- Credit budget: ~100 Trigify + ~150 Prospeo + ~50 AI Ark = ~300 credits.
- Launch ETA: 14 days, gated by CICM directory access.

### Idea #9, CICM Annual Conference speaker + attendee scrape

**Mechanism:** Event scrape (V4.E) × M5 head-to-head OR M9 peer case study.

- Source: CICM Annual Conference (next: typically October). Speaker list public; attendee list requires CICM membership or Trigify-style scrape.
- Volume: ~50 speakers (high-tier) + ~500-1,000 attendees (mixed-tier).
- Build chain: manual scrape + LinkedIn enrichment + Persona 1 filter + Cat 1 construction filter.
- Credit budget: ~50 Prospeo + ~20 AI Ark = ~70 credits.
- Launch ETA: 21 days, gated by conference list availability. Best deployed in Q3 ahead of the next event date.

### Idea #10, BMF Members' Day + UK Construction Week exhibitor scrape

**Mechanism:** Event exhibitor scrape (V4.A + V4.B) × M1 insolvency-list re-use.

- Source: BMF Members' Day (typically September) and UK Construction Week (May / October) exhibitor lists. PDFs published on event sites.
- Volume: BMF Members' Day ~300 exhibitors, UK Construction Week ~600 exhibitors. After dedup with Kirk's 88K master, ~70-80% will already be in scope (so the value here is more about timing the outreach + claiming an event-relevant angle than fresh prospect supply).
- Build chain: manual PDF parse → dedup against 88K → flag event-attendee subset for event-themed copy.
- Credit budget: ~0 incremental (cos already in master).
- Launch ETA: 30+ days, deploy ahead of event date for "see you at the show" angle.

---

# Cross-idea dependencies + critical path

```
                 ┌─ Triangulation ───┐
                 │  (1 day, blocking) │
                 │                    ↓
Idea 1 ──────────┼────→ DM enrichment + verification (3-5 days)
Idea 2 ──────────┘                    ↓
                                  Instantly push
                                      ↓
                              Launch first cohort

Idea 3 ──── TheirStack probe (10min) ────→ full setup (3-5 days) ──→ launch
                                                  │
                                                  ↓
                                            Idea 7 (bundle)

Idea 4 ──── LinkedIn probe (5min) ────→ Trigify scrape (1-2 days) ────→ qualify + enrich (5-7 days) ──→ launch

Idea 5 ──── Manual entity list (1hr) ──→ DM enrich + magnet build (3-5 days) ──→ exec outreach

Idea 6 ──── Serper probe (10min) ────→ daily sweep setup (1-2 days) ──→ launch

Idea 8 ──── CICM membership (separate) ──→ followers + directory scrape (2-3 days) ──→ launch
Idea 9 ──── (Q3 deploy ahead of event)
Idea 10 ─── (Q3 deploy ahead of event)
```

**Bottleneck:** Triangulation + Grand insolvency endpoint + sender capacity gate Ideas 1, 2, 3, 4. These need to start TODAY.

---

# Probes to run now (free, ~25 minutes of work)

| Probe | Purpose | Cost | Time |
|---|---|---|---|
| 1. TheirStack free preview, UK construction × finance titles, 30d window | Confirm Idea #3 volume ≥20 jobs/month | 0 | 5 min |
| 2. LinkedIn follower-count on CreditSafe, Experian, D&B, Graydon, CICM, BMF | Confirm Idea #4 + #8 reach | 0 (manual) | 5 min |
| 3. Serper query test on profit-warning + UK construction | Confirm Idea #6 monthly density | ~10 Serper | 10 min |
| 4. Manual entity-count audit on UK merchant buying groups | Confirm Idea #5 head-office target list | 0 | 5 min |

Recommendation: fire all four probes before Wednesday's strategy call so Kirk sees confirmed numbers, not LLM estimates.

---

# Concrete next actions

| Action | Owner | When | Status |
|---|---|---|---|
| 1. Triangulation script vs 2,900 MCR rows | Bjion + Claude Code | Today | Ready to fire |
| 2. Kick off `/porkbun-domain-ideator` for HeyGrand brand-orbit | Bjion + Claude Code | Today | Ready to fire |
| 3. TheirStack volume probe (Idea #3) | Renato + Claude Code | Tomorrow | Free, blocking nothing |
| 4. LinkedIn follower-count lookups (Idea #4 + #8) | Renato | Tomorrow | Free, blocking nothing |
| 5. Serper test query on profit-warnings (Idea #6) | Renato + Claude Code | Tomorrow | ~10 credits, blocking nothing |
| 6. Buying-group head-office DM enrichment (Idea #5) | Renato + Claude Code | Tomorrow | ~40 credits |
| 7. Geo sub-region decision for Idea #1 pilot | Wednesday call | Wed | Kirk decision |
| 8. Sender-platform decision (Instantly vs Smartlead) | Wednesday call | Wed | Kirk decision |
| 9. Renato gets Instantly access | Kirk | Today | Slack DM |
| 10. Kirk records the Idea #2 base video (3min walkthrough) | Kirk | This week | His calendar |

---

*Campaign maps generated 2026-05-18 via `/lilly-strategy` Phase 5-6. Companion to rev2 shortlist. Ready for Wednesday call.*
