---
name: lilly-sales-nav-builder
description: "Build a LinkedIn Sales Navigator search URL with the correct query-string format so the page loads with all filters pre-applied (companies, titles, geography, seniority, industry, etc.). Use this skill whenever the user wants a Sales Nav link, a sales-nav search, a prospecting URL, a lookalike search URL, or asks to 'build me a Sales Nav search for [criteria]'. Trigger on phrases like 'create a sales nav link', 'sales navigator URL', 'sales nav search for [companies/titles]', 'build me a search for X targeting Y', 'I need a Sales Nav link to find [people]', 'turn this list of companies and titles into a Sales Nav URL', or any request that pairs a list of companies (by name or domain), titles, locations, or other Sales Nav filters with intent to produce a clickable search URL. Always uses scripts/build_sales_nav_url.py rather than hand-encoding the URL — hand-typed URLs frequently break on missed closing parens, single vs double space-encoding, or missing comma separators."
---

# Lilly Sales Nav Builder

## Purpose

Produce a LinkedIn Sales Navigator search URL that loads with the user's filters already applied — companies, titles, geography, seniority, industry, headcount, etc. The output is a clickable URL the user can open or paste into Sales Nav directly.

The hand-typed approach to building these URLs is brittle: Sales Nav uses a custom syntax with specific parenthesisation, double-encoded spaces (`%2520`), encoded colons/commas (`%3A` / `%2C`), a hash-fragment `#query=` URL form (NOT `?query=`), and several filters that need an `id+text` item format instead of text-only. A single missed paren or wrong format and Sales Nav silently drops the filter. **This skill always builds via `scripts/build_sales_nav_url.py`** — the script handles encoding, auto-translates country names → URN IDs, headcount ranges → letter codes, seniority names → numeric IDs, emits both `GEOGRAPHY` (chips) and `REGION` (operational filter) for locations, validates paren balance, and reports the final URL length so you know if it's at risk of browser/server truncation.

---

## When to Use

Trigger on any of:

- "Build me a Sales Nav search for [criteria]"
- "Create a Sales Navigator URL for these companies and these titles"
- "I need a Sales Nav link targeting [decision-makers] at [companies]"
- "Turn this list into a Sales Nav search"
- User pastes a Sales Nav URL with `query=` parameters and asks to modify, extend, or fix it
- User mentions a lookalike list (from Ocean.io, Crunchbase, etc.) and wants to find people at those companies on LinkedIn

**Do not trigger on:**
- "Qualify this CSV of followers" → `lilly-company-followers`
- "Verify these emails" → `lilly-email-verification`
- "Build me a TAM" (lookalike *company* discovery, not URL building) → `lilly-ocean-tam-builder`
- "Find me Sales Nav results from this URL" (scraping, not building) → user needs PhantomBuster/TexAu/Boomerang, not this skill

---

## Workflow

### Step 0 — Confirm what to filter on

Send the user this template (or pre-fill from earlier conversation context). Wait for confirmation before generating anything.

```
I'll build the Sales Nav URL once you confirm the filters. Fill the relevant
sections — leave blank what you don't want to filter on.

1. COMPANIES  (current company filter — text-based, no numeric IDs needed)
   Paste names or domains. One per line.
   →

2. TITLES  (current job title — exact title strings, OR'd together)
   Paste titles, one per line. Include all variations you care about
   (Director / VP / Head of variants of the same role).
   →

   Filter type: CURRENT_TITLE (default) or PAST_TITLE?
   →   (CURRENT for current decision-makers; PAST for movers/alumni)

3. GEOGRAPHY  (optional)
   Country names — full English names matching LinkedIn (e.g. "United States",
   "United Kingdom"). The script auto-translates to URN IDs and emits both
   GEOGRAPHY (visual chips) and REGION (operational filter). Add unmapped
   countries to COUNTRY_TO_URN in build_sales_nav_url.py.
   →

4. SENIORITY  (optional — emitted as SENIORITY_LEVEL filter, id+text format)
   Director, VP, CXO, Owner / Partner, Manager, Senior, Entry Level.
   The script auto-maps these names to Sales Nav's numeric seniority IDs.
   Skip this if your title list already mixes Manager → VP — adding a
   seniority filter on top will exclude legit Manager-level roles.
   →

5. INDUSTRY  (optional)
   E.g. "Apparel & Fashion", "Cosmetics", "Information Technology and Services"
   →

6. COMPANY HEADCOUNT  (optional — emitted as id+text format)
   E.g. "11-50, 51-200, 201-500". The script auto-maps each range to its
   single-letter Sales Nav code (B/C/D/E/F/G/H/I).
   →

7. KEYWORDS  (optional, full-text — searches everything including descriptions)
   Use sparingly; precise filters above are better.
   →
```

If the user replies in freeform prose, structure it back into the 7 fields and ask them to confirm before generating.

### Step 1 — Build the config JSON and run the script

