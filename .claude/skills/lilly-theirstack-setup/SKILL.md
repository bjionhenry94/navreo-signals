---
name: lilly-theirstack-setup
description: "One-time-per-brief setup wizard for TheirStack-driven hiring-signal pipelines. Captures the user's brief (ICP + offer + signal rationale), ideates 4-6 candidate filter angles (title-based + description-keyword-based), free-preview tests each angle across a 30-day window for both TAM volume and sample-fit, merges winning angles into a single saved-search filter, then provisions all the infrastructure: per-brief Google Sheet with Jobs + Decision-Makers tabs, Make.com scenario cloned from a template that routes TheirStack pushes into that Sheet, Smartlead campaign skeleton with the correct merge variables, and a brief config JSON file consumed downstream by lilly-theirstack-data-processing. Outputs a paste-ready UI checklist for the user to create the saved search inside TheirStack's web app (TheirStack does not expose saved-search creation via API). Use this skill whenever the user wants to: add a new hiring-signal brief, ideate TheirStack filter angles for a new audience or client, spin up a TheirStack pipeline for a vertical/ICP, test TAM size and sample-fit across multiple filter angles before committing to a saved search, or onboard a new DFY client whose pipeline will be driven by hiring signals. Trigger phrases: 'set up a new TheirStack brief', 'find me job-signal angles for X', 'spin up a hiring-signal pipeline', 'create a TheirStack search for Y', 'TAM-test these angles', 'set up TheirStack for [client]', 'ideate hiring-signal angles', 'new TheirStack pipeline'. Does NOT run the daily enrichment or push leads to Smartlead — that is lilly-theirstack-data-processing's job, which consumes the brief config file this skill writes."
---

# Lilly TheirStack Setup

## Purpose

Setup wizard for TheirStack-driven hiring-signal pipelines. One brief = one run of this skill = full infrastructure provisioned.

The skill captures the user's brief, ideates multiple filter angles, TAM-tests each one for free (via `blur_company_data: true`), merges the winners into a single saved-search filter, provisions the supporting infrastructure (Google Sheet + Make scenario + Smartlead campaign skeleton + brief config file), and outputs a paste-ready UI checklist for the user to create the saved search in TheirStack's web app.

This skill does NOT run daily enrichment or push leads to Smartlead — that's `lilly-theirstack-data-processing` (separate skill).

## When to Use

Trigger when the user wants to:
- Add a new hiring-signal brief / TheirStack pipeline
- Ideate filter angles for a new audience or client
- TAM-test multiple search angles before committing to a saved search
- Onboard a new DFY client whose outreach will be driven by hiring signals

Skip / don't trigger when:
- The user wants to process today's leads from an existing brief → use `lilly-theirstack-data-processing`
- The user wants a one-off TheirStack pull without setting up a saved search → call `/v1/jobs/search` directly via Bash

## Communication style (MANDATORY across every phase)

**Write for a non-technical reader at every phase, especially Phase 2 results and Phase 3a same-vs-separate campaign decision.** The user is the campaign owner / business owner, not an engineer. They will not parse jargon, they will get frustrated, and they will make worse decisions because the reasoning was obscured behind technical words.

**Banned terms (use the plain-English column instead):**

| Don't say | Say instead |
|---|---|
| array / list of strings | "the list of words we tell the search to look for" or just describe what's in it |
| TAM | "how many jobs we'd see per month" / "how many companies are out there" |
| fit % / precision / sample-fit | "how many out of 10 are the right kind of role" / "quality" |
| threshold / below 60% threshold | "less than 6 out of 10 are clean" |
| substring match | describe what's happening — "TheirStack's search matches partial words, so when we ask for X it also catches Y" |
| acronym collision | "the short code CRO means three different things in three different industries" |
| title-negatives | "words we tell the search to ignore" |
| saved search | "the search you set up in TheirStack" |
| webhook / endpoint / API / payload | describe the function — "the link TheirStack uses to push new jobs to your spreadsheet" |
| iterator / router / blueprint | describe the function — "the bit of the workflow that splits batched data into one row at a time" |
| merge variable / {{variable}} | "the placeholder in the email that gets filled in with the lead's info" |
| qualification gate / role-only judgement layer | "the filter that decides if a job is a good fit before we spend money on it" |
| brief config / JSON | "the settings file for this campaign" / "the campaign's settings" |
| scenario / blueprint | "the workflow in Make" / "the workflow that connects things together" |
| ICP / signal-fit | "the kind of company we want to reach" / "why this kind of job means they'd be a good buyer" |

**Rules for results delivery:**

1. **Lead with what it means, not what it is.** "About 21 new jobs per day" beats "624 total_results over 30 days at ~21/day".
2. **Always explain the WHY behind a verdict.** "Drop this angle because half the matches are the wrong kind of role" beats "Fit % below threshold".
3. **Show concrete examples of the noise.** "It catches 'Personal Assistant to a Commercial Director' which is an admin role" lands harder than "noisy keyword".
4. **Use 'out of 10' instead of percentages** when the sample is small. "6 out of 10 are clean" not "60% precision".
5. **Frame trade-offs as choices a business owner makes.** "More volume but more cleanup work daily" vs "less volume but cleaner signal".
6. **Tables are fine, but explain every column header in plain English at least once.**
7. **Recommendation always comes last and is one clear sentence.** "I recommend going with A + B tightened" — not buried in a paragraph.

**Where this matters most:**
- Phase 2 (TAM test results) — biggest decision point in the wizard
- Phase 3a (same-campaign vs separate-campaigns decision)
- Phase 5 (UI checklist for TheirStack — user actually has to follow these steps)
- Phase 5.7 (dry-run lead pack — user reads the rendered email copy and makes the launch call)

Phases 4 (provisioning) and 6 (scheduling) can stay technical-ish because the user mostly approves the action rather than understanding the mechanics.

## Architecture

```
lilly-theirstack-setup (this skill — wizard + provisioner)
   │
   ├──> Phase 0: Brief capture (ICP, offer, signal rationale, DM titles)
   │
   ├──> Phase 0.5: Role qualification framework
   │       (qualified / disqualified / borderline role patterns —
   │        consumed by lilly-theirstack-data-processing Phase 2.5)
   │
   ├──> Phase 1: Angle ideation (4-6 candidate filter shapes)
   │
   ├──> Phase 2: Free TAM testing (blur_company_data: true, 30-day window per angle)
   │       └──> lilly-lead-score   (per-angle sample-fit scoring)
   │
   ├──> Phase 3: Final filter merge (winning angles → single job_title_or array)
   │
   ├──> Phase 4: Infrastructure provisioning
   │       ├──> Drive: create per-brief Sheet with Jobs + Decision-Makers tabs
   │       ├──> Make.com: clone scenario from templates/make-scenario-blueprint.json
   │       │              with the new Sheet ID baked in
   │       ├──> Smartlead: create campaign skeleton with merge vars
   │       │              ({{first_name}}, {{company_name}}, {{HowWeCanHelp}}, {{Offer}})
   │       └──> Save brief config to briefs/<brief_id>.json
   │
   ├──> Phase 5: UI checklist output (paste-ready TheirStack saved-search settings)
   │       │
   │       └──> User creates saved search in TheirStack UI manually
   │            (TheirStack API does not expose saved-search creation)
   │
   ├──> Phase 5.5: WAIT for user to confirm "saved search live"
   │       (mark theirstack_saved_search.created_in_ui_at in brief config)
   │
   ├──> Phase 5.7: End-to-end dry-run with 2 real companies (~$0.50 in credits)
   │       │
   │       ├─ Pull 2 unblurred rows from same filter (TheirStack ~2 cr)
   │       ├─ POST those 2 to the Jobs webhook (proves Make scenario works)
   │       ├─ Run Phase 2.5 qualification (proves the role gate works)
   │       ├─ Call lilly-tam on 2 domains (~6-10 Prospeo cr)
   │       ├─ Generate per-lead variables for each DM (proves angles read right)
   │       ├─ Push via lilly-bot to Smartlead (campaign PAUSED — no sends yet)
   │       └─ User inspects rendered emails in Smartlead UI + approves
   │
   └──> Phase 6: Schedule daily routine via /schedule
           (ONLY fires after Phase 5.7 approval — no schedule on unproven pipelines)
           Default: 09:00 local daily, invokes /lilly-theirstack-data-processing <brief_id>
```

