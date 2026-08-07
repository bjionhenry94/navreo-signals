---
name: lilly-decision-maker-finder-v2
description: "Streamlined DM finder. Domain list, company names, spreadsheet paste, or CSV file + role → verified-email CSV (plus inline table for ≤10 results). Always shows a probe sample before enrichment — user confirms direction first. Accepts: inline domains/names/multi-column paste, local CSV files, HeyReach lists, Smartlead campaigns. Named searches ('save as X' / 'run X'). Push inline or smart default. Suppression by email or LinkedIn URL. Defaults to Navreo ICP roles if none specified. Trigger on: 'find DMs at', 'find contacts at', 'I need contacts at', 'get me people at', 'build a prospect list from', 'who should I contact at', 'who are the decision makers at', 'find [title] at [companies]', 'companies in /path/file.csv', or 'run [search-name]'."
---

# Lilly DM Finder v2

## ⚡ 2026-07-14 VERIFIED DM METHOD (live-tested 6 briefs — evidence `lilly-tam-recall-lab/RESULTS-30.md` DM addendum; bar = 90%)

Prospeo `/search-person` with the user's canonical method scored **100% title accuracy (150/150 rows)**; this skill's AI Ark current-role + company-ID join stays at its proven **100% post-join (15/15)**. Standing rules, all verified:
- **LLM long-tail title expansion → qualify → titles PRIMARY, Director+ seniority LAYERED. Never seniority/department alone.** Local-language titles ("Geschäftsführer", "Algemeen directeur") match as exact Prospeo canonicals — put them IN the list; canonicalise via free `/search-suggestions`.
- **Director+ floor; no bare Director/Partner** — Partner only behind an industry gate (verified 100% on accounting); President safe on Prospeo exact-match, needs `excludeTitle:"vice president,vp"` on AI Ark (verified 100%).
- **Location default: person AND company location in the target geo** unless told otherwise. AI Ark: set both fields. Prospeo: no person-location filter — post-check `person.location` and drop off-geo rows (measured 0-8% leakage).
- **Prospeo `/search-person` accepts recall-max company shapes directly** (`company_type.subtypes` etc.) — vertical-wide DM pulls inherit the ≥70% company gate in one call.
- **AI Ark open person-search = top-up only**: fuzzy title leaks adjacent functions (strip with excludeTitle) and its companyIndustry gate can leak whole verticals — company-fit ALWAYS comes from the join to a scored company pot, never from Ark's own gate. `people_search` gotchas: `companyKeyword` 401, `companyType` 400, accented titles can break curl payloads.
- **Sample-audit gate scores against 90%** (not 70) before any full pull; never enrich emails/phones without the explicit go-ahead ([[no-email-requests-unless-needed]]).

## Purpose

Domain list + role → verified-email CSV. Always runs a probe first and shows a sample for confirmation — full enrichment only fires after the user approves. This is non-negotiable: the stated brief may not fully capture intent, and enrichment credits are not reversible.

**Example flow:** "Find VP Sales at close.com, drift.com, lemlist.com. Push to HeyReach list 748675."
→ Probe fires → sample shown → user confirms → full run + push.

---

## API Access

Keys in `~/.navreo-keys.env` (auto-loaded by `~/.zshrc`).

