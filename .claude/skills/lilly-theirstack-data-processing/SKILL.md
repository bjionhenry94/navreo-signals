---
name: lilly-theirstack-data-processing
description: "Daily orchestrator for TheirStack hiring-signal pipelines. Reads brief configs provisioned by lilly-theirstack-setup, processes new jobs and decision makers per brief: (1) reads the Jobs tab of each brief's Sheet, identifies new rows not yet processed (via local state file), (2) runs DM enrichment via lilly-tam (Prospeo primary, AI Ark fallback) on each new company, (3) writes enriched DMs to the brief's Decision-Makers tab via the DMs webhook, (4) reads the Decision-Makers tab for new DMs, (5) generates per-lead {{HowWeCanHelp}} personalization anchored to the originating job posting (uses brief's offer + signal rationale), (6) pushes DMs to the brief's Smartlead campaign as leads with merge variables filled, (7) updates state file so next run skips processed rows. Idempotent — safe to re-run any number of times. Use whenever the user wants to: process new jobs in their TheirStack pipeline, enrich new leads, push DMs to Smartlead, run the daily routine, advance the pipeline from new-jobs to Smartlead-ready leads, or check what's queued for processing. Trigger phrases: 'process today's TheirStack leads', 'run the TheirStack pipeline', 'enrich new jobs', 'push new DMs to Smartlead', 'run the daily routine', 'process the pipeline', 'what's queued', 'enrich the new TheirStack rows', 'theirstack daily'. Does NOT create new briefs or saved searches — that's lilly-theirstack-setup. Reads brief configs from ~/.claude/skills/lilly-theirstack-setup/briefs/*.json. Writes state to ~/.claude/skills/lilly-theirstack-data-processing/state/<brief_id>.json."
---

# Lilly TheirStack Data Processing

## Purpose

Daily orchestrator that turns TheirStack-pushed Jobs rows into Smartlead-ready leads with personalised merge variables. Runs when the user invokes it (no schedule — user-gated step) and processes whatever has accumulated since last run.

