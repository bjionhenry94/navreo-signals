---
name: lilly-signal
description: >-
  Lilly's signal-to-campaign automation orchestrator for internal Navreo use. Set up a daily
  prospecting routine driven by any of 5 signal types: news events (funding, launches, rebrands),
  hiring signals (TheirStack), LinkedIn engagement (Trigify), tech adoption (PredictLeads), or
  company attributes (Prospeo). 3 turns to a live scheduled routine: answer one batch of setup
  questions, approve 15 dry-run leads, done. Each day the routine finds matching companies,
  suppresses already-contacted domains, qualifies the ICP, finds decision-makers with verified
  emails, and pushes into Smartlead or HeyReach automatically: no daily clicks. Trigger on:
  "set up a daily prospecting routine", "build a signal campaign", "automate my prospecting for
  [client]", "track companies hiring [role]", "find companies that just raised funding",
  "find companies using [tool]", "build me a routine for [ICP]", "run my [routine name] routine",
  "show me my signal routines", "what routines do I have", "change my [routine name] routine",
  "pause/resume my [routine name]", or any request to create or manage a signal-driven daily
  outreach pipeline for internal Navreo use.
---

# Lilly Signal

Lilly's **signal-to-campaign automation orchestrator**. Define a signal goal once. Lilly finds matching companies daily, qualifies the ICP, finds the right decision-makers, and loads them into your Smartlead campaign or HeyReach list: automatically.

**3 turns to a live daily routine:**
1. Answer one batch of setup questions (all in one go)
2. Lilly fires a 15-company dry-run and shows you the leads
3. You approve, Lilly schedules the daily routine

---

## The one rule: daily credit cap is always set at setup

Lilly always runs on **Autopilot**: no daily confirmations, no permission prompts once the routine is running. The user's only control is the **daily credit cap**, set once at wizard time.

- Required at setup. **Default: 50 credits/day.** Lilly asks if you skip it.
- If today's DM-finding batch would exceed the cap, Lilly takes the top-ranked companies (by ICP score) up to the cap and logs the remainder.
- The cap is a hard ceiling. Lilly never exceeds it and never silently raises it.
- After every run, Lilly posts an end-of-run summary. You always see what was found, enriched, and pushed.

---

## Signal types

Pick one when you run the wizard.

| # | Signal | What it watches for | Source |
|---|--------|--------------------|----|
| 1 | **News** | Funding, product launches, rebrands, new offices, awards, exec hires | WebSearch |
| 2 | **Hiring** | Companies actively hiring a specific role or title | TheirStack |
| 3 | **LinkedIn engagement** | Companies engaging with specific topics or tracked accounts | Trigify |
| 4 | **Tech adoption** | Companies that just adopted or dropped a specific tool | PredictLeads |
| 5 | **Company attribute** | Companies matching a defined profile (industry, size, tech stack) | Prospeo |

**How signal type affects the wizard:**
- Signal 2 (Hiring): After saving the config, Lilly calls `lilly-theirstack-setup` to provision the TheirStack pipeline (Google Sheet, Make scenarios, saved search). A short UI checklist follows. Dry-run waits for "saved search live" confirmation.
- Signal 3 (LinkedIn): After saving the config, Lilly calls `lilly-trigify-setup` to provision the Trigify workflow. Dry-run waits for workflow confirmation.
- Signals 1, 4, 5: No external UI steps. Lilly proceeds straight to the dry-run.

From the user's perspective the wizard is identical across all signal types. The sub-skill calls are invisible.

---

## Setup wizard

### Turn 1 (what Lilly shows)

Present the signal menu, then ask ALL setup questions in one message, grouped into 4 blocks. The user answers everything at once; never ask the same question twice.

```
Lilly: Let's build your routine. A few quick questions:

Block A: Signal
Here are the signals Lilly can watch for:
  1. News: funding, launches, rebrands, new offices, awards, exec hires
  2. Hiring: companies actively hiring a specific role
  3. LinkedIn engagement: companies engaging with a topic or content
  4. Tech adoption: companies that just adopted or dropped a specific tool
  5. Company attribute: companies matching a defined profile

Which one? And one sentence on what specifically (e.g. "companies hiring a VP of
Sales", "companies that just raised Series A", "B2B agencies running Salesforce").

Block B: ICP
What kind of company should qualify?
- Industry / company type (e.g. "B2B SaaS", "digital agencies", "e-commerce brands")
- Employee size range (default: any)
- Geography (default: Navreo ICP geos: US, CA, UK, AU + 10 more high-GDP countries)
- Anything to exclude (sectors, company types)

Block C: Decision-makers
Who inside the company should Lilly find?
- Roles / titles (default: Navreo ICP roles if blank)
- Max people per company (default: 2)
- Email: required or best-effort? (default: best-effort)
- Phone numbers: yes or no? (default: no)

Block D: Destination and cap
- Where should leads go: Smartlead campaign (name or ID) or HeyReach list (name or ID)?
- How many companies per day? (default: 20)
- Daily credit cap? (default: 50)
```