Translate the user's confirmed criteria into a JSON config matching `scripts/build_sales_nav_url.py`'s schema (see the file's docstring for the full schema). Then run:

```bash
python3 scripts/build_sales_nav_url.py --config <config.json>
```

The script will:
- Sanitise titles (strip parentheticals like `(Clinical)`, em-dashes/en-dashes, smart quotes, leading/trailing whitespace)
- Apply the correct double-encoding pattern (spaces → `%2520`)
- Build the nested `(filters%3AList(...))` structure
- Validate paren balance (opens = closes)
- Print a diagnostic report (filter count, total title count, URL length, paren balance)
- Output the final URL

### Step 2 — Return the URL with sanity-check guidance

Hand the URL back to the user with a short "what to expect when you click it" checklist:

```
Sales Nav URL ready. ~N kB, M filters, T titles.

When the page loads, you should see:
- C company chips in Current Company filter (or text suggestions if any didn't auto-resolve)
- T title chips in Current/Past Job Title filter
- Other filters applied as configured
- Result count in the top bar

If any company doesn't auto-resolve to a chip, click into the Company filter
and pick the correct entity from the dropdown — this means the company name's
LinkedIn variant differs from what you supplied (e.g. "Stefanini" vs
"Stefanini Group").
```

Stop here. Do **not** open the URL, scrape it, or auto-trigger the next skill in the chain. That's the user's call.

---

## URL Anatomy (cheat sheet)

Full reference in `references/url_anatomy.md`. Quick version:

```
https://www.linkedin.com/sales/search/people?query=(filters%3AList(<filters>))
```

Where `<filters>` is comma-separated `(type%3A<TYPE>%2Cvalues%3AList(<items>))` tuples, and each `<item>` inside `values%3AList(...)` is `(text%3A<value>%2CselectionType%3AINCLUDED)`.

### Encoding rules
| Character | Encoded as | Notes |
|---|---|---|
| `(` `)` | literal | Sales Nav uses these as syntax delimiters — never encode them |
| `:` | `%3A` | inside the query value |
| `,` | `%2C` | between list items and key:value pairs |
| space | `%2520` | **double-encoded** — `%20` then encoded again |
| `-` `_` `.` | literal | URL-safe |
| `&` `?` `#` | avoid in values | use only as URL delimiters |

### Closing paren count
Count opens and closes — they must match. With **2 filters** (e.g. CURRENT_COMPANY + CURRENT_TITLE) the URL ends with **5 closing parens** after the last `INCLUDED`:
- 1 closes the last item tuple
- 1 closes that filter's `values%3AList(`
- 1 closes the filter tuple `(type%3A...,values%3AList(...))`
- 1 closes `filters%3AList(`
- 1 closes the outer `query=(`

Add 1 more closing paren for each additional filter type (e.g. 3 filters → 6 closing parens at end). The script handles this automatically — never hand-count.

---

## Common Pitfalls

| Problem | Fix |
|---|---|
| Hand-typed URL won't load → blank page or 404-ish error | Almost always a paren imbalance. **Use the script.** Don't try to hand-edit a long URL. |
| URL loads, but only 1 of 2 filters appears | Missing comma separator (`%2C`) between filter tuples, or one filter's closing parens are wrong. Rebuild via script. |
| Companies show as raw text, not chips | The text-based company filter didn't auto-resolve. User has to pick from the UI dropdown. (Numeric LinkedIn company IDs would resolve every time but require a lookup step — see `references/url_anatomy.md` for the ID-based format.) |
| Titles like "VP Supply Chain (Clinical)" don't match anyone | Parentheticals break Sales Nav title matching. The script strips `(...)` and em-dashes by default. If the user really wants the parenthetical text, pass `--keep-parens` (then expect 0 matches). |
| 100+ titles → URL is too long, browser truncates | Sales Nav practical limit is ~60-80 titles per filter. Script warns when you exceed 70. Solution: split into 2 saved searches (e.g. 40 titles each), run separately, dedupe results downstream. |
| User says PAST_TITLE when they mean CURRENT_TITLE | PAST_TITLE = roles a person *previously* held. For decision-maker outreach, default to CURRENT_TITLE. Always confirm in Step 0 if the user explicitly mentions PAST_TITLE — could be intentional (alumni play) or a slip. |
| Title with numbers/symbols (e.g. "C-Suite", "Level 5 Manager") | Numbers and `-` are URL-safe and stay literal. `&`, `+`, `#`, `?` should be removed or replaced — script does this automatically. |
| User pastes a recentSearchParam-laden URL from their browser | That URL has session-specific cruft (`recentSearchParam:(id:...,doLogHistory:true)`). The script ignores it; the output URL is clean. |

---

## Files in This Skill

- `scripts/build_sales_nav_url.py` — programmatic URL builder. Takes a JSON config (or CLI flags), sanitises inputs, applies correct encoding, validates paren balance, outputs the URL. **Always use this rather than hand-typing.**
- `references/url_anatomy.md` — detailed Sales Nav URL format reference (filter types, encoding, structure tree, examples).
- `references/filter_types.md` — list of supported Sales Nav filter type names (`CURRENT_COMPANY`, `CURRENT_TITLE`, `PAST_TITLE`, `INDUSTRY`, `GEOGRAPHY`, `SENIORITY`, `COMPANY_HEADCOUNT`, etc.) with their value formats.

---

## Reference: How This Composes With Other Lilly Skills

| If the user asks… | Use this skill | Then potentially hand off to… |
|---|---|---|
| "Build me a Sales Nav search for [criteria]" | **lilly-sales-nav-builder** (this skill) | scrape the URL → `lilly-company-followers` for qualification |
| "Find lookalike companies to X" | `lilly-ocean-tam-builder` | export domains → **lilly-sales-nav-builder** to build the people-search URL |
| "Qualify these scraped followers" | `lilly-company-followers` | `lilly-email-verification` |
| "Verify / enrich emails" | `lilly-email-verification` | push to Smartlead via `lilly-bot` |
| "Build a Smartlead campaign" | `lilly-bot` | — |