**Prospeo** — `POST https://api.prospeo.io/search-person` | Auth: `X-KEY: $PROSPEO_API_KEY` | 1 credit/page (25 people)
**Prospeo enrich** — `POST https://api.prospeo.io/bulk-enrich-person` | Auth: same | 1 credit/verified email | Batch max: 10
**AI Ark** — `POST https://api.ai-ark.com/api/developer-portal/v1/people` | Auth: `X-TOKEN: $AI_ARK_API_KEY` | Per DM | Rate: 5 req/sec
> For role-precise pulls you MUST use the nested **current-role filter + company-ID join** — NOT the flat `title`/`seniority` params (those match a person's whole career history and contaminate results with side-business founders). See **AI Ark — Current-Role Filtering** below.

---

## Company-discovery hand-off (2026-07-09 methodology lab)

When the input is a BRIEF rather than a fixed company list ("find all the DMs in [vertical]"), the company-discovery step routes by the brief's ENTITY TYPE per the measured laws in `lilly-tam-mapper` (⚡ 2026-07-09 section) and `lilly-tam-methodology-lab/PLAYBOOK-*.md`:

- **UPDATE 2026-07-14: company discovery now runs the RECALL-MAX method** (`lilly-tam-recall-lab/METHODOLOGY.md`, folded into `lilly-tam-mapper` + both list-builders): open at the loosest defensible classifier shape, widen until a rung fails <70%, keep the biggest passing pool. **Prospeo icp_text is BANNED (user 2026-07-13 — ALL lookalike features on ALL providers decay)** — the "icp_text is mandatory" law is retired.
- **Services/contractor briefs**: Prospeo native subtypes/industry enums + self-ID keywords, + Ocean tiers A/B, + AI Ark FILTER search (industry enums + wide self-ID synonym sets — lookalike BANNED; size:10-15 scored gate, hard abort <50%).
- **Brand/product briefs**: Prospeo `company_type.subtypes` ladder E-commerce→Retail→Marketplace (measured 60,769 @ 80% on the DTC brief — brand briefs are NOT structural fails on Prospeo) + "brand"-suffixed keywords + B2C flags as narrowing layers only if the gate fails; Ocean `ecommerce:true`. AI Ark company search stays routed away (~40-50% ceiling). (AI Ark PEOPLE search for DMs uses the current-role FILTER method — never lookalike.)
- Sample Ocean free via the `ocean_data_api` MCP (first pages, `num_results≤10`, `creditsUsed:0`); AI Ark company-search bills ~1 cr/row — probe `size:1` + `size:25`.

---

## AI Ark — Current-Role Filtering (REST, not the MCP)

**The problem this solves.** AI Ark's flat `title` and `seniority` filters — the `mcp__ai-ark__people_search` MCP tool AND the top-level REST params — match against a person's **entire career history**. Anyone who has *ever* been a Founder/Owner/Co-Founder of any side business matches, even when their current role at the target company is junior (e.g. a Brand Strategist who co-founded a side store, an "Executive *to* CEO," a "Vacation Rental Owner"). This is what made AI Ark unreliable for DM finding. The flat filter tops out around 33% precision on "current CEO/sales-leader at this company."

**The fix — nested `contact.experience.current.title`.** The REST endpoint supports a current-positions-only title filter that the MCP wrapper never exposes. Call REST directly:

```json
{
  "page": 0, "size": 75,
  "account": { "domain": { "any": { "include": ["targetdomain.com"] } } },
  "contact": { "experience": { "current": { "title": { "any": { "include": {
    "mode": "SMART",
    "content": ["CEO","Chief Executive Officer","Founder","Co-Founder","Owner","President","Managing Director","Head of Sales","VP of Sales","Sales Director","Director of Sales","Chief Revenue Officer","Chief Sales Officer","Head of Business Development","Director of Business Development"]
  } } } } } }
}
```
- `experience.current` = currently-active positions. `experience.latest` = the "Latest Active Position Only" UI toggle. Use `current`.
- `mode`: `SMART` (fuzzy, best recall — the post-check cleans the noise), `WORD` (whole word), `STRICT` (exact).

**Mandatory company-ID join post-check.** The API evaluates `account.domain` and `current.title` **independently**, so it still returns people whose matching current title is a *concurrent side-business* rather than their role at the target firm. For each returned person:
1. Read `person.company.id` — the account AI Ark matched = the target company.
2. Collect current positions only (`date.end == null`) from `position_groups[]` entries whose `company.id == person.company.id`.
3. Keep the person ONLY if that **current-at-target** title matches the brief role set.

This is what makes it "current role at *this* company." Validated on a 50-domain run: raw pull ~33% precision → ~100% on what's kept (side-gig founders, "Executive to CEO," advertising strategists all correctly dropped).

**Matcher gotchas (apply in the post-check, not the API call):**
- `\bpresident\b` matches the "President" inside "Vice **President**" — strip `vice president`/`vp` from the title before testing for `president`, or every VP-of-Logistics/Tech/Creative leaks through.
- Hard-reject any title containing: `assistant`, `executive to`, `to ceo`, `recruitment`, `coordinator`, `intern`, `specialist`, `analyst`, `associate`, `representative`, `shop owner`, `sales engineering` — the keyword is present but the role is not.
- VPs qualify ONLY as VP of Sales / Business Development (or CRO / CSO) — never VP of Ops/Tech/Creative/Finance/Supply-Chain.
- Dedup by (name, domain) — the same person can return on two position rows.

**Coverage caveat.** `account.domain` + `current` only returns people AI Ark indexes as *currently* at that exact domain. Acquired/rebranded firms and thinly-indexed agencies return 0 (or only off-brief staff). Note these gaps in output and offer a name-based backfill (drop the domain filter, search by company name) — never silently omit.

**Status note.** This supersedes the old "AI Ark title filter is unreliable, never use AI Ark for DM finding" stance *for the current-role method specifically*: with `experience.current` + the company-ID join, AI Ark is current-role-accurate and is the correct path when Prospeo is unavailable (0 credits / renewal window) or when you want a company-scoped current-exec pull.

**✅ 2026-07-10 methodology-loop validation (15/15 briefs, 100% post-join precision — evidence `lilly-aiark-methodology-loop/RESULTS.md`) — additions to the method:**
- **Billed-noise cutter:** when the role set contains CEO/President, also send a nested title exclude — `"exclude": {"mode":"SMART","content":["Vice President","VP"]}` alongside the include. Measured: 8 of 20 billed rows on one pull were VPs matched via the "President" substring; the exclude removes them BEFORE billing (~1 cr/row). Keep the vp-strip in the post-check regardless.
- **Role-set design rule:** never put bare "Director" or "Partner" in the title content list — functional directors (Finance/IT/Ops Director at construction firms) and equity-consultant "Partners" (at consultancies/accounting firms) explode the match while technically passing the literal post-check. Use Managing Director, Managing Partner, Owner, and C-titles; add local-language titles for non-English geos (Geschäftsführer, Directeur).
- **Director-and-above floor (user rule 2026-07-11):** every AI Ark DM pull filters at Director-and-above — the title content list must span the full Director+ ladder for the brief's function (C-titles, Founder/Owner, Managing Director/Partner, VP-of-function where on-brief, Head of X, Director of X scoped to the brief's function). Below-Director titles never go in the include list, and the post-check rejects anything that lands below that floor.
- **Never seniority/department in isolation (user rule 2026-07-11):** the nested `contact.experience.current.title` content list is ALWAYS the primary filter. `seniority` and `departmentAndFunction` params may only be layered ON TOP of a title list to narrow it — never fired alone or as a substitute. Bare seniority/department filters match whole-career and untitled roles and bill for rows the post-check can't validate.
- **Post-check additions to the hard-reject list:** `office of`, `head of ceo office`, `(retired)`, `partner development` (bizdev, not equity), `partner administrative`.
- **DM TAM formula (for TAM-sizing briefs):** calibrate on 3 gated companies → `avg_dms_per_co = post-join keeps ÷ 3` → `DM TAM = company TAM × avg_dms_per_co`. Always measured, never an assumed ×N. Measured anchors by vertical: SMB services/agencies 1-2 · logistics + dev shops 2-3 · construction contractors 3-6 · accounting firms 7-10 (partners) · thin niches can be <1 (ITAD measured 0.7 — widen the company sample or role set and say so).

