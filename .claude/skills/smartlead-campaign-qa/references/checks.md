# Automated Checks Catalogue

Every deterministic check the analyser runs, with severity and rationale.

## Sequence structure (FAIL severity)

| Check | Why |
|---|---|
| Step 1 has at least one variant with non-empty subject | Empty subjects don't send |
| Step 1 has at least one variant with non-empty body | Empty bodies don't send |
| Every follow-up step has empty subject (Step 2+) | Follow-ups thread to the original; subject must be empty per SmartLead spec |
| Every follow-up step has non-empty body | Empty body = no email |
| `%signature%` token present in every active variant body | Without it, no signature appears |
| Delay between Step 1 → Step 2 ≥ playbook minimum (default 3 days) | Anti-spam best practice |
| All step delays ≥ playbook minimum after Step 1 | Same |

## Spintax (FAIL severity)

| Check | Why |
|---|---|
| No malformed single-curly groups (`{` without matching `}` or no `\|` inside non-empty group) | Will render literally instead of varying |
| No empty options inside spintax (`{a\|\|b}`) | Sometimes renders as blank |
| No nested spintax (excluding `{{var}}` inside spintax options — that's allowed) | SmartLead doesn't reliably resolve nested spintax |

## Variables (FAIL or WARN)

| Check | Severity | Why |
|---|---|---|
| No `[bracket]`-style placeholders | FAIL | SmartLead doesn't recognize them — renders literally |
| All `{{var}}` use SmartLead double-brace syntax | FAIL | Single-brace would be treated as spintax |
| Custom variables (anything not in default set) flagged for column-header verification | WARN | Case-sensitive lookup; `{{PE_Firm}}` ≠ `{{pe_firm}}` |
| If variable is dropped into sentence structure (e.g. `If we could {{Why}},`), flag for value-format review | WARN | Requires verb phrase, not noun phrase |
| Mixed variable casing between variants (one variant has it, another doesn't) | WARN | Likely a missed update |

## Encoding & formatting (FAIL or WARN)

| Check | Severity | Why |
|---|---|---|
| No curly apostrophes (`'`, `'`) | FAIL | Render as garbage in some plain-text clients |
| No curly quotes (`"`, `"`) | FAIL | Same |
| No em-dashes (`—`) | WARN | Same risk; less common |
| No mixed straight (`'`) and curly (`'`) apostrophes in same body | FAIL | Inconsistency suggests partial copy-paste from another source |
| No stray `&nbsp;` after `{{Icebreaker}}` or other variables | WARN | Renders as visible space artefact |
| No `&nbsp;` immediately before `%signature%` | WARN | Pushes signature off alignment |
| No inline `style=` attributes on HTML elements | WARN | Stripped by force-plain-text but signals copy-paste from rich text editor |

## Common typos & style (WARN severity)

The analyser checks for known recurring issues from prior QA runs:

| Pattern | Replacement | Notes |
|---|---|---|
| `Alternatively if` | `Alternatively, if` | Missing comma after introductory adverb |
| `which would hold-back` | `that would hold back` | Wrong relative pronoun + spurious hyphen |
| `sales-teams` | `sales teams` | Hyphen wrong |
| `P.S -` | `P.S.` | Convention is period + space (or comma) |
| `P.S. -` | `P.S.` | Same |
| `tech-stack` (in body, when used as compound noun) | `tech stack` | Optional — depends on style guide |

These are pattern matches; the script flags them but doesn't auto-fix unless mechanical-fix mode is on.

## Subject line (WARN severity)

| Check | Why |
|---|---|
| Step 1 subjects across variants — flag if all identical | Subject A/B testing has no signal if subjects are the same |
| Subject doesn't start with capital letter | Stylistic; sometimes intentional for casual feel |
| Subject contains supported variables only | `{{first_name}}`, `{{company_name}}`, etc. |
| Subject doesn't have spintax with empty options | Same risk as body |

## Variant consistency (WARN severity)

| Check | Why |
|---|---|
| Active variant count vs deleted variant count — flag if there are deleted ones | User may have intended to remove them; verify in UI |
| All active variants use the same custom variables (e.g. all use `{{PE_Firm}}` or none do) | If one variant skips a personalisation field, ~25% of leads get less-personalised email |
| All active variants have similar structure (greeting, body, sign-off, P.S.) | Asymmetry is allowed but should be intentional |

## Schedule (FAIL or WARN — depends on playbook)

| Check | Severity | Why |
|---|---|---|
| Step 1 first-touch delay = 0 (default convention) | WARN | Most outbound sends immediately on import; non-zero may be intentional |
| Step delays ≥ playbook minimum | FAIL | Hard rule per playbook |

## What the script does NOT check (handle in Step 6)

- Sentence flow and readability
- Tone consistency between variants
- Factual accuracy of named clients, percentages, time commitments
- Whether `{{Why}}`-style verb-phrase variables will produce readable sentences (depends on data)
- CTA freshness across follow-up steps
- Subject line strength (just diversity)
- Whether the offer is compelling
- Lead-list quality (different tool entirely)
