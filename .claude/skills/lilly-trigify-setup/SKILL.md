---
name: lilly-trigify-setup
description: One-time-per-brief setup wizard for Trigify-driven LinkedIn engagement-signal pipelines. Captures the user's brief (ICP, offer, signal rationale, competitor accounts to track, direct-rival avoid list), provisions all the infrastructure programmatically via the Trigify MCP (one LinkedIn-profile saved search per tracked profile, one Workflow per saved search that fetches engagements and POSTs to Make), Drive (Google Sheet with an Engagers tab), Make.com (single Engagers scenario cloned from a template), Smartlead (campaign skeleton with the correct merge variables), and a brief config JSON file consumed downstream by lilly-trigify-data-processing. Engager IS the lead (no DM-finder phase needed); email enrichment runs via Prospeo enrich-person against each engager's LinkedIn URL, falling back to AI Ark. Use whenever the user wants to set up a new Trigify brief, spin up a LinkedIn engagement pipeline, track competitor engagement signals for a new audience or client, ideate which competitor / thought-leader accounts to track, or onboard a new DFY client whose outreach will be driven by LinkedIn engagement signals on competitor posts. Trigger phrases include 'set up a new Trigify brief', 'spin up a LinkedIn engagement pipeline', 'engagers-of-competitors pipeline', 'track competitor engagement for [client]', 'create a Trigify search for [competitor]', 'new LinkedIn engager pipeline', 'who's engaging with [competitor]'. Does NOT run the daily enrichment or push to Smartlead, that's lilly-trigify-data-processing (separate skill).
---

# Lilly Trigify Setup

## Purpose

Setup wizard for Trigify-driven LinkedIn engagement-signal pipelines. One brief = one run of this skill = full infrastructure provisioned.

The skill captures the user's brief, ideates a candidate "tracked accounts" list (competitors and/or thought-leaders whose post engagers are our signal), pulls a free historical sample via Trigify's API to sample-fit-test the list, locks in the final tracked-accounts list, provisions the supporting infrastructure (Google Sheet + Make scenario + Smartlead campaign skeleton + brief config file), and outputs a paste-ready UI checklist for the user to configure tracked accounts + webhook inside Trigify's web app.

This skill does NOT run daily enrichment or push leads to Smartlead — that's `lilly-trigify-data-processing` (separate skill).

## When to Use

Trigger when the user wants to:
- Add a new LinkedIn engagement-signal brief / Trigify pipeline
- Ideate which competitor / thought-leader accounts to track for a new audience or client
- Spin up a competitor-engagement pipeline for a vertical/ICP
- Onboard a new DFY client whose outreach will be driven by LinkedIn engagement signals

Skip / don't trigger when:
- The user wants to process today's engagers from an existing brief → use `lilly-trigify-data-processing`
- The user wants a one-off engager pull without setting up a tracked-accounts list → call Trigify's API directly via Bash
- The user wants to ideate a hiring-signal pipeline → use `lilly-theirstack-setup`

## Key architectural differences vs `lilly-theirstack-setup`

| Aspect | TheirStack pipeline | Trigify pipeline |
|---|---|---|
| Upstream data | Job postings | LinkedIn post engagements (likes + comments) |
| Lead model | Job → Company → find DMs at that company | Engager IS the lead |
| Enrichment | Full `lilly-tam` waterfall (Prospeo search-person + enrich + AI Ark fallback) | Prospeo `enrich-person` against engager's LinkedIn URL (+ AI Ark fallback for hard markets) |
| Personalisation hook | Job title + tech stack of the open role | The post they engaged with (competitor + post content + their comment text) |
| Make scenarios per brief | TWO (Jobs scenario + DMs scenario) | ONE (Engagers scenario) |
| Sheet tabs | Two (Jobs + Decision-Makers) | One (Engagers) |
| Qualification gate | Role-only (does this hire signal what we target?) | Engager-only (is this person an ICP-fit DM at an ICP-fit co?) |

Everything else (brief config schema, Make team/connection IDs, Smartlead handoff, dry-run loop, scheduling) is the same.

## Architecture

```
Trigify saved search (per tracked profile, fires DAILY)
    │
    └─> Trigify Workflow (fires on every new post discovered)
            │ get_post_likes + get_post_comments (free)
            │ person_enrichment per engager (Trigify-internal)
            │ http_request → Make webhook
            ▼
        Make scenario (Engagers — INSERT only)
            │ addRow → Engagers tab (Status = NEW)
            ▼
        Google Sheet (one Engagers tab per brief)
            ▼
        [daily routine — separate skill: lilly-trigify-data-processing]
            │ 4-gate qualify (location → post-topic → title → company)
            │ Prospeo enrich-person for email (AI Ark fallback)
            │ Generate per-lead variables (perspective-aware angle waterfall)
            │ Push to Smartlead (campaign PAUSED until user starts it)
            │ Mark Status = PROCESSED (via second Make scenario, see Notes)
```

Setup phases:

```
lilly-trigify-setup (this skill: wizard + provisioner)
   │
   ├──> Phase -1: Trigify MCP install (one-time, account-level)
   │
   ├──> Phase 0: Brief capture (ICP, offer, signal rationale, tracked profiles, engager titles,
   │             DIRECT-RIVAL AVOID LIST)
   │
   ├──> Phase 0.5: Engager qualification framework (FOUR gates: location, post-topic,
   │             engager-title, engager-company)
   │
   ├──> Phase 1: Tracked-accounts ideation
   │
   ├──> Phase 2: Free sample-fit testing (lilly-lead-score on 10-engager sample per profile)
   │
   ├──> Phase 3: Final tracked-accounts list lock
   │
   ├──> Phase 4: Infrastructure provisioning
   │       ├──> Drive: per-brief Sheet with Engagers tab
   │       ├──> Make: clone Engagers scenario from templates/engagers-scenario-blueprint.json
   │       ├──> Smartlead: create campaign skeleton with merge vars
   │       └──> Save brief config to briefs/<brief_id>.json
   │
   ├──> Phase 5: PROGRAMMATIC Trigify provisioning (via MCP)
   │       ├──> create_linkedin_profile_search per tracked profile (1 credit each)
   │       └──> create_workflow per saved search (free; engagement-fetch + Make POST)
   │       (UI-only fallback retained in Appendix A for non-MCP setups)
   │
   ├──> Phase 5.5: WAIT for first auto-fire from any Workflow to land a row in the Sheet
   │
   ├──> Phase 5.7: End-to-end dry-run with 2 real engagers (~2 Prospeo credits)
   │       ├─ INLINE chat render of all variants + email steps for user approval
   │       └─ Push to Smartlead ONLY after explicit user approval
   │
   └──> Phase 6: Schedule daily routine via /schedule
           (Default: 09:00 local Mon-Fri, invokes /lilly-trigify-data-processing <brief_id>)
```

After this skill completes:
- 1 Trigify saved search per tracked profile is live, scheduled DAILY
- 1 Trigify Workflow per saved search is live, listening for new posts
- The Sheet exists, ready to receive engager rows
- The Make Engagers scenario is active and listening on its webhook
- The Smartlead campaign exists, ready to receive personalised leads
- The brief config is on disk, ready for `lilly-trigify-data-processing` to consume

