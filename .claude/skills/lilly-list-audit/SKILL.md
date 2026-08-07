---
name: lilly-list-audit
description: >-
  Audit the composition of the leads ALREADY ENROLLED in an existing Smartlead campaign, by job
  function and ICP fit. Pulls every lead (or a fast random sample), classifies each title into
  OWNER/EXEC, SALES-LEADER, SALES-SUPPORT, MARKETING, CREATIVE, ACCOUNT, OPS, TECH, FINANCE, HR,
  LEGAL, etc., and reports how much of the list is on-ICP vs off-ICP, with CSV exports. Use this
  whenever the user wants to spot-check or audit WHO is actually in a campaign: "audit the list in
  campaign X", "what's the title / function mix", "how much of this campaign is sales leaders /
  on-ICP", "are the right people in this list", "spot test 100 leads at random", "is this campaign
  full of non-sales people", "share the owner/exec roles", "compare the Clay vs Prospeo list
  quality". This is READ-ONLY and runs against a LIVE campaign's enrolled leads. It is NOT lilly-qa
  (pre-launch copy / sequence / spintax / variable QA) and NOT lilly-lead-score (scoring a company
  CSV before import). Trigger it even when the user just names a Smartlead campaign and asks "who is
  in this?" or "is this list any good?".
---

# lilly-list-audit

Audit the job-function / ICP composition of the leads inside a live Smartlead campaign. The point
is to answer "are the right people actually in this campaign?" after it has been built and loaded,
which is different from checking the copy (`lilly-qa`) or scoring a company list before import
(`lilly-lead-score`).

This skill is **read-only**. It only issues GET requests. It never adds, edits, or removes leads.

## When to use

- The user wants a function / ICP breakdown of an existing campaign's leads.
- A "spot test": sample N leads at random to gauge list quality fast.
- Comparing two campaigns built from different sources (e.g. Clay vs Prospeo) on list quality.
- The user asks who the owners / execs / sales leaders / non-sales people in a campaign are.

When NOT to use: pre-launch copy/sequence checks (`lilly-qa`), scoring a fresh company CSV before
import (`lilly-lead-score`), or fixing lead field values (`lilly-updates-leads`).

## Running it

The script is `scripts/audit_campaign.py`. It reads `SMARTLEAD_API_KEY` from the environment
(Navreo: `source ~/.navreo-keys.env` first).

```bash
source ~/.navreo-keys.env
# full audit (all leads):
python3 scripts/audit_campaign.py --campaign-id 3285048
# quick spot-test (random sample), the fast first read:
python3 scripts/audit_campaign.py --campaign-id 3285048 --sample 100
# retarget for a non-sales ICP campaign:
python3 scripts/audit_campaign.py --campaign-id 3285048 --on-icp "MARKETING/PR,OWNER/EXEC"
```

If the user gives a campaign **name** instead of an id, resolve it first: `GET /campaigns` and match
the name, or ask which one if ambiguous. Default `--out-dir` is `~/Downloads`.

For a quick read, start with `--sample 100` (it extrapolates the off-ICP rate to the full campaign).
Run the full audit when the user wants the complete, actionable lists.

## Reading the output

The report gives the **on-ICP %** (headline), the full function mix (each bucket flagged ON or off),
and OFF-ICP examples per bucket. Two CSVs are written: `..._all.csv` (every lead with its function
label) and `..._off-icp.csv` (just the off-ICP leads, for review).

Interpret it honestly, in plain English (no jargon like "fit %", "substring", "array"):

- The headline is the share of titled leads whose function matches the target ICP.
- Treat `OTHER-LEADERSHIP` as the **uncertain** bucket: bare "Director" / "Partner" / "Growth Lead"
  titles with no function word. Some may be real targets with truncated titles. Do not call them
  "definitely wrong" without eyeballing the off-ICP CSV.
- The classifier is heuristic. Before reporting big numbers, sanity-check a handful of titles in the
  CSV so you can stand behind the figure.

The classifier and its non-obvious rules (word-boundary abbreviation matching, why "Vice President"
is not an exec, why "Partner" is owner-level, ambiguous C-level abbreviations, how to retarget the
ICP) are documented in `references/classification-rules.md`. Read it before tuning `classify()`.

## Presenting results to the user

Render findings as tables, not prose. The reader wants to scan composition, not read paragraphs.
Use one of two formats depending on how many campaigns you audited.

### One campaign: the off-ICP sub-type breakdown

Open with a single header line: `<Campaign name>  -  <N> off-ICP`. Then a table of the off-ICP
leads grouped into two tiers, so confidently-wrong is visually separated from merely-ambiguous:

| Sub-type | Count | % of off-ICP | Example titles |
|---|---|---|---|
| **Tier 1: clearly wrong function (~3,100)** | | | |
| Creative/Content | 1,401 | 21% | Art Director, Creative Director |
| Marketing/PR/Comms | 931 | 14% | Director of Marketing, Brand Director |
| Account/Client services | 406 | 6% | Client Director, Director of Client Success |
| Operations/Delivery/PM | 191 | 3% | Operations Director, Delivery Director |
| Tech/Product/Eng | 74 | 1% | Data Engineering Director, Product Director |
| HR/Talent, Finance, Legal | 102 | 2% | HR Director, CFO & Director |
| **Tier 2: generic / ambiguous (~3,450)** | | | |
| Generic leadership (Dir/Mgr/Officer, no function word) | 2,728 | 42% | "Director", "Growth Lead" |
| Other | 728 | 11% | "B2B Growth Strategist", "Demand Strategy" |

Tier 1 is the concrete off-target functions. Tier 2 is `OTHER-LEADERSHIP` + `OTHER`, the bare-title
roles you cannot confirm are wrong. Keeping them apart is the whole point: it stops a headline like
"52% off-ICP" being read as "52% definitely wrong" when half of it is unconfirmed.

### Several campaigns: the scorecard

When auditing or comparing a book of campaigns (e.g. a spot-test across many), give one compact
scorecard, one row per campaign:

| Campaign | n | On-ICP % (grade) | What carried it |
|---|---|---|---|
| Agency Sales Leaders (Prospeo) | 100 | 97% (A+) | title 100% on-function |
| Agency Sales Leaders (Clay) | 100 | 89% (B) | headline masks ~51% true Tier-1 fit |
| CEO's Leaders | 9 | n/a | only 9 leads, meaningless |

The `What carried it` column is the most important one and is non-negotiable: it is where you state
the truth the single number hides. Always flag:

- **Tiny n** (under ~50 sampled): the grade is noise, say so plainly.
- **Headline masking true fit**: when a healthy on-ICP % leans on the ambiguous Tier-2 bucket, or
  only a fraction are confidently on-function, give the real Tier-1 figure next to it.
- **Hygiene vs function**: a list can be clean (verified, deduped) and still be the wrong people. If
  the grade only reflects hygiene, label it "hygiene only" and report the title-fit % separately.

Grade bands from on-ICP % of titled leads: A+ >=95, A 90-94, B+ 85-89, B 80-84, C 70-79, D 60-69,
F <60. The grade is a convenience; the `What carried it` note is what the reader should actually trust.

## Keep running until at least B+ (>=85%)

One audit is a checkpoint, not a verdict. **If the on-ICP rate is below B+ (85%), the list is not
ready.** Treat the audit as the first turn of a loop, not a one-off, and say so to the user:

1. Report the grade and, crucially, **name what is leaking** (the off-ICP buckets + example titles).
2. **Prompt the user to tighten and re-run, explicitly.** e.g. *"That's a C at 74% - below our B+
   bar. The leak is mostly Ops and wholesale Sales. Want me to exclude those and re-pull a fresh
   100?"* Never let a sub-B+ list proceed silently.
3. Tighten the targeting, re-pull a fresh batch, and **re-audit. Repeat until the grade is B+ or
   better.** Each pass should name the lever it changed so the lift is traceable.

Tightening levers that work (proven on the Amplifyy build, which climbed 38% -> 86% -> 95% over
three passes):
- **Exclude the leaking function by title.** A broad seniority pull (e.g. `Founder/Owner + C-Suite`)
  drags in back-office chiefs; a `person_job_title.exclude` on COO/CFO/CTO/Chief-of-Staff strips
  them. Exact-match exclude is leaky on combined/parenthetical variants ("COO (fractional)"), so
  expect a residual ~1-3%.
- **Prefer exact-title include-nets over broad department filters** for functional roles. Department
  buckets are noisy: a `dept=Marketing` pull leaked Customer-Experience / Content / Creative (~40%
  off), while the exact eCommerce and CMO/marketing title-nets audited 100% clean.
- **Drop whole off-ICP function buckets from the pull.** For a consumer-brand Amazon ICP, generic
  `dept=Sales` is ~94% wholesale/field/retail (not the buyer), so it is excluded entirely.
- **Split a fuzzy seniority band by the leaking function** (count founders/owners separately from
  functional chiefs, target each with the right filter).

The goal of the loop is a list you would stand behind, not a number. Stop at B+; push to A/A+ only
if the remaining leak is cheap to strip.

## Acting on the findings

This skill stops at the audit on purpose. Removing off-ICP leads from a live campaign is destructive
and has several silent traps (backup-before-delete, reply-guard, async uploads, the reversed
`ignore_duplicate_leads_in_other_campaign` flag). If the user wants to prune or restore based on the
audit, read `references/acting-on-results.md` first and confirm the exact scope with them before
touching anything.

## Files

- `scripts/audit_campaign.py` - the read-only audit (pull, classify, report, export CSVs).
- `references/classification-rules.md` - the function taxonomy, the gotchas, and how to retarget.
- `references/acting-on-results.md` - the rules to follow IF you later remove/restore leads.

## Related skills

- `lilly-qa` - pre-launch copy / sequence / spintax / variable QA (different job).
- `lilly-lead-score` - scores a company CSV against an ICP before import (pre-campaign).
- `lilly-updates-leads` - fixes / normalises lead field values inside a campaign.
- `lilly-optimiser` - performance optimisation of running campaigns.
