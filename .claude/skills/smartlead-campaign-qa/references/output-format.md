# Report Output Format

Use this exact structure for every QA report. Keep tone direct, specific, and actionable.

## Template

```markdown
# QA Report — [Campaign Name]

**Campaign ID:** [id] • **Status:** [DRAFTED/ACTIVE/...] • **Date:** [yyyy-mm-dd] • **Playbook:** [Generic/Navreo/Custom]

---

## ❌ FAIL — must fix before launch

[Numbered list. Each item: 1-2 sentence description, then a quoted example or specific location. If 0 fails, write "None — clean run."]

## ⚠️ WARN — review before launch

[Numbered list. Each item: 1-2 sentences with location and rationale.]

## Content-level issues (judgment calls)

[The findings from your manual content read in Step 6. Awkward sentences, factual claims to verify, tone, CTA repetition, weak subjects, etc. These are NOT auto-detected — they're things you noticed reading the rendered copy.]

## ✅ PASS — these are clean

[Specific bullet list of what was checked and passed. Don't say "looks good" — say what you actually verified.]

## 🚫 Cannot verify via API (need UI eyeballs)

[Standard list from references/api-blind-spots.md — include this section even if no other findings.]

## Top priorities before launch

[Ordered list, 3-7 items. Most important fix first. Group by mechanical-easy vs editorial-decision. End with "Want me to draft fixes?" or similar prompt.]
```

## Tone rules

- **Be specific.** "Step 1/B uses curly apostrophe in `we'll`" — not "some apostrophes are wrong".
- **Quote the actual problem text** when flagging it. The user shouldn't have to hunt.
- **Don't pad PASS items.** Listing 20 things that passed is fine; listing 50 is noise. Group when you can ("Spintax syntax valid in all variants").
- **Lead with the most important issue.** Don't bury a curly apostrophe under 12 nitpicks.
- **Don't be cheerleader-y.** "Great campaign!" / "Looking good!" — skip it. The user wants the assessment, not a vibes check.
- **Don't apologize for finding issues.** "Unfortunately I found..." is wrong. Just report.

## Examples of good vs bad findings

### Bad

> ⚠️ The variants might have some inconsistencies you may want to look at.

### Good

> ⚠️ **Variant A has no `{{Icebreaker}}`, Variant B does.** With randomized distribution, ~50% of leads will get a less-personalised email. Decision needed: add Icebreaker to A, or remove from B?

### Bad

> ❌ Some text formatting issues found.

### Good

> ❌ **Step 2 contains a curly apostrophe** in `we'll {take|use|leverage}`. Will likely render as `â€™` garbage in some plain-text email clients. Standardise to straight `'`.

## When findings are 0

A clean campaign is rare. If you genuinely have zero FAILs, say so plainly:

> ## ❌ FAIL — must fix before launch
> 
> None. Mechanical checks all clean.

Don't pad. Don't invent issues to fill space.

## When you can't fetch the campaign

If the campaign ID returns 404 or the leads endpoint fails, say so directly and stop. Don't speculate.

> Couldn't fetch campaign 3217780 — got 404 on `get_campaign_sequences`. Either the ID is wrong, the campaign is in a different SmartLead account, or my access changed. Can you confirm the ID?
