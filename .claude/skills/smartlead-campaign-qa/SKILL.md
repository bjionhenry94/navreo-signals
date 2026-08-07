---
name: smartlead-campaign-qa
description: Run quality assurance on a SmartLead email campaign before launch — checking sequence structure, copy, spintax, variables, formatting, and personalisation against a configurable playbook. Use whenever the user mentions QA'ing a SmartLead campaign, asks to "check" or "review" a campaign before sending, asks to validate email copy, asks about variants or spintax errors, asks to fix mechanical issues in campaign copy, or shares a campaign ID/name with intent to inspect it. Trigger this even if the user only says "review my campaign" or names a SmartLead campaign without explicitly saying "QA" — anyone working with SmartLead campaigns benefits from this skill before launch.
---

# SmartLead Campaign QA

A pre-launch quality gate for SmartLead email campaigns. Validates sequence structure, copy, spintax, variables, and personalisation; flags FAIL / WARN / PASS findings; optionally proposes or applies fixes.

## What this skill does

Three modes, picked by the user at the start of every QA session:

1. **READ-ONLY QA** — fetch the campaign and produce a structured findings report. No changes made.
2. **QA + PROPOSE FIXES** — same as above, plus output corrected copy as paste-ready text the user can drop into the SmartLead UI.
3. **QA + APPLY FIXES** — attempt to write corrected copy back via the SmartLead `save_campaign_sequences` tool. Falls back to mode 2 if the API rejects (often does — many integrations are read-only).

## When to trigger

The user is referring to a SmartLead campaign and any of:

- explicit QA request ("QA this campaign", "check this", "review", "audit", "validate before launch")
- they share a campaign ID or campaign name
- they ask about copy errors, spintax, variants, personalisation, or merge fields
- they ask to "fix" or "clean up" a campaign's copy
- they're preparing to launch and want pre-flight checks

If the user references a campaign but their intent is unclear, ASK which mode they want before proceeding.

## Workflow

### Step 1 — Ask which mode

Before doing anything, ask:

> Which mode do you want?
> 1. **Read-only QA** — I check and report, no changes
> 2. **QA + propose fixes** — I check, then output corrected copy you can paste yourself
> 3. **QA + apply fixes** — I check, then try to write the fixes directly via API (may not work depending on tool scope)

If they don't have a campaign ID handy, ask for the campaign **name or ID**. Search the campaign list if needed.

### Step 2 — Identify the SmartLead account

The user may have multiple SmartLead accounts connected (e.g. `smartlead-account1`, `smartlead-account2`). If unclear, ask. If the user mentions "Account 2" or similar, use that. If they just say "my campaign", check the most recently active account first; if not found, try the others.

### Step 3 — Ask about playbook

> Which playbook should I QA against?
> - **Generic** — universal best practices (no client-specific rules)
> - **Navreo** — adds Navreo-specific rules (3-day minimum delays, plain-text only, P.S. format, etc.)
> - **Custom** — paste your playbook config and I'll use that

See `references/playbooks.md` for what each profile includes.

### Step 4 — Fetch sequences

Call `get_campaign_sequences` with the campaign ID. Save the raw JSON.

### Step 5 — Run the analyser

Run `scripts/analyze_sequence.py` against the sequence JSON. It emits structured findings: FAIL / WARN / PASS, plus issue location and severity. See `references/checks.md` for the full list of automated checks.

### Step 6 — Augment with content-level review

The script catches mechanical issues. Then read the rendered copy yourself and look for:

- Awkward sentence flow
- Factual claims that should be sanity-checked (specific numbers, named clients, time commitments)
- Tone mismatches between variants
- CTA repetition across follow-up steps
- Subject lines that are weak or duplicated
- Variable usage that depends on lead-data quality (e.g. `{{Why}}` / `{{Icebreaker}}` integration into sentences)

These findings go into a separate "Content-level issues" section of the report — they're judgment calls, not deterministic checks.

### Step 7 — Note API blind spots

There are settings the read API can't see. List them in the report under "🚫 Cannot verify via API" — see `references/api-blind-spots.md`. The user needs to verify these in the SmartLead UI.

### Step 8 — Output the report

Format: structured Markdown inline in the conversation. Sections in this order:

1. **Header** — campaign name, ID, status, date
2. **❌ FAIL** — must-fix before launch
3. **⚠️ WARN** — review before launch (mechanical issues, inconsistencies)
4. **Content-level issues** — judgment calls from human-style review
5. **✅ PASS** — what's clean (be specific, don't just say "looks good")
6. **🚫 Cannot verify via API** — UI-only checks
7. **Top priorities before launch** — ordered list of the most important fixes

End the report with a question: "Want me to draft fixes? / Want me to QA another campaign?"

### Step 9 — If mode 2 or 3, prepare fixes

For mechanical fixes (deterministic — apostrophe standardisation, `&nbsp;` removal, common typos), apply them automatically. See `references/common-fixes.md` for the catalogue.

For editorial decisions (sentence rewrites, subject diversification, P.S. asymmetry between variants), present options and wait for user confirmation. Do NOT make editorial calls unilaterally.

### Step 10 — If mode 3, attempt the save

Call `save_campaign_sequences` with the corrected payload. If it returns 400 or any error:
- Re-fetch sequences to confirm nothing got damaged
- Tell the user the API write failed
- Fall through to mode 2: output the corrected copy as paste-ready text

## Critical rules

- **Never make editorial decisions silently.** Mechanical fixes only. Editorial = user confirms.
- **Always re-fetch after any save attempt** to verify state. The original copy must not be silently overwritten.
- **The script is a starting point, not the whole QA.** Always do the content-level read in Step 6 — that's where most real problems hide.
- **Variable case sensitivity is a recurring failure mode.** Always flag custom variables like `{{Icebreaker-2}}` or `{{PE_Firm}}` for column-header verification.
- **Don't skip the API blind spots section.** The user needs to know what wasn't checked.

## Files in this skill

- `references/checks.md` — full catalogue of automated checks with severity
- `references/playbooks.md` — Generic vs Navreo profile rules
- `references/common-fixes.md` — mechanical fix patterns with examples
- `references/api-blind-spots.md` — settings the API can't see
- `references/output-format.md` — the report template with examples
- `scripts/analyze_sequence.py` — the deterministic check engine

Read the reference files when you need details on what they cover. The SKILL.md is the workflow; the references are the depth.