No manual Trigify-UI step is required when the MCP path runs cleanly. Appendix A retains the UI-only path for fallback.

---

## Phase -1 — Trigify MCP install (one-time, account-level)

The skill below assumes the Trigify MCP is installed in Claude Desktop. If it is not yet installed, walk the user through this BEFORE Phase 0. Skip if `mcp__a06d3a94-...__list_searches` and friends are already callable.

Steps:

1. Open Claude Desktop **Settings** → **Connectors**.
2. Click **Add custom connector**. Fill in:
   - Name: `Trigify`
   - URL: `https://api.trigify.io/mcp`
3. Save. Start a new conversation (the MCP tools register on conversation start).
4. The first invocation of any Trigify tool triggers OAuth: log in with Trigify credentials, authorize the MCP.

**Tier note (HARD requirement).** Trigify Workflows require a Max plan or higher. Starter tier blocks Workflow creation. Confirm the user is on Max+ before proceeding. The Enterprise-only `bulk_track_profiles` tool is deliberately NOT used by this skill, Max-tier Workflows give the same result for free.

After the MCP is live, return to Phase 0.

---

## Phase 0 — Brief capture

Ask the user, in one batched block, for the following. Pre-fill defaults from prior conversation if available.

| Question | Notes |
|---|---|
| **Brief ID** (kebab-case) | e.g. `navreo-competitor-engagers` — used as folder/file names. Auto-generate from brief name if user doesn't specify. |
| **Client / account** | e.g. `Navreo (internal)`, `Amplifyy`, etc. For multi-client setups. |
| **ICP description** (plain English) | e.g. "B2B sales leaders at 51-200 emp services companies actively researching cold-email vendors" |
| **Offer** (what the user/client sells) | e.g. "Done-for-you cold-email infrastructure — sender pools, sequences, inbox management, pay-per-result pricing" |
| **Why this signal = fit** | e.g. "When someone likes/comments on a cold-email vendor's post, they're already shopping the category. We don't have to educate; we just have to be the better option." |
| **Tracked accounts** (LinkedIn URLs of competitors / thought-leaders) | The CORE input. Free-text list of competitor company pages OR thought-leader personal profiles whose post engagers should be tracked. Ask for 5-20 accounts. |
| **Direct-rival AVOID list** (NEW, mandatory) | Paste-list of direct rival agencies/companies whose engagers we do NOT want to outreach (e.g. competing cold-email DFY shops, rival lead-gen agencies, sister consultancies). These are companies whose engagers we don't want to poach. Goes into `qualification.company_avoid_list`. Ask explicitly, do not auto-infer. |
| **Engagement types** | Default: `["like", "comment"]`. Some briefs may want comments-only (higher intent, lower volume). |
| **Engagement recency window** (days) | Default: 14. Only push engagers within last N days — older engagements have decayed intent. |
| **Company size** (min, max employees) of engager's employer | Default: 10-200 |
| **Countries** (ISO-2 codes) of engager's location | Default: Navreo's 14-country high-GDP set — US, CA, GB, AU, IE, NZ, DE, NL, CH, SE, NO, DK, FI, SG. User can subset (e.g. "English-only" → US, CA, GB, AU, IE, NZ, SG). |
| **Daily volume cap** (max engagers/day) | Default: 50 |
| **Engager target titles** | Who we'll outreach. Default: Head of Sales, Head of GTM, Head of Marketing, VP Sales, CRO, CMO. User can customise per brief — e.g. for a product-led brief, swap to Head of Product / VP Engineering. |
| **Smartlead campaign** | Existing campaign ID to push to, OR ask the skill to create a new one with skeleton sequence |

Confirm before proceeding to Phase 0.5.

### 0a. Validate tracked-accounts list

For each LinkedIn URL the user provides:
- Confirm it resolves to a valid `linkedin.com/company/<slug>` OR `linkedin.com/in/<slug>` URL.
- Flag any obvious typos / non-LinkedIn URLs.
- If the user pasted bare company names without URLs, run `lilly-linkedin-page-finder` first to resolve them, then return.

Do NOT silently drop unresolvable URLs — surface them to the user and ask whether to drop, fix, or replace.

---

## Phase 0.5 — Engager qualification framework (FOUR gates)

