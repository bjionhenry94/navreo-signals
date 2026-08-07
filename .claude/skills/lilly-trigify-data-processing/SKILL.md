---
name: lilly-trigify-data-processing
description: "Daily orchestrator for Trigify LinkedIn engagement-signal pipelines. Reads brief configs provisioned by lilly-trigify-setup, processes new engager rows in each brief's Google Sheet, applies a 4-gate qualification (location, post-topic, engager-title, engager-company), surfaces borderline rows for user verdict before spending credits, enriches verified emails via Prospeo enrich-person with bidirectional AI Ark fallback, double-checks Prospeo-source emails via lilly-email-verification (MillionVerifier Stage 1) when brief opts in, generates per-lead Icebreaker + HowWeCanHelp variables using a perspective-aware angle waterfall (first-person for the sender's own posts, role-anchored with ZERO post reference for tracked competitor founder posts), pushes QUALIFIED engagers to the brief's Smartlead campaign via lilly-bot and/or HeyReach list via HeyReach MCP, writes Status back to the Sheet via a Make sidecar scenario (or Apps Script fallback), and emits an end-of-run summary with negative-title suggestions plus per-tracked-profile precision stats. Idempotent, safe to re-run any number of times. Use whenever the user wants to: process today's engagers, run the daily Trigify routine, advance the pipeline, push qualified engagers to Smartlead/HeyReach, check what's queued, or resolve borderline rows from a previous run. Trigger phrases: 'process today's Trigify engagers', 'run the Trigify pipeline', 'enrich new engagers', 'push Trigify engagers to Smartlead', 'run the daily routine', 'process the engagers tab', 'what's queued', 'trigify daily', 'resolve borderlines', 'run lilly-trigify-data-processing'. Does NOT create new briefs or saved searches, that's lilly-trigify-setup. Reads brief configs from ~/.claude/skills/lilly-trigify-setup/briefs/*.json. Writes state to ~/.claude/skills/lilly-trigify-data-processing/state/<brief_id>.json."
---

# Lilly Trigify Data Processing

## Purpose

Daily orchestrator that turns Trigify-pushed Engagers rows into Smartlead-ready and/or HeyReach-ready leads with personalised merge variables. Runs when the user invokes it (no auto-schedule unless set up via `/schedule`) and processes whatever has accumulated since last run.

This is the user-facing counterpart to the autonomous `lilly-trigify-setup` pipeline. The autonomous half (Trigify Workflow → Make → Engagers tab) runs without the user. This skill bridges Engagers tab → qualified leads → Smartlead campaign / HeyReach list.

## When to Use

Trigger when the user wants to:
- Process today's new Trigify engagers into outreach leads
- Enrich new engagers with verified emails
- Push qualified engagers to Smartlead and/or HeyReach
- Run the "daily routine" / advance the pipeline
- Resolve borderline rows from a previous run
- Check what's queued (rows with Status = NEW in Engagers tab)

Skip / do not trigger when:
- The user wants to create a NEW brief / saved search → use `lilly-trigify-setup`
- The user wants to QA an existing Smartlead campaign → use `lilly-qa`
- The user wants to enrich a generic domain list → use `lilly-tam` directly

## Prerequisites

The user must have already run `lilly-trigify-setup` for at least one brief, which produces:
- A brief config at `~/.claude/skills/lilly-trigify-setup/briefs/<brief_id>.json`
- A per-brief Google Sheet with an Engagers tab being filled by Trigify Workflows via Make
- A Smartlead campaign skeleton (and/or HeyReach list) bound in `infrastructure.smartlead_campaign_id` / `infrastructure.heyreach_list_id`

This skill consumes those artefacts. It never modifies brief configs or recreates infrastructure.

## Key architectural differences vs `lilly-theirstack-data-processing`

| Aspect | TheirStack data-processing | Trigify data-processing |
|---|---|---|
| Upstream row | Job posting | LinkedIn post engagement (like or comment) |
| Lead model | Job → Company → find Decision Makers at that company | Engager IS the lead, no DM-finder phase |
| Qualification | One-gate (role only) | FOUR-gate (location → post-topic → engager-title → engager-company), in cheapness order |
| Personalization | Anchored to job posting (hiring_for, tech_stack) | Perspective-aware angle waterfall, anchored to engager role + company (NEVER to the post when post-author is a competitor) |
| Enrichment | Full waterfall via lilly-tam | Single Prospeo `enrich-person` per row + AI Ark fallback (Trigify pre-fills name, title, company, country) |
| Downstream | Smartlead only | Smartlead and/or HeyReach (per-brief config) |
| Sheet write-back | None (Status stays NEW forever) | Status write-back via Make sidecar scenario (default) or Apps Script (fallback) |

## Architecture

```
lilly-trigify-data-processing (this skill, daily orchestrator)
   |
   +-- For each brief config in ~/.claude/skills/lilly-trigify-setup/briefs/*.json:
   |
   +-- Phase 1: Read brief config + state file, parse Engagers tab, dedupe vs state
   |
   +-- Phase 2: 4-gate qualification (cheapest first)
   |     location -> post-topic -> engager-title -> engager-company
   |     verdict: QUALIFIED / BORDERLINE / OFF_BRIEF
   |
   +-- Phase 2.5: Surface BORDERLINE rows for user verdict (keep/drop)
   |     before any credits get burned
   |
   +-- Phase 3: Email enrichment via Prospeo enrich-person on QUALIFIED rows
   |     Bidirectional AI Ark fallback when Prospeo returns NO_MATCH
   |     Drop rows whose verified email is undeliverable
   |
   +-- Phase 3.5: MillionVerifier double-check on Prospeo-source emails (opt-in via brief config)
   |     Delegates to lilly-email-verification (Stage 1 MV only)
   |     Drops MV-failed rows BEFORE Phase 4 variable-gen wastes tokens
   |     Skipped for AI-Ark-source emails (bidirectional fallback)
   |
   +-- Phase 4: Per-lead variable generation (perspective-aware)
   |     Icebreaker  -> angle waterfall by post author (first-person vs role-anchored)
   |     HowWeCanHelp -> offer-anchored to engager role + company (NEVER post-referencing)
   |
   +-- Phase 5: Push QUALIFIED+email rows to outreach channels
   |     Smartlead via lilly-bot (mandatory delegation)
   |     HeyReach via MCP add_leads_to_list_v2
   |     Routed by brief.outreach.channels = ["smartlead" | "heyreach" | "both"]
   |
   +-- Phase 6: Sheet Status write-back
   |     Default: POST batch to Make sidecar scenario (Path A)
   |     Fallback: emit Apps Script for the user to paste once (Path B)
   |
   +-- Phase 7: Persist state + end-of-run summary
   |     Counts, per-tracked-profile precision, negative-title suggestions
   |     Borderline rows queued for next run
```