---

## Default Role (when brief contains no role)

If no role is specified in the brief, default to **seniority only**:
- Seniority: Director and above (all departments)
- Never ask the user to specify — just apply the default and proceed
- Note in output: `No role specified — returning all Director+ contacts`

---

## Role → Filter Mapping (internal — never show user)

| Plain English | Prospeo seniority | Prospeo department |
|---|---|---|
| Founder / CEO / Owner | Founder/Owner, C-Suite | Chief Executive, Founder |
| VP Sales / Head of Sales / Sales Director | Vice President, Head, Director | Sales, Sales Leader |
| BD / Partnerships / Head of Partnerships | Vice President, Head, Director | Business Development |
| RevOps / Revenue Operations / Sales Operations | Vice President, Head, Director | Revenue Operations, Sales Operations, Business Operations |
| Operations / COO | C-Suite, Vice President, Head | Operations |
| Finance / CFO | C-Suite, Vice President, Head | Finance |
| Marketing / CMO | C-Suite, Vice President, Head | Marketing |
| Technical / CTO | C-Suite, Vice President, Head | Information Technology, Product |

---

## Input Source Parsing

Before any API call, identify and extract the domain list:

**Option A — Inline (any format):**
- Comma-separated, bullet list, numbered list, one per line, CSV column paste
- **Multi-column paste detection:** If the input block contains tab characters or looks like multi-column data (3+ tokens per row):
  1. Split each row by tabs (or `|` for pipe-separated)
  2. Identify the column whose values most match domain pattern (`*.tld`, no spaces) — use that column
  3. If no domain column: fall back to the column whose values most look like company names
  4. Skip header rows (row where the matched column's value doesn't match domain pattern and contains no `.`)
  5. Show one-line note: `Multi-column paste detected — using column "[header]" for domains`
- For each token, classify as one of:
  1. **Domain** (`*.tld`): use directly
  2. **LinkedIn company URL** (`linkedin.com/company/{slug}`): extract slug, resolve slug → real domain (LLM-first, then Prospeo company search if unknown)
  3. **Company name** (no TLD): resolve to canonical domain (LLM-first for well-known cos; Prospeo `/search-company` for unknown)
  4. **Unresolvable**: skip and flag in a one-line note at the top of the output

- Resolution note (shown before probe, one line only): `Resolved: HubSpot → hubspot.com, Gong → gong.io`
- Unresolvable note (at end, not before results): `Could not resolve: AcmeCo Inc — skipped`

**Option B — HeyReach list:**
- Brief says "in my HeyReach list [ID or name]"
- Call `get_leads_from_list(listId)` → paginate until empty → extract unique `company_domain` fields
- If by name: call `get_all_lists` first, fuzzy match (case-insensitive substring, prefer exact). If one match: proceed with note `Using list "[actual name]"`. If multiple matches: show list and ask. If no match: show all list names.
- Skip leads with no `company_domain` (log count silently, never ask)

