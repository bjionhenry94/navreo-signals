---
name: lilly-qa
description: Run pre-launch quality assurance on a Smartlead email campaign. Checks sequence structure, copy, spintax, variables, formatting, personalisation, and lead-data hygiene (first_name + company_name normalisation, fill-rate verification across every contact for every variable in copy) against a configurable playbook (Navreo default, Generic, or Custom). Use whenever the user mentions QA'ing a Smartlead campaign, asks to "check", "review", "audit", or "validate" a campaign before sending, asks about variants or spintax errors, asks to fix mechanical issues in campaign copy, asks to clean or normalise first_name / company_name on a campaign's leads, or shares a campaign ID/name with intent to inspect it. Trigger this even if the user only says "review my campaign" or names a Smartlead campaign without explicitly saying "QA". Three operating modes: read-only report, propose fixes (paste-ready text), or apply fixes via API.
---

# Lilly-QA

Pre-launch quality gate for Smartlead campaigns. Validates sequence structure, copy, spintax, variables, and personalisation; flags FAIL / WARN / PASS findings; optionally proposes or applies fixes.

## What this skill does

Three modes, picked by the user at the start of every QA session:

1. **Read-only QA**: fetch the campaign and produce a structured findings report. No changes made.
2. **QA + propose fixes**: same as above, plus output corrected copy as paste-ready text the user can drop into the Smartlead UI.
3. **QA + apply fixes**: attempt to write corrected copy back via `mcp__smartlead__smartlead_save_campaign_sequence`. Falls back to mode 2 if the API rejects (often does, since many fields are read-only via API).

## When to trigger

The user is referring to a Smartlead campaign and any of:

- explicit QA request ("QA this campaign", "check this", "review", "audit", "validate before launch")
- they share a campaign ID or campaign name
- they ask about copy errors, spintax, variants, personalisation, or merge fields
- they ask to "fix" or "clean up" a campaign's copy
- they're preparing to launch and want pre-flight checks

If the user references a campaign but their intent is unclear, ASK which mode they want before proceeding.

## Workflow

### Step 1: Ask which mode

Before doing anything, ask:

> Which mode?
> 1. **Read-only QA**: I check and report, no changes.
> 2. **QA + propose fixes**: I check, then output corrected copy you can paste yourself.
> 3. **QA + apply fixes**: I check, then try to write the fixes directly via API (may not work).

If they don't have a campaign ID handy, ask for the campaign **name or ID**. Use `mcp__smartlead__smartlead_list_campaigns` to search if needed.

### Step 2: Identify the Smartlead client

The user has campaigns under multiple Smartlead clients:

- **Navreo primary** (default key)
- **Navreo additional** (client key `1417c9a6-...zto0vlj`, also Navreo-titled campaigns; pull this on every cross-account run)
- **Amplifyy / Kevin Dormer** DFY account (Amazon-seller campaigns)

If unclear which one to fetch from, ask. Default first attempt is the Navreo primary key.

### Step 3: Pick playbook

> Which playbook should I QA against?
> - **Navreo (default)**: 3+ day delays, plain-text only, P.S. format, straight apostrophes, no em-dashes, ≥2 Step 1 variants, subject diversity required.
> - **Generic**: universal best practices, no client-specific rules.
> - **Custom**: paste your playbook config and I'll use that.

If the user just says "QA this campaign" without specifying, default to **Navreo**. See `references/playbooks.md` for full profile contents.

### Step 4: Fetch sequence + metadata

Call `mcp__smartlead__smartlead_get_campaign_sequence` with the campaign ID. Save the raw JSON.

For header context (name, status, created date), also call `mcp__smartlead__smartlead_get_campaign`.

### Step 5: Run the analyser

Run `scripts/analyze_sequence.py` against the sequence JSON:

```bash
python3 ~/.claude/skills/lilly-qa/scripts/analyze_sequence.py sequence.json \
  --playbook navreo \
  --campaign-id <id> \
  --campaign-name "<name>" \
  --campaign-status <status>
```

It emits structured findings (FAIL / WARN / PASS) with location and severity. See `references/checks.md` for the full automated check list.

### Step 5b: Lead-variable fill check (NEW — required)

For every custom `{{variable}}` the analyser flagged in the copy, verify every lead in the campaign actually has that custom field populated. A variable in the copy with an empty value on the lead renders as a blank — the email reads broken.

Run:

```bash
SMARTLEAD_API_KEY=$key python3 ~/.claude/skills/lilly-qa/scripts/check_lead_variable_fill.py \
  --campaign-id <id> \
  --variables "Cold Email Video Angle,Why,Icebreaker,..."
```

Pass the comma-separated list of custom variables surfaced by Step 5 (skip `first_name`, `company_name`, and other default lead fields — those are top-level on the lead object, not in `custom_fields`, and are covered by Step 5d).

