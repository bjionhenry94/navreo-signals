# Lead Field Hygiene — first_name + company_name cleaning rules

`{{first_name}}` and `{{company_name}}` render directly in every email. Messy values destroy deliverability and credibility:

- `Hi JOHN,` (shouting) → reads like a cold-email blast
- `Hi dr. mary-jane,` (lowercase title) → reads like a bot
- `recorded a video for Smith Consulting LLC...` (legal suffix in a sentence) → reads like a contract
- `recorded a video for Pereira Dabul Advogados...` (profession tail in a sentence) → stilted
- `Hi ,` (empty name) → broken render, immediate delete
- `recorded a video for Immersa.ai...` (TLD-shaped brand) → email client auto-hyperlinks the brand mid-sentence

The cleaner used by `scripts/check_lead_field_hygiene.py` applies the rules below. Both per-language coverage and the auto-hyperlinking TLD list are intentionally exhaustive — the cost of a regex line is zero, the cost of a missed dirty value rendering in a live send is high.

## First-name cleaning rules

1. **Whitespace and casing**
   - Strip leading/trailing whitespace
   - Title-case: `JOHN → John`, `john → John`, `jOhN → John`
   - Preserve hyphens: `mary-jane → Mary-Jane`
   - Preserve compound first names with spaces: `mary jane → Mary Jane` (common in Spanish/Portuguese)
   - Preserve diacritics: `álvaro → Álvaro` (Smartlead renders UTF-8 fine)

2. **Strip titles and prefixes** (then re-clean remainder)
   - English: `Dr.`, `Mr.`, `Mrs.`, `Ms.`, `Miss`, `Prof.`, `Rev.`, `Sir`, `Lord`, `Dame`
   - DACH: `Herr`, `Frau`, `Dr.`, `Dipl.-Ing.`, `Ing.`
   - Romance: `M.`, `Mme.`, `Sr.`, `Sra.`, `Dr.`, `Ing.`
   - Example: `Dr. John → John`, `M. Jean-Pierre → Jean-Pierre`

3. **Always use only the first whitespace-separated token**
   - `John Smith → John` (drop family name if it crept in)
   - `John F. → John` (drop middle initial)
   - `John Smith Jr. → John` (drop suffix)
   - `Mary Jane → Mary` (compound first names with a space collapse to the first token)
   - Hyphenated names stay intact because they are a single token: `Jean-Pierre Smith → Jean-Pierre`
   - This is a silent auto-fix, not a flag — multi-word first names are never reported as "dirty"; they're just cleaned

4. **Email-derived fallback** (when `first_name` is empty but email exists)
   - Extract local part: `john.smith@acme.com → john` → title-case → `John`
   - **Only if** the local part looks name-like. Role-based mailboxes (`info`, `contact`, `sales`, `hello`, `office`, `admin`, `enquiries`) → fallback to `there`
   - If name-like prefix has a dot, take the first segment: `john.smith → John`

5. **Junk detection** (fallback to "there" and flag for review)
   - Single-character values (`'J'`)
   - Obvious junk: `test`, `unknown`, `user`, `user123`, numeric-only, empty string
   - Identical to `company_name` (data-entry mix-up)