Each phase is idempotent. Re-running is always safe, already-PROCESSED rows skip via state file.

---

## Phase 1, Read + parse + dedupe Sheet

### 1a. Load brief configs

For each `~/.claude/skills/lilly-trigify-setup/briefs/*.json`:
- Skip if `infrastructure.smartlead_campaign_id` is null AND `infrastructure.heyreach_list_id` is null (no destination to push to)
- Skip if `infrastructure.sheet_id` is null (no Engagers Sheet yet)
- Load state from `~/.claude/skills/lilly-trigify-data-processing/state/<brief_id>.json`. If absent, initialise:
  ```json
  {
    "brief_id": "...",
    "last_run_at": null,
    "processed_engagers": [],
    "stats": {"total_runs": 0, "total_engagers_processed": 0, "total_pushed": 0}
  }
  ```

Surface to user a per-brief preview before doing real work: `Brief X, N rows in Engagers tab, estimated K NEW, P borderlines pending. Proceed?`

### 1b. Read the brief's Sheet via Drive MCP

Use `mcp__91841cbc-...__read_file_content` with `fileId = brief.infrastructure.sheet_id`. **Large Sheets exceed the MCP token limit and the tool saves the response to disk**, parse from the on-disk file rather than from the inline response.

The Sheet has a single Engagers tab with **32 columns** (v2 schema, verified against real Trigify payload 2026-05-17 — see Phase 4a of `lilly-trigify-setup`):

```
A:  Date Pulled            J:  Engaged At                  S:  LinkedIn URN
B:  Post URL               K:  Comment Text                T:  LinkedIn Headline
C:  Post Author Name       L:  Comment Permalink           U:  Profile Picture URL
D:  Post Author LinkedIn   M:  Comment Likes Count         V:  Open To Work
E:  Post Date Posted       N:  First Name                  W:  Job Title
F:  Post Text (full)       O:  Last Name                   X:  Company Name
G:  Post Likes Count       P:  Full Name                   Y:  Company Domain
H:  Post Comments Count    Q:  LinkedIn URL                Z:  Company Industry
I:  Engagement Type        R:  LinkedIn Username           AA: Company HeadCount
                                                           AB: Company Description
                                                           AC: Country
                                                           AD: Location
                                                           AE: Status
                                                           AF: Raw Payload
```

Canonical column→source mapping lives in `brief.engagers_sheet_schema.columns[]`. The Raw Payload column (AF) is the full Trigify webhook JSON as a string — catchall in case the column-mapping misses a field (e.g. Trigify adds a new key in a future release).

**v1 → v2 migration:** the existing 5,589 rows under v1's 17-column schema stay as-is. Going-forward writes only. v1 rows have empty cells in columns C / E / F-H / L-M / R-V / Z / AB / AD / AF — qualification logic must gracefully treat empty as "unknown" rather than failing the gate.

### 1c. Dedupe vs state

For each row:
- Use `linkedin_url` as the row identifier (normalised, strip trailing slash, lowercase host, strip query string).
- Skip if `linkedin_url` is in `state.processed_engagers[*].linkedin_url`.
- Skip if Sheet's Status column is already `PROCESSED`, `OFF_BRIEF`, or `PUSHED` (defensive, Status write-back may have lagged the state file on a previous run).
- Otherwise add to the run's `new_engagers` working set with all 17 column values captured.

**Within-run dedup by linkedin_url**, if the same engager appears on multiple posts in the same run (engaged with both Bjion's post AND a competitor's post on the same day), keep the row with the OWN-POST author first (lets the first-person angle fire), then the most recent by Engaged At.

Surface: `Found N new engagers across M tracked profiles for brief <brief_name>. Moving to qualification.`

---

## Phase 2, 4-gate qualification (cheapness order)

Apply gates in this order. **Fail fast** on the cheap gate before spending LLM tokens on the slow ones. All four MUST pass for QUALIFIED. Any single hard fail = OFF_BRIEF. Ambiguity in any gate = BORDERLINE.

Gates source from `brief.qualification.*`. The canonical shape lives in `briefs/navreo-competitor-founder-engagers.json` under `qualification`.

### 2a. Location gate (pure string check, no LLM, no derivation)

- Read column **AC (Country)** directly from the Sheet row. Trigify's `enrich.country` populates this with the UI-label form (e.g. "United States", "United Kingdom"). Map UI label → ISO-2 via the country-code table in `lilly-trigify-setup` Phase 5 (`United States` → `US`, `United Kingdom` → `GB`, etc.).
- If mapped code is in `brief.qualification.location_gate.qualified_country_codes` → PASS.
- If Country is empty/null → BORDERLINE (`reason = "loc=missing"`). Privacy-strict LinkedIn profiles in qualified countries land here.
- Otherwise → OFF_BRIEF (`reason = "loc=<country>"`). Do not evaluate further gates.

### 2b. Post-topic gate (LLM judgement on full post body)