Verdicts per variable:
- **✅ PASS** if 100% (or 99.9%+) filled
- **⚠️ WARN** if 95–99.9% filled — small gap, likely a few stragglers
- **❌ FAIL** if < 95% filled — meaningful share of leads will send broken copy

The script also flags **case-mismatches** — leads where the variable's value lives under a slightly different key (e.g. `cold email video angle` vs `Cold Email Video Angle`). Smartlead's variable lookup is case-sensitive, so these render empty unless the keys are normalised.

Fold the output of this check into the WARN / FAIL sections of the report. If any variable is < 100%, **do not let the user launch** without either backfilling or removing the variable from copy.

### Step 5c: Icebreaker integrity check (NEW — required when {{Icebreaker}} is in copy)

The fill check (Step 5b) confirms the variable is populated. This check confirms the variable is *good*. Run only when `{{Icebreaker}}` (or `{{icebreaker}}`, etc.) appears in the rendered copy.

Two sub-checks: (a) name/company normalisation, (b) coherence with the email body.

#### 5c-a: Name + company normalisation in the rendered line

Pull every unique `{{Icebreaker}}` value across the campaign's leads. Apply these heuristic regex checks against each value:

| Pattern | Example match | Severity |
|---|---|---|
| Legal entity suffix in company name | `Acme Inc., Acme LLC, Acme Ltd, Acme GmbH, Acme S.A., Acme Pty, Acme Limited, Acme Corp` | **FAIL** |
| Profession tail in company name | `John Smith Photography, Acme Consulting Group, Foo Marketing Services` | **WARN** |
| Descriptive reach tail in company name (`International`, `Worldwide`, `Global`) | `Advantage Group International → Advantage, Jex Global → Jex` (industry nouns like `Talent`/`Associates` left intact) | **WARN** |
| All-caps company name (≥3 chars, mid-sentence) | `joined ACME as Sales Director` | **WARN** |
| Lowercase first letter of company name mid-sentence | `joined acme as Sales Director` | **WARN** |
| First-name title prefix | `you, Dr. Smith ...`, `you, Mr. Jones ...` | **WARN** |
| Empty / null name slots | `you,  or  was the right person at` | **FAIL** |
| Doubled spaces / trailing spaces / leading commas | `Apologies if this isn't relevant.  I wasn't sure ...` | **WARN** |
| Em-dashes (`—`) in the line | per `feedback_no_em_dashes` | **FAIL** |

Output table per finding: `lead_email | icebreaker_value | pattern_matched | severity`. Group by pattern so the user can fix at the source — usually that means running Step 5d to clean `first_name` / `company_name` upstream (then regenerate icebreakers), or re-running `lilly-icebreaker` with cleaner inputs.

Implementation: deterministic regex pass — fast, free, runs over a CSV export of the campaign's leads. Save the full check as `~/.claude/skills/lilly-qa/scripts/check_icebreaker_integrity.py` on first run if it doesn't exist; otherwise re-use.

If any FAIL pattern fires on ≥1% of leads, **block launch** until fixed. WARN patterns surface in the report but don't block.

#### 5c-b: Coherence with the wider email context

A normalised icebreaker can still be tonally or topically off. Examples that pass 5c-a but should fail 5c-b:

- Icebreaker says *"noticed you're using Salesforce"* but the email body pitches a Salesforce-replacement product. Tone-deaf.
- Icebreaker says *"saw you recently joined Acme as Sales Director"* but the body asks *"how long have you been at Acme?"*. Incoherent.
- Icebreaker says *"saw Acme closed a Series B round recently"* but the body opens with *"hope this email finds you well in these challenging times"*. Tonally inconsistent.
- Icebreaker mentions a colleague (cover-line tone) but the body references *"your team"* without acknowledging the cover.

**How:** dedup `{{Icebreaker}}` values to unique lines (typically 5-30 unique lines per campaign — most leads share one of the 6 angle templates). For each unique line, send (icebreaker_line + email_body_step_1) to a cheap LLM with this prompt:

```
You are checking if a cold-email icebreaker line tonally and topically fits the rest of the email body.

Icebreaker line: {line}
Email body (step 1): {body}

Output one of:
- PASS — fits cleanly, no rewrite needed
- WARN — minor tonal or topical friction, flag but doesn't block
- FAIL — meaningful contradiction, would read badly to the prospect

If WARN or FAIL, add a one-sentence reason after the verdict.
```

Cost: 5-30 cheap LLM calls per campaign (Haiku-class). Trivial.

Output per unique line: `verdict | line | body_step | reason | num_leads_affected`. Surface FAIL-verdict lines as launch-blockers; WARN-verdict lines go in the report for user judgment.