Present this verbatim. Do not show JSON, file paths, or API dials. Do not ask about run mode: it is always Autopilot.

If the user has no campaign yet: offer to create a skeleton Smartlead campaign (name, schedule, sending settings only). Note that email copy must be added separately via `lilly-copywriter` before the campaign can send.

### Turn 2 (after user answers)

1. Translate every plain-English answer into routine config fields.
2. Resolve the destination campaign or list name to its ID (call Smartlead or HeyReach API).
3. Fill in all defaults for anything left blank.
4. Save to `~/.claude/skills/lilly-signal/routines/<routine_id>.json`.
5. Render the **plain-English read-back** (template below).
6. For signal 2: call `lilly-theirstack-setup` with the ICP, signal label, and destination; show the UI checklist; wait for "saved search live" before firing the dry-run.
7. For signal 3: call `lilly-trigify-setup`; show the workflow setup steps; wait for confirmation.
8. For signals 1, 4, 5: fire the **15-company dry-run** immediately (see Dry-run section).
9. Show the dry-run leads table inline.
10. Close with: *"Here are your 15 dry-run leads. Do these look right? Say 'approved' to schedule the daily routine, or tell me what to adjust."*

### Turn 3 (dry-run approval)

- **Approved**: create the daily scheduled task via the `schedule` skill (default: 9am Mon-Fri). Confirm task ID. Show the 3 run sentences (run, show, change).
- **Tweaks**: update the config, re-run the dry-run on 15 fresh companies, show results again.

### The plain-English read-back

Render after saving, and whenever the user says "show me my [name] routine":

```
[Routine name]

Watching for:      [signal label]
Source:            [TheirStack / WebSearch / Trigify / PredictLeads / Prospeo]
How recent:        last [N] days
How many a day:    [N] companies
Companies must be: [ICP description]
Finding inside:    [roles], up to [N] per company
Emails:            [required / best-effort]
Phone numbers:     [yes / no]
Pushing to:        [campaign/list name]
Daily credit cap:  [N]
Schedule:          [9am Mon-Fri / custom]

Want to change anything? Just tell me.
```

If part of the routine is not set yet (e.g. no campaign ID), show that line as "not set yet, want to fill it in?" rather than hiding it.

---

## The daily run

Load `routines/<routine_id>.json` first. If no routine is saved, offer the wizard instead.

### Phase A: Build exclude list and find companies

**Before firing the signal source**, pull all domains already in the destination (Smartlead campaign leads or HeyReach list). Pass them as exclusions to the signal query so already-contacted companies never appear in today's batch.

Then find companies using the source for this routine's signal type:

**Signal 1 (News / WebSearch):** Build 3-5 targeted queries from the signal label (e.g. `"Series A announcement" "2026" site:techcrunch.com OR site:businesswire.com`). Collect distinct company names and domains from results within the recency window. Drop press agencies, job boards, and aggregator results. Target at least `target_companies` distinct companies before continuing.

**Signal 2 (Hiring / TheirStack):** Read new rows from the Google Sheet Jobs tab provisioned by `lilly-theirstack-setup` (brief_id stored in `sub_skill_refs.theirstack_brief_id`). Rows added since the last run = today's batch. If no new rows: say so plainly and stop.

**Signal 3 (LinkedIn / Trigify):** Read new engagers from the Trigify workflow (workflow_id in `sub_skill_refs.trigify_workflow_id`). New engagers since last run = today's batch.

**Signal 4 (Tech adoption / PredictLeads):** Call `PredictLeads discover_technology_technology_detections` with the technology name and detection date after today minus `recency_days`. Collect distinct company domains.

**Signal 5 (Company attribute / Prospeo):** Call `lilly-tam` with the ICP filters. Pass the exclude list so already-contacted domains are not returned.