This skill is the user-facing counterpart to the autonomous `lilly-theirstack-setup` pipeline. The autonomous half (TheirStack → Sheet's Jobs tab) runs without the user. This skill bridges Jobs tab → Decision-Makers tab → Smartlead campaign.

## When to Use

Trigger when the user wants to:
- Process today's new TheirStack jobs into Smartlead leads
- Enrich new jobs with decision-maker contacts
- Push fresh DMs to Smartlead with personalisation
- Run the "daily routine" / advance the pipeline
- Check what's queued (rows in NEW status across briefs)

Skip / don't trigger when:
- The user wants to create a NEW brief / saved search → use `lilly-theirstack-setup`
- The user wants to QA an existing Smartlead campaign → use `lilly-qa`
- The user wants pure DM finding without the TheirStack pipeline → use `lilly-tam` directly

## Prerequisites

The user must have already run `lilly-theirstack-setup` for at least one brief, which produces:
- A brief config file at `~/.claude/skills/lilly-theirstack-setup/briefs/<brief_id>.json`
- A per-brief Google Sheet with Jobs + Decision-Makers tabs populated by TheirStack/Make
- A Smartlead campaign skeleton (or campaign_id available for binding)

This skill consumes those — never modifies brief configs or recreates infrastructure.

## Architecture

```
lilly-theirstack-data-processing (this skill — daily orchestrator)
   │
   ├── For each brief config in ~/.claude/skills/lilly-theirstack-setup/briefs/*.json:
   │
   ├── Phase 1: Load brief config + state file
   │
   ├── Phase 2: Read brief's Sheet → Jobs tab → identify NEW rows
   │       (NEW = job_url not in state.processed_jobs)
   │
   ├── Phase 2.5: Role qualification pass (LLM-classify each new row)
   │       → QUALIFIED  → goes into enrich queue
   │       → BORDERLINE → enqueue for user confirmation, defer
   │       → OFF_BRIEF  → skip, log for negative-keyword suggestions
   │
   ├── Phase 2.75: Suppression + already-contacted gate (MANDATORY)
   │       → drops domains matching navreo_db.check_exclusions() or contact_history
   │       → unattended-safe: an unavailable check drops nothing, just warns
   │
   ├── Phase 3: For each QUALIFIED, non-suppressed, non-contacted company → call lilly-tam
   │       (per-brief dm_finder.target_titles + max_dms_per_company)
   │
   ├── Phase 4: POST DMs batch to brief's dms_webhook_url
   │       → writes rows to Decision-Makers tab with Status=NEW
   │       → mark each job's URL in state.processed_jobs
   │
   ├── Phase 5: Read Sheet → Decision-Makers tab → identify NEW DMs
   │       (NEW = email not in state.processed_dms)
   │
   ├── Phase 6: For each NEW DM → LLM generates {{HowWeCanHelp}}
   │       Input: brief.ideation.offer + brief.ideation.why_signal_fits_angles
   │             + DM's joined job context (hiring_for, tech_stack, job_posting)
   │
   ├── Phase 7: Push DM to Smartlead campaign as a lead
   │       Custom fields: HowWeCanHelp + brief.personalization.* mapping
   │       Standard fields: first_name, last_name, email, company_name, etc.
   │
   ├── Phase 8: Persist state file
   │       state.processed_jobs += newly-processed job URLs
   │       state.processed_dms += newly-pushed DM emails
   │       state.last_run_at = now
   │
   └── Phase 8.5: Suggest negative keywords (analyse OFF_BRIEF set,
           propose UI saved-search refinements to the user)
```

Each phase is idempotent. Re-running the skill is safe — already-processed rows skip.

## Phase 1 — Load brief config + state

For each `~/.claude/skills/lilly-theirstack-setup/briefs/*.json` file:
- Skip if `infrastructure.smartlead_campaign_id` is null (brief still pending Smartlead campaign creation)
- Skip if `theirstack_saved_search.created_in_ui_at` is null (saved search not live)
- Load state from `~/.claude/skills/lilly-theirstack-data-processing/state/<brief_id>.json`
  - If state file doesn't exist, initialise empty: `{"brief_id": "...", "processed_jobs": [], "processed_dms": [], "last_run_at": null}`

Confirm with user before processing: list each brief that will run, with counts of new rows pending (queue size in Jobs tab) and approximate Prospeo/Smartlead cost.

## Phase 2 — Read Jobs tab + identify new rows

**Read the COMPLETE Jobs tab. NEVER use `read_file_content` for these sheets.** Each sheet holds two tabs (Decision-Makers is the FIRST tab, Jobs is SECOND) and grows to hundreds of rows. `read_file_content` renders Decision-Makers first and caps its output at ~107K chars, so on a real sheet it never reaches the newest Jobs rows. That is the exact failure that made the daily run report "0 new jobs" while jobs kept landing (SDR: it surfaced 165 of 797 real rows). Use the full-workbook download + parser instead:

1. Call Drive MCP `download_file_content` with:
   - `fileId = brief.infrastructure.sheet_id`
   - `exportMimeType = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"`
   The result overflows and the harness saves it to a file (schema `{"content": "<base64 xlsx>", "id", "mimeType", "title"}`). Note the saved file path it prints. (If it returns `Resource has been exhausted / quota`, wait ~30s and retry: it is a transient Drive export limit.)
2. Run the parser (reads the named tab in full via openpyxl, dedups against state, writes new rows to `--out`):
   ```
   python3 ~/.claude/skills/lilly-theirstack-data-processing/scripts/parse_theirstack_sheet.py \
     "<saved_download_path>" Jobs "<state_path>" --out /tmp/theirstack/<brief_id>_new_jobs.json
   ```
   stdout is a compact summary: `total_data_rows`, `already_in_state`, `new_count`, `unique_new_companies`, date span, sample rows.
3. Load `/tmp/theirstack/<brief_id>_new_jobs.json` for the new-jobs working set (one object per row, keyed by column header). Each row is new iff its `Job Posting` URL is not already in `state.processed_jobs` (the parser has already applied this, URL-normalised). Never rely on the stdout sample list, and never re-introduce `read_file_content`.

### 2.0 Backlog safety: newest-first, staleness skip, per-run cap

The Jobs tab can hold a large unprocessed backlog (especially the first run after this read fix lands, when 600+ rows suddenly become visible). To bound spend and keep signals fresh, BEFORE qualification:

1. **Sort** the new-jobs set newest-first by `Date Pulled`.
2. **Staleness skip:** any new job whose `Date Pulled` is older than `MAX_JOB_AGE_DAYS` (default **21**) is NOT enriched. Add its `Job Posting` URL to `state.processed_jobs` (so it never recounts) and tally it as `skipped_stale`. Rationale: a 3+ week-old hiring post is a weak signal and the role may already be filled.
3. **Per-run cap:** from the remaining fresh jobs, take only the newest `ENRICH_CAP_PER_RUN` (default **60**) unique companies this run. The rest stay unprocessed (NOT added to state) and are picked up, still newest-first, on subsequent runs, so a large backlog drains over several days instead of firing one massive Prospeo/Smartlead spend.
4. Surface: `"<brief>: N new jobs → enriching A newest (cap), skipped B stale (>21d), C remaining for future runs."`

Both limits are overridable per brief via `brief.infrastructure.max_job_age_days` and `brief.infrastructure.enrich_cap_per_run` when present.

**Dedup by company domain within this run** — if the same domain appears in multiple new job rows, keep only the first (most recent by Date Pulled). The Status column on the second-occurrence rows can stay NEW; they'll just be skipped on next run because their job_url is added to state alongside the dedup-winner.

Surface to user: `"Found N new jobs across M unique companies for brief <brief_name>."` Move to Phase 2.5 — qualification — before paying for DM enrichment.

## Phase 2.5 — Role qualification pass

**Purpose.** TheirStack's `job_title_or` is a coarse string match — it catches roles that share keywords with the signal but don't actually signal "building a GTM system". The qualification gate adds judgement: classify each new Jobs row by **role only**. Companies are **NEVER** excluded by this gate — only specific roles. A company hiring an intern today is still a fine prospect for a different brief tomorrow.

### 2.5a. Pending borderlines from prior runs (handle FIRST)

Before classifying new rows, check the brief's queue file at `~/.claude/skills/lilly-theirstack-data-processing/queue/<brief_id>.json` for any `pending_confirmations` from earlier runs.

If pending items exist, surface them to the user at the very start of the run:

```
You have N borderline rows pending from previous runs. Resolve before we process today's new batch:

1. CPM Educational Program — RevOps Specialist at 90-emp edtech nonprofit (added 2026-05-13). [y/n]?
2. ...

(Reply "y all" / "n all" / a comma-separated mix like "y, n, y")
```

Apply user responses:
- `y` → move row into the run's `qualified` set (will be enriched in Phase 3 with today's batch)
- `n` → move row into the run's `off_brief` set with reason `user rejected (borderline review)`; add job_url to `state.processed_jobs` so it never reappears

### 2.5b. LLM-classify each new Jobs row from Phase 2

For each row, run LLM classification against `brief.qualification`. Inputs to LLM:
- `Job Title`
- `Seniority`
- `Company`
- `Company Size`
- `Tech Stack`
- `Country`

Prompt the LLM with the brief's `qualification.role_signal_definition`, `qualified_role_patterns`, `disqualified_role_patterns`, and `borderline_role_patterns`. Ask for one of three verdicts plus a one-sentence reason:

- `QUALIFIED` — clear match against qualified_role_patterns
- `BORDERLINE` — partial match, or matches a borderline_role_pattern
- `OFF_BRIEF` — clear match against disqualified_role_patterns

### 2.5c. Route by verdict

