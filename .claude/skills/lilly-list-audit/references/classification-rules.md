# Classification rules and gotchas

The function classifier lives in `scripts/audit_campaign.py` (`classify()`). This file explains
the taxonomy, the hard-won gotchas, and how to point the audit at a different ICP. Read it before
you tune the classifier, because most of these rules exist to stop specific real-world mistakes.

## Function buckets

Every titled lead is assigned exactly ONE function label:

| Label | What it captures | Default ICP |
|---|---|---|
| `OWNER/EXEC` | Founder, Owner, CEO, President (not VP), Managing Director, Managing Partner, Principal, Chair, equity Partner | ON |
| `SALES-LEADER` | Sales / Revenue / Commercial / BD / New Business / Growth chiefs and leaders | ON |
| `SALES-SUPPORT` | Sales Ops, Sales Enablement, RevOps, Pre-Sales | ON |
| `MARKETING/PR` | CMO, Marketing, Brand, Comms, Social, SEO/PPC, Demand Gen | off |
| `CREATIVE/CONTENT` | Creative/Art/Design Director, Editorial, Content, Copy, Video | off |
| `ACCOUNT/CLIENT` | Account / Client services, Customer Success | off |
| `OPERATIONS/DELIVERY` | COO, Operations, Delivery, Project/Program Manager, PMO | off |
| `TECH/PRODUCT` | CTO/CIO, Engineering, Software, Data, Product | off |
| `FINANCE` | CFO, Finance, Accounting, Controller | off |
| `HR/TALENT` | People, Talent, Recruiting, HR, L&D | off |
| `LEGAL` | Legal, Counsel, Compliance | off |
| `OTHER-LEADERSHIP` | Bare Director / Manager / Officer / Head / Lead with no function word | off (ambiguous) |
| `OTHER` | Anything else | off |
| `UNTITLED` | No title found; excluded from percentages | n/a |

## The gotchas (and why they matter)

**1. Match abbreviations on word boundaries, never as substrings.** This is the single biggest
trap. `"cto" in "Director"` is True (`Dire-cto-r`), so a naive substring check tags every Director
as a CTO. The same hides `cro`, `cso`, `cio`, `coo` inside other words. The classifier uses
`\bcto\b` style regex. If you add an abbreviation, use the `wb()` helper, never `in`.

**2. "Vice President" contains "president".** If the owner check sees "president" it will pull every
VP into `OWNER/EXEC`, which is wrong: a VP is a function leader (VP Sales is sales, VP Marketing is
marketing). `is_vp()` detects VP-ness and keeps it out of the owner bucket so VPs land in their
function instead.

**3. "Partner" / "Founding Partner" is an OWNER, even alongside a function.** At agencies and
consultancies, "Founding Partner, Creative Director" or "Partner & CMO" is a business owner who also
runs a function. Scoring them on the functional half ("Creative", "Marketing") misclassifies an owner
as off-ICP. The owner check runs FIRST and `is_owner_partner()` claims these, after excluding the
partnerships / HR "business partner" noise (see `PARTNER_NOISE`) which are not ownership.

**4. Some C-level abbreviations are genuinely ambiguous.** `CSO` = Chief Sales OR Chief Strategy OR
Chief Security. `CCO` = Chief Commercial OR Chief Creative OR Chief Content. Because of that, the
classifier does NOT treat bare `cso`/`cco`/`cgo` as sales. It relies on spelled-out forms
("chief revenue", "chief sales", "chief commercial", "chief growth") plus `cro`. Sales-relevant
chiefs are caught; ambiguous ones fall through to their function or to `OTHER-LEADERSHIP`. If you
widen this, document the ambiguity.

**5. The title lives in `custom_fields`, not a column.** Smartlead returns leads with the title
inside `custom_fields` under keys like `Title` / `Job Title`. `title_of()` checks the common
variants. If a campaign stores titles under a non-standard key, add it to `TITLE_KEYS`.

**6. `OTHER-LEADERSHIP` is the "look before you act" bucket.** A bare "Director" or "Partner Lead"
or "Growth Lead" has no function word, so it could be a sales director with a truncated title or any
function. The audit reports it as off-ICP, but it is the LEAST certain bucket. Never treat it as
"definitely wrong" without eyeballing the off-ICP CSV.

**7. Growth / demand / strategy are borderline GTM.** "Growth Lead", "Demand Strategist",
"Strategy Director" sit between sales and marketing. Only "head of growth", "chief growth",
"vp growth" are scored as sales-leader; the rest fall to `OTHER`/`OTHER-LEADERSHIP`. This is
deliberate, not a bug. Decide per brief whether growth counts as on-ICP.

## Retargeting the ICP (non-sales campaigns)

The default ON-ICP set is `OWNER/EXEC, SALES-LEADER, SALES-SUPPORT`, because Navreo's campaigns
target commercial decision-makers. To audit a campaign aimed at a different function, pass
`--on-icp` with the labels that should count as on-target, for example:

- Heads-of-Marketing campaign: `--on-icp "MARKETING/PR,OWNER/EXEC"`
- Ops / RevOps campaign: `--on-icp "OPERATIONS/DELIVERY,SALES-SUPPORT"`

The classifier still assigns the same function labels; only the ON/OFF split changes. If a campaign
targets a function the taxonomy lumps together (e.g. you need to split "Demand Gen" out of
`MARKETING/PR`), add a more specific branch in `classify()` ABOVE the broader one, and keep the
word-boundary rule in mind.