**Option C — Smartlead campaign:**
- Brief says "in Smartlead campaign [ID or name]"
- Call `GET /campaigns/{id}/leads?offset=0&limit=100` paginated (increment offset by 100 until empty) → extract unique `website` fields
- If by name: call `get_campaigns` first, fuzzy match (case-insensitive substring, prefer exact). If one match: proceed with note `Using campaign "[actual name]"`. If multiple matches: show list and ask. If no match: show all campaign names.
- Auto-suppress: existing leads in that campaign are automatically added to the suppression set (always duplicates — no need for the user to state this explicitly)
- Push default: if no push destination given, offer the source campaign as default: `Push to Smartlead campaign [X]? (same as input — or specify different)`

**Option D — Local CSV file:**
- Brief says "companies in /path/to/file.csv" or "companies in ~/Downloads/export.csv"
- Read the file with the Read tool
- Column detection priority: `domain` > `website` > `company_domain` > `url` > any column with mostly `*.tld` values > `company` / `company_name` (triggers name resolution)
- If two candidate columns exist: use first domain-looking one, note in output which column was used
- If no usable column found: `Could not read [file] — no domain or company column detected. Available columns: [list]`
- Otherwise: extract column values, treat as inline list (runs through name resolution if needed)

**Email address detection** (within Option A inline input, before domain normalization):
- Tokens containing `@` are treated as email addresses
- Extract the domain after `@` and use it as the company domain
- Skip consumer providers silently (not flagged as errors): `gmail.com, hotmail.com, outlook.com, yahoo.com, icloud.com, me.com, protonmail.com, aol.com, msn.com, live.com`
- Report in one line before probe: `"3 emails → acme.com, drift.com, example.io | 2 consumer emails skipped (gmail, outlook)"`

**Domain normalization (applied to all input sources, before probe):**
1. Strip `www.` prefix (`www.salesforce.com` → `salesforce.com`)
2. Lowercase all domains (`HubSpot.com` → `hubspot.com`)
3. Remove path fragments and trailing slashes (`close.com/blog` → `close.com`)
4. Remove port numbers (`company.com:443` → `company.com`)
5. Dedup after normalization — report count if any collapsed: `Deduped: www.salesforce.com → salesforce.com (3 duplicates removed)`
6. Strip invalid subdomains: drop domains where second-to-last part is a country code and TLD is `.com` (e.g. `foo.uk.com`).

---

## Gate Logic — Always Show Sample First

The sample gate is **mandatory on every run**. There is no auto-fire. Accuracy determines whether to abort or proceed to sample — it never determines whether to skip the sample.

Fire Prospeo probe (A1) first. Then decide:

| Probe outcome | Action |
|---|---|
| ≥90% on-brief (A grade) | **Show sample** — table + confirm, then full run on approval |
| 70-89% on-brief | **Do NOT proceed to full run.** Show the sample + the leak (top off-brief titles), tighten filters, re-probe. Full run unblocks only at ≥90%, or on an explicit user override in so many words ("pull it anyway") |
| <70% after max iterations | **Abort** — diagnostic message (see below) |

The 90% bar is the A grade from `lilly-list-audit`'s grade bands: **a spot sample below A means the rest of the list must not be pulled** (2026-07-10 rule — a sub-A pull put ~26% flagged titles into the live Commercial Roofing campaign and forced a 973-lead prune).

Always: complete A1+A2, show sample table, wait for approval, then run B.
When abort: show diagnostic message:
```
Accuracy: [X]% — couldn't reach 70% after [N] filter attempts.

Most common off-brief titles found:
  [Title A] ([N]×)
  [Title B] ([N]×)
  [Title C] ([N]×)
  [Title D] ([N]×)

Suggestion: try one of:
  → "[Specific title list from brief + common on-brief patterns]"
  → "exclude [most common off-brief pattern]"
```
Suggestion should be a specific, usable re-phrasing — not generic advice. List the top 4 off-brief titles by frequency so the user knows exactly what to exclude.

---

## Suppression Lists

**Inline exclusions (parsed from brief before probe):**
Keywords: "exclude", "skip", "but not", "don't include", "not including"
- **Domain exclusion**: "skip drift.com" / "exclude drift.com" → remove that domain from the input list before probe fires (no credits spent on it). Show: `(drift.com excluded from input)`
- **Prior-contact exclusion (all domains, automatic, before any paid call):** call `navreo_db.check_exclusions(client_id=..., domains=<input domain list>)` — a `None` return means the check is unavailable, NOT "no exclusions"; treat unavailable as skip-the-check, never silently proceed as if clear. Also check the Supabase `contact_history` table for the input domains via `navreo_db.rest("GET", "/rest/v1/contact_history", params={"select":"company_domain","company_domain":"in.(<batched domain list>)"})`, batched (~100 domains/call). Remove matched domains from the input list before the probe fires. Report before any paid call: `(N domains skipped — already in contact_history / exclusion list)`.
- **Email suppression**: "exclude john@acme.com" / "but not sarah@drift.com" → add that email to the suppression set. Applied at B1.5 (primary) and post-B4 (final safety net — see **Suppression Timing** below).
- Multiple inline exclusions allowed: "exclude drift.com, john@acme.com, hubspot.com"
- Report in one line: `(drift.com excluded from input | 1 email added to suppression)`