| Verdict | Action |
|---|---|
| `QUALIFIED` | Add to `qualified` set → goes to Phase 3 enrichment |
| `BORDERLINE` | Append to queue file's `pending_confirmations[]` with `{added_at, row_data, reason, user_decision: null}`. NOT enriched this run. Surface to user at start of NEXT run (or at end of THIS run if user wants to resolve now). |
| `OFF_BRIEF` | Append to run's `off_brief` set with `{job_title, company, reason}`. Add job_url to `state.processed_jobs` so the row never re-classifies. Used by Phase 8.5 to suggest negative keywords. |

### 2.5d. Surface the classification result

Show the user a table before paying for enrichment:

```
Qualification pass: 21 new rows → 9 qualified, 2 borderline, 10 off-brief.

✅ Qualified (will enrich):
  • Osmind — Senior RevOps Manager (70 emp)
  • Sift — AI Automation Engineer GTM (82 emp)
  • ... [show all 9]

⚠️ Borderline (queued for your yes/no — defer to next run, or resolve now):
  • CPM Educational Program — RevOps Specialist (90 emp, edtech nonprofit)
  • Bluefin Payment Systems — Marketing Ops Manager (CN office, role-qualified but off-geo)

❌ Off-brief (skipped, never re-classified):
  • Mackintosh — Wholesale Sales & Ops Executive (wholesale apparel ops role)
  • Kahuna — Sales Operations Intern (intern level)
  • Ramp — Senior Software Engineer | GTM Platform (internal product engineer)
  • ... [show all 10 with one-line reason each]
```

Wait for user confirmation before Phase 3. Default action: enrich the `qualified` set.

## Phase 2.75 — Suppression + already-contacted gate (MANDATORY, before any DM-enrichment spend)

A cost audit found ~30% of DM-enrichment credits going to companies already contacted or on an exclusion list, because nothing gated the `qualified` set before it was handed to `lilly-tam`. This phase runs after Phase 2.5's qualification and BEFORE Phase 3 fires, filtering the qualified domain set so the DM finder never even sees suppressed / already-contacted companies.

**This is a daily unattended pipeline — the gate must be unattended-safe.** Never silently drop a domain because the check couldn't run; only drop domains the check positively confirms as excluded or contacted.

1. **Exclusion check:** `navreo_db.check_exclusions(client_id, domains=[unique domains from qualified set])` (helper at `~/.claude/skills/_shared/navreo_db.py`).
   - If it returns a list, collect `matched_domain` values into a drop set.
   - **If it returns `None` (Supabase unreachable):** do NOT drop anything on this check. Log a warning line into the run summary — `"⚠️ Exclusion check unavailable this run (Supabase unreachable) — proceeded WITHOUT suppression filtering for N domains."` — and continue. An unattended run must never silently skip real leads because a dependency was briefly down, and it must never silently drop leads it couldn't actually verify as excluded either.
2. **Already-contacted check:** query `contact_history` for `company_domain` matches, batched ~100 domains per call:
   ```python
   for batch in chunks(qualified_domains, 100):
       navreo_db.rest(
           "GET", "/rest/v1/contact_history",
           params={"select": "company_domain", "company_domain": f"in.({','.join(batch)})"}
       )
   ```
   Collect distinct `company_domain` matches into a second drop set. This call uses `rest()` directly (not `check_exclusions`), so it has no "unavailable" ambiguity — if the REST call fails, treat it the same as the Supabase-unreachable case above: log a warning, drop nothing from this check, continue.
3. **Drop both sets from the `qualified` domain set before Phase 3.** Dedupe domains that land in both sets when counting.
4. **Report in the run summary (same place Phase 2.5d reports qualification):**
   > `"Suppression + contact-history check: {N} suppressed, {M} already contacted, {K} proceeding to DM enrichment."`

Only the surviving `{K}` domains' companies are passed into Phase 3.

## Phase 3 — DM enrichment via lilly-tam

Invoke `lilly-tam` skill with args:
- Domains: list of unique domains from Phase 2.75's gated set (post-qualification AND post-suppression/contact filtering — NOT all new jobs, NOT the raw Phase 2.5 `qualified` set)
- Target titles: `brief.dm_finder.target_titles`
- Max DMs per company: `brief.dm_finder.max_dms_per_company` (default 3)
- Country: derived from job rows' Country column (typically a mix; pass as inferred filter)
- Verified emails only: true
- Phone enrichment: false (default; can be overridden per-brief in future)

Receive: CSV/list of enriched DMs per company with `first_name`, `last_name`, `title`, `email`, `linkedin_url`, `phone`, `source` (prospeo or ai_ark).

For each DM, **join the originating job context** from the Phase 2 row:
- company, website, country, company_size (from Jobs row)
- hiring_for = Jobs row's Job Title
- tech_stack, remote, job_posting, open_roles (from Jobs row)
- date_added = today

## Phase 4 — POST DMs batch to dms_webhook_url

Group DMs into ONE batch per brief and POST to `brief.infrastructure.dms_webhook_url`:

```json
{
  "rows": [
    {
      "first_name": "...",
      "last_name": "...",
      "email": "...",
      "title": "...",
      "linkedin": "...",
      "phone": "'+1-555-000-0000",   // NOTE: leading apostrophe to prevent Sheets formula interpretation
      "company": "...",
      "website": "...",
      "country": "...",
      "company_size": "...",
      "hiring_for": "...",
      "tech_stack": "...",
      "remote": "...",
      "job_posting": "...",
      "open_roles": "...",
      "date_added": "2026-05-13",
      "source": "prospeo"
    },
    ...
  ]
}
```

