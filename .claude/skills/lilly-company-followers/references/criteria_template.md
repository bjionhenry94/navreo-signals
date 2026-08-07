# Qualification Criteria Template

Send this verbatim to the user in Step 0 of every run, with any pre-fillable fields filled in (and explicitly called out as inferred so the user can correct them).

---

```
I'll qualify the list once you confirm the criteria for this task. Fill in the
sections below — or paste a freeform description and I'll structure it back to you.

1. ROLE CRITERIA *(required)*
   Which titles qualify? Either:
   • Paste a list of titles (e.g. "CEO, Founder, VP Sales, Head of Marketing,
     Marketing Director, ..."), OR
   • Describe by rule (e.g. "Director and above in sales/marketing/revenue/growth,
     plus all founder/CEO-tier roles")
   Anything to exclude even if it matches keywords? (e.g. "exclude any 'Manager'
   level even with a domain word")
   →

2. LOCATION CRITERIA *(required)*
   • Any location, or specific countries, or High-GDP preset?
     (High-GDP preset = US, CA, UK, IE, DE, CH, AT, SE, NO, DK, FI, NL, BE, LU, FR,
     IT, ES, AU, NZ, JP, SG, HK, UAE, KSA, IL)
   • Match against company location or person location? (Company location is
     usually more reliable for B2B targeting.)
   →

3. COMPANY SIZE CRITERIA  *(only if the file has employee counts)*
   • Minimum employee count? (e.g. 11+)
   • US-based age rule? (e.g. "if US-based, company must also be 5+ years old")
   • If the file has no size data, write "N/A" and I'll skip this rule and tell
     you which rows weren't size-checked.
   →

4. SENDER COMPANY *(required — one sentence on what YOU sell)*
   This is used to identify which companies in the list are competitors or
   adjacencies we should avoid.
   Example: "Navreo runs outbound sales campaigns for B2B companies — we build
   Smartlead infrastructure, write copy, and book meetings."
   →

5. AVOID LIST *(required — categories of companies to skip)*
   List the categories of companies that should be flagged "1 - avoid". Common
   ones for outbound-services senders:
   • Sales enablement, GTM services, go-to-market consulting
   • Cold outbound agencies, lead generation, appointment setting
   • Sales outsourcing, SDR/BDR-as-a-service, fractional sales leaders
   • RevOps services, demand generation agencies, ABM services
   • Outbound tooling vendors (e.g. Smartlead, Apollo, Clay, Outreach.io,
     Instantly, Lemlist, Salesloft, Gong)
   Add or remove based on this run's intent.
   →

6. SPECIAL RULES *(optional)*
   Anything else specific to this upload, e.g.:
   • Dedupe by company (one prospect per company)
   • Exclude prospects without a LinkedIn URL
   • Only include prospects created in the last 30 days
   • Prefer email_first; fall back to email_second if blank
   • Exclude any title with "Sales Operations" / "Sales Enablement" inside our own
     company list (since those are the buyers we're avoiding)
   →
```

---

## Pre-fill rules

When you (Claude) send this to the user, look back at the conversation for context that lets you pre-fill any field — but always show the pre-filled value with a clear marker so the user can correct it:

```
1. ROLE CRITERIA  *(pre-filled from earlier — confirm or edit)*
   Director-and-above in sales/marketing/revenue/growth, plus founder/CEO tier.
   Same as the 6Sense / Boomerang qualification we ran on Apr 23.

2. LOCATION CRITERIA  *(pre-filled — confirm or edit)*
   High-GDP preset, matched against company location.

[etc.]
```

Pre-fillable signals to look for in the conversation:
- Earlier qualification runs in the same conversation (re-use those criteria)
- The Navreo-default ICP (high-GDP, director-and-above sales/marketing, 11+ headcount) when working with Bjion's lists — see `navreo_default_preset.md`
- The user's earlier-stated sender description (look for phrases like "what we sell" / "our offer")
- The avoid-list from earlier runs

If nothing is inferable, send the template empty and let the user fill all 6 fields.

## Freeform criteria handling

If the user pastes freeform criteria instead of filling the template, your job is to **restructure their answer back into the 6-field template** and ask "did I capture this right?" — don't proceed to qualification until they explicitly confirm. Misalignment on the criteria is the most expensive mistake at this step (every downstream row is mis-judged).