Cap the raw batch at **3x `target_companies`** before continuing to prevent over-enrichment on a loud signal day.

### Phase B: Suppress already-contacted

Drop any domain from the batch that appears in the destination (Smartlead campaign or HeyReach list). This is a hard secondary filter: it catches any edges that Phase A's exclusion missed. Log how many were dropped.

### Phase C: Qualify companies

Run `lilly-lead-score` on the remaining batch with the ICP description as the brief. Keep QUALIFIED and BORDERLINE; drop OFF_BRIEF. Log dropped count and reason.

If fewer than 5 companies remain after Phase C: stop the run, post a thin-day notice in the summary, and do not proceed to Phase D.

### Phase D: Find DMs and verify emails

Call `lilly-tam` with:
- The qualified domain list from Phase C
- The routine's role / title set (`decision_makers.roles`)
- `max_per_company` from the routine config
- Email mode: required or best-effort

`lilly-tam` handles Prospeo search, enrichment, email verification, and domain-match filtering internally. Do not override its source routing.

Track credits used against `daily_credit_cap`. If Phase D would exceed the cap, process the top-ranked companies first (ordered by ICP score from Phase C); note the remainder in the summary.

### Phase E: Phone numbers (optional)

If `decision_makers.phone = true` in the routine config, call `lilly-phone-finder` on the Phase D results. Attach found numbers to the lead records.

### Phase F: Push to destination

**Smartlead campaign:** Call `lilly-bot` to add the Phase D leads to the campaign. Map to Smartlead's lead schema: `email`, `first_name`, `last_name`, `company_name`, plus any custom fields from Phase E (phone). Campaign stays in its current status: do not auto-activate.

**HeyReach list:** Call `lilly-heyreach-upload` to add Phase D leads to the named list.

If `destination.campaign_id` is null: abort Phase F and tell the user to set the campaign before running.

### Phase G: End-of-run summary

Always post after every run, whether the run was full or thin:

```
[Routine name]: [date]

Companies found via signal:      [N]
Already contacted (suppressed):  [N]
Qualified (ICP match):           [N]
Decision-makers found:           [N] across [M] companies
Credits used today:              [N] / [cap]
Leads pushed to [destination]:   [N]

[If cap hit: X companies held: rolling to tomorrow]
[If thin day: only X companies qualified: no leads pushed today]
```

---

## Dry-run

Fires automatically after Turn 2 (for signals 1, 4, 5) or after UI step confirmation (signals 2, 3). Runs the full pipeline (Phases A-G) on **15 real companies**. Destination campaign stays paused or in draft. Results shown inline as a table with: company, domain, DM name, title, email status, ICP verdict.

**Dry-run gates:**
- If more than 6/15 companies are cut at Phase C, suggest tightening the signal definition before scheduling.
- If Phase F fails (e.g. no campaign ID), tell the user what to fix and do not create the schedule.
- If fewer than 5 pass Phase C: call it a dry-run failure and suggest adjusting the ICP or signal.

Dry-run cost: approximately 15-40 credits depending on how many companies pass Phase C.

---

## Routine config schema

Save to `~/.claude/skills/lilly-signal/routines/<routine_id>.json`.

```json
{
  "routine_id": "navreo-vp-sales-hiring",
  "routine_name": "VP Sales hiring signal",
  "client": "Navreo",
  "created_at": "2026-06-25",
  "run_mode": "autopilot",
  "daily_credit_cap": 50,

  "signal": {
    "type": "hiring",
    "source": "theirstack",
    "label": "Companies hiring a VP of Sales",
    "params": {
      "recency_days": 14,
      "target_companies": 20
    }
  },

  "company_filter": {
    "description": "B2B services agencies, 50-500 employees, Navreo ICP geos",
    "size_min": 50,
    "size_max": 500,
    "countries": ["US","CA","UK","AU","IE","NZ","DE","NL","CH","SE","NO","DK","FI","SG"],
    "exclusions": []
  },

  "decision_makers": {
    "roles": ["VP Sales", "Head of Sales", "CRO", "CEO"],
    "max_per_company": 2,
    "email_required": false,
    "phone": false
  },

  "destination": {
    "type": "smartlead_campaign",
    "campaign_id": "abc123",
    "campaign_name": "Navreo - VP Sales Hiring Signal"
  },

  "suppression": {
    "check_existing_leads": true
  },

  "schedule": {
    "cron": "0 9 * * 1-5",
    "task_id": "task_abc123"
  },

  "sub_skill_refs": {
    "theirstack_brief_id": "navreo-vp-sales",
    "trigify_workflow_id": null
  },

  "state": {
    "last_run_at": null,
    "last_run_domains": []
  }
}
```