**Phone number gotcha:** Make's `valueInputOption: USER_ENTERED` causes Google Sheets to interpret phone numbers starting with `+` as math formulas (e.g. `+1-555-000-0000` evaluates to `-554`). Always prepend a single apostrophe (`'`) to the phone string before sending. Sheets will display it as text without showing the apostrophe.

**Make polling-mode gotcha — manual trigger required after POST.** The DMs scenario is created with `scheduling: {type: "indefinitely", interval: 900}` + webhook `parameters.maxResults: 1` (Make's defaults for non-instant webhook scenarios). This means a webhook POST does NOT trigger immediate execution — it queues the payload, and the scenario only consumes it at the next 15-minute polling tick. With `maxResults: 1`, a single execution drains only ONE queued payload, so multiple POSTs accumulate.

For the daily run, after POSTing the DMs batch, **call `mcp__702eb79f-3fb6-46d4-80ad-3c3df1b23c60__scenarios_run` against the brief's `dms_scenario_id` to fire the scenario immediately**. Otherwise rows can sit in the webhook queue for up to 15 minutes before landing in the Decision-Makers tab, blocking Phase 5's re-read. Pattern:

```python
# After POST returns 200:
import requests
# (POST already done above)

# Manually trigger the scenario to consume the queued payload now (not in 15 min)
make_run = call_mcp("scenarios_run", scenarioId=brief.infrastructure.dms_scenario_id, responsive=True)
# Verify status:
detail = call_mcp("executions_get-detail", scenarioId=..., executionId=make_run.executionId)
assert detail.status == "SUCCESS"
```

This is mandatory — without it the Sheet re-read in Phase 5 races the 15-min polling tick and finds nothing.

After POST returns HTTP 200 AND `scenarios_run` returns SUCCESS, mark each job's URL as processed in state:
- `state.processed_jobs += [each new job's URL from Phase 2]`

Save state file after the POST + run succeeds.

## Phase 5 — Read Decision-Makers tab + identify new DMs

Re-download the workbook with the SAME complete-download method as Phase 2 (Make's write needs a few seconds; if new DMs aren't visible yet, wait 10s and re-download). **Never use `read_file_content`.**

1. `download_file_content(fileId = brief.infrastructure.sheet_id, exportMimeType = xlsx)` → saved file path.
2. Parse the Decision-Makers tab:
   ```
   python3 ~/.claude/skills/lilly-theirstack-data-processing/scripts/parse_theirstack_sheet.py \
     "<saved_download_path>" Decision-Makers "<state_path>" --out /tmp/theirstack/<brief_id>_new_dms.json
   ```
   The parser keys on `Email` vs `state.processed_dms` and also drops within-read duplicate emails (the Decision-Makers tab is known to hold exact-duplicate rows from Make iterator re-fires).
3. Load `/tmp/theirstack/<brief_id>_new_dms.json` as the "new DMs" working set (one object per row, keyed by column header).

Surface to user: `"Found N new DMs ready for Smartlead push in brief <brief_name>."`

## Phase 6 — Per-DM personalization (variable-agnostic, copy-driven)

**Architectural principle:** the email copy is the ground truth for what to personalise. Skill 2 doesn't hardcode any specific variable — it reads the copy, finds every `{{merge_variable}}` placeholder, cross-references with the brief's `personalization.per_lead_variables` config, and generates a value per DM for each.

### 6a. Fetch the Smartlead campaign email body FIRST (once per run, cached)

**Before generating any `{{HowWeCanHelp}}` values**, fetch the Smartlead campaign's actual email body so the LLM can write a fragment that reads naturally in context. Without this, the LLM has no idea what surrounds the merge variable and produces output that may clash with the surrounding copy, repeat the hook, or break the grammar of the sentence.

Use Smartlead API (or `lilly-bot` skill) to fetch the campaign sequence:

```
GET /api/v1/campaigns/<smartlead_campaign_id>/sequences
```

Capture the email body of step 1 (the first email — that's where `{{HowWeCanHelp}}` typically lives) with merge variable placeholders intact. Cache it as `email_body` for this run.

If the campaign has multiple variants of step 1, fetch all of them and use the variant the user designates as "primary" (typically variant A) — or ask user which one to anchor against.

### 6b. Identify all per-lead variables in the copy

Parse the fetched email body and extract every `{{merge_variable}}` placeholder. Build the working set:
- **Standard Smartlead variables** (`{{first_name}}`, `{{last_name}}`, `{{company_name}}`, etc.) — these are auto-populated by Smartlead from the lead's standard fields, skill 2 doesn't generate them. Drop from working set.
- **Per-lead variables to generate** — everything else. These are what skill 2 generates.

(There are NO static campaign-level merge variables managed by this skill. Sender context — what the brand/sender does — lives in `brief.ideation.offer` and is used as BACKGROUND for the LLM prompt, not pushed to Smartlead as a variable. All sales language for the brand lives directly in the campaign email copy.)

Cross-reference per-lead variables with `brief.personalization.per_lead_variables`:

| Scenario | Action |
|---|---|
| Variable in copy AND in brief config | ✅ Generate per DM using brief's `instructions` |
| Variable in copy, NOT in brief config | ⚠️ **Halt brief's Phase 6.** Surface to user: "Email copy uses `{{XYZ}}` but the brief has no generation instructions for it. Add it to `brief.personalization.per_lead_variables` (with instructions + validation) OR remove it from the email copy." |
| Variable in brief config, NOT in copy | ℹ️ Skip silently (config has a variable that the copy doesn't currently use — harmless) |

This halt-on-missing-config behaviour is intentional. Generating personalization without explicit instructions produces generic LLM output that defeats the point.

### 6c. Generate each per-lead variable per DM using email body as context

For each new DM AND each per-lead variable in the working set:

**Branch by `generation_strategy`:**

- **`angle_waterfall`** (e.g. `HowWeCanHelp`): evaluate each `angles[]` entry in priority order (lowest priority number first). For each angle, check its `trigger` condition against the DM's joined context (hiring_for, company_size, dm.title, tech_stack, open_roles, etc.). First matching angle wins. The fallback angle (`priority: 99`) ALWAYS matches as a last resort — no `{{var}}` should ever come out empty. Once an angle is selected, generate the value via LLM using THAT angle's `instructions` + the variable's `validation`. Pass the angle's `example` as a one-shot demonstration.

- **`delegate_to_skill`** (e.g. `Icebreaker` → `lilly-icebreaker`, `Cold Email Video Angle` → `lilly-personalisation`, `CaseStudy` → `lilly-personalisation` bucketed): invoke the referenced skill with the DM context + any args from the brief config (e.g. `skip_angles: [Hiring]` for Icebreaker). Use the skill's return value directly.

- **`direct_lookup`** (e.g. `Role` → `hiring_for` from the joined Jobs row): no LLM call. Copy the value verbatim from the named source field. Fail loud if the source field is empty.

- **`inline_llm`** (legacy / one-off variables without a structured strategy): plain LLM prompt using the variable's `instructions` and the email body as context. Use the variable-agnostic prompt template below.

**Prompt template (variable-agnostic — substitute `{{var_name}}` and `{{var_instructions}}` per call):**

```
You are writing the per-lead {{var_name}} merge variable. Your output drops into an existing cold-email body — your job is to make sure it reads naturally in context.

═══════════════════════════════════════════════════════════════
THE EMAIL BODY YOUR OUTPUT GOES INTO (merge variable placeholders shown as {{VAR}}):
═══════════════════════════════════════════════════════════════
{email_body_from_phase_6a}
═══════════════════════════════════════════════════════════════

Identify where {{var_name}} sits in that body. Your output replaces that placeholder. The result must:
- Flow grammatically with the words immediately before AND after the placeholder
- Not repeat content already in the email (especially the hook or other merge variables)
- Match the tone of the surrounding copy

SENDER CONTEXT (background — what the sender / our brand does; NOT a merge variable, NOT in the email):
{brief.ideation.offer}

WHY THIS LEAD FITS (signal rationale angles — pick ONE that best matches this lead's job context):
{brief.ideation.why_signal_fits_angles joined as bullets}

PER-LEAD GENERATION INSTRUCTIONS FOR {{var_name}}:
{brief.personalization.per_lead_variables[var_name].instructions}

VALIDATION RULES:
{brief.personalization.per_lead_variables[var_name].validation}

THIS LEAD'S CONTEXT:
- Company: {dm.company}
- Decision Maker: {dm.first_name} {dm.last_name}, {dm.title}
- Company is hiring for: {dm.hiring_for}
- Tech stack from job posting: {dm.tech_stack}
- Job posting URL: {dm.job_posting}
- Company size: {dm.company_size} employees
- Open roles in last 30d: {dm.open_roles}

TASK:
Write the {{var_name}} value following the generation instructions above. The output must satisfy the validation rules.

OUTPUT: only the value, no quotes, no preamble. Ready to drop into {{var_name}}.
```

Validate output against the brief-config's validation rules for this variable. If invalid, retry the LLM call once with stricter instructions. After second failure, skip the DM (for this variable) with a notice and continue.

### 6d. Cache the email body for the run

Cache `email_body` for the rest of the run — don't re-fetch per DM. If user runs the skill multiple times in a day, re-fetch on first invocation of each run (in case they edited the email copy via Smartlead UI or `/lilly-bot` between runs).

## Phase 7 — Push DM to Smartlead campaign

**Always delegate to `lilly-bot` for the actual Smartlead lead-add call.** Never call the Smartlead API directly from this skill. `lilly-bot` owns the Smartlead campaign-building / lead-upload contract and knows the right field names, custom-field-creation flow, dedup behaviour, and error-handling for Smartlead.

Direct API calls from this skill fail with cryptic errors (e.g. `"lead_list[0].company" is not allowed` — Smartlead expects `company_name`; `"lead_list[0].title" is not allowed` — title isn't a top-level lead field, it must be a custom field). `lilly-bot` handles these contract details so the skill doesn't have to.

Hand off to `lilly-bot` with:
- `campaign_id`: `brief.infrastructure.smartlead_campaign_id`
- `leads`: array of DM records with standard fields (`first_name`, `last_name`, `email`, `phone_number`, `company_name`, `website`, `location`, `linkedin_profile`) plus the brief's `personalization.per_lead_variables` filled per-lead under `custom_fields`.

Standard Smartlead lead fields:
- `first_name`, `last_name`, `email`, `phone_number`
- `company_name` (from dm.company)
- `website` (from dm.website)
- `location` (from dm.country)
- `linkedin_profile` (from dm.linkedin)

Custom fields (configurable per Smartlead campaign schema):
- `HowWeCanHelp` (from Phase 6 LLM output)
- `hiring_for` (from dm.hiring_for — for icebreaker reference if email body uses it)
- `tech_stack` (from dm.tech_stack)
- `job_posting` (from dm.job_posting)

Note: this skill does NOT push any "Offer" or sender-context field — the email copy itself contains all brand/offer language directly written by the copywriter.

After Smartlead confirms the lead added, mark email in state:
- `state.processed_dms += [dm.email]`

Save state file.

## Phase 7.5 — Phone enrichment + Notion cold-call sync (conditional, per-brief)

Both steps are OPT-IN per brief. Skip the whole phase for any brief that does not set the relevant config — most briefs won't.

### 7.5a — Phone enrichment (only if `brief.dm_finder.enrich_phone == true`)

For each NEW DM identified in Phase 5, attach a verified mobile via the brief's `dm_finder.phone_finder` skill (default `lilly-phone-finder` — BetterContact → Prospeo waterfall):

```bash
set -a; source ~/.navreo-keys.env; set +a
python3 ~/.claude/skills/lilly-phone-finder/scripts/find_phones.py <new_dms.csv> <out.csv>
```

Input columns: `first_name`, `last_name`, `company`, `website`, `linkedin`, `email` (already present on each DM). Output adds `mobile`, `mobile_source`, `mobile_status`. Cost is ~10 BetterContact credits per number FOUND (no charge on a miss) — for an unattended daily run the new-DM count is small, so no spend confirmation is needed; for a large one-off backfill, confirm the rough max spend (rows × ~10) first. Clean each mobile to a leading `+<digits/spaces/dashes>` (strip any trailing `· Country` text the Prospeo fallback may append). Phone is for cold-calling only — it does NOT change the Smartlead push.

### 7.5b — Notion cold-call sync (only if `brief.notion_sync` is present)

For each NEW DM (deduped by `brief.notion_sync.dedup_key`, default `Email`), write one page to the brief's Notion table via `notion-create-pages` (parent = `brief.notion_sync.data_source_id`, batches of up to 100):

- Map fields per `brief.notion_sync.field_map` (job + company + decision-maker + the enriched mobile + `Phone Source`).
- Title (`brief.notion_sync.title_property`) = `brief.notion_sync.title_format` (e.g. `{first_name} {last_name} — {company}`); icon = `brief.notion_sync.default_icon`.
- Set `Call Status` = `Not called` on every new row.
- **Additive only.** Never `replace_content`; never overwrite an existing page. Dedup new DMs against the table's existing `Email` values before writing (the Decision-Makers tab has historically held exact-duplicate rows — see `brief.notion_sync._gotchas`).
- The Notion table is a SEPARATE destination from Smartlead; a brief can sync to Notion, push to Smartlead, or both.

This phase touches no Smartlead state. Mark nothing extra in the state file for it — the DM's presence in `state.processed_dms` (set in Phase 7) is the dedup key that stops it being re-synced next run.

## Phase 8 — Persist state + summary

After all briefs processed:

Save each brief's state file with:
- `last_run_at`: now ISO timestamp
- `processed_jobs`: accumulated list (dedup)
- `processed_dms`: accumulated list (dedup)

Surface summary to user:

```
Run complete (2026-05-13 16:30):

Brief: Navreo GTM Hiring Signal
  • Jobs processed: 12 new (skipped 0 already-done)
  • DMs enriched via Prospeo: 28 verified emails (4 NO_MATCH dropped)
  • DMs pushed to Smartlead: 28
  • Smartlead campaign: 12345 ("Navreo — GTM Hiring Signal")

Run complete.
```

If any brief had errors (Prospeo API failures, Smartlead rejection, etc.), surface them honestly with the specific rows that failed.

## Phase 8.5 — Negative-keyword suggestions

After the run summary, analyse the run's `off_brief` set from Phase 2.5 and propose concrete saved-search refinements for the user to apply in TheirStack UI.

### 8.5-pre. Cross-check with brief's currently-applied negatives

**Before suggesting new keywords**, load `brief.theirstack_saved_search.negative_title_keywords` (the list of keywords already supposed to be applied in the TheirStack saved search). Then check today's `off_brief` set:

- **For each off-brief title**: if it matches a keyword already in `negative_title_keywords`, that signals **the user hasn't actually applied the keyword in TheirStack UI yet** (or the keyword's match logic is too narrow). Escalate this to the user with: `⚠️ '{{title}}' matches your already-confirmed negative '{{keyword}}' — TheirStack saved-search isn't filtering it out. Verify the keyword is actually in your Job Titles → Exclude chip.`
- **Only suggest NEW keywords** that aren't already in `negative_title_keywords`. Don't re-suggest what's already there.

This prevents the daily run from re-proposing the same 5 keywords every day when the user has already confirmed them.

### 8.5a. Cluster off-brief rows by reason category

Group by the LLM-tagged reason from Phase 2.5b. Standard categories:

| Category | Example off-brief rows | Suggested fix |
|---|---|---|
| **Junior level** | `Intern`, `Junior`, `Associate`, `Coordinator` titles | Add to Title-Exclude in TheirStack UI |
| **Branch / regional P&L** | `Branch Manager`, `Regional Manager`, `Area Manager`, `Branch Sales` | Add to Title-Exclude |
| **Internal product engineer** | `Software Engineer` / `Backend Engineer` paired with `GTM Platform` / `Growth Platform` in description | Add `Software Engineer` to Title-Exclude (acceptable false-positive risk on rare exec titles) |
| **Wholesale / distribution ops** | `Wholesale Sales`, `Distribution Sales`, `Account Manager` at distributor | Add `Wholesale` to Title-Exclude |
| **Geography drift** | Rows in countries outside `filter.job_country_code_or` | Verify Location filter is set to `Job Location` not `Company HQ` |
| **Industry pattern** | Repeated off-brief cos sharing industry signals (real estate, aviation, RV manufacturing) | Add company-name patterns to a separate exclude list OR tighten the seniority filter |

### 8.5b. Output the negative-keyword suggestions block

Place at the end of the run summary, framed as recommendations the user can choose to apply:

```
🔍 Negative-keyword suggestions (based on today's <N> off-brief rows)

To tighten your TheirStack saved search "<brief_name>", consider adding these to Filters → Job Titles → Exclude:

  • "Intern" — caught 1 row today
  • "Coordinator" — caught 3 rows today
  • "Branch Manager" — caught 1 row today
  • "Wholesale" — caught 1 row today
  • "Software Engineer" — caught 1 row (internal GTM-platform engineer)

Geography check:
  • 2 rows slipped through your country filter today (PH, CN). Verify your TheirStack saved search filters by "Job Location" (not "Company HQ Location"), since US-HQ companies post overseas roles.

Apply these in the TheirStack UI → your saved search → Filters → Job Titles (Exclude chip).

ℹ️ First 7 days of running this pipeline, expect to iterate on these daily. After 7 days the saved search should be ~85% precise and the qualification pass becomes mostly cosmetic.
```

### 8.5c. Persist suggestion history

Append the run's suggestions to `~/.claude/skills/lilly-theirstack-data-processing/queue/<brief_id>.json` under `negative_keyword_history[]` so future runs can:
- Show whether previous suggestions were already applied (cross-check by counting off-brief titles that match prior-suggested keywords)
- Surface "stale" suggestions if the user hasn't applied them but the same keyword keeps catching new off-brief rows

Suggestion entries do NOT auto-apply. The user applies them manually in TheirStack UI.

---

## Cloud upload (mandatory)

Every run's new-DM batch (the rows pushed to Smartlead in Phase 7) MUST also be uploaded to the central Supabase list store before the run ends — a batch that only lives in this machine's state file isn't done. Write the batch to a CSV and run:

`python3 ~/.claude/skills/_shared/list_upload.py <final.csv> --name "<descriptive list name>" --client "<Client>" [--folder "<Theme>"] --source-skill lilly-theirstack-data-processing --brief "<one-line brief>" --owner "<who asked>"`

Then show the returned `https://navreo-signals.onrender.com/app/lists.html#<id>` link to the user as part of the Phase 8 summary, alongside the Smartlead push confirmation.

Folder rules: `--client` = the client named in the brief (internal/Navreo pulls → `Navreo`); add `--folder` ONLY when the brief names a campaign theme or segment (e.g. client `Amplifyy`, folder `Beauty`); never deeper than two levels. Re-runs with the same name+client replace that list's rows in place (safe).

---

## State file schema

`~/.claude/skills/lilly-theirstack-data-processing/state/<brief_id>.json`:

```json
{
  "brief_id": "navreo-gtm-hiring-signal",
  "last_run_at": "2026-05-13T16:30:00Z",
  "processed_jobs": [
    "https://acmemock.com/careers/demand-gen-director",
    "..."
  ],
  "processed_dms": [
    "kkaur@google.com",
    "..."
  ],
  "stats": {
    "total_runs": 5,
    "total_jobs_processed": 78,
    "total_dms_pushed": 192
  }
}
```

State files are LOCAL — not in any cloud sync. If the user moves machines, the state needs to be transferred manually OR the user accepts duplicate work on the new machine (Smartlead's own duplicate-detection will catch most of it).

---

## Queue file schema

`~/.claude/skills/lilly-theirstack-data-processing/queue/<brief_id>.json` holds two things: borderline rows pending user confirmation, and the rolling history of negative-keyword suggestions.

```json
{
  "brief_id": "navreo-gtm-hiring-signal",
  "pending_confirmations": [
    {
      "added_at": "2026-05-14T08:30:00Z",
      "row_data": {
        "company": "CPM Educational Program",
        "website": "cpm.org",
        "job_title": "Revenue Operations Specialist",
        "company_size": 90,
        "country": "US",
        "tech_stack": "hubspot|salesforce|tableau",
        "job_posting": "https://recruiting.paylocity.com/...",
        "date_pulled": "2026-05-14"
      },
      "verdict": "BORDERLINE",
      "reason": "Specialist-level RevOps at 90-emp edtech nonprofit — could be first dedicated hire OR admin support",
      "user_decision": null
    }
  ],
  "negative_keyword_history": [
    {
      "suggested_at": "2026-05-14T09:00:00Z",
      "suggestions": [
        {"keyword": "Intern", "off_brief_rows_caught": 1, "applied_by_user": null},
        {"keyword": "Coordinator", "off_brief_rows_caught": 3, "applied_by_user": null},
        {"keyword": "Branch Manager", "off_brief_rows_caught": 1, "applied_by_user": null}
      ]
    }
  ]
}
```

`user_decision` is `"y"` / `"n"` / `null` (null = unresolved). When the user resolves a pending row, the entry stays in the file as audit history; its `user_decision` is set and it's no longer surfaced at run-start.

`negative_keyword_history` tracks whether suggestions are getting repeated across runs (indicating the user hasn't applied them in TheirStack UI). If the same keyword keeps catching off-brief rows for 3+ days, Phase 8.5 escalates the recommendation with `"⚠️ This keyword has been suggested 3 times and the same titles keep coming through — apply it now to clear the noise"`.

---

## Smartlead campaign requirements

The brief's Smartlead campaign must have these custom fields defined:

| Field | Source | Lifecycle |
|---|---|---|
| `{{first_name}}` | Standard | Filled per-lead from DM |
| `{{last_name}}` | Standard | Filled per-lead from DM |
| `{{company_name}}` | Standard | Filled per-lead from DM (joined from Jobs row) |
| `{{HowWeCanHelp}}` | Custom, per-lead | Filled by Phase 6 LLM output per DM |
| `{{hiring_for}}` (optional) | Custom, per-lead | Joined from originating Jobs row |
| `{{tech_stack}}` (optional) | Custom, per-lead | Joined from originating Jobs row |

If the user's Smartlead campaign doesn't have `{{HowWeCanHelp}}` configured, push to Smartlead will fail. Either:
- Fail the run and tell user to add the custom field via `/lilly-bot`, OR
- Push with `HowWeCanHelp` in the lead metadata and Smartlead will store but not render until the field is added

Default behaviour: surface the missing custom-field error and halt the brief's Phase 7. Other briefs continue.

---

## Phone number formatting (Make scenario gotcha)

**Always prepend `'` (single apostrophe) to phone numbers before POSTing to the DMs webhook.**

Make's Google Sheets module uses `valueInputOption: USER_ENTERED`, which causes Google Sheets to interpret strings starting with `+` as math formulas. A phone like `+1-555-000-0000` evaluates to `-554` (1 minus 555 minus 0 minus 0).

The apostrophe forces Sheets to treat the value as text. Sheets displays the value without showing the apostrophe.

For DMs without phones (empty string), do nothing — empty cell is fine.

---

## Key reference values (Navreo)

- Brief configs path: `~/.claude/skills/lilly-theirstack-setup/briefs/`
- State files path: `~/.claude/skills/lilly-theirstack-data-processing/state/`
- Sheet reads: `download_file_content` (xlsx export) + `scripts/parse_theirstack_sheet.py`. **NEVER `read_file_content`** (it renders the Decision-Makers tab first and caps at ~107K chars, silently hiding the newest Jobs rows)
- Sheet-read parser: `~/.claude/skills/lilly-theirstack-data-processing/scripts/parse_theirstack_sheet.py` (tab-targeted, openpyxl, dedups vs state, writes new rows to `--out`)
- Smartlead API key: `$SMARTLEAD_API_KEY` from `~/.navreo-keys.env`
- Prospeo / AI Ark: invoked via `lilly-tam`, no direct calls from this skill

---

## Linked skills

- **Prerequisite**: `lilly-theirstack-setup` (creates the brief, Sheet, scenarios, webhook URLs this skill consumes)
- **Called per run**: `lilly-tam` (Phase 3 — Prospeo/AI Ark DM enrichment)
- **Called per run**: `lilly-bot` (Phase 7 — Smartlead lead-add; MANDATORY, never call Smartlead API directly)
- **Optional pre-skill 2**: `lilly-personalisation` can substitute for Phase 6 if user wants more sophisticated multi-variable generation (Why, CaseStudy, etc.) — but `lilly-personalisation` operates on a Smartlead campaign that ALREADY has leads in it, so the chain becomes Phase 7 first → then `lilly-personalisation` to backfill Why/CaseStudy after leads are in Smartlead.

---

## Guardrails

1. **Idempotency.** Every phase respects state. Re-running is always safe.
2. **State file is authoritative.** If a row's identifier is in state, skip. Don't read Sheet's Status column as the dedup mechanism — Status is for human visibility only.
3. **Confirm Prospeo cost before Phase 3.** Show user: "N companies × ~3 DM credits each = ~3N Prospeo credits. Proceed?"
4. **Confirm Smartlead push before Phase 7.** Show user: "N DMs about to be added to campaign X. Proceed?"
5. **Phone apostrophe is non-negotiable.** Sheets-formula gotcha eats valid phone numbers silently otherwise.
6. **Skip briefs without Smartlead campaign.** If `infrastructure.smartlead_campaign_id` is null, skip the brief (with a notice) — don't enrich without somewhere to push to.
7. **Never push DMs without verified emails.** `lilly-tam` already filters to verified-only, but double-check before Smartlead push.
8. **Respect `lilly-tam`'s domain-match filter.** Drop DMs whose verified email's domain doesn't match the company domain (cross-contamination from cached job-history).
9. **No retroactive Status updates in Sheet.** This skill doesn't write back to the Sheet's Status column (Drive MCP can't update specific cells). State file is the source of truth. The Sheet's Status column stays `NEW` forever — purely cosmetic.
10. **Each brief processes independently.** If one brief fails, others continue. Errors surfaced at the end.
11. **ALL Smartlead operations (add, update, fetch, custom-field changes, sequence reads) MUST go through `/lilly-bot`.** No exceptions. Never call the Smartlead MCP tools or HTTP API directly from this skill or any sub-step. `lilly-bot` owns the Smartlead contract end-to-end — field-name quirks (`company_name` not `company`, `title` is a custom field), custom-field creation flow, dedup behaviour, update endpoints, error-handling. Direct calls hit cryptic schema errors and contract mismatches. The pattern: prepare the full payload in this skill, then delegate to `/lilly-bot` with explicit operation type (add / update / fetch) + the data, and let it pick the right endpoint. This rule applies to Phase 7 lead-add, Phase 6a sequence-fetch, mid-pipeline lead-updates, and any other Smartlead touch.
12. **Suppression + already-contacted gate before Phase 3 spend (MANDATORY, Phase 2.75).** Batch-check the Phase 2.5 `qualified` domain set against `navreo_db.check_exclusions(client_id, domains=[...])` and `contact_history` (via `navreo_db.rest`) before handing anything to `lilly-tam`. Report N suppressed / M already-contacted / K proceeding. This closed a ~30%-of-credits leak where DM enrichment ran against companies already contacted or suppressed. **Unattended-safe:** since this is a daily automated run with no user watching, an unavailable `check_exclusions` (returns `None`) must NEVER be treated as "no exclusions" — log a warning into the run summary and proceed WITHOUT dropping anything from that particular check, rather than silently either dropping real leads or silently skipping the safety check.
13. **Sheet reads use the xlsx download + parser, NEVER `read_file_content`.** `read_file_content` renders the Decision-Makers tab first and caps at ~107K chars, so it silently hides the newest Jobs rows. This caused 13+ consecutive "0 new jobs" runs while 600+ jobs sat unenriched (the Decision-Makers tab grew large enough to consume the entire read budget). Phase 2 and Phase 5 MUST read via `download_file_content` (xlsx) + `scripts/parse_theirstack_sheet.py`, which targets the tab by name and reads it in full.

---

## Failure modes + recovery

| Failure | Recovery |
|---|---|
| Brief config missing required fields | Skip brief, surface specific field to user |
| Sheet read fails (permissions) | Surface; user re-shares Sheet |
| `download_file_content` returns `Resource has been exhausted / quota` | Transient Drive export limit. Wait ~30s, retry. Do NOT fall back to `read_file_content` (it truncates and hides new Jobs rows) |
| Parser prints `{"error":"tab not found"}` | The sheet's tab was renamed or the download was incomplete. Re-download; confirm the tab is named exactly `Jobs` / `Decision-Makers` |
| Prospeo returns 0 DMs for all companies | Surface; consider AI Ark fallback (already in lilly-tam) or alert user that domains may need WebFetch verification |
| DMs webhook returns non-200 | Halt brief; surface; user checks Make scenario status |
| LLM generates invalid `{{HowWeCanHelp}}` | Retry once with stricter prompt; if still invalid, skip lead with notice |
| Smartlead lead push fails (e.g. missing custom field) | Halt brief's Phase 7; surface error; user fixes campaign config |
| State file corrupted | Surface; user manually clears state OR skill re-initialises with empty state (will re-push leads — Smartlead dedups by email) |


## Upload gate (MANDATORY)

Before ANY lead push into a Smartlead campaign that results from this skill (`add_leads_to_campaign` or equivalent), hand off to `lilly-upload-gate` and let it run to a green gate: every enabled check PASS or explicitly OVERRIDDEN per-flag, and the audit row written to `list_upload_qa_runs` BEFORE the first add-leads call. Never upload around the gate.