6. **Safety rail** — never push an empty or single-character first_name. If cleaning would produce that, fall back to a generic greeting marker (user's choice: either `there` so emails say "Hi there," or skip the lead entirely and flag).

## Company-name cleaning rules

1. **Whitespace and casing**
   - Strip leading/trailing whitespace
   - Preserve brand casing: `PwC`, `IBM`, `SIHL`, `McKinsey` stay as-is
   - Preserve lowercase-start brand styling: `iCrossing`, `iFrog`, `inBLUME`, `iStoria`, `eBay` stay as-is — that IS the brand's chosen casing
   - ALL CAPS: Title Case it (`ACME CORP → Acme`, `IMAGEMOTION → Imagemotion`, `WESEO → Weseo`) **unless** the name is ≤4 letters and all-caps (likely a real acronym — keep `SIHL`, `IBM`, `KPMG`, `WPP`, `BCG`)

2. **Strip legal entity suffixes** (when they are the trailing tokens)
   - English: `LLC`, `L.L.C.`, `Ltd`, `Ltd.`, `Limited`, `Inc`, `Inc.`, `Incorporated`, `Corp`, `Corp.`, `Corporation`, `Co`, `Co.`, `Company`, `Pty`, `Pty Ltd`, `PLC`, `P.L.C.`, `LLP`
   - DACH: `GmbH`, `GmbH & Co. KG`, `AG`, `UG`, `KG`, `OHG`, `eG`, `mbH`
   - Romance: `S.A.`, `S.L.`, `S.R.L.`, `SRL`, `S.A.S.`, `S.p.A.`, `SPA`, `SARL`, `SAS`, `SASU`, `EURL`
   - Portuguese/Brazilian: `Ltda`, `Ltda.`, `ME`, `EIRELI`, `Limitada`, `S.A.`
   - Dutch: `B.V.`, `BV`, `N.V.`, `NV`, `V.O.F.`
   - Nordic: `AB`, `ApS`, `A/S`, `AS`, `Oy`, `Oyj`
   - Japanese: `K.K.`, `Co. Ltd.`, `株式会社` (leading or trailing)
   - Indian: `Pvt Ltd`, `Pvt.`, `Pvt. Ltd.`, `Private Limited`
   - CEE: `S.R.O.` (Czech), `Sp. z o.o.` (Polish), `OOO` (Russian), `Kft.` (Hungarian)
   - Mexican: `S.A. de C.V.`
   - Examples: `Acme Corp Inc. → Acme`, `Schmidt GmbH & Co. KG → Schmidt`, `Silva Ltda → Silva`

3. **Strip profession tails** (when they are the trailing tokens and clearly describe the firm's profession, not the brand)
   - Legal: `Advogados` (PT), `Avvocati` (IT), `Avocats` (FR), `Abogados` (ES), `Rechtsanwälte` (DE), `Advocates`, `Attorneys`, `Law Office`, `Law Firm`, `Kancelaria` (PL), `Studio Legale` (IT)
   - Accounting: `Commercialisti` (IT), `CPA`, `Chartered Accountants`
   - Careful: keep `Consulting` / `Consultants` **when they're clearly part of the brand** (BCG → Boston Consulting Group). Drop only if a standalone suffix after a personal name (`Smith Consulting → Smith` is OK; `Boston Consulting Group → Boston Consulting Group` stays).

4. **Strip descriptive tails** (cautiously)
   - Parentheticals: `Acme (UK Operations) → Acme`, `Acme (Europe) → Acme`
   - **Acronym exception**: when the parenthetical IS the brand's acronym (2-6 uppercase letters), use the acronym instead of stripping. `UK Power Engineers (UKPE) → UKPE`, `Posizionarte (PZT) → PZT`. The acronym is what the company calls itself; the long form is just the legal name.
   - Division descriptors after dash/colon: `Acme - Manufacturing Division → Acme`
   - Trailing reach/scale descriptors are now stripped automatically by the hygiene checker (`DESCRIPTIVE_TAILS` = `International`, `Worldwide`, `Global`), interleaved with the legal-suffix strip so multi-layer tails peel fully: `Advantage Group International → Advantage`, `Fraser Dove International → Fraser Dove`, `Jex Global → Jex`. Flagged as **WARN** (`descriptive-tail`), auto-cleaned under `--apply`. Deliberately conservative — only scope words, NOT industry nouns (`Talent`, `Solutions`, `Associates`, `Search`, `Partners`), which are frequently the brand and are left intact (`Nonprofit Talent`, `Allen Associates` stay).

5. **Strip trailing non-Latin transliterations**
   - `Haushalt International 家庭国际 → Haushalt International`
   - `UBIK 玉弼科顧問 → UBIK`

6. **Website-as-company-name — FAIL severity, strip the TLD**
   - When the company name IS basically a website (`navreo.ai`, `ocean.io`, `bolt.new`, `Immersa.ai`), email clients auto-link the brand mid-sentence and the email reads as `recorded a video for Navreo.ai` with `Navreo.ai` rendered as a blue underlined link. This looks unprofessional, hurts deliverability, and breaks the cold-email tone instantly. **This is FAIL severity, not WARN** — fix it before launch.
   - Strip the trailing TLD when the company name ends with `.<2-6 letter known TLD>` AND removing it leaves ≥ 2 characters. Then title-case the result.
   - Examples: `navreo.ai → Navreo`, `ocean.io → Ocean`, `Immersa.ai → Immersa`, `bolt.new → bolt`, `ControlRooms.ai → ControlRooms`, `DataStorage.com → DataStorage`, `Trans.eu → Trans`, `Smartpricing.it → Smartpricing`, `Automaite.io → Automaite`
   - Apply this AFTER legal-suffix and parenthetical stripping (e.g. `Trans.eu Group → Trans.eu → Trans`).
   - Skip if removing the TLD leaves ≤ 2 characters.
   - Distinct from rule 8 (URL detection): rule 8 flags full URLs with schemes/paths (`https://acme.com/about`) for manual review; rule 6 strips the lightweight `<brand>.<tld>` pattern that's just a stylised brand.

7. **Preserve these always**
   - Apostrophes: `McDonald's`, `L'Oréal`
   - Ampersands: `Procter & Gamble`, `Smith & Nephew`
   - Hyphens: `Saint-Gobain`, `Coca-Cola`
   - Multi-word brands: `Hornby Hobbies`, `General Electric` — don't strip either word
   - Intentional capitalisation: `IBM`, `SAP`, `3M`, `H&M`
   - **Lowercase-start brand styling**: `iCrossing`, `iFrog`, `inBLUME`, `iStoria`, `eBay`. The first letter is intentionally lowercase — that IS the brand. Never flag and never re-case. (The cleaner does not flag `lowercase-start` as dirty for this reason.)
   - **Short all-caps brands**: ≤4 letters all-caps are likely real acronyms — keep `IBM`, `SAP`, `KPMG`, `BCG`, `SIHL`, `WPP` as-is. Only title-case all-caps when the name is >4 characters AND clearly looks like shouting (`IMAGEMOTION → Imagemotion`, `WESEO → Weseo`).

8. **Junk detection** (fall back to original or flag)
   - **Full URL** in the company_name field (with `http(s)://` scheme or `/path`): flag — needs the real company name.
   - Obvious junk: `Unknown`, `-`, `N/A`, `TBD`, `Self`, `Self-employed`, `Freelance`, `None`, empty
   - Identical to `first_name` (data-entry mix-up)
   - All-numeric

9. **Safety rail** — if cleaning would produce an empty or ≤2-character company name, keep the original and flag for manual review.

## Verdicts

The hygiene script emits four severity levels per finding:

| Severity | Trigger | Behaviour |
|---|---|---|
| **❌ FAIL — missing** | Empty / single-char / junk-marker (`Unknown`, `N/A`, `-`, etc.) on `first_name` or `company_name` referenced in copy | Block launch — every lead must have a renderable value |
| **❌ FAIL — dirty** | Legal suffix, full URL, em-dash, all-numeric, **website-as-name** (`navreo.ai`, `ocean.io`, `Immersa.ai`) | Block launch — these render obviously broken or auto-linked sentences |
| **⚠️ WARN — dirty** | Profession tail, ALL-CAPS shouting (>4 chars, not an acronym), parenthetical (no acronym), non-Latin tail | Surface in report — fix recommended but not blocking |
| **✅ PASS** | Clean per all rules. **Lowercase-start brand styling (`iCrossing`, `iFrog`, `eBay`) and short all-caps acronyms (`IBM`, `KPMG`, `SAP`) are PASS — never flagged.** | No output |

Threshold: if FAIL findings affect ≥ 1% of leads, the campaign is blocked from launch until cleaned.

## Workflow integration

The script is run as part of QA Step 5d. It supports two phases:

1. **Detection** (always runs) — scans all leads, computes clean values, emits report
2. **Push** (mode 2 propose / mode 3 apply) — dry-run diff first, user confirms, then batch-pushes via `/campaigns/{id}/leads` POST in batches of 200

Default behaviour is detection only. The `--apply` flag enables the push phase, but always with a dry-run gate that requires explicit user confirmation in the conversation before any write. Cleaning is destructive — the original values are overwritten, so dry-run is mandatory.

Manual-review cases (URL in company_name field, junk markers, identical first/company values) are written to `/tmp/lilly_qa_manual_review_{campaign_id}.csv` for the user to fix by hand. Never silently clobber unusable values.

## When to run

- **Always** during pre-launch QA when the copy contains `{{first_name}}` or `{{company_name}}` (essentially: every Navreo campaign)
- Re-run periodically as new leads are added to long-running campaigns (the optimiser cadence handles this)
- Skip only if leads were imported from a known-clean source (e.g. a freshly-exported CSV that was already normalised by `lilly-updates-leads`)

The cleaning replaces what used to live in `lilly-personalisation` (Lead Field Hygiene section, retired). Personalisation now relies on QA having run first — clean fields propagate into clean Why/CaseStudy outputs because both downstream fields render `{{company_name}}` in their phrasing.