**Field notes:**
- `run_mode`: always `"autopilot"`. Lilly Signal has no supervised mode.
- `signal.type`: one of `"news"`, `"hiring"`, `"linkedin"`, `"tech_adoption"`, `"company_attribute"`.
- `sub_skill_refs.theirstack_brief_id`: set only for `type: "hiring"` (brief_id from `lilly-theirstack-setup`).
- `sub_skill_refs.trigify_workflow_id`: set only for `type: "linkedin"`.
- `state.last_run_domains`: list of domains processed on the last run. Used to dedup between runs for signal types without their own state tracking (signals 1, 4, 5).
- `schedule.task_id`: set after the `schedule` skill creates the task.

---

## Running it day to day

| You say | What happens |
|---|---|
| `run my [name] routine` | Lilly loads the config and runs Phases A-G |
| `show me my [name] routine` | Lilly renders the plain-English read-back |
| `what routines do I have?` | Lilly lists all routines with signal label and destination |
| `pause my [name] routine` | Lilly pauses the scheduled task |
| `resume my [name] routine` | Lilly resumes the scheduled task |
| `change the ICP on [name]` | Lilly updates `company_filter` and reads back |
| `change the cap on [name] to N` | Lilly updates `daily_credit_cap` |
| `add [role] to [name]` | Lilly adds the role to `decision_makers.roles` |
| `switch [name] to campaign X` | Lilly updates `destination` and re-resolves the campaign ID |
| `delete [name]` | Lilly deletes the config and stops the scheduled task |

After any change, Lilly reads the updated routine back in plain English. Never hand the user the JSON file or ask them to edit it.

To answer "what routines do I have?": read the `routines/` folder, print each routine's friendly name, signal label, destination name, and daily cap on one line each.

---

## Guardrails

1. **Daily credit cap is always set.** Required at wizard time. Hard ceiling on every run. Never exceed or silently raise it.
2. **Build the exclude list before Phase A fires.** Pull contacted domains from the destination first; pass as exclusions to the signal query so we never surface already-touched companies upstream.
3. **Suppress before qualify.** Phase B (suppress) runs before Phase C (qualify): never waste ICP-scoring credits on companies already in the campaign.
4. **Qualify before enrich.** Phase C (`lilly-lead-score`) runs before Phase D (DM finding). Never enrich off-brief companies.
5. **Dry-run mandatory.** No schedule created until the user approves 15 dry-run leads. Campaign stays paused during dry-run.
6. **Use `lilly-tam` as-is.** Do not override its source routing or add constraints not in the skill.
7. **Destination must exist before Phase F.** If `campaign_id` is null, abort and tell the user. Do not create campaigns mid-run.
8. **Sub-skills own their setup.** For type 2, `lilly-theirstack-setup` provisions the TheirStack infrastructure. For type 3, `lilly-trigify-setup` does. Lilly-signal reads from them; it does not replicate their logic.
9. **No em dashes.** Use commas, colons, or full stops.
10. **Maildoso warmup is always off.** If mailboxes are on smtp.maildoso.com, warmup inactive is intentional. Never re-enable it.
11. **Thin-day grace.** If fewer than 5 companies qualify in Phase C, stop the run and note it in the summary. Do not proceed to Phase D.
12. **Config changes are additive.** When updating roles, ICP, or exclusions: add to the existing config. Never wipe existing values without explicitly confirming what gets removed.

---

## Related skills

- `lilly-theirstack-setup`: provisions TheirStack pipelines for Signal 2 (hiring)
- `lilly-theirstack-data-processing`: daily processor for TheirStack briefs (Phase A data source for Signal 2)
- `lilly-trigify-setup`: provisions Trigify workflows for Signal 3 (LinkedIn engagement)
- `lilly-tam`: Phase A for Signal 5 (company attribute)
- `lilly-lead-score`: Phase C ICP qualification
- `lilly-tam`: Phase D DM finding and email verification
- `lilly-phone-finder`: Phase E phone numbers (optional)
- `lilly-bot`: Phase F Smartlead push
- `lilly-heyreach-upload`: Phase F HeyReach push
- `lilly-copywriter`: copy writing for the campaign (done separately before or after routine setup)