After this skill completes:
- The Sheet exists, ready to receive TheirStack pushes
- The Make scenario is active and listening on its webhook
- The Smartlead campaign exists, ready to receive personalised leads
- The brief config is on disk, ready for `lilly-theirstack-data-processing` to consume
- The user has a checklist to paste into TheirStack UI to create the saved search

The TheirStack UI step is the user's only manual touchpoint per brief.

---

## Phase 0 — Brief capture

Ask the user, in one batched block of questions, for the following. Pre-fill defaults from prior conversation if available.

| Question | Notes |
|---|---|
| **Brief ID** (kebab-case) | e.g. `navreo-gtm-hiring-signal` — used as folder/file names. Auto-generate from brief name if user doesn't specify. |
| **Client / account** | e.g. `Navreo (internal)`, `Amplifyy`, etc. For multi-client setups. |
| **ICP description** (plain English) | e.g. "Small-to-mid B2B companies hiring for roles that signal building a GTM system internally" |
| **Offer** (what the user/client sells) | e.g. "We do cold email infrastructure — handling sender setup, sequences, and inbox management for B2B teams" |
| **Why this signal = fit** | e.g. "When a company hires Demand Gen / GTM Engineers, they're building outbound capabilities and often need help with execution" |
| **Company size** (min, max employees) | Default: 10–200 |
| **Countries** (ISO-2 codes) | Default: Navreo's 14-country high-GDP set — US, CA, GB, AU, IE, NZ, DE, NL, CH, SE, NO, DK, FI, SG. User can subset (e.g. "English-only" → US, CA, GB, AU, IE, NZ, SG) |
| **Direct employer only** (skip recruiting agencies) | Default: yes (`company_type: direct_employer`) |
| **Daily volume cap** (max jobs/day) | Default: 50 |
| **DM target titles** (who we'll outreach to) | Default: Head of Sales, Head of GTM, Head of Marketing, VP Sales, CRO, CMO, Chief Revenue Officer. User can customise per brief — e.g. for a product-led brief, swap to Head of Product / VP Engineering. |
| **Smartlead campaign** | Existing campaign ID to push to, OR ask the skill to create a new one with skeleton sequence |

Confirm before proceeding to Phase 0.5.

---

## Phase 0.5 — Role qualification framework

**Purpose.** TheirStack's saved-search `job_title_or` is a coarse string match — it will catch roles that share keywords with the signal but don't actually signal "building a GTM system internally". The qualification framework is a **role-only judgement layer** applied by `lilly-theirstack-data-processing` on every daily batch.

**Hard rule: this gate is about the ROLE, not the COMPANY.** A wholesale apparel brand or an RV manufacturer might be a fine prospect under a different brief — the qualification framework just decides whether THIS hire signals what THIS brief is targeting. Never bake industry / company-type exclusions into this gate.

### 0.5a. Auto-draft default patterns based on the brief's signal

For a `gtm_system_building` signal type (the default for Navreo's hiring-signal briefs), pre-populate these defaults. User reviews + edits before they're baked into the brief config.

```json
"qualification": {
  "_purpose": "Role-only judgement layer applied by lilly-theirstack-data-processing. Classifies each new Jobs row as QUALIFIED / BORDERLINE / OFF_BRIEF based on whether the role signals 'building or scaling a GTM system internally'. Never excludes companies — only roles.",

  "role_signal_definition": "The new hire will own, build, or strongly influence the company's internal GTM system — its process, tooling, or growth motion. Not a person executing orders inside an established operational structure.",

  "qualified_role_patterns": [
    "Manager / Senior Manager / Director / Lead / VP / Head / Chief of (Demand Gen | RevOps | Sales Operations | Marketing Operations | GTM Operations)",
    "GTM Engineer / Go-to-Market Engineer / Growth Engineer",
    "Founding / First (Sales | Marketing | Growth | GTM | AE | BDR) hire",
    "Demand Generation Specialist or Manager at <100 emp B2B SaaS (likely first dedicated demand-gen hire)"
  ],

  "disqualified_role_patterns": [
    "Intern / Junior / Associate level — no system-build authority",
    "Coordinator-level — admin/execution layer, not GTM owner",
    "Branch / Regional / Area / Field Manager — field P&L role, not GTM-stack buyer",
    "Software / Backend / Frontend Engineer for internal GTM Platform / Growth Platform — product engineer, not GTM buyer",
    "Wholesale / Distribution Sales Operations — account ops, not GTM build",
    "VP / Director of Operations & Sales at brokerages / dealerships / distributors — transactional commercial ops, not GTM stack"
  ],

  "borderline_role_patterns": [
    "Specialist (RevOps | Demand Gen | Marketing Ops) at 50-200 emp — could be first dedicated hire or admin layer",
    "Sales / Marketing Ops Manager at <30 emp — likely first-of-kind, may need company-context check"
  ]
}
```

### 0.5b. Surface to user

Show all three pattern lists as plain English. Ask:
- "Anything to add to qualified patterns?"
- "Anything to add to disqualified patterns?"
- "Anything to move between borderline and one of the other two?"

The defaults above are calibrated against the standard Navreo GTM hiring-signal brief. For other signal types (engineering hiring, leadership hiring, etc.), the wizard re-drafts the defaults to fit that signal type.

### 0.5c. Bake into brief config

Save the user-confirmed patterns into the brief config under `qualification`. This is consumed by `lilly-theirstack-data-processing` Phase 2.5.

### 0.5d. Reinforce the first-7-days iteration loop

Tell the user explicitly:

> "For the first 7 days after this brief goes live, expect to iterate on negative keywords daily. Each daily run surfaces (a) borderline rows for your yes/no, and (b) suggested negative keywords from the off-brief rows. Apply those negatives in your TheirStack saved-search UI. After 7 days the saved search should be ~85% precise and the qualification pass becomes mostly cosmetic."

This sets expectations — Day 1 will be noisy, that's by design.

---

## Phase 1 — Angle ideation

Given the brief, generate 4–6 candidate filter angles. Each angle is one TheirStack filter shape. Cover different facets of the same signal.

Standard angle archetypes (adapt per brief):

| Archetype | Filter type | Example for GTM brief |
|---|---|---|
| **Title — direct role** | `job_title_or: [primary role titles]` | Demand Generation, Demand Gen, GTM Engineer, Go-To-Market Engineer |
| **Title — adjacent ops** | `job_title_or: [ops/enablement role titles]` | RevOps, Revenue Operations, Sales Operations, Marketing Operations, GTM Operations |
| **Title — founding/first** | `job_title_or: [founding-X / first-X titles]` | Founding Account Executive, Founding GTM, First Sales Hire, Founding Marketer |
| **Description — tool stack** | `job_description_contains_or: [GTM tools]` | Clay, Apollo, Outreach (capitalised → case-sensitive; high false-positive risk — see notes) |
| **Description — phrase intent** | `job_description_contains_or: [phrases that imply the motion]` | "cold outbound", "outbound sequences", "GTM stack", "build the GTM" |
| **Description — methodology** | `job_description_contains_or: [methodology terms]` | "predictable revenue", "PLG motion", "ABM" |

Show all candidates to the user with a one-line rationale for each. Ask which to test. Allow the user to add their own custom angles.

**Tightness tip:** Description-keyword angles tend to be NOISY. Words like "outreach" (generic verb) and "Apollo" (also a candidate sourcing tool) produce false positives. Flag this when proposing those angles, and offer the regex-tightened alternative (`job_description_pattern_or` with `\b...\b` word boundaries) if the user wants to keep them.

---

## Phase 2 — Free TAM testing

For each angle the user approves:

```json
{
  "posted_at_max_age_days": 30,
  "job_country_code_or": ["<countries from brief>"],
  "min_employee_count": <min from brief>,
  "max_employee_count": <max from brief>,
  "company_type": "direct_employer",

  // Angle-specific filter slots in here:
  "job_title_or": [...]
  // OR
  "job_description_contains_or": [...]

  "blur_company_data": true,         // FREE — must always be true at this phase
  "include_total_results": true,     // gets us total_results + total_companies
  "limit": 10                        // 10 blurred samples per angle
}
```

POST to `https://api.theirstack.com/v1/jobs/search` with `Authorization: Bearer $THEIRSTACK_API_KEY` (sourced from `~/.navreo-keys.env`).

Capture per angle:
- `total_results` (30-day TAM count)
- `total_companies` (unique companies)
- Sample of 10 blurred jobs (job titles visible, company names hidden)
- Daily estimate: `total_results / 30`

**Cost:** Zero. `blur_company_data: true` is free.

**Then run `lilly-lead-score`** against each angle's 10-sample to get a fit %. Reject angles with fit % < 60%.

Build a comparison table for the user. Example shape:

| Angle | 30-day jobs | Companies | Daily est. | Fit % | Verdict |
|---|---|---|---|---|---|
| A: Title — Demand Gen + GTM Eng | 292 | 248 | ~10/day | 100% | ✅ Keep |
| B: Description — GTM tools | 23,717 | 14,418 | ~790/day | 40% | ❌ Drop (noisy) |
| C: Title — Ops roles | 1,001 | 867 | ~33/day | 80% | ✅ Keep |
| D: Title — Founding/First | 184 | 146 | ~6/day | 100% | ✅ Keep |
| E: Description — phrases | 292 | 231 | ~10/day | 100% | ⚠️ Likely overlaps A |

---

## Phase 3 — Final filter merge

User picks the winning angle(s) from Phase 2.

### 3a. Same-campaign or separate-campaigns? (NEW — mandatory question)

**Before merging anything, ask the user explicitly:**

> "You picked N winning angles. Do you want all of them to:
> - **(a) Funnel into ONE campaign** — merge filters, one Sheet, one Smartlead campaign, one set of copy. Best when angles target the same buyer persona with the same offer messaging.
> - **(b) Run as SEPARATE campaigns** — one Sheet + saved search + Make scenario + Smartlead campaign per angle. Best when angles target different audiences/seniorities/regions that need different copy."

This question is mandatory. The skill MUST NOT auto-merge silently — that silently buries angles' distinctness. Lesson learned 2026-05-13: Navreo GTM brief collapsed Angles A+C+D into one campaign; Angles B+E were dropped without revisiting whether they'd have warranted their own campaign with tighter / different copy.

### 3b. If user chose "same campaign":

- Merge winning title-based angles → union their patterns into one `job_title_or` array.
- Title-based + description-based angle → cannot be ANDed cleanly in a single saved search; either run two separate saved searches (revert to choice 3a (b)) OR drop one.
- Standard chassis (countries, employee size, direct_employer) carries over unchanged.
- Continue to Phase 4 with a single brief config.

### 3c. If user chose "separate campaigns":

- For each winning angle, treat it as its own independent brief.
- Generate a brief_id per angle (e.g. `navreo-gtm-demand-gen`, `navreo-gtm-ops`, `navreo-gtm-founding-hires`).
- Run Phase 4 (infrastructure provisioning) once per brief — each gets its own Sheet, Make scenarios, Smartlead campaign, brief config file.
- Phase 5 outputs N UI checklists (one per saved search).
- The user's ICP description, offer, and sender context are shared across all child briefs unless they want to differentiate copy per-campaign.

Confirm the merged filter shape (3b) or the per-angle filter shapes (3c) with the user before proceeding to provisioning.

Also confirm the **daily volume estimate** after merge — if the combined daily estimate exceeds the cap (e.g. >50/day), tighten the filter or accept that TheirStack's saved-search will cap at the user's plan limit. For separate campaigns, each campaign gets its own volume budget.

---

## Phase 4 — Infrastructure provisioning

### 4a. Google Sheet (copy from template)

**Template Sheet ID**: `1FUUWljpeHN3Ba_jIuqzVg5fuwEDWwul79dszSNdETmQ`
**Template Sheet URL**: https://docs.google.com/spreadsheets/d/1FUUWljpeHN3Ba_jIuqzVg5fuwEDWwul79dszSNdETmQ/edit

**Naming convention (Sheet + Make scenario must match exactly):**

```
TheirStack — <Brief Name>
```

Example: `TheirStack — Navreo GTM Hiring Signal`. Use this exact title format for both the Sheet (Phase 4a) AND the Make scenario (Phase 4b) so the user can navigate between them by name without thinking.

Use Drive MCP `copy_file` to clone the template Sheet with the title above. The template already contains the correct tab structure (`Jobs` + `Decision-Makers` tabs) WITH the Status column header in column O (Jobs) and column R (Decision-Makers) — copying preserves them. **Never write to the template Sheet directly** — it's reference only.

**Jobs tab headers** (row 1, 15 columns — already in template):

```
Date Pulled	Date Posted	Company	Website	Country	City	Company Size	Job Title	Seniority	Remote	Tech Stack	Job Posting	Open Roles	Company LinkedIn	Status
```

**Decision-Makers tab headers** (row 1, 18 columns — already in template):

```
First Name	Last Name	Email	Title	LinkedIn	Phone	Company	Website	Country	Company Size	Hiring For	Tech Stack	Remote	Job Posting	Open Roles	Date Added	Source	Status
```

Note: `Status` column is the idempotency mechanism — `lilly-theirstack-data-processing` only processes rows with Status = `NEW`.

**Important**: when copying the template, any test data inside it carries over. The skill should warn the user to clear any rows below row 1 (preserve headers) before the brief goes live. The user can do this manually in the Sheet UI (select all rows from row 2 down → right-click → delete rows).

Capture the new Sheet ID for the brief config.

### 4b. Make.com scenarios (TWO per brief)

**Architecture decision (locked 2026-05-13):** every brief gets **TWO separate Make.com scenarios + TWO webhooks**, NOT one unified scenario with a router. The unified pattern was attempted and failed — Make's webhook schema inference does not reliably learn union/wrapped payload shapes across multiple call types. See the "Make schema inference gotcha" note below.

**Per brief, create:**

1. **Jobs scenario** — receives `job.new` events from TheirStack's saved-search webhook
   - Template: `templates/jobs-scenario-blueprint.json`
   - Flow: `webhook → addRow to Jobs tab` (no router, no iterator — TheirStack sends one job per POST)
   - Webhook URL goes into TheirStack saved-search UI (per Phase 5 instructions)
   - Filter NOT needed — only TheirStack pushes to this webhook

2. **Decision-Makers scenario** — receives DM batches pushed by `lilly-theirstack-data-processing` (skill 2)
   - Template: `templates/dms-scenario-blueprint.json`
   - Flow: `webhook → iterator over {{1.rows}} → addRow to Decision-Makers tab`
   - Webhook URL is stored in the brief config (consumed by skill 2)
   - Payload shape (sent by skill 2): `{"rows": [{...17 DM fields...}]}`

Per scenario, use Make.com MCP:
- `hooks_create` for the webhook
- `scenarios_create` with the customised blueprint (replace `{{spreadsheet_id}}`, `{{webhook_hook_id}}`, `{{google_connection_id}}`)
- Note both webhook URLs — Jobs URL → TheirStack UI; DMs URL → brief config

Team ID for Navreo: **536258**. Google connection ID: **9696598**. These are fixed.

**Both scenarios need a redetermine-data-structure pass BEFORE first activation** — Make's webhook structure inference happens at first payload, and an inactive scenario silently swallows test fires (returns HTTP 200, never runs the flow). The Phase 5 UI checklist explicitly walks the user through this for the Jobs webhook in **Step 6** (redetermine → fire TheirStack test → save → activate → fire test again to verify). For the DMs webhook, the equivalent pass happens during Phase 5.7 (the dry-run skill 2 sends its first sample payload while the user has Make in "redetermine data structure" mode on the DMs scenario).

**Anti-pattern to avoid:** "Activate first, then redetermine" — activation locks the webhook schema as empty/unknown, and Make then can't bind the addRow mappings to anything. The order MUST be: redetermine → capture sample → save → activate → verify. The Step 6 wording above bakes this in; don't shortcut it for "speed".

#### Make schema inference gotcha (the reason we use TWO scenarios)

Make.com webhooks learn their schema from the first payload received during "Determine data structure" mode. The schema is then strict — payloads with a different shape are silently discarded (HTTP 200 returned, but the scenario doesn't trigger).

When two different payload shapes arrive at the same webhook (e.g. TheirStack's `{id, type, payload}` and our `{rows: [...]}`), Make either:
- Treats one shape as canonical and silently drops the other, OR
- Captures a partial union but iterator/field references on the "secondary" shape return empty/undefined

This was attempted multiple times during 2026-05-13 build with a `{id, type, payload.rows}` wrap pattern — execution ran but the iterator received empty array, no row written.

**Resolution: one webhook per payload shape, always.** Two scenarios per brief is mildly more setup but completely sidesteps the schema-inference fragility.

### 4c. Smartlead campaign skeleton

Either:
- (a) User provides existing campaign ID → use as-is
- (b) Skill creates new campaign via Smartlead API with skeleton sequence + the right merge variable schema (`{{first_name}}`, `{{company_name}}`, `{{HowWeCanHelp}}`, `{{Offer}}`)

The `{{Offer}}` variable is set at the campaign level in Smartlead (one value for all leads in the campaign). The user fills this in via Smartlead UI or `lilly-bot` afterward.

### 4c.5. Draft personalisation angle libraries (when applicable)

For each `per_lead_variable` in the brief config that uses `generation_strategy: angle_waterfall`, draft 4-6 candidate angles WITH the user before baking them into the brief config.

**Process:**

1. **Identify each waterfall variable** by reading the campaign's email copy (already fetched in Phase 4c). For each `{{custom_variable}}` that will be filled by `angle_waterfall` (not delegated to another skill, not a direct lookup), the variable needs an angle library.

2. **Auto-draft 4-6 candidate angles** based on:
   - The brief's offer + signal-fit rationale (`ideation.offer` + `ideation.why_signal_fits_angles`)
   - The DM's likely job context (hiring_for role, company_size buckets, tech_stack signals)
   - The email's sentence-stem that this variable completes (so the angle reads naturally in context)

3. **Surface candidates to the user** in a table format:

   | # | Angle | Trigger condition | Example output |
   |---|---|---|---|
   | 1 | Founding/first-hire signal | `hiring_for matches /(Founding\|First)/i` | "founding roles like this typically end up doing everything except what they were hired for, and we handle the execution piece" |
   | ... | ... | ... | ... |
   | N | **Fallback (always works)** | always — no specific signal needed | "we've built outbound systems for 50+ B2B teams and can run yours on a pay-per-result basis" |

4. **User confirms / edits / drops** angles. **The fallback angle is non-negotiable** — there must always be a last-resort that fires when no specific signal matches. Insist on it.

5. **Bake confirmed angles into the brief config** as the `per_lead_variables.<var_name>.angles[]` array, with the schema:

   ```json
   {
     "id": "<short_kebab_id>",
     "priority": <integer, lower = higher priority>,
     "trigger": "<plain-English condition referencing DM/job context fields>",
     "instructions": "<LLM prompt augmentation for this angle>",
     "example": "<one-shot demo output>"
   }
   ```

   Fallback always has `"priority": 99` and `"trigger": "always — fires when no specific angle matches"`.

**Same pattern applies to future briefs too** — never bake a flat `instructions` string for a waterfall variable; always draft the angle library with user confirmation first.

### 4d. Brief config JSON

Save to `~/.claude/skills/lilly-theirstack-setup/briefs/<brief_id>.json`:

```json
{
  "brief_id": "navreo-gtm-hiring-signal",
  "brief_name": "Navreo GTM Hiring Signal",
  "client": "Navreo (internal)",
  "created_at": "2026-05-13",

  "ideation": {
    "icp_description": "...",
    "offer": "...",
    "why_signal_fits": "..."
  },

  "filter": {
    "posted_at_max_age_days": 1,
    "job_country_code_or": ["US","CA","GB","AU","IE","NZ","DE","NL","CH","SE","NO","DK","FI","SG"],
    "min_employee_count": 10,
    "max_employee_count": 200,
    "company_type": "direct_employer",
    "job_title_or": ["Demand Generation","Demand Gen","GTM Engineer","Go-To-Market Engineer","Go to Market Engineer","RevOps","Revenue Operations","Sales Operations","Marketing Operations","GTM Operations","First Sales Hire","Founding Account Executive","Founding GTM","Founding Sales","Founding Marketer","Founding Marketing","First Growth Hire"],
    "limit": 50
  },

  "dm_finder": {
    "target_titles": ["Head of Sales","Head of GTM","Head of Marketing","VP Sales","CRO","CMO","Chief Revenue Officer","Chief Marketing Officer"],
    "providers_preference": ["prospeo", "ai_ark"],
    "max_dms_per_company": 3
  },

  "infrastructure": {
    "sheet_id": "1FUUWljpeHN3Ba_jIuqzVg5fuwEDWwul79dszSNdETmQ",
    "sheet_url": "https://docs.google.com/spreadsheets/d/.../edit",
    "make_scenario_id": 9226982,
    "make_webhook_url": "https://hook.eu2.make.com/...",
    "smartlead_campaign_id": null,
    "smartlead_campaign_url": null
  },

  "theirstack_saved_search": {
    "ui_label": "GTM hiring signals — Navreo",
    "created_in_ui_at": null,
    "user_must_create_in_ui": true
  }
}
```

The `created_in_ui_at` field is `null` until the user confirms they've created the saved search in TheirStack UI. `lilly-theirstack-data-processing` will warn if it's still null after a brief is created.

---

## Phase 5 — UI checklist output

Output a clean, readable checklist for the user to create the saved search in TheirStack UI. **Format note: do NOT use ASCII boxes / horizontal rules around content.** Use plain numbered steps with markdown tables or bulleted detail blocks where needed. Heading-and-list structure is fine; decorated boxes are not.

### Required content

For each step, show:

**Step 1 — Launch a new search.** Real UI flow (don't shortcut to "New job search" — that phrase doesn't appear anywhere in the actual UI):

1. Open `app.theirstack.com` and log in
2. Click **"Search"** in the left sidebar
3. Click the green **"+ New search"** button in the TOP-RIGHT of the Search page (NOT "New job search" — the button just says "+ New search")
4. A new search interface opens with two tabs at the top: **Companies** and **Jobs**. Click the **"Jobs"** tab (it may default to Companies, which is the WRONG tab — every saved search for hiring-signal pipelines must be on the Jobs tab)

**Step 2 — Apply filters** (use a small markdown table to show field → value mapping):

| Field | Value |
|---|---|
| Posted date | Last 1 day |
| Job Title **contains any of** | `<comma-separated INCLUDE patterns from filter>` |
| Job Title **does NOT contain any of** (negatives) | `<comma-separated EXCLUDE patterns, OR write "none — see notes" if the brief has zero exclusions>` |
| Job Description **contains any of** (if brief uses description-keyword angle) | `<comma-separated description keywords, OR skip row entirely if title-only brief>` |
| Employees | between `<min>` and `<max>` |
| Company HQ Location is any of (⚠️ NOT "Job Location" — see geography note below) | `<comma-separated country UI labels — see country mapping below>` |
| Company Type | Direct employer |

**Default-visible filter chips on the new-search page are limited:** only `Posted date`, `Job Location`, `Job Title`, and `Job Description` appear out of the box. Everything else (`Employees`, `Company HQ Location`, `Company Type`, plus any other filter) must be added via the **"+ Add Filter"** button (left of the Search button on the filter row). **Walk the user through this explicitly** — they will look for an Employees / HQ / Company Type chip on the default toolbar, not find one, and get stuck. Tell them: "Click '+ Add Filter' and search for [Employees / Company HQ Location / Company Type]". Same applies for any saved search where the brief's filter shape includes a non-default field.

**Default `Job Location` chip is NOT the right filter** — it filters by where the role is physically located, which lets a US-HQ company posting a remote-PH role slip through (and conversely, screens out a UK-HQ company posting a US role). Have the user either ignore the default Job Location chip OR delete it after adding, then add `Company HQ Location` via `+ Add Filter`. Confirm in the table they're applying Company HQ Location.

**ALWAYS surface the title-negatives row to the user**, even when the brief has zero exclusions — show the row with value `none — none required for this brief` so they consciously confirm rather than miss the step. Title negatives in TheirStack UI are a separate filter chip from positives; users have lost rows because they applied positives but forgot the negatives chip.

**Source the negatives from `brief.theirstack_saved_search.negative_title_keywords`** — this list grows over time as `lilly-theirstack-data-processing` Phase 8.5 surfaces new off-brief patterns. For first-run briefs the list may be empty; over the brief's first 7 days the list typically fills to 5-10 keywords. The UI checklist shows the CURRENT confirmed list.

**Geography rule (CRITICAL — was reversed in previous SOP, fixed 2026-05-17):** Use `Company HQ Location`, NOT `Job Location`. Rationale (per GTM brief 2026-05-15): we target companies whose HQ is in a high-GDP country (money / decision-making lives at HQ), regardless of which office posted the role. A US-HQ company posting a remote PH role IS qualified. The default UI chip is "Job Location" so the user must actively switch to HQ Location.

**Same applies to job-description filters** if the brief uses any description-keyword angle (e.g. an Angle B "Clay/Apollo/Outreach mentioned in description" brief). Surface a Job Description row in the table; the UI control is a separate filter chip from job-title filters.

**Step 3 — Click green "Search"** → confirm roughly the expected number of results from preview (give a specific number based on Phase 2 estimate)

**Step 4 — Click orange "Save"** → name it: `<Brief Name>`

**Step 5 — Connect the webhook:**
1. Click the **"Webhooks"** button in the top-right of the saved search
2. Tick the checkbox **"Trigger once per company"** (prevents duplicates if a company posts multiple matching jobs in the same window)
3. Paste the webhook URL: `<Make webhook URL>`
4. Click **"Create webhook"**

**Step 6 — Activate the Jobs scenario in Make** (do this BEFORE the verify test fire — otherwise the test payload arrives at an inactive webhook, returns HTTP 200, and silently gets queued without writing a row):
1. Open the [Jobs scenario in Make] (provide the `jobs_scenario_url` from the brief config)
2. **Click the webhook module** (first module in the flow) → click **"Redetermine data structure"**. Make will show "Waiting for data".
3. While Make is waiting, go back to TheirStack and hit **"Send test"** on the saved search. The payload arrives, Make captures its schema, the webhook module shows a green tick.
4. Click **"OK" / "Save"** inside the scenario editor.
5. Toggle the scheduling switch at the bottom-left to **"ON"** (activate). The scenario is now live.

**Step 7 — Verify** by hitting **"Send test"** in TheirStack a SECOND time (this time against the activated scenario). Within ~30 seconds:
- A row appears in the Jobs tab of the brief's Sheet
- The scenario's executions log shows `operations: 2` (1 webhook + 1 addRow)

**Step 7a — If nothing happens after 30 seconds (this is COMMON and EXPECTED on first activation):** Newly-activated Make scenarios with `scheduling.type = "indefinitely"` + a 900-second polling interval will NOT process queued webhook payloads until their next poll cycle, which can be up to 15 minutes after activation. To force immediate execution, follow this exact two-step order: **(1) first hit "Send test" on the TheirStack saved search** — this queues a fresh payload at the webhook — **THEN (2) open the Make scenario and click the "Run once" button** (next to the scheduling toggle) so the scenario processes that queued payload immediately. The order matters: "Run once" does nothing if no payload is queued, so the TheirStack test MUST fire first. The row then appears in the Sheet within ~10 seconds, and from that point onwards the scenario runs continuously without intervention.

This first-poll-delay only affects the very first execution after activation. All subsequent webhook fires (real TheirStack pushes during normal operation) are processed without delay.

**Surface "Step 7a / Run once" to the user EVERY time** — even though it's only needed when the first verify fails, the user will hit it on every brief's first activation and not know what to do. Default behaviour is to wait 15 minutes and assume the setup is broken. Tell them upfront: "if nothing arrives in 30s, send a test from TheirStack FIRST, then click 'Run once' in Make" — in that order, because Run once only processes a payload that is already queued.

If the row STILL didn't appear after Step 7a's "Run once" click, debug via `executions_list` → `executions_get-detail`. Common causes: a field reference in the blueprint doesn't match TheirStack's actual payload shape (e.g. `payload.company` vs `payload.company_name`), or the Google Sheet binding broke.

**Step 8 — Reply** "saved search live" so the skill can mark `theirstack_saved_search.created_in_ui_at` in the brief config.

### Country code → TheirStack UI label mapping

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

Use the country names matching TheirStack's UI labels:
- US → United States
- CA → Canada
- GB → United Kingdom
- AU → Australia
- IE → Ireland
- NZ → New Zealand
- DE → Germany
- NL → Netherlands
- CH → Switzerland
- SE → Sweden
- NO → Norway
- DK → Denmark
- FI → Finland
- SG → Singapore

---

## Phase 5.7 — End-to-end dry-run with 2 real companies

**Purpose.** Close the gap between "saved search created" and "we know the personalization reads right". Run the full downstream pipeline against 2 real companies BEFORE the saved search starts pumping 50 jobs/day into a broken setup. Worth ~$0.50 in credits to surface issues now rather than after Day 1's batch lands wrong.

**MANDATORY PROGRESSION — process rule (do not skip).** Every brief setup ALWAYS advances through the decision-maker enrichment test. The process never stops at "saved search created" or "jobs are landing in the Sheet" — a pipeline is not considered set up until at least 2 real decision-makers have been enriched from real jobs (via `lilly-tam`) and their emails rendered for approval. If the email copy is not finalised yet, still run the DM-enrichment half against draft copy so the decision-maker side of the pipeline is proven before go-live.

**Triggers ONLY after the user has explicitly confirmed `theirstack_saved_search.created_in_ui_at` is set AND THE WEBHOOK IS ATTACHED.** Until then, hold this phase.

### 5.7-pre. ENFORCE the TheirStack-saved-search loop closure BEFORE proceeding

The single most common failure mode is the user saying "progress now" or implicitly waving you through Phase 5.7 without having actually clicked **Save** + **Create webhook** inside TheirStack's UI. When that happens, the entire pipeline appears to work — DM enrichment runs, Smartlead leads are pushed, daily routine schedules — but **no actual TheirStack jobs are flowing in**. The pipeline runs dry forever.

**Before starting any work in Phase 5.7, explicitly verify all four loop-closure conditions:**

1. **Saved search exists in TheirStack UI.** Ask the user directly: "Have you created and saved the search in TheirStack UI with the exact filters and label `<brief.theirstack_saved_search.ui_label>`?" Don't accept "yes I'm progressing" — require explicit YES on this specific item.
2. **Webhook URL is attached.** "Did you paste `<brief.infrastructure.jobs_webhook_url>` into the saved search's webhook config and click 'Create webhook'?" Require explicit YES.
3. **"Trigger once per company" is ticked.** "Did you tick the 'Trigger once per company' checkbox?" Require explicit YES.
4. **Test fire fired AT LEAST ONE row into the Jobs tab.** Verify via Make `executions_list` against the brief's `jobs_scenario_id` — look for an `auto` execution with `operations: 2`. If you see a `manual` execution but no `auto`, the user fired test from terminal (your verify POST) but TheirStack itself hasn't tested. They MUST hit "Send test" from inside the TheirStack UI saved search.

**ALL FOUR must be confirmed before Phase 5.7 starts.** If any is missing, halt and surface the gap to the user explicitly. Do NOT proceed on faith.

After confirmation, write the timestamp into the brief config:
```json
"theirstack_saved_search": {
  "created_in_ui_at": "<ISO8601 timestamp>",
  "webhook_attached": true,
  "trigger_once_per_company": true,
  "test_fire_verified_at": "<ISO8601 timestamp of the auto execution from Make>"
}
```

If you can't fill in all four of those fields, you don't have permission to start Phase 5.7. This is non-negotiable.

### 5.7a. Pull 2 unblurred sample rows from TheirStack

Re-fire the SAME filter as Phase 2 with two changes: `blur_company_data: false` and `limit: 2`. Cost: ~2 TheirStack credits.

```bash
curl -X POST "https://api.theirstack.com/v1/jobs/search" \
  -H "Authorization: Bearer $THEIRSTACK_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "posted_at_max_age_days": 1,
    "job_country_code_or": [<brief countries>],
    "min_employee_count": <brief min>,
    "max_employee_count": <brief max>,
    "company_type": "direct_employer",
    "job_title_or": [<brief titles>],
    "limit": 2
  }'
```

Pick the 2 most ICP-shaped results (cleanest job title + company size in mid-range, well-known company if possible). If the filter returns <2 results for today, drop posted_at_max_age_days to 7 and retry. If still <2, fail this phase and tell the user the filter is too narrow — they need to widen before going live.

### 5.7b. POST the 2 rows to the brief's Jobs webhook

Construct 2 fake `job.new` payloads matching TheirStack's webhook shape and POST them to `brief.infrastructure.jobs_webhook_url`. This proves the Make scenario routes correctly + writes the right fields to the Sheet's Jobs tab.

```bash
for row in row1 row2; do
  curl -X POST "$JOBS_WEBHOOK_URL" \
    -H "Content-Type: application/json" \
    -d "{\"id\": <timestamp>, \"type\": \"job.new\", \"payload\": <unblurred row>}"
done
```

Wait ~10s, re-read the Sheet, confirm both rows landed in the Jobs tab with all 15 columns filled.

**HARD RULE: every live sample touched during Phase 5.7 MUST be POSTed to the Jobs webhook — including replacement samples after a swap.** If you swap a sample (e.g. caralegal → orderbird because the original had no verified email), POST the REPLACEMENT to the webhook too. The Sheet is the user's source-of-truth for what the daily routine will produce; if Phase 5.7's final 2 leads aren't all visible in the Sheet, the dry-run hasn't fully exercised the Make pipeline on the leads the user is about to approve. Lesson learned 2026-05-17 (navreo-vp-head-sales brief): caralegal + Pave Finance were posted at the start of Phase 5.7, then caralegal got swapped to GoldBook (dry hole) → orderbird (success), and orderbird was never posted to the Sheet until the user flagged it. Don't repeat this.

**Pattern: every time you finalize a Phase 5.7 sample, immediately POST it to the Jobs webhook before moving to the next step.** Treat the Sheet write as part of the sample-acceptance ritual, not a one-time step at Phase 5.7b's start.

### 5.7c. Run `lilly-theirstack-data-processing` against the brief in test mode

Invoke the data-processing skill with `--dry-run` flag (or equivalent — the skill walks Phase 2.5 qualification → DM enrichment → personalization → Smartlead push using only those 2 rows). Cost: ~6-10 Prospeo credits, 1 AI Ark call if fallback fires.

### 5.7d. Render the FULL campaign copy with variables slotted — INLINE in chat (NOT in Smartlead UI)

**Inspection happens in chat first, BEFORE the Smartlead push.** Pushing leads and then asking the user to open Smartlead UI to inspect is slow, breaks the iteration loop, and forces the user to context-switch between chat and Smartlead. The correct primary inspection surface is chat.

**MANDATORY pre-step: WebFetch every company's website BEFORE generating `{{Cold Email Video Angle}}`.** The angle must reference the company's ACTUAL ICP — not your guess at what they do based on industry classification. Industry tags like "Media Production" or "IT Services and IT Consulting" are far too coarse: Inhance (Media Production) does immersive AI/XR for major brands; another Media Production company might do podcast post-production. Without WebFetch verification, you'll routinely mis-pitch the angle. Fall back to the LinkedIn job posting URL if the homepage is JS-rendered and returns empty. Only after WebFetch confirmation should the angle be locked in.

**Render format (mandatory layout per DM):**

For EACH DM, produce TWO sections in chat:

1. **A resolved-variable table** with: variable name, resolved value, and trigger/source. Shows the user at-a-glance which angle fired, what the ICP slot resolved to, etc. Lets the user catch a bad angle decision BEFORE reading the rendered copy.
2. **Full rendered email blocks** — one per variant per email step (e.g. Email 1 Variant A, Email 1 Variant B, Email 2 follow-up). Subject line + body + P.S. with all merge variables substituted. **Keep spintax visible** — do NOT pre-resolve `{build|set up}` etc. so the user can see Smartlead's variant pool.

The table-first-then-emails layout is non-negotiable: variable table FIRST so the user knows what to look for in the rendered emails, full emails SECOND so the user can verify the rendered output matches the intent.

For each rendered email:
- Substitute every merge variable (including standard Smartlead fields like `{{first_name}}`, `{{company_name}}`) with the resolved per-lead value.
- Show subject + body + P.S. as one code block per (DM, variant, email step).
- For a 2-DM × 2-variant × 2-email-step sequence that's 8 rendered emails — show all of them.

This is the inspection surface. The user reads the rendered copy and validates:
1. The hook reads naturally — `Saw you were hiring a {{Role}}` should not produce "a Sales, Customer Experience Operations" (comma artefact)
2. `{{HowWeCanHelp}}` flows after "wanted to reach out because" — no double-because, no full-sentence-starting-with-capital, no clash with the surrounding copy
3. `{{Cold Email Video Angle}}` slots after the email's stem (e.g. "what we'd build to ___") without redundancy
4. `{{Icebreaker}}` (if used) doesn't reference hiring (skip_angles enforced)
5. `{{CaseStudy}}` in email 2 has hard numbers and isn't a TikTok dupe of the P.S.
6. Variants A and B both render coherently (they may differ in pricing language — variant A "guaranteed 30 qualified leads in 90 days", variant B "pay-per-lead basis" — pick the one that matches your brief's pricing language or flag the mismatch)

Surface to user:

> ## Dry-run lead pack
>
> **Lead 1** — `<dm.full_name>`, `<dm.title>` @ `<dm.company>` (`<email>`)
>
> ### Email 1, Variant A — subject: `<rendered subject>`
> ```
> <fully rendered email body with merge variables substituted, spintax kept visible>
> ```
>
> ### Email 1, Variant B — subject: `<rendered subject>`
> ```
> <fully rendered email body>
> ```
>
> ### Email 2 (follow-up, day +N) — subject: `<rendered subject>`
> ```
> <fully rendered email body including {{CaseStudy}}>
> ```
>
> **Lead 2** — `<dm.full_name>`, `<dm.title>` @ `<dm.company>` (`<email>`)
>
> ### Email 1, Variant A — subject: ...
> ```
> ...
> ```
>
> ### Email 1, Variant B — ...
> ### Email 2 — ...
>
> ---
>
> Reply **"approve and push"** to proceed to Smartlead push (campaign PAUSED — no sends), or specify edits (e.g. "Lead 2's HowWeCanHelp is too generic", "Cold Email Video Angle for Inhance doesn't match what they do") and I'll iterate. We may also iterate on the BRIEF CONFIG (e.g. add COO to target_titles if a DM was included as a small-co exception).

### 5.7e. Iterate on rendered copy until approved

If the user flags issues:
- Per-DM variable mistakes → fix in memory, re-render, surface again (cheap — no API costs).
- Brief-config mistakes (e.g. wrong angle trigger, missing target title, wrong pricing language) → edit `briefs/<brief_id>.json`, regenerate the affected variables, re-render.
- Smartlead campaign copy issues (e.g. variant A's "guaranteed 30 leads" doesn't fit the brief's pay-per-lead pricing) → edit the campaign copy via `lilly-bot`, re-fetch the body, re-render.

Loop until the user replies "approve and push". DO NOT push to Smartlead before approval — saves you having to update leads via `lilly-bot` after each render iteration.

### 5.7f. After approval — push to Smartlead

NOW invoke `lilly-bot` to push the approved leads to the brief's Smartlead campaign (campaign stays PAUSED — no sends). The Smartlead UI then becomes a SECONDARY visual confirmation (the user can flip through the leads to see them in the actual UI, but the primary correctness check happened in chat).

### 5.7e. Iterate until approved

If the user flags issues, fix in the brief config's `personalization.per_lead_variables` (adjust angle waterfall triggers, instructions, or examples), re-run the personalization step on the SAME 2 dry-run leads (no need to re-enrich DMs — Smartlead supports lead updates via lilly-bot), surface again. Loop until approved.

---

## Phase 6 — Schedule daily routine via `mcp__scheduled-tasks__create_scheduled_task`

**ONLY fires after Phase 5.7 is approved.** Phase 6 must be the LAST step of setup — a routine on a broken pipeline silently fails or worse, mis-emails real prospects daily.

**Use `mcp__scheduled-tasks__create_scheduled_task` — NOT the `/schedule` skill.** The `/schedule` skill repeatedly failed with "We're having trouble connecting with your remote claude.ai account" errors (2026-05-14/15) and the cloud-routine architecture has fundamental local-file-access limitations regardless. The `mcp__scheduled-tasks` MCP is local, reliable, and matches the existing GTM brief's pattern (`theirstack-navreo-gtm-daily` task firing daily at 09:04 local since 2026-05-14).

**Steps:**

1. **Check for existing task first** via `mcp__scheduled-tasks__list_scheduled_tasks`. The task ID convention is `theirstack-<brief_id>-daily` (e.g. `theirstack-navreo-sdr-daily`). If it already exists, surface it to the user — don't recreate.

2. **Create the task** with these params:
   - `taskId`: `theirstack-<brief_id>-daily`
   - `description`: `Daily TheirStack pipeline for <Brief Name> — enriches qualified jobs into Smartlead leads`
   - `cronExpression`: `0 9 * * 1-5` (Monday-Friday, 9:00am LOCAL timezone — cron is evaluated in local time, NOT UTC)
   - `notifyOnCompletion`: `true`
   - `prompt`: mirror the GTM task's structure (read `/Users/bjionhenry/.claude/scheduled-tasks/theirstack-navreo-gtm-daily/SKILL.md` as the template). Per-brief variations:
     - swap `brief_id` to this brief's ID
     - swap `sheet_id` to this brief's Sheet ID
     - swap Smartlead campaign ID
     - reflect brief-specific qualification rules (e.g. borderlines disabled vs enabled)
     - reflect brief-specific personalization angles (e.g. SDR brief's "pay-per-lead" vs GTM's "performance basis")
     - reflect brief-specific webhook + scenario quirks (e.g. SDR brief needs `scenarios_run` on dms_scenario_id 9233401 after POST due to polling-mode webhook)

3. **Allow user override** before creating — ask "Default is daily 9am Mon-Fri local. Override? (y / different time / different days)".

4. **Save schedule metadata into brief config** under `brief.infrastructure`:
   ```json
   "schedule_task_id": "theirstack-<brief_id>-daily",
   "schedule_task_path": "/Users/bjionhenry/.claude/scheduled-tasks/theirstack-<brief_id>-daily/SKILL.md",
   "schedule_cron": "0 9 * * 1-5",
   "schedule_timezone": "Europe/London (local)",
   "schedule_created_at": "<today>",
   "schedule_mcp_tool": "mcp__scheduled-tasks__create_scheduled_task"
   ```

**Why NOT `/schedule`:** Cloud routines run in a stateless environment that doesn't reliably resolve local skills, brief configs in `~/.claude/skills/`, state files, MCP servers (Smartlead/Make/AI Ark/Prospeo), or the `~/.navreo-cache/` cache. Even when /schedule's connection works, the resulting cloud routine cannot invoke local skills against local resources. `mcp__scheduled-tasks` runs the task on the user's machine via the same Claude Code session pattern that local interactive use provides — full access to skills, configs, MCPs, cache, everything.

### Phase 6 hand-off message

After scheduling, end the setup wizard with:

> Brief `<brief_id>` is live. Daily routine scheduled for 9am Mon-Fri local.
> - **Today:** the 2 dry-run leads are already in Smartlead campaign <id> (campaign is PAUSED — flip to START in Smartlead UI when ready to send)
> - **Tomorrow + ongoing:** TheirStack auto-pushes new jobs → the 9am routine enriches DMs → uploads to Smartlead. Open the Sheet to see what landed.
> - **First 7 days:** expect Claude to suggest negative keywords at the end of each daily run. Apply them in your TheirStack saved search UI to tighten the filter.
>
> Pause the routine anytime with `/lilly-theirstack-data-processing <brief_id> --pause`. Resume with `--resume`.

---

## Default DM target titles (Phase 0 fallback)

If the user doesn't specify DM target titles, use this default set for B2B GTM-signal briefs:

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

For non-GTM briefs (e.g. engineering hiring signals), adapt to: CTO, VP Engineering, Head of Engineering, Director of Engineering, etc.

---

## Key reference values (Navreo account)

- Make.com **Organisation ID**: 1634255
- Make.com **Team ID**: 536258
- Make.com **Google connection ID**: 9696598
- TheirStack API key: `$THEIRSTACK_API_KEY` from `~/.navreo-keys.env`
- Prospeo API key: `$PROSPEO_API_KEY` (used downstream by `lilly-theirstack-data-processing` via `lilly-tam`)
- Smartlead API key: `$SMARTLEAD_API_KEY`

---

## Hand-off

When this skill completes:

1. Tell the user the brief is provisioned and saved.
2. List the artefacts: Sheet URL, Make scenario URL, Smartlead campaign URL (if created), brief config file path.
3. Provide the UI checklist (Phase 5).
4. Tell the user: "Once you've created the saved search in TheirStack UI and confirmed a row landed, you can run `lilly-theirstack-data-processing` whenever you want to enrich DMs and push leads to Smartlead. The TheirStack push is autonomous — it happens regardless of whether you run anything else."

---

## Editing an existing brief

If the user wants to edit a brief that already exists:
1. Load `briefs/<brief_id>.json`
2. Walk through the relevant Phase questions, pre-filling current values
3. After capturing changes, re-provision affected infrastructure:
   - Filter changes → output new UI checklist for the user to update in TheirStack UI (TheirStack saved searches are editable, but only via UI)
   - DM target title changes → no infrastructure update needed; takes effect on next `lilly-theirstack-data-processing` run
   - Smartlead campaign changes → update the campaign_id reference
4. Save the updated brief config.

---

## Deleting a brief

If the user wants to delete a brief:
1. Confirm with the user (this is destructive).
2. Delete the Make scenario via `scenarios_delete`.
3. Delete the webhook via `hooks_delete`.
4. Archive the brief config (move to `briefs/archive/`).
5. Tell the user to manually delete the TheirStack saved search in UI (TheirStack API doesn't support this).
6. Leave the Sheet and Smartlead campaign intact unless user explicitly asks to delete (these may contain historical data).

---

## Notes / gotchas

- **TheirStack webhook payload shape is non-obvious.** When TheirStack pushes a `job.new` event to the Make webhook, the payload looks like:
  ```json
  { "id": <int>, "type": "job.new", "payload": { ...job + company_object... } }
  ```
  NOT like `{ type: "jobs", rows: [...] }`. Key implications:
  - Make scenario filter for the Jobs branch must check `type == "job.new"` (NOT `"jobs"`)
  - TheirStack sends **one job per HTTP POST** (not batched), so the Jobs branch has **NO iterator** — addRow runs directly off `{{1.payload.<field>}}` references
  - Job fields are nested inside `payload` (e.g. `{{1.payload.company}}`, `{{1.payload.job_title}}`)
  - `company_object` is a nested object inside `payload` (e.g. `{{1.payload.company_object.employee_count}}`)
  - Arrays like `technology_slugs` need `{{join(1.payload.technology_slugs; "|")}}` to flatten for cell write
  - The DMs branch is different — it receives batched payloads `{ type: "dms", rows: [...] }` from `lilly-theirstack-data-processing` and DOES use an iterator. Two route shapes intentionally diverge.
- **TheirStack docs reference for payload schema:** `/en/docs/webhooks/event-type/webhook_job_new` (root keys: `id`, `type`, `payload`).
- **`blur_company_data: true` is mandatory during Phase 2 testing.** Otherwise every preview costs credits.
- **Drive MCP can only create files at root.** The Sheet lands in the user's Drive root. The user can move it manually after creation, or we accept it lives at root.
- **Drive MCP can't rename existing files.** Sheet name has to be set at `copy_file` / `create_file` time. If a rename is needed later, user must do it in the Sheet UI.
- **Make.com filter placement.** When constructing the Make scenario blueprint, route filters MUST be placed at the route's first-module top-level `filter` field, NOT inside `metadata.filter` (Make treats the latter as design-time only). The template already does this correctly — don't break it when modifying.
- **TheirStack saved searches are not API-managed.** All saved-search CRUD must happen in TheirStack UI. This is a hard limitation.
- **Phase 2 sample-fit check uses `lilly-lead-score`.** Don't try to score samples inline — that skill exists for a reason and handles the LLM-first confidence ladder properly.
- **Test fire validation is mandatory before declaring a brief live.** After Phase 5, the user must trigger a manual test fire from TheirStack UI (their saved search has a "Send test" button). Then check the scenario's executions in Make and confirm operations > 1 (≥1 webhook + ≥1 addRow). If only 1 op fired, the filter rejected the payload — usually a schema mismatch. See `executions_list` → `executions_get-detail` for debugging.