If the campaign uses **per-variant body copy** (multiple email-1 variants), run the coherence check against each variant. An icebreaker that fits variant A may not fit variant B.

### Step 5d: Standard-lead-field hygiene + fill check (NEW — required when {{first_name}} or {{company_name}} is in copy)

Step 5b verifies fill rate for `custom_fields.*`. This step covers the default lead fields that 5b skips — `first_name` and `company_name` rendered via `{{first_name}}` / `{{company_name}}` merges. Two checks in one pass:

1. **Fill rate** — every lead has a non-empty, non-junk value for the field. Empty / single-char / junk-marker values (`Unknown`, `N/A`, `-`, `Self`, etc.) render as broken sentences in the email (`Hi ,` or `recorded a video for Unknown ...`).
2. **Hygiene** — values are clean per the rules in `references/lead-field-hygiene.md`. Legal suffixes (`Acme Inc.`), profession tails (`Pereira Dabul Advogados`), shouting (`ACME`), auto-hyperlinking TLDs (`Immersa.ai`), and similar issues are flagged.

This step is required whenever the copy contains `{{first_name}}` or `{{company_name}}` — essentially every Navreo campaign. It replaces the "Lead Field Hygiene" section that used to live in `lilly-personalisation` (now retired); the cleaning lives here so QA owns the gate end-to-end.

#### Run

Detection only (default):

```bash
SMARTLEAD_API_KEY=$key python3 ~/.claude/skills/lilly-qa/scripts/check_lead_field_hygiene.py \
  --campaign-id <id>
```

Detection + apply (after the user reads the report and OKs the fix):

```bash
SMARTLEAD_API_KEY=$key LILLY_QA_CONFIRMED=1 python3 \
  ~/.claude/skills/lilly-qa/scripts/check_lead_field_hygiene.py \
  --campaign-id <id> --apply
```

Never set `LILLY_QA_CONFIRMED=1` without explicit user approval in the conversation. Cleaning is destructive — original values are overwritten via `/campaigns/{id}/leads` POST.

#### Verdicts

Per the severity table in `references/lead-field-hygiene.md`:
- **❌ FAIL** — missing values OR FAIL-pattern dirty (legal suffix, URL, em-dash, all-numeric)
- **⚠️ WARN** — WARN-pattern dirty (profession tail, ALL-CAPS, lowercase start, parenthetical, auto-hyperlinking TLD)
- **✅ PASS** — clean

If FAIL findings affect ≥ 1% of leads, **block launch** until cleaned. WARN findings surface in the report but don't block. Manual-review cases (URLs in `company_name`, junk markers, identical first/company values) are written to `/tmp/lilly_qa_manual_review_{campaign}.csv` for the user to fix by hand — never silently clobbered.

#### Mode-specific behaviour

- **Mode 1 (read-only)**: run detection, fold findings into FAIL/WARN sections of Step 8 report. Do not push.
- **Mode 2 (propose fixes)**: run detection, surface the report, offer the dry-run diff (10 sample changes) as paste-ready text. User can apply via `lilly-updates-leads` or the Smartlead UI.
- **Mode 3 (apply fixes)**: run detection, surface dry-run, ask the user "Confirm push of N first_name + M company_name updates?", then re-run the script with `--apply LILLY_QA_CONFIRMED=1` only after explicit OK.

#### Skip rule

Skip Step 5d only when:
- Copy contains neither `{{first_name}}` nor `{{company_name}}` (rare for Navreo)
- The leads were imported from a known-clean source within this conversation (e.g. a freshly-exported CSV that was already normalised by `lilly-updates-leads`)

When in doubt, run it — detection is fast and free.

### Step 6: Augment with content-level review

The script catches mechanical issues. Then read the rendered copy yourself and look for:

- Awkward sentence flow
- Factual claims to sanity-check (specific numbers, named clients, time commitments)
- Tone mismatches between variants
- CTA repetition across follow-up steps
- Subject lines that are weak or duplicated
- Variable usage that depends on lead-data quality (e.g. `{{Why}}` integration into sentences). `{{Icebreaker}}` is covered deterministically in Step 5c — don't re-do here.
- Em-dashes (`—`) in body or subject. Per Navreo style they're a WARN; suggest comma, colon, period, or parenthesis replacements

These findings go into a separate "Content-level issues" section of the report. They're judgment calls, not deterministic checks.

### Step 7: Note API blind spots

Some settings the read API can't see. List them in the report under "🚫 Cannot verify via API". See `references/api-blind-spots.md`. The user verifies these in the Smartlead UI.

### Step 8: Output the report

Format: structured Markdown inline in the conversation. Sections in this order:

1. **Header**: campaign name, ID, status, date, playbook.
2. **❌ FAIL**: must-fix before launch.
3. **⚠️ WARN**: review before launch (mechanical issues, inconsistencies).
4. **Content-level issues**: judgment calls from human-style review.
5. **✅ PASS**: what's clean (be specific, don't just say "looks good").
6. **🚫 Cannot verify via API**: UI-only checks.
7. **Top priorities before launch**: ordered list of the most important fixes.

End the report with: "Want me to draft fixes? Or QA another campaign?"

### Step 9: If mode 2 or 3, prepare fixes

For mechanical fixes (deterministic: apostrophe standardisation, `&nbsp;` removal, common typos, em-dash replacement), apply them automatically. See `references/common-fixes.md` for the catalogue.

For editorial decisions (sentence rewrites, subject diversification, P.S. asymmetry between variants), present options and wait for user confirmation. Do NOT make editorial calls unilaterally.

### Step 10: If mode 3, attempt the save

**If the campaign has real send history, ask the user for an explicit go-ahead before writing** (state the fixes and confirm all ids will be carried). Then build the payload with the ID-intact recipe (verified 2026-08-02):

1. Re-fetch via `get_campaign_sequences` IMMEDIATELY before saving — ids must be fresh, never from the earlier QA fetch.
2. Build the POST body as `{"sequences": [...]}`, translating three names from the GET: steps wrapped in `sequences` (PLURAL), `sequence_variants` → `seq_variants`, `seq_delay_details.delayInDays` → `delay_in_days`.
3. Echo every step `id` and every variant `id` back UNCHANGED; apply only the approved mechanical fixes to `subject`/`email_body`. Never omit a variant — an omitted variant is deleted and its stats are orphaned permanently, no recovery.
4. Save, then verify: re-GET shows every pre-existing variant with its EXACT id, and `get_campaign_variant_statistics` still shows the prior sent/reply history. On a 429 (200 req/min account cap) wait ~70s and retry — never skip the verify. Worked payload example: `lilly-bot` → "THE ID-INTACT RECIPE".

Call `mcp__smartlead__smartlead_save_campaign_sequence` with the corrected payload. If it returns an error:

- Re-fetch the sequence to confirm nothing got damaged.
- Tell the user the API write failed.
- Fall through to mode 2: output the corrected copy as paste-ready text.

**Always re-fetch after a save attempt** to verify state — including that every pre-existing variant kept its exact `id`. Never trust that the save did what you intended without verifying.

## Critical rules

- **Never make editorial decisions silently.** Mechanical fixes only. Editorial decisions need user confirmation.
- **Always re-fetch after any save attempt** to verify state. The original copy must not be silently overwritten.
- **The script is a starting point, not the whole QA.** Always do the content-level read in Step 6 (that's where most real problems hide).
- **Variable case sensitivity is a recurring failure mode.** Always flag custom variables like `{{Icebreaker-2}}` or `{{PE_Firm}}` for column-header verification.
- **Don't skip the API blind spots section.** The user needs to know what wasn't checked.
- **No em-dashes in flagged copy.** Per Navreo style, em-dashes (`—`) in body or subject are a WARN; suggest comma, colon, period, or parenthesis replacements.
- **Icebreaker integrity (Step 5c) is required when `{{Icebreaker}}` is in copy.** Run BOTH sub-checks: (5c-a) name/company normalisation regex pass + (5c-b) coherence with email body. FAIL-verdict findings block launch; WARN-verdict findings surface in the report.
- **Standard-lead-field hygiene (Step 5d) is required when `{{first_name}}` or `{{company_name}}` is in copy.** Verify fill rate AND cleanliness on every lead. FAIL findings (missing values, legal suffixes, URLs, em-dashes) block launch when they affect ≥1% of leads. Cleaning pushes are destructive — always dry-run + explicit user confirmation before `--apply`.

## Hand-offs

- For campaign creation, sequence editing beyond mechanical fixes, or new copy generation: hand off to `lilly-bot`.
- For data-driven optimisation across live campaigns (reply rates, leads-to-add, variant pruning): see `lilly-optimiser`.
- For lead-data cleanup before re-import: see `lilly-updates-leads`.

## Files in this skill

- `references/checks.md`: full catalogue of automated checks with severity.
- `references/playbooks.md`: Generic vs Navreo profile rules.
- `references/common-fixes.md`: mechanical fix patterns with examples.
- `references/api-blind-spots.md`: settings the API can't see.
- `references/output-format.md`: the report template with examples.
- `references/lead-field-hygiene.md`: cleaning rules + severity table for Step 5d.
- `scripts/analyze_sequence.py`: the deterministic sequence-level check engine.
- `scripts/check_lead_variable_fill.py`: Step 5b — fill-rate check for custom_fields variables.
- `scripts/check_lead_field_hygiene.py`: Step 5d — fill-rate + hygiene for first_name / company_name.

Read the reference files when you need details on what they cover. SKILL.md is the workflow; the references are the depth.