**Purpose.** Trigify pushes engagers based on a coarse account-level signal (anyone who liked or commented on a tracked profile's post). Not every engager is an ICP-fit prospect. The qualification framework is a FOUR-GATE judgement layer applied by `lilly-trigify-data-processing` on every daily batch, in cheapness order so the slow LLM gates only run on rows that survive the cheap string checks.

**ALL FOUR gates must pass for QUALIFIED. Any single fail = OFF_BRIEF. Ambiguity in any gate = BORDERLINE (user reviews daily).**

1. **Location gate** (cheapest, runs first). `engager.country_code` is in the brief's qualified-country set. Pure string check.
2. **Post-topic gate**. LLM reads `post.content_snippet` and verdicts whether the originating post is a GTM/sales-adjacent signal (vs lifestyle, personal, politics, etc.). A perfect-fit ICP engaging on a competitor's birthday post is NOT a sales signal.
3. **Engager-title gate**. Pattern-match `engager.title` against qualified / disqualified / borderline patterns.
4. **Engager-company gate**. Reject companies on the avoid list (direct rivals, recruiting agencies, Fortune 500, etc.); enforce size band.

**Hard rule.** These gates judge whether the ENGAGER is a prospect, not whether the engagement is meaningful. A like is a like, the question is who liked it AND what they liked.

### 0.5a. Auto-draft default 4-gate config based on the brief

The canonical shape lives in `briefs/navreo-competitor-founder-engagers.json`. Pre-populate these defaults, user reviews + edits before they're baked into the brief config.

```json
"qualification": {
  "_purpose": "Four-gate qualification applied by lilly-trigify-data-processing daily routine, in order. ALL FOUR GATES MUST PASS for QUALIFIED. Any single fail = OFF_BRIEF. Ambiguity in any gate = BORDERLINE. Gates run in order of cheapness, fail fast on country before evaluating the slower LLM gates.",

  "location_gate": {
    "_purpose": "Drop engagers outside the brief's high-GDP target set. Cheapest filter, pure string check on engager.country_code. Runs first.",
    "qualified_country_codes": ["US", "CA", "GB", "AU", "IE", "NZ", "DE", "NL", "CH", "SE", "NO", "DK", "FI", "SG"],
    "_note": "If country is missing/null, mark BORDERLINE (could be a privacy-strict profile in a qualified country)."
  },

  "post_topic_gate": {
    "_purpose": "Reject engagers whose originating post is NOT a sales-signal. Personal stories, lifestyle, motivational quotes, and holiday greetings are NOT sales signals even if the engager is a perfect-fit ICP.",
    "qualified_topics": [
      "Sales / GTM / outbound / cold email / lead generation",
      "Demand generation / marketing operations / RevOps",
      "Agency growth / services-business operations",
      "Founder lessons (only if business-focused: hiring, pricing, scaling ops)",
      "Sales tooling, AI-for-sales, automation",
      "Hiring sales / GTM teams",
      "Closing / deal-flow / pipeline mechanics"
    ],
    "disqualified_topics": [
      "Personal stories (health, family, relationships, struggles)",
      "Politics / current events / commentary",
      "Lifestyle / fitness / travel / food",
      "Inspirational / motivational (not tied to business action)",
      "Holiday greetings / personal milestones / birthdays",
      "Pure entertainment / memes / humor without business angle",
      "Sports / hobbies"
    ],
    "judge_using": "post.content_snippet, LLM reads the snippet and verdicts qualified / disqualified / borderline."
  },

  "qualified_engager_title_patterns": [
    "C-suite at <200 emp: CRO, CSO, CEO, Founder, Co-Founder",
    "VP-level: VP Sales, VP Revenue, VP GTM, VP Growth, VP Marketing",
    "Head/Director: Head of (Sales | GTM | Growth | Marketing | Revenue | RevOps), Director of (Sales | BD | Partnerships)",
    "BD & Partnerships: BD Director, Director of Partnerships, Head of Partnerships",
    "RevOps senior: Head of RevOps, Director of Revenue Operations"
  ],

  "disqualified_engager_title_patterns": [
    "Technical ICs: Software Engineer, Backend / Frontend Engineer, DevOps, Data Engineer, ML Engineer",
    "Junior tier: Intern, Junior, Associate, Assistant, Coordinator",
    "Wrong function: Recruiter, Talent Acquisition, Sourcer, HR Manager, People Ops",
    "Not B2B prospects: Student, Independent Consultant, Freelancer, Career Coach, Resume Writer",
    "Customer-facing IC: Customer Success Manager (non-Head), Support, Account Manager (non-Director)"
  ],

  "borderline_engager_title_patterns": [
    "Sales Manager (no Director title) at <50 emp, could be first dedicated hire OR admin layer",
    "Account Executive at <30 emp B2B, sometimes the founder-AE; verify by company size",
    "Head of X at >500 emp, engagement real, company too big for SMB pricing",
    "Growth / Demand Gen / Marketing Ops Manager, tooling-buying influence but not always primary buyer"
  ],

  "company_avoid_list": [
    "Direct cold-email tool competitors: Smartlead, Instantly, Lemlist, Apollo, Mailshake, Reply.io, Outreach, Salesloft, Lavender, Clay",
    "Trigify itself",
    "Recruiting / staffing agencies (recruiting-shape engagement, not buying)",
    "Fortune 500 / enterprise (>1000 emp, pricing/sales-cycle mismatch)",
    "Direct Navreo DFY/lead-gen agency competitors, PASTE-LISTED BY USER in Phase 0"
  ]
}
```

### 0.5b. Surface to user

Show the four gates as plain English. Ask:
- Location gate: "Confirm the 14-country list, or subset / add codes."
- Post-topic gate: "Anything to add to qualified-topics? disqualified-topics?"
- Engager-title gate: "Anything to add / move between qualified, borderline, disqualified?"
- Engager-company gate: "Confirm the avoid list (we already captured your direct-rival paste-list in Phase 0). Anything else to exclude?"

The defaults above are calibrated for B2B services briefs (Navreo's default). For other ICP shapes (e.g. e-commerce brands, hardware vendors), redraft to fit.

### 0.5c. Bake into brief config

Save the user-confirmed patterns into the brief config under `qualification`. Consumed by `lilly-trigify-data-processing` Phase 2.5.

### 0.5d. Reinforce the first-7-days iteration loop

Tell the user explicitly:

> "For the first 7 days after this brief goes live, expect to iterate on the qualification patterns + the tracked-accounts list daily. Each daily run will surface (a) borderline rows for your yes/no, (b) suggested negative title patterns from the off-brief rows, and (c) per-account precision (% qualified). Drop or replace tracked accounts whose precision sits below 30% after 100+ engagers. After 7 days the pipeline should be running ~80% precise."

This sets expectations — Day 1 will be noisy.

---

## Phase 1 — Tracked-accounts ideation

Given the brief, the user has either already supplied a tracked-accounts list (Phase 0) or asked for help building one. If they supplied a list, skip to Phase 2. If they asked for help, ideate 10-20 candidate accounts to track. Cover different facets of the engagement signal.

Standard tracked-account archetypes:

| Archetype | Why track | Example for cold-email vendor brief |
|---|---|---|
| **Direct competitor (company page)** | Their post engagers are shopping the category | Smartlead, Instantly, Lemlist, Mailshake, Reply.io |
| **Direct competitor (founder profile)** | Founder profiles often outperform brand pages in B2B reach | The CEO / VP-Sales personal LinkedIn of each direct rival |
| **Adjacent category competitor** | Buyers of "outbound platforms" are often shopping for "lead-gen agencies" too | Lead-gen agencies, fractional-CRO firms, RevOps consultancies |
| **Category thought-leader** | High-signal: people who follow + engage with thought-leadership posts are buyer-shaped | Industry voices who post about cold-email / outbound / GTM — verified by `lilly-linkedin-page-finder` |
| **Adjacent thought-leader** | Same buyer, different topical entry point | E.g. people posting about Clay, Apollo, Trigify itself |
| **Niche-specific publication / community** | Lower volume but very on-brief | Industry newsletters, podcast hosts |

For each candidate, surface to the user:
- LinkedIn URL (verified resolves)
- Follower count (via `lilly-linkedin-page-finder` if needed)
- One-line positioning / why-track rationale
- Estimated daily engager volume (rough — based on follower count × engagement rate × % of post-volume that's tracked)

Show all candidates as a numbered list. Let the user keep / drop / add / replace before Phase 2.

**Volume tip:** Trigify charges per engager pushed. A 100K-follower account with 5 posts/week and 1% engagement = ~5,000 engagements/week = ~700/day. That's far over a 50/day cap. The skill should warn when individual tracked accounts will blow the daily cap and suggest either tightening qualification or dropping the highest-volume accounts.

---

## Phase 2 — Free sample-fit testing

For each tracked account the user wants to keep (or the top 3-5 by expected volume if the list is long):

**If Trigify exposes a historical-engagement API endpoint** (preferred):

```bash
curl -X GET "https://api.trigify.io/v1/engagements?account_url=<tracked_account>&since=$(date -u -v-30d +%Y-%m-%dT%H:%M:%SZ)&limit=10" \
  -H "Authorization: Bearer $TRIGIFY_API_KEY"
```

Capture per account:
- Total 30-day engager count
- Daily estimate: `total / 30`
- Sample of 10 engagers (name, title, company, LinkedIn URL, engagement type)

**If Trigify does NOT expose a historical-engagement API endpoint** (fallback):

Phase 2 cannot run a free test. Instead:
1. Document this in the brief config (`sample_fit_method: "live-window"`).
2. Set the daily volume cap conservatively (default 25 instead of 50).
3. Tell the user explicitly: "Trigify doesn't expose historical engagement data via API, so we can't sample-fit-test before going live. Day 1's batch IS the sample-fit test — qualification will run normally but expect the first 24-48h to surface tracked-accounts that aren't pulling ICP-fit engagers."
4. Skip to Phase 3 with all tracked accounts marked `sample_fit: "unverified"`.

**Cost:** Zero (if API exists). One free Trigify API call per tracked account tested. No credits charged for blurred/historical lookups in the API; only live pushes via webhook are billable.

**Then run `lilly-lead-score`** against each account's 10-engager sample to get a fit %. Reject accounts with fit % < 60%.

Build a comparison table for the user. Example shape:

| # | Tracked account | 30-day engagers | Daily est. | Fit % | Verdict |
|---|---|---|---|---|---|
| 1 | Smartlead (company page) | 2,400 | ~80/day | 70% | ✅ Keep |
| 2 | Instantly (company page) | 1,800 | ~60/day | 65% | ✅ Keep |
| 3 | Adam Brown / VP-Sales / Smartlead | 950 | ~32/day | 85% | ✅ Keep (highest precision) |
| 4 | Lemlist (company page) | 3,600 | ~120/day | 40% | ⚠️ Drop (lots of brand engagement, low buyer-shape) |
| 5 | Lead-gen-agency thought-leader X | 220 | ~7/day | 90% | ✅ Keep |

**Daily volume sanity check.** Sum the daily estimates of all kept accounts. If sum > daily cap × 2, recommend dropping the lowest-precision accounts. If sum < daily cap, the brief may be under-pulling — recommend adding more tracked accounts.

---

## Phase 3 — Final tracked-accounts list lock

User reviews the Phase 2 table and confirms the final list. Lock it in `brief.trigify.tracked_accounts[]`.

### 3a. Same-campaign or separate-campaigns? (NEW — mandatory question)

**Before locking, ask the user explicitly:**

> "You picked N tracked accounts. Do you want all engagers from all accounts to:
> - **(a) Funnel into ONE campaign** — same Sheet, same Smartlead campaign, same copy. Best when accounts target the same buyer persona with the same offer messaging.
> - **(b) Run as SEPARATE campaigns** — one Sheet + Trigify config + Make scenario + Smartlead campaign per account-cluster (e.g. "direct competitors" vs "thought leaders" vs "adjacent category"). Best when the engagement intent differs by source enough to warrant different copy/CTAs."

This question is mandatory. Lesson from theirstack equivalent: collapsing distinct signals silently kills downstream personalisation quality.

### 3b. If user chose "same campaign":

- One Sheet, one Make scenario, one Smartlead campaign.
- All tracked accounts share one `brief.trigify.tracked_accounts` array.
- Continue to Phase 4 with a single brief config.

### 3c. If user chose "separate campaigns":

- Cluster tracked accounts (let user decide the clustering — usually direct-competitors / thought-leaders / adjacent-category).
- Generate a `brief_id` per cluster (e.g. `navreo-direct-rival-engagers`, `navreo-thought-leader-engagers`).
- Run Phase 4 (infrastructure provisioning) once per brief_id.
- Phase 5 outputs N UI checklists (one per Trigify tracked-accounts-search config).

Confirm final shape with the user before proceeding to provisioning.

---

## Phase 4 — Infrastructure provisioning

### 4a. Google Sheet (copy from template)

**Template Sheet ID**: TBD on first run. The first time this skill runs, prompt the user to create a template Sheet manually with the headers below (one-time), capture its ID, and store it at the skill-level config (`~/.claude/skills/lilly-trigify-setup/.template-sheet-id`). On subsequent runs the skill reads that file and uses `copy_file` to clone.

**Naming convention (Sheet + Make scenario must match exactly):**

```
Trigify — <Brief Name>
```

Example: `Trigify — Navreo Competitor Engagers`. Use this exact title format for both the Sheet AND the Make scenario so the user can navigate between them by name without thinking.

Use Drive MCP `copy_file` to clone the template Sheet with the title above. **Never write to the template Sheet directly** — it's reference only.

**Engagers tab headers** (row 1, 32 columns — v2 schema verified against real Trigify payload 2026-05-17):

```
Date Pulled	Post URL	Post Author Name	Post Author LinkedIn	Post Date Posted	Post Text	Post Likes Count	Post Comments Count	Engagement Type	Engaged At	Comment Text	Comment Permalink	Comment Likes Count	First Name	Last Name	Full Name	LinkedIn URL	LinkedIn Username	LinkedIn URN	LinkedIn Headline	Profile Picture URL	Open To Work	Job Title	Company Name	Company Domain	Company Industry	Company HeadCount	Company Description	Country	Location	Status	Raw Payload
```

The canonical inventory (column letter, name, source field, gate signal where applicable) lives in the brief config's `engagers_sheet_schema.columns[]` — Phase 4d below saves it.

Note: `Status` column (column AE) is the idempotency mechanism — `lilly-trigify-data-processing` only processes rows with Status = `NEW`. It marks rows `PROCESSED` after enrichment + Smartlead push, `OFF_BRIEF` if qualification rejects, `BORDERLINE` if it needs user review. The last column `Raw Payload` (AF) holds the full Trigify webhook JSON as a string — safety net for any field added in future without re-plumbing.

**Important**: when copying the template, any test data inside it carries over. Warn the user to clear rows below row 1 (preserve headers) before the brief goes live.

Capture the new Sheet ID for the brief config.

### 4b. Make.com scenario (ONE per brief)

Unlike `lilly-theirstack-setup` (which provisions TWO scenarios per brief — Jobs + DMs), Trigify briefs need only ONE scenario:

**Engagers scenario** — receives webhooks from Trigify
- Template: `templates/engagers-scenario-blueprint.json`
- Flow: `webhook → addRow to Engagers tab` (no router, no iterator — Trigify sends one engager per POST; verify this at Determine-data-structure time)
- Webhook URL goes into Trigify tracked-accounts-search UI per Phase 5 instructions

Use Make.com MCP:
- `hooks_create` for the webhook
- `scenarios_create` with the customised blueprint (replace `{{spreadsheet_id}}`, `{{webhook_hook_id}}`, `{{google_connection_id}}`)
- Note the webhook URL — it goes into the Trigify UI

Team ID for Navreo: **536258**. Google connection ID: **9696598**. These are fixed.

**The scenario needs a Redetermine-data-structure pass BEFORE first activation.** This is critical and the order matters:

1. Open the scenario in Make
2. Click the webhook module → **"Redetermine data structure"** — Make shows "Waiting for data"
3. From Trigify UI, hit "Send test webhook" (or whatever Trigify's equivalent is — covered in Phase 5)
4. Make captures the schema, webhook module shows green tick
5. Save the scenario
6. Toggle scheduling switch to ON (activate)
7. Verify with a SECOND test fire — row should appear in Engagers tab within ~60s

**Anti-pattern to avoid:** "Activate first, then redetermine" — activation locks the schema as empty/unknown and Make can't bind the addRow mappings. The order MUST be: redetermine → capture sample → save → activate → verify.

#### Trigify webhook payload schema (VERIFIED 2026-05-17)

Verified against workflow `cab0bc16-da3e-4942-8f79-ed5fbd90222f` (Bjion's), run `01KRNK054FNGR6PB22EE3B87WS`. The Trigify Workflow's `http_request::pushToClay` step assembles the body from the upstream `__trigger__`, `linkedin_get_post_comments::getComments`, and `person_enrichment::enrich` steps. The body must forward EVERY field below for the 32-column Sheet schema to populate:

```json
{
  "postAuthorName":   "<HARDCODED per workflow — e.g. 'Bjion Henry'>",
  "postUrl":          "https://www.linkedin.com/feed/update/urn:li:activity:...",
  "postAuthorUrl":    "https://www.linkedin.com/in/...",
  "postDatePosted":   "2026-05-15T08:01:01.054Z",
  "postText":         "<full post body>",
  "postLikes":        1,
  "postComments":     1,

  "engagementType":   "comment",
  "engagedAt":        "2026-05-15 09:53:30",
  "commentText":      "<full comment body>",
  "commentPermalink": "https://www.linkedin.com/feed/update/urn:li:activity:...?commentUrn=...",
  "commentLikes":     0,

  "engagerFirstName":    "Tersh",
  "engagerLastName":     "Blissett",
  "engagerFullName":     "Tersh Blissett",
  "engagerLinkedinUrl":  "https://www.linkedin.com/in/tershblissett",
  "engagerUsername":     "tershblissett",
  "engagerUrn":          "ACoAABXopXsB_DS4fKe7PCEdmaIVccNg6iS5lDY",
  "engagerHeadline":     "I help home service businesses save 20+ hrs/week with AI automation | Host of...",
  "engagerProfilePicture": "https://media.licdn.com/dms/image/.../profile-displayphoto-scale_400_400/...",
  "engagerOpenToWork":   false,
  "engagerJobTitle":     "Co-Founder & Chief Experience Officer",

  "engagerCompanyName":        "Trade Automation Pros",
  "engagerCompanyDomain":      "tradeautomationpros.com",
  "engagerCompanyIndustry":    "Business Consulting and Services",
  "engagerCompanyHeadCount":   "1",
  "engagerCompanyDescription": "<1-3 sentence tagline from LinkedIn>",
  "engagerCountry":            "United States",
  "engagerLocation":           "Savannah, Georgia, United States"
}
```

The blueprint references `{{1.postUrl}}`, `{{1.engagerJobTitle}}`, `{{1.engagerCompanyIndustry}}` etc. on this verified shape. **Each workflow's `pushToClay` body template must be patched** to forward every key above — see `templates/engagers-scenario-blueprint.json` `_pushtoclay_body_template_required` block for the full template. Patch is per-workflow (60+ workflows for the Navreo brief alone).

### 4c. Smartlead campaign skeleton

Either:
- (a) User provides existing campaign ID → use as-is.
- (b) Skill creates a new campaign via Smartlead API with skeleton sequence + the right merge variable schema:
  - `{{first_name}}` — standard
  - `{{company_name}}` — standard
  - `{{HowWeCanHelp}}` — per-lead personalised, anchored to the post they engaged with
  - `{{Icebreaker}}` — per-lead opener referencing the engagement ("saw you commented on [Post Author]'s post about X")
  - `{{Offer}}` — campaign-level (one value for all leads), filled by user via Smartlead UI or `lilly-bot`

The Trigify pipeline produces RICHER personalisation than TheirStack because we have:
- The exact post URL the engager engaged with
- The competitor whose post it was
- The engager's comment text (if they commented)
- Post content snippet

This is gold for `{{Icebreaker}}` and `{{HowWeCanHelp}}`. See Phase 4c.5 for the angle library.

### 4c.5. Draft personalisation angle libraries — PERSPECTIVE-AWARE + HARD RULE

**HARD RULE (most important rule in this skill).** When the post author is a tracked competitor founder (i.e. NOT the sender), the email body must NEVER mention the competitor's post, the competitor founder by name, or anything that betrays we saw the engagement. The engagement is the LEAD-GENERATION signal (used to find the prospect), not the EMAIL-CONTENT signal. Naming the competitor or their post leaks our intel-gathering and burns the relationship. Only the sender's OWN posts (post.author_name == sender) are fair game to reference directly.

Why this matters: a Trigify brief discovers prospects by watching who engages with competitors. If we then write "saw your comment on Smartlead's post", we've told the prospect we monitor a competitor's audience, that prospect immediately rejects the email and likely warns their network.

**Angle waterfall for `{{Icebreaker}}` — perspective-aware (canonical shape in `briefs/navreo-competitor-founder-engagers.json`):**

| # | Angle ID | Trigger condition | Perspective | Example output |
|---|---|---|---|---|
| 1 | `first_person_own_post` | `post.author_name == sender` | First-person, post-referencing OK | "saw your comment on my post about [topic] — your point caught my eye" |
| 2 | `role_anchored_for_founder_post` | `post.author_name` is a tracked competitor founder | Role/company-anchored, NO POST OR FOUNDER REFERENCE | "your role leading sales at [engager.company] caught my eye — quick question" |
| 3 | `fallback` | always (when 1 & 2 don't fire, or fields missing) | Generic, always works | "your name came up in some [category] circles — wanted to reach out" |

For angle 2, the anchors that ARE allowed: `engager.title`, `engager.company`, company size, vertical / industry, function. The anchors that are FORBIDDEN: `post.author_name`, `post.content_snippet`, `post.url`, `comment.text`, "saw you engaged with", "noticed your comment", "your reaction to".

Surface to the user with the HARD RULE called out in bold, let them edit, insist on angle 3 (fallback) being present, bake into `brief.personalization.per_lead_variables.icebreaker.angles[]`.

**`{{HowWeCanHelp}}`** uses `generation_strategy: offer_anchored_to_engager_role_and_company`, NOT a waterfall. Anchor on engager's title + company size + offer (e.g. "for a VP Sales at a 50-emp agency, pay-per-result pricing makes outbound a P&L lever, not a fixed cost"). Same HARD RULE: do NOT reference the originating post or competitor founder in `{{HowWeCanHelp}}` either.

### 4d. Brief config JSON

Save to `~/.claude/skills/lilly-trigify-setup/briefs/<brief_id>.json`:

```json
{
  "brief_id": "navreo-competitor-engagers",
  "brief_name": "Navreo Competitor Engagers",
  "client": "Navreo (internal)",
  "created_at": "2026-05-15",

  "ideation": {
    "icp_description": "...",
    "offer": "...",
    "why_signal_fits": "..."
  },

  "trigify": {
    "tracked_accounts": [
      {
        "id": "tracked-001",
        "name": "Smartlead (company page)",
        "linkedin_url": "https://www.linkedin.com/company/smartlead-ai/",
        "type": "company",
        "sample_fit_pct": 70,
        "estimated_daily_engagers": 80,
        "added_at": "2026-05-15"
      },
      {
        "id": "tracked-002",
        "name": "Adam Brown (VP Sales, Smartlead)",
        "linkedin_url": "https://www.linkedin.com/in/adam-brown-...",
        "type": "person",
        "sample_fit_pct": 85,
        "estimated_daily_engagers": 32,
        "added_at": "2026-05-15"
      }
    ],
    "engagement_types": ["like", "comment"],
    "engagement_max_age_days": 14,
    "daily_volume_cap": 50,
    "trigify_search_id": null
  },

  "qualification": {
    "qualified_engager_title_patterns": [...],
    "disqualified_engager_title_patterns": [...],
    "borderline_engager_title_patterns": [...],
    "company_avoid_list": [...]
  },

  "filter": {
    "country_code_or": ["US","CA","GB","AU","IE","NZ","DE","NL","CH","SE","NO","DK","FI","SG"],
    "min_employee_count": 10,
    "max_employee_count": 200
  },

  "enrichment": {
    "provider": "prospeo",
    "fallback": "ai_ark",
    "skip_unverified_emails": true,
    "run_millionverifier_post_prospeo": true
  },

  "personalization": {
    "per_lead_variables": {
      "icebreaker": {
        "generation_strategy": "angle_waterfall",
        "angles": [...]
      },
      "how_we_can_help": {
        "generation_strategy": "angle_waterfall",
        "angles": [...]
      }
    }
  },

  "infrastructure": {
    "sheet_id": "<google_sheet_id>",
    "sheet_url": "https://docs.google.com/spreadsheets/d/.../edit",
    "engagers_scenario_id": null,
    "engagers_scenario_url": null,
    "engagers_webhook_url": null,
    "smartlead_campaign_id": null,
    "smartlead_campaign_url": null,
    "schedule_id": null
  },

  "trigify_config": {
    "ui_label": "Competitor Engagers — Navreo",
    "created_in_ui_at": null,
    "webhook_attached": false,
    "test_fire_verified_at": null,
    "user_must_create_in_ui": true
  }
}
```

`created_in_ui_at`, `webhook_attached`, and `test_fire_verified_at` are null until the user confirms each step. `lilly-trigify-data-processing` will warn if any are still null.

---

## Phase 5 — UI checklist output

Output a clean, readable checklist for the user to configure tracked accounts + webhook in Trigify's UI. **Format note: do NOT use ASCII boxes or horizontal rules around content.** Use plain numbered steps with markdown tables / bulleted detail where needed.

### Required content

**Step 1 — Open `app.trigify.io` → New tracked-accounts search** (or whatever Trigify's UI calls it; adapt label once verified)

**Step 2 — Add tracked accounts.** Paste-list:

| # | Account name | LinkedIn URL | Type |
|---|---|---|---|
| 1 | Smartlead (company page) | https://www.linkedin.com/company/smartlead-ai/ | Company |
| 2 | Adam Brown (Smartlead VP) | https://www.linkedin.com/in/adam-brown-... | Person |
| ... | ... | ... | ... |

**Step 3 — Apply engagement filters:**

| Field | Value |
|---|---|
| Engagement types | Likes + Comments |
| Recency window | Last 14 days |
| Engager location | `<comma-separated country UI labels — see country mapping below>` |
| Engager company size | between 10 and 200 |
| Engager title contains any of | `<comma-separated qualified title patterns from brief.qualification.qualified_engager_title_patterns>` |
| Engager title does NOT contain any of | `<comma-separated disqualified title patterns>` |

**ALWAYS surface the "does NOT contain" row to the user**, even when empty — show with value `none — none required for this brief` so they consciously confirm rather than miss the step.

**Source the negative title patterns from `brief.qualification.disqualified_engager_title_patterns`** — this list grows over time as `lilly-trigify-data-processing` Phase 8.5 surfaces new off-brief patterns. For first-run briefs the list may be empty; over the brief's first 7 days the list typically fills to 5-10 keywords.

**Step 4 — Click "Save search"** → name it: `<brief.trigify_config.ui_label>`

**Step 5 — Connect the webhook:**
1. Open the saved search → click the **"Webhooks"** or **"Integrations"** tab (whatever Trigify's UI calls it)
2. Paste the webhook URL: `<Make webhook URL from brief.infrastructure.engagers_webhook_url>`
3. Set webhook trigger: `engagement.new` (or whatever Trigify calls "fire when new engager detected")
4. Click **"Create webhook"** / **"Save"**

**Step 6 — Activate the Engagers scenario in Make** (do this BEFORE the verify test fire — otherwise the test payload arrives at an inactive webhook, returns HTTP 200, and silently gets queued without writing a row):
1. Open the [Engagers scenario in Make] (provide the `engagers_scenario_url` from the brief config)
2. **Click the webhook module** (first module in the flow) → click **"Redetermine data structure"**. Make will show "Waiting for data".
3. While Make is waiting, go back to Trigify and hit **"Send test webhook"** on the saved search. The payload arrives, Make captures its schema, the webhook module shows a green tick.
4. **Verify Trigify's actual payload schema matches `templates/engagers-scenario-blueprint.json`'s field references.** Most likely the field nesting will differ slightly. If so, edit the addRow mapper's `values` block to match the real payload before saving.
5. Click **"OK" / "Save"** inside the scenario editor.
6. Toggle the scheduling switch at the bottom-left to **"ON"** (activate). The scenario is now live.

**Step 7 — Verify** by hitting **"Send test webhook"** in Trigify a SECOND time (this time against the activated scenario). Within ~60 seconds:
- A row appears in the Engagers tab of the brief's Sheet
- The scenario's executions log shows `operations: 2` (1 webhook + 1 addRow)

If the row didn't appear after the second test, debug via `executions_list` → `executions_get-detail`. Common causes: a field reference in the blueprint doesn't match Trigify's actual payload shape (e.g. `engager.first_name` vs `firstName`), or the Google Sheet binding broke.

**Step 8 — Reply** "Trigify search live" so the skill can mark `trigify_config.created_in_ui_at`, `webhook_attached: true`, and `test_fire_verified_at` in the brief config.

### Country code → Trigify UI label mapping

Use the UI labels (not ISO codes) when telling the user what to paste:

| ISO | UI label |
|---|---|
| US | United States |
| CA | Canada |
| GB | United Kingdom |
| AU | Australia |
| IE | Ireland |
| NZ | New Zealand |
| DE | Germany |
| NL | Netherlands |
| CH | Switzerland |
| SE | Sweden |
| NO | Norway |
| DK | Denmark |
| FI | Finland |
| SG | Singapore |

---

## Phase 5.7 — End-to-end dry-run with 2 real engagers

**Purpose.** Close the gap between "Trigify search live" and "we know the personalization reads right". Run the full downstream pipeline against 2 real engagers BEFORE the saved search starts pumping 50 engagers/day into a broken setup. Worth ~I.50 in credits to surface issues now rather than after Day 1's batch lands wrong.

**Triggers ONLY after the user has explicitly confirmed `trigify_config.created_in_ui_at` is set AND THE WEBHOOK IS ATTACHED.** Until then, hold this phase.

### 5.7-pre. ENFORCE the Trigify-search loop closure BEFORE proceeding

Same enforcement as `lilly-theirstack-setup` 5.7-pre. The single most common failure mode is the user saying "progress now" without having actually clicked **Save** + **Create webhook** inside Trigify's UI. When that happens, the downstream pipeline appears to work but no real engagers are flowing in.

**Before starting any work in Phase 5.7, explicitly verify all four loop-closure conditions:**

1. **Tracked-accounts search exists in Trigify UI.** Ask the user directly: "Have you created and saved the tracked-accounts search in Trigify UI with label `<brief.trigify_config.ui_label>` containing the N tracked accounts we agreed on?" Don't accept "yes I'm progressing" — require explicit YES.
2. **Webhook URL is attached.** "Did you paste `<brief.infrastructure.engagers_webhook_url>` into the saved search's webhook config and save?" Require explicit YES.
3. **Engagement filters are configured correctly.** "Did you set engagement types to Likes+Comments, recency to 14 days, the countries list, and the title filters?" Require explicit YES.
4. **Test fire fired AT LEAST ONE row into the Engagers tab.** Verify via Make `executions_list` against the brief's `engagers_scenario_id` — look for an `auto` execution with `operations: 2`. If you only see `manual` executions (from terminal-fired curls), the user hasn't fired test from inside Trigify's UI. They MUST hit "Send test webhook" from Trigify itself.

**ALL FOUR must be confirmed before Phase 5.7 starts.** If any is missing, halt and surface the gap explicitly. Do NOT proceed on faith.

After confirmation, write the timestamps into the brief config:
```json
"trigify_config": {
  "created_in_ui_at": "<ISO8601 timestamp>",
  "webhook_attached": true,
  "filters_configured": true,
  "test_fire_verified_at": "<ISO8601 timestamp of the auto execution from Make>"
}
```

### 5.7a. Pull 2 recent engagers from Trigify

Fire Trigify's historical-engagement API with a small `limit`:

```bash
curl -X GET "https://api.trigify.io/v1/engagements?search_id=$TRIGIFY_SEARCH_ID&since=$(date -u -v-7d +%Y-%m-%dT%H:%M:%SZ)&limit=2" \
  -H "Authorization: Bearer $TRIGIFY_API_KEY"
```

(Adapt to Trigify's actual API surface — the exact endpoint may differ. If Trigify doesn't expose this, fall back to: wait for 2 real engagers to come through the webhook naturally; pause campaign-arming until they do.)

Pick the 2 most ICP-shaped results (engager title that clearly qualifies, mid-range company size, well-known company if possible). If the search returns <2 in 7 days, drop the recency to 30 days. If still <2, fail this phase and tell the user the tracked-accounts list is too narrow — they need to widen before going live.

### 5.7b. POST the 2 rows to the brief's Engagers webhook

Construct 2 fake `engagement.new` payloads matching Trigify's webhook shape (verified during Step 5/6 above) and POST them to `brief.infrastructure.engagers_webhook_url`. This proves the Make scenario routes correctly + writes the right fields to the Sheet's Engagers tab.

```bash
for engager_json in engager1.json engager2.json; do
  curl -X POST "$ENGAGERS_WEBHOOK_URL" \
    -H "Content-Type: application/json" \
    -d @"$engager_json"
done
```

Wait ~10s, re-read the Sheet, confirm both rows landed in the Engagers tab with all 17 columns filled.

### 5.7c. Run `lilly-trigify-data-processing` against the brief in test mode

Invoke the data-processing skill with `--dry-run` flag (or equivalent — that skill walks Phase 2.5 qualification → Prospeo email enrichment → personalization → Smartlead push using only those 2 rows). Cost: ~2 Prospeo credits, 1 AI Ark call if fallback fires.

### 5.7d. Render the FULL campaign copy with variables slotted — INLINE in chat (NOT in Smartlead UI)

**Inspection happens in chat first, BEFORE the Smartlead push.** Pushing leads and then asking the user to open Smartlead UI to inspect is slow, breaks the iteration loop, and forces the user to context-switch between chat and Smartlead. The correct primary inspection surface is chat.

**WebFetch is a FALLBACK ONLY when Trigify's companyDescription + companyIndustry can't carry the angle.** Trigify's `companyIndustry` (e.g. "Business Consulting and Services") and `companyDescription` (1-3 sentence company tagline) usually carry enough specificity to anchor `{{HowWeCanHelp}}` without an HTTP fetch. Walk this ladder:

1. Read `Company Industry` + `Company Description` from the Sheet row.
2. If the LLM can confidently anchor the value-prop using just those fields + the engager's `Job Title` + the brief's offer → done.
3. Only when BOTH industry and description are thin (industry is a generic umbrella like "Marketing and Advertising" AND description is one vague sentence) → WebFetch the company website for one sentence of clarification.

Matches the `feedback_company_classification_llm_first` rule. Skip the fetch by default, fall back when truly thin.

**Render format (mandatory layout per engager):**

For EACH engager, produce TWO sections in chat:

1. **A resolved-variable table** with: variable name, resolved value, and trigger/source. Shows the user at-a-glance which angle fired, what the engagement-context slot resolved to, etc.
2. **Full rendered email blocks** — one per variant per email step. Subject line + body + P.S. with all merge variables substituted. **Keep spintax visible** so the user can see Smartlead's variant pool.

For each rendered email:
- Substitute every merge variable (including standard Smartlead fields like `{{first_name}}`, `{{company_name}}`) with the resolved per-lead value.
- Show subject + body + P.S. as one code block per (engager, variant, email step).
- For a 2-engager × 2-variant × 2-email-step sequence that's 8 rendered emails — show all of them.

Surface to user:

> ## Dry-run lead pack
>
> **Lead 1** — `<engager.full_name>`, `<engager.title>` @ `<engager.company>` (`<email>`)
>
> | Variable | Resolved value | Source |
> |---|---|---|
> | `{{first_name}}` | Jane | engager.first_name |
> | `{{company_name}}` | Acme Co | engager.company (normalized) |
> | `{{Icebreaker}}` | "saw your '[comment text]' on Adam Brown's post — caught my eye" | Angle 2 fired (comment + ≤5 words) |
> | `{{HowWeCanHelp}}` | "..." | Angle 3 fired |
>
> ### Email 1, Variant A — subject: `<rendered subject>`
> ```
> <fully rendered email body, spintax kept visible>
> ```
>
> ### Email 1, Variant B — subject: ...
> ### Email 2 (follow-up, day +N) — subject: ...
>
> **Lead 2** — ...
>
> ---
>
> Reply **"approve and push"** to proceed to Smartlead push (campaign PAUSED — no sends), or specify edits (e.g. "Lead 2's HowWeCanHelp is too generic", "Icebreaker for Lead 1 references the wrong angle — the comment text is too short to quote directly").

### 5.7e. Iterate until approved

If the user flags issues:
- Per-engager variable mistakes → fix in memory, re-render, surface again (cheap — no API costs).
- Brief-config mistakes (e.g. wrong angle trigger, missing target title, wrong pricing language) → edit `briefs/<brief_id>.json`, regenerate affected variables, re-render.
- Smartlead campaign copy issues → edit copy via `lilly-bot`, re-fetch the body, re-render.

Loop until the user replies "approve and push". DO NOT push to Smartlead before approval.

### 5.7f. After approval — push to Smartlead

NOW invoke `lilly-bot` to push the approved leads to the brief's Smartlead campaign (campaign stays PAUSED — no sends). The Smartlead UI becomes a SECONDARY visual confirmation.

---

## Phase 6 — Schedule daily routine via /schedule

**ONLY fires after Phase 5.7 is approved.** Phase 6 must be the LAST step of setup — a routine on a broken pipeline silently fails or worse, mis-emails real prospects daily.

Delegate to the `/schedule` skill:

- **Cron expression:** `0 9 * * 1-5` (Monday-Friday, 9:00am local user-timezone)
- **Command to invoke:** `/lilly-trigify-data-processing <brief_id>`
- **Failure handler:** notify user on completion of each run with summary (counts of qualified / borderline / off-brief engagers, emails enriched, leads pushed)
- **Allow user override** before creating — ask "Default is daily 9am Mon-Fri local. Override? (y / different time / different days)"

Save the schedule_id into `brief.infrastructure.schedule_id` for future edit/delete operations.

### Phase 6 hand-off message

After scheduling, end the setup wizard with:

> Brief `<brief_id>` is live. Daily routine scheduled for 9am Mon-Fri local.
> - **Today:** the 2 dry-run leads are already in Smartlead campaign `<id>` (campaign is PAUSED — flip to START in Smartlead UI when ready to send).
> - **Tomorrow + ongoing:** Trigify auto-pushes new engagers → the 9am routine enriches emails → uploads to Smartlead. Open the Sheet to see what landed.
> - **First 7 days:** expect Claude to suggest negative title patterns at the end of each daily run, AND per-tracked-account precision stats. Apply title-pattern updates in the Trigify saved-search UI; drop tracked accounts whose precision < 30% after 100+ engagers.
>
> Pause the routine anytime with `/lilly-trigify-data-processing <brief_id> --pause`. Resume with `--resume`.

---

## Default engager target titles (Phase 0 fallback)

If the user doesn't specify engager target titles, use this default set for B2B services / SaaS briefs:

```json
[
  "Head of Sales",
  "Head of GTM",
  "Head of Marketing",
  "Head of Growth",
  "Head of Revenue",
  "VP Sales",
  "VP Marketing",
  "VP Revenue",
  "VP GTM",
  "Chief Revenue Officer",
  "CRO",
  "Chief Marketing Officer",
  "CMO",
  "Chief Sales Officer",
  "CSO",
  "Founder",
  "Co-Founder",
  "CEO"
]
```

For non-GTM briefs (e.g. product-led, engineering-buyer), adapt to the appropriate function leadership (CTO, VP Engineering, Head of Product, etc.).

---

## Key reference values (Navreo account)

- Make.com **Organisation ID**: 1634255
- Make.com **Team ID**: 536258
- Make.com **Google connection ID**: 9696598
- Trigify API key: `$TRIGIFY_API_KEY` from `~/.navreo-keys.env` (add this key if not yet present — see Notes/gotchas)
- Prospeo API key: `$PROSPEO_API_KEY` (used downstream by `lilly-trigify-data-processing` for email enrichment)
- AI Ark key: `$AI_ARK_API_KEY` (fallback for email enrichment when Prospeo returns NO_MATCH)
- Smartlead API key: `$SMARTLEAD_API_KEY`

---

## Hand-off

When this skill completes:

1. Tell the user the brief is provisioned and saved.
2. List the artefacts: Sheet URL, Make scenario URL, Smartlead campaign URL (if created), brief config file path.
3. Provide the UI checklist (Phase 5).
4. Tell the user: "Once you've configured the tracked accounts + webhook in Trigify UI and confirmed a row landed in the Engagers tab, run `lilly-trigify-data-processing` whenever you want to enrich emails and push leads to Smartlead. The Trigify push is autonomous — it happens regardless of whether you run anything else."

---

## Editing an existing brief

If the user wants to edit a brief that already exists:
1. Load `briefs/<brief_id>.json`
2. Walk through the relevant Phase questions, pre-filling current values
3. After capturing changes, re-provision affected infrastructure:
   - Tracked-accounts changes → output new UI checklist for the user to update in Trigify UI
   - Title-pattern changes → no infrastructure update needed; takes effect on next `lilly-trigify-data-processing` run (and may require updating Trigify UI's title filter too — surface this)
   - Smartlead campaign changes → update the `campaign_id` reference
4. Save the updated brief config.

---

## Deleting a brief

If the user wants to delete a brief:
1. Confirm with the user (this is destructive).
2. Delete the Make scenario via `scenarios_delete`.
3. Delete the webhook via `hooks_delete`.
4. Archive the brief config (move to `briefs/archive/`).
5. Tell the user to manually delete the Trigify tracked-accounts search in UI (Trigify API likely doesn't support this).
6. Leave the Sheet and Smartlead campaign intact unless user explicitly asks to delete (these may contain historical data).

---

## Notes / gotchas

- **Trigify webhook payload schema is NOT pre-verified.** The blueprint at `templates/engagers-scenario-blueprint.json` makes reasonable assumptions (nested `engager.*`, `post.*`, `comment.*` objects) but the real schema is only confirmed at "Determine data structure" time inside Make. Step 6.4 in Phase 5 explicitly walks the user through verifying + updating field references if reality differs from the blueprint.
- **Trigify API key must be added to `~/.navreo-keys.env`.** First run of this skill — prompt the user to obtain a Trigify API key from their Trigify dashboard (Settings → API) and add it as `TRIGIFY_API_KEY=...`. Without it, Phase 2 (sample-fit testing) and Phase 5.7a (dry-run pull) cannot run.
- **Engager IS the lead — no DM-finder phase.** Don't accidentally inject `lilly-tam` anywhere in this skill. Email enrichment is a single Prospeo `enrich-person` call against the engager's LinkedIn URL, with AI Ark fallback when Prospeo returns NO_MATCH.
- **Engagers-of-companies vs engagers-of-people.** Both tracked-account types (company pages and personal profiles) are supported. Personal profiles tend to have higher precision (followers are pre-selected for being interested in that person's content) but lower volume (one person can only post so much). Company pages have higher volume but lower precision.
- **Volume blowback risk.** A single high-follower tracked account can produce 100+ engagers/day. Surface this risk explicitly in Phase 2 / 3 and recommend tightening qualification or dropping the account when the daily estimate exceeds the cap.
- **Comment-text personalisation is the killer feature.** Engagers who COMMENT (vs only like) give us their literal words. The Icebreaker angle library reflects this — comment-text references get priority over like-based angles when both apply. Insist on this in the angle library Phase 4c.5.
- **Drive MCP can only create files at root.** The Sheet lands in the user's Drive root. The user can move it manually after creation.
- **Drive MCP can't rename existing files.** Sheet name has to be set at `copy_file` time. If a rename is needed later, user must do it in the Sheet UI.
- **Trigify tracked-accounts searches are not API-managed (assumption).** All saved-search CRUD likely happens in Trigify UI. Verify this on first run; if Trigify exposes a saved-search API, update this skill to use it.
- **Phase 2 sample-fit check uses `lilly-lead-score`.** Don't try to score samples inline.
- **Test fire validation is mandatory before declaring a brief live.** After Phase 5, the user must trigger a manual test fire from Trigify UI. Then check the scenario's executions in Make and confirm `operations > 1`. If only 1 op fired, the filter rejected the payload — usually a schema mismatch.