Skip this gate entirely when `Post Author Name` (column C) `== brief.ideation.outreach_voice` (the sender's own post). The sender's own posts are presumed on-topic by definition.

Otherwise, prompt an LLM with:
- column **F (Post Text)** — the FULL post body (v2 schema captures the whole thing, not a 200-char snippet)
- `brief.qualification.post_topic_gate.qualified_topics[]`
- `brief.qualification.post_topic_gate.disqualified_topics[]`

Ask for verdict: `QUALIFIED` / `DISQUALIFIED` / `BORDERLINE`.

- QUALIFIED → PASS, continue to gate 2c
- DISQUALIFIED → OFF_BRIEF (`reason = "post_topic=<one-line classification>"`)
- BORDERLINE → BORDERLINE (`reason = "post_topic=ambiguous: <one-line>"`)

### 2c. Engager-title gate (pattern match against BOTH clean role and raw headline)

Read column **W (Job Title)** AND column **T (LinkedIn Headline)** from the row. The clean Job Title is Trigify's `enrich.jobTitle` — canonicalised, role-only. The LinkedIn Headline is the engager's raw self-written `author.title` — frequently contains pitch-language ("Host of...", "I help X do Y") that the clean Job Title hides. **Read both. The headline often catches signals the clean title misses, and vice versa.**

Run LLM-judgement (training-knowledge-first per `feedback_company_classification_llm_first`) against `brief.qualification.engager_title_gate` and the three pattern arrays (qualified, disqualified, borderline).

- Both Job Title AND Headline empty → BORDERLINE (`reason = "title=missing"`)
- Either field matches a disqualified pattern → OFF_BRIEF (`reason = "title=<the pattern that hit>"`)
- Either matches a borderline pattern (and none disqualified) → BORDERLINE
- Either matches a qualified pattern (and none disqualified or borderline) → PASS, continue to gate 2d
- Neither matches any pattern → BORDERLINE (`reason = "title=<job title>, headline=<headline>, unclassified"`)

### 2d. Engager-company gate (Trigify fields first, WebFetch fallback only)

**Decision ladder** (per `brief.qualification.engager_company_gate`):

1. **Open To Work check.** Read column **V (Open To Work)**. If `true` → OFF_BRIEF (`reason = "co=open-to-work, not a buyer"`).
2. **Size check.** Read column **AA (Company HeadCount)**. Parse as number or low/high range:
   - If outside `[brief.filter.min_employee_count, brief.filter.max_employee_count]` → OFF_BRIEF (`reason = "co=size=<n>, outside band"`).
   - EXCEPT: US 1-10 allowance applies — if `HeadCount ≤ 10` AND column AC (Country) `== "United States"` → still PASS the size check (per the 2026-05-17 rule).
   - Empty HeadCount → don't fail here; fall through to step 3.
3. **Industry + Description classification (PRIMARY, NO WebFetch).** Read column **Z (Company Industry)** and column **AB (Company Description)**. Pass both to LLM with:
   - column **X (Company Name)**
   - `brief.qualification.company_avoid_list[]`
   - the brief's offer + ICP-shape context
   - the brief's `engager_company_gate.decision_ladder`
   - Ask the LLM to verdict QUALIFIED / BORDERLINE / OFF_BRIEF in one pass.
   - Apply the LLM's training knowledge first (most brands of any size are classifiable from name alone). The industry + description is supporting evidence.
4. **WebFetch fallback (ONLY when step 3 is genuinely uncertain).** Trigger ONLY when ALL of:
   - The LLM verdict from step 3 is BORDERLINE or low-confidence
   - AND Industry is a generic umbrella ("Marketing and Advertising", "Information Technology and Services", etc.) — not a specific descriptor like "Business Consulting and Services"
   - AND Description is one vague sentence or empty
   - AND the company name doesn't ring a bell from training knowledge
   Then WebFetch column Y (Company Domain) for one sentence of clarification, re-verdict with LLM.
5. **Direct/near-competitor exclusion (CATEGORY rule, not just named rivals).** Drop any engager whose company sells what the sender sells, or sells the tooling that replaces the sender. For a DFY-outbound sender like Navreo, pitching "we'll book your meetings" to a company that itself books meetings (or builds the tool that does) is incoherent and burns a peer. This is a HARD drop even when the company is a perfect ICP on size + geo. Three buckets:
   - **DFY lead-gen / appointment-setting / cold-outbound agencies** (they book calls / generate pipeline as a service).
   - **GTM / RevOps-as-a-service agencies** (they build or run your outbound + revenue engine, "fractional GTM/RevOps", "revenue engine partner").
   - **Cold-outbound execution tools** (the software that does the sender's job): AI SDRs, LinkedIn / email outreach automation, sales-engagement / cold-email platforms, AI cold-calling / voice dialers for outbound.
   This bucket is dense on engagement-signal briefs because the tracked posts are *about* outbound/GTM, so the engager pool is full of outbound vendors. Calibration: on the 2026-05-24 competitor-founder A-tier batch, 28 of 128 "qualified" leads were direct/near competitors (lead-gen agencies, GTM/RevOps-as-a-service, AI SDRs, outreach tools) that slipped through size+geo+industry and had to be pulled. Match → OFF_BRIEF (`reason = "co=competitor:<bucket>"`). KEEP adjacent-but-not-competing companies that merely *sell to* sales teams (intent/signal data, ICP intelligence, CRM tooling, ABM analytics, content/personal-branding, recruiting, training, vertical SaaS) — they have a sales team that needs pipeline and are NOT competitors.
6. **Avoid-list overlay.** Run avoid-list patterns from `brief.qualification.company_avoid_list[]` AFTER steps 1-5. A 50-emp direct rival agency passes the size + industry checks but should still drop here. Avoid-list match → OFF_BRIEF (`reason = "co=avoid-list:<pattern>"`).
7. **Empty Company Name** → BORDERLINE (`reason = "co=missing"`).

Per-run cost: ~95% of rows resolve in step 3 with zero WebFetch. The remaining ~5% trigger step 4 — saves ~120-150 WebFetches per typical 130-row daily batch.

### 2e. Final verdict per row

- All 4 gates PASS → `QUALIFIED`
- Any gate hard-fails → `OFF_BRIEF` with reason
- Any gate is ambiguous → `BORDERLINE` with reason

Use the **shortest** failing-reason string so the run summary stays readable:
- `loc=India`
- `title='Customer Success Manager' | co=Direct competitor`
- `co=Solo consultant, avoid list`

### 2f. Reference implementation

A Python reference implementation lives at `scripts/qualify.py`. It takes a parsed Engagers-tab CSV plus the brief config JSON and emits the three-pot verdict file. Use it directly when the user prefers a deterministic pass, or treat it as a starting point and override per-gate behaviour with LLM calls when judgement is needed (gates 2b, 2c, 2d).

---

## Phase 2.5, Surface borderline rows for user verdict

**Purpose.** BORDERLINE rows are uncertainty. We do not burn Prospeo credits enriching uncertain rows. Surface them in chat for a fast keep/drop verdict before Phase 3.

### 2.5a. Pending borderlines from prior runs (handle FIRST)

Before showing today's borderlines, check `~/.claude/skills/lilly-trigify-data-processing/queue/<brief_id>.json` for any `pending_confirmations` from earlier runs with `user_decision: null`.

Surface those first:

```
You have N borderline rows pending from previous runs. Resolve before today's batch:

1. Jane Doe, Sales Manager @ Acme Co (added 2026-05-13). Reason: title borderline, co <50 emp. [y/n]?
2. ...

(Reply "y all" / "n all" / a comma-separated mix like "y, n, y")
```

Apply user responses:
- `y` → move row into today's `qualified` set (will be enriched in Phase 3)
- `n` → move row into today's `off_brief` set with `reason = "user rejected (borderline review)"`, mark in state so it never reappears

### 2.5b. Today's borderlines

Show a compact table with each borderline row's identifying fields plus the verdict reason:

```
Today's qualification pass: N new rows -> Q qualified, B borderline, O off-brief.

Borderlines (need your verdict):

| # | Name | Title | Company | Country | Post Author | Reason |
|---|------|-------|---------|---------|-------------|--------|
| 1 | ... | ... | ... | ... | ... | title=missing |
| 2 | ... | ... | ... | ... | ... | co=Unknown   |
| ... |

Reply "y all" to keep all, "n all" to drop all, or per-row "1y, 2n, 3y, ...".
You can also reply "defer" to push all to next run's queue for later review.
```

Wait for explicit user response. Default action if user simply says "proceed" is "defer all borderlines and enrich qualified set". Never enrich a borderline without an explicit `y`.

### 2.5c. Persist borderline queue

For any borderline NOT resolved this run, append to queue file:

```json
{
  "added_at": "2026-05-18T09:00:00Z",
  "row_data": {<full Engagers row, all 17 cols>},
  "verdict": "BORDERLINE",
  "reason": "...",
  "user_decision": null
}
```

For resolved-this-run borderlines, write `user_decision = "y"` or `"n"` into the queue as audit history.

---

## Phase 3, Prospeo enrich-person (with bidirectional AI Ark fallback)

**Only enrich QUALIFIED rows** (today's pass + user-approved borderlines). Skip everything else.

Trigify pre-fills name, title, company, country, LinkedIn URL on the Engagers row. The single missing piece is a verified email.

### 3a. Cache check first

Cache directory: `~/.navreo-cache/prospeo/enrich-person/` and `~/.navreo-cache/ai_ark/enrich-person/`. Filenames keyed by canonicalised LinkedIn URL hash.

For each QUALIFIED row:
1. Check Prospeo cache → if hit and email present + deliverable, use it. 0 credits.
2. Check AI Ark cache → if hit, use it. 0 credits.
3. Cache miss → run Phase 3b.

### 3b. Prospeo enrich-person (primary)

Call Prospeo `/enrich-person` with `linkedin_url = engager.linkedin_url` (canonicalised). Mirror the contract from `lilly-tam` exactly:
- Verified emails only (`skip_unverified_emails: true` from `brief.enrichment.skip_unverified_emails`)
- 1 credit per enrich
- Cache the response payload to `~/.navreo-cache/prospeo/enrich-person/<hash>.json`

If Prospeo returns email AND email is verified-deliverable → save to row, mark `enrichment_source = "prospeo"`, proceed.

### 3c. AI Ark fallback (bidirectional)

If Prospeo returns NO_MATCH or returns an unverified-only result, fall back to AI Ark per the bidirectional pattern from `feedback_dm_finder_bidirectional_email`:
- Call AI Ark `enrich_profile` with the LinkedIn URL.
- Cache to `~/.navreo-cache/ai_ark/enrich-person/<hash>.json`.
- If AI Ark returns a person record with email → use it. Mark `enrichment_source = "ai_ark"`.
- If AI Ark returns a person record WITHOUT email → run Prospeo bulk-enrich as a reverse fallback (LinkedIn → email).
- Both fail → drop the row with `reason = "NO_VERIFIED_EMAIL"`. Mark Status as `OFF_BRIEF_NO_EMAIL` in the write-back batch.

### 3d. Domain-match sanity check

For each enriched email, compare its host vs `engager.company_website` host. If they mismatch significantly (cross-contamination from cached job-history data), drop the email and mark `OFF_BRIEF_NO_EMAIL`. Borrowed verbatim from `lilly-tam` guardrail.

---

## Phase 3.5, MillionVerifier double-check on Prospeo-source emails (brief-config opt-in)

**Purpose.** Prospeo's `skip_unverified_emails: true` is a single SMTP probe — catch-all / greylisted / stale-MX rows can sneak through. MillionVerifier is the second-layer check Navreo's cold-email pipeline runs on every other source. The cost (1 MV credit per email, flat) is small relative to the bounce-rate hit on a hot inbox.

**Trigger.** Only runs when `brief.enrichment.run_millionverifier_post_prospeo == true`. Default for new briefs created via `lilly-trigify-setup` is `true`. To opt out, set the field to `false` in `~/.claude/skills/lilly-trigify-setup/briefs/<brief_id>.json` once — the daily run reads the config and applies it silently (no per-run prompt to preserve the autonomous cadence).

**Scope.** Only Prospeo-source emails (`enrichment_source == "prospeo"`) get the MV check. Rows where `enrichment_source == "ai_ark"` (the bidirectional NO_MATCH fallback) are exempt — AI Ark's verification is opaque and the row has already been cross-checked against both providers; double-checking adds cost without obvious value.

**Why before Phase 4.** Phase 4 spends LLM tokens generating Icebreaker + HowWeCanHelp per row. Running MV first means we don't pay variable-gen costs on rows that will be dropped for bounce risk.

### 3.5a. Build the MV input CSV

From the QUALIFIED + email-enriched working set, filter to rows where `enrichment_source == "prospeo"` AND the row has a verified email. Write a transient CSV with columns: `email, first_name, last_name, company_name, company_domain, linkedin_url`. Path: `~/.claude/skills/lilly-trigify-data-processing/state/<brief_id>_mv_input_<timestamp>.csv`.

If the filtered set is empty (all enrichments came from AI Ark fallback, or no QUALIFIED rows reached Phase 3), skip Phase 3.5 entirely.

### 3.5b. Delegate to `lilly-email-verification`

Hand off the transient CSV. The verification skill auto-detects this is NOT an AI-ARK source (no `AI Ark People ID` column) and runs MillionVerifier on every row in Stage 1. Stage 2 (find-missing) is a no-op because every row already has an email.

Pass an explicit hint to short-circuit the source-detection prompt:
```
Source: prospeo_dm_finder (skip Stage 2, run MV Stage 1 on all rows)
```

### 3.5c. Apply the MV verdicts back to the working set

Read the output CSV (`<basename>_enriched.csv`) and audit JSON. For each row:

| MV verdict | Action |
|---|---|
| `ok` | Keep. Mark `enrichment_method = "prospeo+millionverifier"`. |
| `catch_all` | Keep. Flag `verification_method = "catch_all"` (downstream can deprioritise). |
| `invalid` / `disposable` / `unknown` / `unverified` | Drop. Mark Status as `OFF_BRIEF_NO_EMAIL_MV_FAILED` in the write-back batch. |

The MV-failed rows are dropped from the Phase 4 + Phase 5 working set so we don't generate variables or push them to Smartlead/HeyReach. They DO get a Status write-back in Phase 6 so the Sheet shows why they were dropped.

### 3.5d. Cost surfacing

Add to the Phase 1 confirmation message the line: `Will pipe N_prospeo Prospeo-verified emails through MillionVerifier (~N_prospeo MV credits) — set brief.enrichment.run_millionverifier_post_prospeo=false to skip.`

---

## Phase 4, Generate per-lead variables (perspective-aware angle waterfall)

### 4a. Fetch the Smartlead campaign email body FIRST (once per run, cached)

Same pattern as `lilly-theirstack-data-processing` Phase 6a. Delegate to `lilly-bot` to fetch the campaign sequence (NEVER call Smartlead API directly):

```
GET /api/v1/campaigns/<smartlead_campaign_id>/sequences
```

Cache the step 1 body for the run. If the user has multiple variants, fetch all and pick the variant designated "primary" in the brief (default: variant A).

If the brief pushes ONLY to HeyReach (no Smartlead campaign), skip this fetch. Use the brief's HeyReach message template instead (TBD: HeyReach message body source needs `brief.outreach.heyreach_message_template_id`, added when needed).

### 4b. Identify variables in the copy

Parse the fetched email body. Extract every `{{merge_variable}}` placeholder:
- Standard Smartlead fields (`{{first_name}}`, `{{last_name}}`, `{{company_name}}`) → auto-populated, skip generation.
- Per-lead variables defined in `brief.personalization.per_lead_variables` → generate per row.
- Variable in copy but NOT in brief config → HALT and tell user to either add it to the brief or remove it from copy.

### 4c. Icebreaker, perspective-aware angle waterfall by post author

**HARD RULE (the single most important rule in this skill).** When `post.author_name != brief.ideation.outreach_voice`, the email body must NEVER reference the post, the post author, the post topic, the engager's comment, or anything that betrays we saw the engagement. The engagement is the LEAD-GENERATION signal (how we found the prospect), NOT the EMAIL-CONTENT signal. Mentioning a competitor founder's post leaks our intel-gathering and burns the relationship.

Only when `post.author_name == brief.ideation.outreach_voice` (the sender's OWN post) is post-referencing allowed.

The waterfall is defined in `brief.personalization.per_lead_variables.icebreaker.angles[]`:

| # | Angle ID | Trigger | Perspective | Output style |
|---|---|---|---|---|
| 1 | `first_person_own_post` | `post.author_name == outreach_voice` | First-person, post-referencing OK | "saw your comment on my post about [topic], your point caught my eye" |
| 2 | `role_anchored_for_founder_post` | `post.author_name` is a tracked competitor founder/employee | Role/company-anchored, NO POST REFERENCE | "your role leading sales at [engager.company] caught my eye, quick question" |
| 3 | `fallback` | always (when angles 1-2 missing fields) | Generic, always fires | "your name came up in some sales-leader circles, wanted to reach out" |

**Allowed anchors for angle 2 (HARD enforced):** `engager.title`, `engager.company`, company size, vertical, function.

**FORBIDDEN anchors for angle 2:** `post.author_name`, `post.content_snippet`, `post.url`, `comment.text`, phrases like "saw you engaged with", "noticed your comment", "your reaction to", "interesting take on", "I saw you liked".

Validate every generated angle-2 icebreaker against the forbidden list before saving. If forbidden text appears, retry once with strict prompting. After second failure, downgrade to angle 3 fallback.

### 4d. HowWeCanHelp, offer-anchored to engager role + company

From `brief.personalization.per_lead_variables.how_we_can_help`:
- Strategy: `offer_anchored_to_engager_role_and_company`
- Anchor: engager's title + company size + the brief's offer language
- HARD RULE: same as 4c, do NOT reference the originating post or the tracked profile that surfaced this engager.

Example output: "for a VP Sales at a 50-emp agency, pay-per-result pricing makes outbound a P&L lever, not a fixed cost, useful when you're scaling sales without burning runway."

### 4e. Prompt template (per-variable, with HARD RULE substitution)

When generating angle 2 or HowWeCanHelp, the LLM prompt MUST include this stanza verbatim:

```
HARD RULE, DO NOT VIOLATE:
- This lead engaged with a post by [post.author_name], a tracked competitor.
- The engagement is the LEAD-GENERATION signal. It is NOT the EMAIL-CONTENT signal.
- Your output must NEVER mention the post, the post author, the post topic, or the engagement.
- Forbidden phrases include: "saw you engaged with", "noticed your comment on", "your reaction to", "your take on [post topic]", "I saw you liked", "your comment on [author]'s post".
- Allowed anchors: engager.title, engager.company, company size, vertical, function.

The output must read as a normal Bjion-to-prospect cold email with NO signal trail.
```

Wrap this stanza around the per-variable generation prompt drawn from `brief.personalization.per_lead_variables.<var>.angles[<chosen>].instructions`.

### 4f. Cold Email Video Angle (if present)

If the brief's copy uses `{{Cold Email Video Angle}}`, generate it via `lilly-personalisation` and ensure the angle references the prospect's TITLE not just the company (per `feedback_cold_email_angle_title_relevance`).

---

## Phase 5, Push to outreach channels (Smartlead and/or HeyReach)

### 5a. Determine destinations

Read `brief.outreach.channels` (added to brief config schema by this skill):
- `["smartlead"]` → Phase 5b only
- `["heyreach"]` → Phase 5c only
- `["smartlead", "heyreach"]` or `"both"` → Both, parallel

Add `brief.infrastructure.heyreach_list_id` field to the brief config schema (currently absent in `lilly-trigify-setup/briefs/*.json`). If missing on a brief targeting `heyreach`, halt that brief and surface to user.

### 5b. Smartlead push (delegate to lilly-bot, mandatory)

ALL Smartlead operations go through `lilly-bot`. Never call Smartlead API directly. Pattern is identical to `lilly-theirstack-data-processing` Phase 7.

Hand off to `lilly-bot` with:
- `campaign_id`: `brief.infrastructure.smartlead_campaign_id`
- `leads`: array of records with standard fields + custom fields under `custom_fields`

Standard Smartlead lead fields:
- `first_name`, `last_name`, `email`, `phone_number` (rare on Trigify rows)
- `company_name` (from engager.company)
- `website` (from engager.company_website)
- `location` (from engager.country UI label)
- `linkedin_profile` (from engager.linkedin_url)

Custom fields:
- `Icebreaker` (Phase 4c output)
- `HowWeCanHelp` (Phase 4d output)
- Any other variable in the brief's `personalization.per_lead_variables`

After Smartlead confirms success per lead, write to state: `state.processed_engagers += [{linkedin_url, status: "PUSHED_SMARTLEAD", pushed_at, smartlead_lead_id}]`.

### 5c. HeyReach push (via HeyReach MCP)

If HeyReach MCP is installed, call `add_leads_to_list_v2` with:
- `list_id`: `brief.infrastructure.heyreach_list_id`
- Leads: array of `{linkedin_url, first_name, last_name, email, company, custom_fields: {Icebreaker, HowWeCanHelp, ...}}`

If HeyReach MCP is NOT installed, halt the HeyReach push and tell the user how to install it.

Track per-lead success/failure. State: `state.processed_engagers += [{linkedin_url, status: "PUSHED_HEYREACH", pushed_at, heyreach_lead_id}]`.

### 5d. DRY-RUN approval on first run per brief

**MANDATORY:** the very first run on a new brief MUST render the full email body (or HeyReach message) inline in chat for every push-eligible lead, BEFORE any Smartlead/HeyReach API call fires. Mirror Phase 5.7d from `lilly-trigify-setup`.

Format per lead:

```
Lead N, Jane Doe, VP Sales @ Acme Co (jane@acme.com)

| Variable | Resolved value | Source |
|---|---|---|
| {{first_name}} | Jane | engager.first_name |
| {{company_name}} | Acme Co | engager.company (normalized) |
| {{Icebreaker}} | "your role leading sales at Acme caught my eye, quick question" | Angle 2 fired (role_anchored, founder-post HARD RULE applied) |
| {{HowWeCanHelp}} | "..." | offer_anchored_to_role_and_company |

Email 1, subject: "[rendered]"

[fully rendered body]
```

Wait for `"approve and push"` before firing. Surface this requirement only on first runs; subsequent runs trust the brief's locked-in copy. The state file tracks `state.first_dryrun_approved_at` (null until user approves once).

---

## Phase 6, Sheet Status write-back

Drive MCP has no `update_cell` tool. Two viable paths:

### Path A (DEFAULT), Make sidecar scenario

**One-time setup** (run during this skill's first invocation per workspace):
1. Create a new Make scenario named `Trigify Status Writeback Sidecar` (or one per brief if user prefers isolation).
2. Trigger module: Webhook → `Custom webhook` (instant). Capture the webhook URL.
3. Add an Iterator module to walk the `rows` array from the webhook payload.
4. Add Google Sheets `Search Rows` to find the matching row by `LinkedIn URL` column.
5. Add Google Sheets `Update Row` to write the new Status to column Q.
6. Activate the scenario.
7. Save the webhook URL to `~/.claude/skills/lilly-trigify-data-processing/.status-writeback-webhook` and per-brief to `brief.infrastructure.status_writeback_webhook_url`.

The scenario reuses the existing Google connection id `9696598`. Team id `536258`. Org id `1634255`.

**Per-run usage:**

POST to the webhook a JSON batch:
```json
{
  "sheet_id": "<brief.infrastructure.sheet_id>",
  "rows": [
    {"linkedin_url": "https://www.linkedin.com/in/jane-doe", "new_status": "PUSHED"},
    {"linkedin_url": "...", "new_status": "OFF_BRIEF"},
    {"linkedin_url": "...", "new_status": "BORDERLINE"},
    {"linkedin_url": "...", "new_status": "OFF_BRIEF_NO_EMAIL"}
  ]
}
```

After POST returns HTTP 200, call `mcp__702eb79f-...__scenarios_run` against the sidecar's scenario id to fire it immediately (same polling-mode workaround as `lilly-theirstack-data-processing` Phase 4). Verify the run status returned SUCCESS before considering write-back complete.

**Cost:** ~1 Make op per status update. For a 100-row daily batch, ~100 ops. Within Make Core plan's 10K ops/month budget.

### Path B (FALLBACK), Apps Script paste

If Make ops are tight or the user explicitly opts out of the sidecar, emit a generated Apps Script that the user pastes ONCE into the Sheet's Extensions > Apps Script editor. The script polls a small JSON endpoint (or accepts inline arrays) and updates rows.

```javascript
function updateStatuses() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName("Engagers");
  const data = sheet.getDataRange().getValues();
  const headerRow = data[0];
  const linkedinCol = headerRow.indexOf("LinkedIn URL");
  const statusCol = headerRow.indexOf("Status");

  // PASTE BELOW: array of {linkedin_url, new_status} produced by lilly-trigify-data-processing
  const updates = [
    {"linkedin_url": "https://www.linkedin.com/in/jane-doe", "new_status": "PUSHED"},
    // ...
  ];

  const urlToStatus = {};
  updates.forEach(u => { urlToStatus[u.linkedin_url] = u.new_status; });

  for (let i = 1; i < data.length; i++) {
    const url = data[i][linkedinCol];
    if (urlToStatus[url]) {
      sheet.getRange(i + 1, statusCol + 1).setValue(urlToStatus[url]);
    }
  }
}
```

Surface the generated script with the updates array pre-filled, plus the run instruction: `open Sheet > Extensions > Apps Script > paste > save > run updateStatuses`. Slower iteration (~1 click per daily run) but no Make infrastructure required.

### 6c. Default path

DEFAULT is Path A (Make sidecar) once the user has run this skill at least once with the user-confirmed `setup-status-writeback` step. On runs before sidecar setup, fall through to Path B and prompt the user to consider standing up the sidecar (~5 min one-time cost).

---

## Phase 7, End-of-run summary

Surface to user:

```
Trigify run complete (2026-05-18 09:15).

Brief: Navreo, Competitor Founder Engagers
  Engagers in Sheet:          247 total
  Already processed (skip):   119
  NEW this run:               128
    Qualified:                  3
    Borderline:                15  -> queued for your next-run verdict
    Off-brief:                110  -> Status marked OFF_BRIEF
  Enriched (Prospeo):           3 verified emails
    Prospeo hits:                2
    AI Ark fallback hits:        1
    NO_VERIFIED_EMAIL:           0
  Pushed to Smartlead:          3   campaign 12345
  Pushed to HeyReach:           3   list 67890

Per-tracked-profile precision (qualified / total):
  Bjion Henry              (own post):   1 / 4   =  25%
  Kenny Damian      (competitor):        0 / 18  =   0%
  Sacha Martinot    (competitor):        2 / 31  =   6%
  Manthan (Leadgen) (competitor):        0 / 22  =   0%
  ...

Suggested negative title patterns (extracted from today's OFF_BRIEF title-fails):
  - "Account Manager"          (caught 4 off-brief rows today, already on competitor-tier exclusion)
  - "Customer Success Manager" (caught 3, consider adding to qualification.disqualified_engager_title_patterns)
  - "Software Engineer"        (caught 2, wrong-function technical IC)
  - "Operations Associate"     (caught 1, junior tier)
  - "Creative Director"        (caught 1, wrong function)

Suggested geography drift:
  - 22 OFF_BRIEF rows in India, 6 in Spain, 4 in Nigeria. If Trigify search-level location filter is set, verify it; otherwise these are expected leakage from competitor audiences in non-target geos.

Suggested company-avoid additions:
  - "Solo consultant" cluster caught 4 rows (already on avoid list).
  - "Adjacent competitor" cluster caught 3 rows that ARE on avoid list, verify the actual company names against your current avoid list and refine.

Next run: borderlines from this run will appear first for your verdict.
```

Append the suggestions to `~/.claude/skills/lilly-trigify-data-processing/queue/<brief_id>.json` under `negative_title_history[]` so future runs can detect stale (repeated) suggestions.

---

## Cloud upload (mandatory)

Every run's new-lead batch (the qualified engagers pushed to Smartlead/HeyReach in Phase 5) MUST also be uploaded to the central Supabase list store before the run ends — a batch that only lives in this machine's state file isn't done. Write the batch to a CSV and run:

`python3 ~/.claude/skills/_shared/list_upload.py <final.csv> --name "<descriptive list name>" --client "<Client>" [--folder "<Theme>"] --source-skill lilly-trigify-data-processing --brief "<one-line brief>" --owner "<who asked>"`

Then show the returned `https://navreo-signals.onrender.com/app/lists.html#<id>` link to the user as part of the Phase 7 end-of-run summary, alongside the Smartlead/HeyReach push confirmation.

Folder rules: `--client` = the client named in the brief (internal/Navreo pulls → `Navreo`); add `--folder` ONLY when the brief names a campaign theme or segment (e.g. client `Amplifyy`, folder `Beauty`); never deeper than two levels. Re-runs with the same name+client replace that list's rows in place (safe).

---

## State file schema

`~/.claude/skills/lilly-trigify-data-processing/state/<brief_id>.json`:

```json
{
  "brief_id": "navreo-competitor-founder-engagers",
  "last_run_at": "2026-05-18T09:15:00Z",
  "first_dryrun_approved_at": "2026-05-17T11:00:00Z",
  "processed_engagers": [
    {
      "linkedin_url": "https://www.linkedin.com/in/jane-doe",
      "status": "PUSHED_SMARTLEAD",
      "verdict": "QUALIFIED",
      "pushed_at": "2026-05-18T09:14:31Z",
      "smartlead_lead_id": "abc-123",
      "heyreach_lead_id": null,
      "enrichment_source": "prospeo",
      "post_author": "Bjion Henry"
    }
  ],
  "stats": {
    "total_runs": 3,
    "total_engagers_processed": 247,
    "total_qualified": 8,
    "total_pushed_smartlead": 8,
    "total_pushed_heyreach": 0
  }
}
```

State files are LOCAL and not cloud-synced. If the user moves machines, state must be transferred manually, OR they accept that re-runs will resurface already-processed rows (Smartlead's email dedup catches most of it; HeyReach also dedups on linkedin_url).

---

## Queue file schema

`~/.claude/skills/lilly-trigify-data-processing/queue/<brief_id>.json`:

```json
{
  "brief_id": "navreo-competitor-founder-engagers",
  "pending_confirmations": [
    {
      "added_at": "2026-05-17T17:00:00Z",
      "row_data": {<full 17-col Engagers row>},
      "verdict": "BORDERLINE",
      "reason": "title='GTM Engineer' | co=Unknown, likely content services",
      "user_decision": null
    }
  ],
  "negative_title_history": [
    {
      "suggested_at": "2026-05-17T17:00:00Z",
      "suggestions": [
        {"pattern": "Account Manager", "off_brief_rows_caught": 4, "applied_by_user": null},
        {"pattern": "Customer Success Manager", "off_brief_rows_caught": 3, "applied_by_user": null}
      ]
    }
  ]
}
```

If the same negative-title pattern keeps catching new OFF_BRIEF rows across 3+ runs and the user hasn't applied it, escalate in Phase 7: `WARN: pattern X has been suggested 3 times and the same titles keep coming through, please add it to brief.qualification.disqualified_engager_title_patterns`.

---

## Cache writes (per lilly-tam convention)

All cacheable API responses land in `~/.navreo-cache/<provider>/<endpoint>/<hash>.json`:
- `prospeo/enrich-person/<linkedin_url_hash>.json`
- `prospeo/search-person/<query_hash>.json` (unused by this skill but reserved)
- `ai_ark/enrich-person/<linkedin_url_hash>.json`

Cache hits are 0 credits. Pre-flight every enrichment call against the cache first. Mirror the cache conventions from `lilly-tam` and `lilly-icebreaker`.

---

## Guardrails (anti-patterns codified)

1. **NEVER mention competitor founder posts in email copy.** This is the HARD RULE from `brief.personalization._HARD_RULE`. Mentioning a competitor's post burns the relationship and signals intel-gathering. Only the sender's own posts may be referenced directly. Enforced via the forbidden-phrase validator in Phase 4c.

2. **NEVER push to outreach channels on a new brief without dry-run approval first.** First-run-per-brief MUST render full emails inline in chat before any Smartlead/HeyReach call fires. Mirrors `lilly-trigify-setup` Phase 5.7d. Tracked via `state.first_dryrun_approved_at`.

3. **NEVER enrich BORDERLINE rows until user verdicts them.** Prospeo credits aren't free. Surface borderlines first, wait for explicit `y`, then enrich.

4. **Comments-only by default; max=25 throttle.** Codified in the live brief (`engagement_types: ["comment"]`, `workflow_per_post_max_engagers: 25`). Don't widen to likes+comments without the user opting in explicitly, earlier likes+comments runs at maxLikes=100 caused a Make ops blast (~10K ops in hours) and Google Sheets 429s.

5. **No em-dashes anywhere.** Navreo style rule. Use commas, colons, periods, parentheses. Hyphens and arrows fine. Lint generated copy before saving.

6. **ALL Smartlead operations through lilly-bot.** No direct Smartlead API calls from this skill or any sub-step. Same rule as `lilly-theirstack-data-processing`.

7. **Domain-match drop on enriched emails.** If the verified email host doesn't match the engager's company website host, drop the lead. Cross-contamination from cached job-history is real. Borrowed from `lilly-tam`.

8. **State file is authoritative.** Don't read Sheet's Status column as the dedup mechanism. Status is for human visibility; state file is for idempotency.

9. **Each brief processes independently.** If one brief fails (Sheet permissions, Smartlead campaign down), other briefs continue. Errors surfaced at end-of-run.

10. **Skip briefs missing infrastructure.** If `smartlead_campaign_id == null` AND `heyreach_list_id == null`, skip the brief with a one-line notice.

11. **Use "Decision Makers" not "DMs" in deliverables.** This skill doesn't surface decision-maker terminology often (engager IS the lead), but if it does (e.g. cross-references in the run summary), use the full phrase.

12. **Phone numbers: prepend apostrophe.** Same Sheets-formula gotcha as `lilly-theirstack-data-processing`. Trigify rows rarely contain phones, but if they do, `+1-555-...` evaluates to a negative number in Sheets without the leading apostrophe.

13. **LLM-first company classification.** When the company-gate (2d) needs to judge a company, use training knowledge first. Only WebFetch a website when genuinely uncertain. Per `feedback_company_classification_llm_first`.

14. **Trigify-supplied fields ALWAYS come before external lookups.** The v2 32-column schema already captures Country, Company Industry, Company Description, Company HeadCount, Open To Work, LinkedIn Headline, Job Title, plus the full Post Text. Every gate (2a-2d) reads these columns directly. Never re-fetch from Prospeo / AI Ark / WebFetch just because it "feels safer" — Trigify's `person_enrichment` step runs the same lookup at row-write time and is already paid for. The ONLY external call this skill makes per row is Prospeo `/enrich-person` for the verified EMAIL (which Trigify doesn't supply). WebFetch is fallback ONLY when company industry + description together are insufficient to verdict (step 4 of the engager-company gate decision ladder) — typically ~5% of rows.

---

## Cost calibration

| Item | Cost | Notes |
|---|---|---|
| Prospeo `enrich-person` | 1 credit per match (0 on NO_MATCH) | Cache hits free |
| AI Ark `enrich_profile` fallback | Per-tier (typically 0.5-1 credit per match) | Only fires on Prospeo NO_MATCH; cache hits free |
| Smartlead lead add via lilly-bot | Free (Smartlead doesn't charge per lead) | Custom-field-creation flow handled by lilly-bot |
| HeyReach `add_leads_to_list_v2` | Free (HeyReach doesn't charge per lead) | Per-account caps still apply on outbound sends |
| Make sidecar `Update Status` op | 1 op per status write | ~100 ops per typical daily batch; well within Core plan budget |
| LLM tokens per row (gates 2b-2c-2d) | ~500 input + 50 output | Cheap; mostly classification |
| LLM tokens per per-lead variable | ~1000 input + 100 output | Two variables (Icebreaker + HowWeCanHelp) per QUALIFIED row |

For a typical 128-row daily batch with ~3-5 QUALIFIED:
- Prospeo: 3-5 credits
- AI Ark: 1-2 fallback hits, similar credit cost
- LLM: ~50 classification calls + ~10 variable-generation calls
- Make ops: ~128 status writes
- Total daily cost: well under $1, dominated by Make ops if the user is on a tight plan

---

## Key reference values (Navreo)

- Brief configs path: `~/.claude/skills/lilly-trigify-setup/briefs/`
- State files path: `~/.claude/skills/lilly-trigify-data-processing/state/`
- Queue files path: `~/.claude/skills/lilly-trigify-data-processing/queue/`
- Drive MCP for Sheet reads: `mcp__91841cbc-1fd8-4bfb-87c2-ab05b0e0981b__read_file_content`
- Make MCP scenario-run: `mcp__702eb79f-3fb6-46d4-80ad-3c3df1b23c60__scenarios_run`
- Make Team id: 536258, Org id: 1634255, Google connection id: 9696598
- Prospeo / AI Ark / Smartlead keys: `~/.navreo-keys.env`

---

## Linked skills

- **Prerequisite:** `lilly-trigify-setup` (creates the brief, Sheet, Workflows, Make scenario, Smartlead campaign this skill consumes)
- **Called per run:** `lilly-bot` for ALL Smartlead operations (mandatory)
- **Optional per run:** `lilly-personalisation` if the brief's copy uses additional variables beyond Icebreaker + HowWeCanHelp (e.g. Why, CaseStudy)
- **NOT called per run:** `lilly-tam`, engager IS the lead, no DM-finder phase. Don't accidentally inject it.

---

## Failure modes + recovery

| Failure | Recovery |
|---|---|
| Brief config missing required fields | Skip brief, surface specific field |
| Sheet read fails (permissions) | Surface; user re-shares Sheet |
| Engagers tab is empty | Skip brief with "no new rows" notice |
| Prospeo returns 0 emails for entire qualified set | Surface; expect AI Ark fallback to recover; if both fail, halt brief's Phase 4 |
| LLM generates icebreaker that violates the HARD RULE (post reference) | Retry once with strict prompt; on second failure downgrade to fallback angle |
| Smartlead lead push fails (missing custom field) | Halt brief's Phase 5b; surface error; user adds field via `/lilly-bot` |
| HeyReach MCP not installed but brief targets HeyReach | Halt that channel; tell user how to install |
| Status write-back webhook returns non-200 | Surface; user checks sidecar scenario; state file already updated so next run still works |
| State file corrupted | Surface; user manually clears state OR skill re-initialises with empty state (re-runs will resurface leads but Smartlead/HeyReach dedup on email/linkedin_url catches duplicates) |

---

## Open questions / punted decisions

1. **HeyReach message template source.** The brief config currently has no `outreach.heyreach_message_template_id` field. Personalised LinkedIn messages need a template id and field mapping. Punted: add when the first brief targets HeyReach. Default behaviour: skip HeyReach push and tell the user to add the template id.
2. **Multi-tracked-profile dedup.** When the same engager engages on multiple tracked profiles' posts in the same day, current logic prefers the own-post author, then most-recent. Open: should we generate two leads (one per post-author angle) for richer A/B? Punted: single-lead default; user can override per brief.
3. **Comment-text extraction for first-person angles.** Trigify's `Comment Text` column is the prospect's literal words. When `post.author_name == outreach_voice`, we can quote that comment back at them. Codified but the prompt needs hardening with concrete one-shots.
4. **HARD-RULE validator on HowWeCanHelp.** Same forbidden-phrase list as Icebreaker angle 2 should run on every HowWeCanHelp output. Easy add; codified in Phase 4e but the validator code lives wherever the LLM gateway is, confirm with user on first run.
5. **Sidecar scenario create-on-first-run.** The skill can either prompt the user to stand up the sidecar manually (5-min one-time UI work) OR provision it programmatically via Make MCP `scenarios_create` + `hooks_create`. Default = manual prompt for transparency; programmatic provisioning available if the user prefers (extra ~30 lines of orchestration).


## Upload gate (MANDATORY)

Before ANY lead push into a Smartlead campaign that results from this skill (`add_leads_to_campaign` or equivalent), hand off to `lilly-upload-gate` and let it run to a green gate: every enabled check PASS or explicitly OVERRIDDEN per-flag, and the audit row written to `list_upload_qa_runs` BEFORE the first add-leads call. Never upload around the gate.