**Named-source suppression** (if brief includes "exclude anyone in [source]"):
- Fetch suppression identifiers in parallel with Step A1 probe (don't block)
- HeyReach list (by ID or name): `get_leads_from_list` → extract email AND linkedin_url fields
- Smartlead campaign (by ID or name): `GET /campaigns/{id}/leads` paginated → extract email AND linkedin_url fields
- Local CSV file: read file → extract email column if present; extract linkedin_url column if present
- "same as last time" or "previous run": load last run's output CSV → extract both fields
- After B4 merge, remove any result that matches the suppression set on EITHER email OR LinkedIn URL — **final safety net only**; the primary filter runs at B1.5, before enrichment spend (see **Suppression Timing** below)
- Report suppressed count in output: `(N suppressed — already in [source])`

Multiple exclusion sources allowed. If a suppression source has neither email nor linkedin_url column, flag it: `Note: could not read suppression from [source] — no email or linkedin_url column found`

**Run log** — append to `~/.navreo-cache/lilly-dm-runs.log` based on outcome:
- Complete run (all domains processed) → write immediately after B6 output
- Partial success (Prospeo failed mid-run) → write with output path pointing to `-partial.csv`; on successful retry, overwrite that log entry with final path
- Zero results (all domains returned 0) → write; enables named search retry and "same as last time" reference
- Aborted run (<70% accuracy, user didn't clarify) → do NOT write to log (no output was produced)
- AI Ark failure only → write as complete run (Prospeo output is complete)

After each run, append one line to `~/.navreo-cache/lilly-dm-runs.log`:
`{YYYY-MM-DD} | {N} domains | {role-slug} | {output-file-path} | push:{destination-or-none} | name:{slug-or-none}`
Enables "same as last time", "exclude from my last run", smart push default, and named search re-run.
Cap at 100 lines (trim oldest on append). Human-readable format.

**Named searches:**
- Brief contains "save as [name]" or "save this as [name]" → store name in run log entry
- Brief says "run [name]" → fuzzy-match slug against all run log names (case-insensitive substring; prefer exact match, then longest prefix match). If one match: proceed. If multiple: show options. If none: show all saved search names. → Load its domains, role, push destination → **auto-suppress against ALL prior log entries with that name** (collect all output CSV paths, extract email + LinkedIn URL, build suppression set)
  - Report: `(N contacts auto-suppressed — already found in prior [name] runs)`
  - Override: "run [name] from scratch" → disables auto-suppression for that run only
- "Run [name], exclude last run" → same behavior as "run [name]" (auto-suppression already covers this; phrase is accepted but redundant)
- Names are slugified on save (spaces → hyphens, lowercase)
- If a prior run's output CSV has been moved or deleted: skip it silently, don't abort the suppression build

---

## Suppression Timing (spend guard)

Suppression is a SPEND GUARD, not just an output filter — most of it must happen before paid enrichment fires, not after. A cost audit found ~30% of a run's credits going to already-suppressed/already-contacted contacts because the old flow filtered only at B4.

1. **Build the full suppression set BEFORE Step A (before the A1 probe fires):** inline email/LinkedIn exclusions + named-source suppression (HeyReach/Smartlead/CSV/previous-run/named-search) + auto-suppress (Smartlead-campaign-as-input, named-search reruns) + the prior-contact/`contact_history` domain check above. Fetch named-source identifiers in parallel with A0/A1 — don't block the probe — but have the full set ready before B1 fires.
2. **Filter immediately after B1, before B2/B3 (Step B1.5, below):** once Prospeo full-pull results are in, drop anyone matching the suppression set on email OR LinkedIn URL BEFORE spending B2 enrich credits or B3 AI Ark credits on them. This is where most of the savings happen — enrichment credits are per-person and non-refundable.
3. **Post-B4 filter (final safety net, not primary):** the existing post-B4 pass (see **Suppression Lists** above) still runs — it catches anything merged in from AI Ark (Set B) that wasn't in the B1 pool at filter time. It should catch near-zero matches if step 2 worked.

---

## Cache Write-Back & Spend Ledger (mandatory)

The central Supabase cache is checked first (see A0 below) — but it only stays useful if every run feeds it back. Never let a paid call's result live only in the local file cache or the output CSV.

After EVERY paid Prospeo or AI Ark call (A1 probe, A2 probe, B1 pull, B2 enrich, B3 pull):
1. **Write-back:** `navreo_db.put_enrichment("company", domain, provider="prospeo"|"ai_ark", payload=<raw response>, endpoint="<endpoint>", source_skill="lilly-decision-maker-finder-v2")`.
2. **Ledger:** `navreo_db.log_provider_usage(provider="prospeo"|"ai_ark", credits=<actual credits spent this call>, endpoint="<endpoint>", source_id="lilly-decision-maker-finder-v2")` — log actual spend, never estimate.

**After B4 merge, per verified row:** upsert every contact with a verified email via `navreo_db.upsert_person(email=..., linkedin_slug=..., first_name=..., last_name=..., title=..., company_domain=..., provider="ai_ark")`. Pass `provider="ai_ark"` ONLY for AI-Ark-sourced rows (this auto-stamps `email_verification`/`email_verified_at`). Never pass `provider="ai_ark"` for Prospeo rows, and never fabricate a verification stamp for a Prospeo row that B5 didn't actually verify.

---

## Execution

### Step A — Probe + Filter Lock-in (always silent)

**A0 — Cache check (before any API call, Supabase first)**
1. **Supabase (central, check first — before any paid call):** for each domain, call `navreo_db.get_enrichment("company", domain, provider="prospeo")` (and `provider="ai_ark"` if AI Ark will be used) — `max_age_days=30`. Also query `navreo_db.rest("GET", "/rest/v1/people", params={"select":"first_name,last_name,title,email,linkedin_slug,email_verified_at","company_domain":"eq.<domain>","email":"not.is.null"})`. If the returned people already satisfy the requested role brief (title matches, verified emails present), use them directly and spend 0 credits on that domain — mark it Supabase-served.
2. **Local file cache (fallback, domains not Supabase-served):** check `~/.navreo-cache/prospeo/companies/{domain}.json`.
   - If file exists AND `fetched_at` is within 30 days: use cached data. 0 credits.
   - Cache miss or stale: falls through to A1.

Track both cache tiers silently. Mention counts in output only if ≥1 hit (one line: `N from Supabase, N from local cache`). Report Supabase-served domains again in the final B6 summary (they never touch B1-B3).

Cache is shared with `lilly-icebreaker`, `lilly-decision-maker-finder`, `lilly-prospeo-list-builder` — treat all as valid sources.

**A1 — Prospeo probe + auto-tighten (cache-miss domains only)**
1. **If uncached domains > 50**: sample the first 25 for the probe (representative accuracy check — does not need to cover all domains). If ≤50: pass all.
2. Fire Prospeo `/search-person` page 1 with inferred filters on the probe domain set.
3. Classify returned titles against role brief. On-brief = matches target function/seniority.
4. If on-brief rate <70%: tighten filters (narrow seniority, add title exclusions) and re-fire. Max 5 iterations. Silent during execution — report tightening in the final output if it occurred (e.g. `Filters tightened 2× to reach 84% accuracy`).
5. Enrich sample batch (up to 10 people, batches of 10) via `/bulk-enrich-person` → seeds Set A (verified Prospeo email).

**A2 — AI Ark probe + auto-tighten**
1. Fire AI Ark page 1 on same domains using the **nested `contact.experience.current.title` filter + company-ID join** (see **AI Ark — Current-Role Filtering** above). NEVER probe with the flat `title`/`seniority` params for a role-specific brief — they match full career history and will sit near 33% precision no matter how you tighten. Exclusions = Set A LinkedIn URLs only.
   - Prospeo NO_MATCH people (Set B) are NOT excluded — AI Ark can find their email.
2. Classify AI Ark titles against role brief **after the company-ID join** (judge the current-at-target title, not the headline title).
3. If on-brief rate <70%: the lever is the title `content` list and the post-check matcher, NOT seniority/department. Tighten and re-fire. Max 3 iterations. Silent during execution — include in final output note if tightening occurred.
4. **AI-Ark-primary mode:** when Prospeo is unavailable (0 credits / renewal window) or the brief is explicitly "by current role," AI Ark current-role filtering becomes the primary source — run the full company-ID-join method across all domains rather than treating AI Ark as Set-B-only supplement.

**A3 — Sample (always shown)**

Show a mixed sample so the user can validate both direction and noise before enrichment fires:

```
Probe: ~[N] decision-makers across [N] companies ([X]% on-brief).

On-brief (what we'll pull):
| Name | Title | Company |
|---|---|---|
| [on-brief person 1] | [title] | [company] |
| [on-brief person 2] | [title] | [company] |
| [on-brief person 3] | [title] | [company] |
[up to 5 rows]

[Only show this block if any off-brief exist:]
Off-brief ([N] found — will be filtered):
| Name | Title | Company |
|---|---|---|
| [off-brief person] | [off-brief title] | [company] |
[up to 5 rows; if more, "and N more"]

Proceed, exclude a title pattern, or change role?
```

Rules:
- Always show this sample — no exceptions
- On-brief block: up to 5 rows drawn from contacts that matched the brief (so the user can confirm the direction is right, not just that noise is low)
- Off-brief block: only show if off-brief contacts exist; up to 5 rows
- If accuracy is 100% (no off-brief): omit the off-brief block entirely, just show on-brief sample
- Show actual title variants found, never Prospeo filter labels

Three valid responses:
- "Proceed" (or "go" / "yes" / "looks good") → Step B fires immediately
- "Exclude [pattern]" → tighten filters, re-run A1, re-show updated sample
- "[Different role description]" → re-infer filters from new description, re-run A1 from scratch

---

### Step B — Full Execution (no pauses, no iteration)

**B1 — Prospeo full pull**
Paginate all pages with locked filters. Collect all LinkedIn URLs + people data.

**Domain batching for large lists:** If uncached domains > 50, batch into groups of 50 per Prospeo call (prevents silent truncation from API limits on `company.websites.include` array size). Paginate each batch fully before moving to the next. Merge all batch results before B2. Note batch count in output only if ≥4 batches: `(processed in 4 batches)`.

**B1.5 — Suppression filter (before spend, mandatory)**
Filter B1 results against the suppression set built before Step A (email OR LinkedIn URL match — see **Suppression Timing** above). Drop matches now, before B2 enrich credits or B3 AI Ark credits are spent on them. Report: `(N pre-filtered — already suppressed, 0 credits spent)`.

**B2 — Prospeo enrich (cache-first)**
Before firing `/bulk-enrich-person`, check per-person email cache:
- Path: `~/.navreo-cache/prospeo/people/{linkedin-url-slug}-email.json`
- Contents: `{"email": "x@y.com", "status": "valid", "fetched_at": "YYYY-MM-DD"}`
- ≤30 days old → use cached email, skip API call for this person (0 credits)
- Stale or missing → falls through to API call

Fire `/bulk-enrich-person` on cache-miss contacts only, batches of 10. After each call, write results to per-person cache.

Produces:
- **Set A** — verified email (from cache or fresh enrich)
- **Set B** — NO_MATCH (no email found, neither cache nor API)

**B3 — AI Ark full pull**
Fire with locked filters. Exclusions = Set A LinkedIn URLs only. Set B remains fair game.

**B4 — Merge**
Combine all results. Dedup by LinkedIn URL only. For Set B people found in AI Ark: use AI Ark record. For Set B not in AI Ark: include with blank email.

**B5 — Email verification**
Auto-run `lilly-email-verification` on Set A emails that came from a FRESH enrich call (not from cache). Cached emails were already verified when stored — skip re-verification. AI Ark emails pre-verified — skip. No prompt needed.

**B6 — Output**

CSV columns: `first_name`, `last_name`, `title`, `company`, `domain`, `linkedin_url`, `email`, `email_status`, `source`

Always write to `/tmp/lilly-dm-YYYYMMDD-{role-slug}.csv` (date-stamped, role-derived slug). Date prevents overwrites on same-day multi-run sessions.

**Inline table for small result sets:**
If total contacts ≤ 10: show inline table after the summary line, before the file path.
```
| Name | Title | Company | Email |
|---|---|---|---|
| [First Last] | [Title] | [Company] | [email or —] |
```
If total contacts > 10: summary line + file path only (no inline table).
Inline table applies regardless of push destination.

**Column schema adapts to push destination:**
- HeyReach push: `firstName, lastName, linkedInUrl, email, companyName, title`
- Smartlead push: `first_name, last_name, email, company_name, website, job_title`
- No push: canonical `first_name, last_name, title, company, domain, linkedin_url, email, email_status, source`

Note destination format in output: `Saved → /tmp/lilly-dm-... (HeyReach format)`

```
Done. [N] decision-makers | [N] verified emails | [N] companies

[CSV or file path]
```

If brief included a push destination: resolve by ID or name, execute push automatically, confirm in one line.
- "push to HeyReach list 748675" → direct push
- "push to HeyReach Exporters list" → `get_all_lists` → fuzzy match name → push
- "add to Smartlead campaign X" → same fuzzy name-resolution pattern

**Pre-push field validation + quality filtering:**
- HeyReach push: requires `linkedin_url`. Remove contacts with no LinkedIn URL before pushing. Remove contacts with `email_status = "invalid"`. Note combined count: `(32 added, 6 skipped — no LinkedIn URL, 2 skipped — invalid email, retained in CSV)`
- Smartlead push: requires `email`. Remove contacts with no email. Remove contacts with `email_status = "invalid"` (confirmed hard-fail — would generate bounces). Include `valid`, `catch_all`, `unknown`. Note combined count: `(39 added, 2 skipped — invalid email, retained in CSV)`
- CSV always retains ALL contacts regardless of push eligibility.
- Never exclude `catch_all` or `unknown` automatically — they're uncertain, not confirmed invalid.

If no destination given AND verified emails ≥1, pick default in this order:
1. Input was Smartlead campaign X → offer that campaign: `Push to Smartlead campaign [X]? (same as input — or specify different)`
2. Run log has a last push destination → offer it: `Push to [last destination]? (last used — or specify different)`
3. No prior context → `Push to HeyReach list or Smartlead campaign? (or skip)`

User replies "yes" → push to offered destination. Or specifies new destination → push there, update log.

---

## Zero-Results Handling

If both Prospeo AND AI Ark return 0 people for a domain: include a note in the final output summary, don't silently omit.

```
Done. 12 decision-makers | 9 verified emails | 4 of 5 companies

Note: tiny-agency.xyz returned 0 results (not indexed by either provider)

[CSV]
```

Never deliver a silently incomplete CSV.

---

## Partial Success / API Error Handling

Distinguish between Prospeo failure and AI Ark failure:

**Prospeo fails mid-run (B1 or B2):**
1. Stop paginating — don't retry
2. Write completed domains to CSV (`lilly-dm-YYYYMMDD-{slug}-partial.csv`)
3. Deliver with retry offer:
```
Done. 14 decision-makers | 10 verified emails | 6 of 12 companies
(Prospeo unavailable midway — 6 domains not yet processed)

Saved → /tmp/lilly-dm-20260625-vp-sales-partial.csv

Retry remaining 6 domains? (Reply "yes" or I'll list them)
```
On "yes": fire on incomplete domains → merge → rename file (remove `-partial`).

**AI Ark fails (B3):**
AI Ark is supplementary — Prospeo results are complete. Do NOT call it partial.
Deliver full Prospeo results, note AI Ark unavailability:
```
Done. 28 decision-makers | 20 verified emails | 12 of 12 companies
(AI Ark unavailable — Set B contacts not enriched; some DMs without verified email may be missing)
```
No retry needed.

**Rate-limit (429, either provider):** pause 10s, retry once. If second attempt also fails, treat as 5xx per provider type above.

---

## Per-Company Limit

If brief contains "one per company", "max 1 per company", "max N per company", "top person at each company", or similar:
- After B4 merge, group contacts by domain
- Keep top N per domain, ranked: (1) exact title match to brief > (2) adjacent senior role > (3) Prospeo result order
- Discard lower-ranked contacts at that domain
- Note in summary: `(1 per company)` or `(max 2 per company)`

Default: no limit (return all matches). Only apply when user specifies.

---

## Multi-Role Briefs

If brief contains "AND" between distinct role categories ("VP Sales AND Head of Marketing"):
- Run separate Prospeo searches per role category (different `department` filters)
- Run separate AI Ark searches per role category
- Merge all results, dedup by LinkedIn URL
- Output is one combined CSV

Single role with multiple title variants ("VP Sales or Head of Sales") = one search with combined seniority filter.

---

## Verified-Only Filter

If brief contains "verified emails only", "emails required", or equivalent:
- After B5, remove any contact without a verified email from the output
- Note exclusion count: `(N excluded — no verified email found)`
- Combine with suppression count in the same parenthetical if both apply

---

## Hard Rules

- **Always show the A3 sample before enrichment — no auto-fire, no exceptions**
- Never show Prospeo seniority/department filter names — translate to plain English titles
- Never show cost estimates or credit counts
- Never pause mid-Step B for any reason
- Never use domain-match dedup — LinkedIn URL only
- Never use Ocean.io people endpoints
- `lilly-email-verification` auto-fires by default — never ask again at end
- Never show tightening/iteration activity in user-facing output — results only
- Sample header: show actual title variants found, not filter labels
- Zero results at a domain = note in output, never silent omission
- Smartlead campaign as input source → auto-suppress existing leads, offer same campaign as push default

---

## Cloud upload (mandatory)

The finished verified-email DM CSV (the same file used for the inline table / push) MUST be uploaded to the central Supabase list store before the run ends — never leave a run's list living only on this machine. Run:

`python3 ~/.claude/skills/_shared/list_upload.py <final.csv> --name "<descriptive list name>" --client "<Client>" [--folder "<Theme>"] --source-skill lilly-decision-maker-finder-v2 --brief "<one-line brief>" --owner "<who asked>"`

Then show the returned `https://navreo-signals.onrender.com/app/lists.html#<id>` link to the user — that link is part of the deliverable, alongside the CSV and (if requested) the push confirmation.

Folder rules: `--client` = the client named in the brief (internal/Navreo pulls → `Navreo`); add `--folder` ONLY when the brief names a campaign theme or segment (e.g. client `Amplifyy`, folder `Beauty`); never deeper than two levels. Re-runs with the same name+client replace that list's rows in place (safe) — this pairs naturally with the named-search "run [name]" re-run convention above.


## Upload gate (MANDATORY)

Before ANY lead push into a Smartlead campaign that results from this skill (`add_leads_to_campaign` or equivalent), hand off to `lilly-upload-gate` and let it run to a green gate: every enabled check PASS or explicitly OVERRIDDEN per-flag, and the audit row written to `list_upload_qa_runs` BEFORE the first add-leads call. Never upload around the gate.
