---
name: getleads-dm-list-builder
description: Orchestration skill for building decision-maker (DM) lead lists from targeting briefs using GetLeads — both super-targeted lists (narrow niche + keyword-qualified) and broad lists (wide ICP sweeps). Runs a fixed goal → steps → done-rule loop per brief with a Loop Training Mode toggle (pause-for-approval vs autonomous). Every list is verified to ≥70% accuracy by WebFetching a sample of the actual company websites (NOT trusting GetLeads' industry tag or bio, which overstate accuracy) AND sanity-checked for realistic volume before export. Use when asked to build a list with GetLeads, run a DM search, create targeted/broad lists from briefs, or someone says "run the GetLeads list builder".
---

# GetLeads DM List Builder

A static, pre-baked loop for taking targeting briefs → qualified GetLeads DM searches → verified lists → pushed to the tool. Read it top to bottom once; it does not change between runs.

---

## ⚙️ LOOP TRAINING MODE  →  **OFF**

Flip this one word to change how the whole loop runs. Default is **ON**.

**When ON (default — training):**
- **Pause at every step.** Do the step, show the result, then STOP and wait for my explicit approval before moving to the next step.
- **Skip any step that already passes its done-rule.** Don't redo finished work — check the done-rule first; if it's already green, say so and move on.
- **Only re-run steps that fail.** If a step's done-rule fails, fix and re-run that step only — not the whole loop.
- **Retry cap: 3.** Max 3 attempts on any one step. After 3 fails, STOP and surface the blocker in plain English. Never loop forever.

**When OFF (autonomous):**
- **No pauses.** Run every step start to finish without waiting for approval.
- **Keep the done-rule checks.** Every step is still gated on its done-rule; a failed done-rule still blocks progress.
- **Keep the retry cap (3).** Same 3-attempts-then-stop rule. Autonomous ≠ infinite.

> To change it later: edit the line above to `→ OFF` (or back to `→ ON`). Nothing else in this file needs touching.

---

## 🎯 Goal

From one or more targeting briefs, produce **DM lead lists qualified with GetLeads** — super-targeted lists that nail a niche, and broad lists that sweep a wide ICP — where every list is **≥70% accurate to its brief** (verified by sampling real rows, not by trusting the filters) and its **size is realistic** for the market it claims to cover. A list that matches the brief but is implausibly small (or large) is a filter problem, not a result.

**Briefs.** The user supplies them; each brief is tagged **TARGETED** or **BROAD**. If none are supplied, run the baked-in demo set:
1. *TARGETED* — Founders/owners of US marketing agencies, 11–50 staff, whose company About mentions outbound/lead gen.
2. *TARGETED* — SaaS founders (US/UK, ≤200 staff) whose personal bio mentions "sales" or "revenue".
3. *BROAD* — All sales leaders (VP Sales, Head of Sales, CRO) at US B2B companies, 11–200 staff.
4. *BROAD* — Directors/owners of UK recruitment agencies, any size.

---

## 🪜 Steps (run per brief; each has its own done-rule — that's what Loop Training Mode gates on)

**1 · Frame.** Restate each brief in one line, tag it TARGETED or BROAD, and — before touching any tool — write down an **expected size range** (order of magnitude) for its market, e.g. "US marketing agency owners: 50k–300k DMs, not 3k". This written expectation is what Step 3's realism gate checks against.
  - *Done-rule:* every brief has a one-liner, a tag, and a written expected range.

**2 · Design filters.** Translate the brief into GetLeads filters. Use `recommend_filters` (0 credits) for the mapping and `get_available_values` for exact enum spellings (`personas`, `seniority`, `industries`, `job_functions`, …) — never guess enum values. TARGETED briefs lean on `company_description` / `person_description` keyword filters (comma = OR) plus tight size/geo; BROAD briefs lean on `personas`/`seniority`/`job_titles` + `industries` + geo only. Always include `require_email: true` and `email_status: ["VALID"]` (the enum is VALID — never "verified").
  - *Done-rule:* a written filter set per brief, every enum value confirmed to exist, qualification filters (`require_email`, `email_status`) present.

**3 · Size + realism gate.** `count_contacts` (free, exact) each filter set. Compare `total_matching` to Step 1's expected range. **Within range → pass. More than ~10× below → too narrow to be real; more than ~10× above → filters aren't filtering.** On fail, name which filter you're loosening/tightening and re-count — that's one retry.
  - *Done-rule:* every brief's count is inside its expected range, with the count and the range shown side by side.

**4 · Sample-verify 70% — against the LIVE COMPANY, not the provider's fields.** Two passes; the second is the one the done-rule scores.
  - **4a · Field pre-screen (cheap).** Pull ~30 rows via `search_contacts` (vary `offset`). Screen the person side — is this genuinely the DM described (title/seniority, right geo)? Title/seniority are reliable in the data. This catches persona/title leaks (e.g. "Account Director" ≠ sales leader; GetLeads `personas` is loose — prefer explicit `job_titles` + Director+ seniority).
  - **4b · Ground-truth WebFetch (THE gate).** Take ~12–15 companies from the sample and **WebFetch each company's live website** — classify what the company ACTUALLY is against the brief, ignoring GetLeads' `Company Industry (LinkedIn)` tag and `About` bio. **Never trust the industry tag or bio as proof of company type** — proven 2026-08-03: the tag+bio methodology overstated accuracy by 20–40 points. `Business Consulting and Services` is a catch-all that returns family offices, ERP/NetSuite implementers, public-sector asset advisors, org-culture coaches; `Technology; Information and Internet` returns ISPs, hosting/colocation, IT-services consultancies; even `Software Development` leaks IT-services/support shops and igaming operators. Score = on-brief companies ÷ **reachable** companies (a dead/403/socket-closed site is *unverified*, not a pass). **≥70% of reachable → pass.** Also report the **unreachable rate** — if >30% of sites won't load, the pool is low-quality, flag it.
  - On fail, the WebFetch misses name the leaking filter — almost always a broad industry tag. Fix: drop the catch-all industry and re-gate with the clean tags (`Advertising/Marketing/PR/Design Services`, `Software Development`) plus a self-ID `company_description` keyword, or add `exclude_job_titles`/`exclude_industries`. Re-count (Step 3), re-sample (4a), re-WebFetch (4b). Retry cap 3.
  - *Done-rule:* every brief scores **≥70% on the WebFetch ground-truth pass** (not the field pass), with the score, the reachable/unreachable split, and 2–3 real off-brief companies (name + what they actually do) recorded.

**5 · Export.** For each passing brief: `export_contacts` (needs `confirmed: true` — confirm with the user first when Training Mode is ON) with the final filters, `max_per_company: 2` for BROAD briefs, then poll `check_contact_export` until `job_status: completed` and download the CSV. If `rows_exported` < `rows_available`, relay `cap_message` verbatim.
  - *Done-rule:* a downloaded CSV per brief with a row count matching Step 3's count (or an explained cap).

**6 · Qualify + push.** Net each CSV against Supabase suppressions + `contact_history` (never re-contact), then push every list into the signals tool via `/list-autopush` — a pulled list that isn't in the Lists page doesn't exist. Flag in the hand-off that GetLeads' VALID overstates deliverability ~24% (memory: `data-provider-duel-verdict`) — **Listmint-verify before any send**.
  - *Done-rule:* every list visible on the Lists page, suppression-netted, with the Listmint caveat stated.

**7 · Record.** One summary table in chat — brief · tag · count vs expected · sample accuracy · rows exported · list link — and update memory if anything surprising was learned about GetLeads' data.
  - *Done-rule:* table delivered; memory updated only if warranted.

---

## ✅ Overall done-rule

Done when **every brief** has a list that (a) scores **≥70% on the Step 4b WebFetch ground-truth pass** — verified against live company websites, NOT the provider's industry tag or bio — (b) sits **inside its written expected size range** — 70% accurate but implausibly small is NOT done — and (c) is suppression-netted and live on the Lists page. A list verified only on GetLeads' own fields is NOT done. Anything less is not done; anything past 3 failed attempts on a step stops and reports the blocker.

## 🧭 Runbook quick-reference
- Tools (GetLeads hosted MCP): `recommend_filters` · `get_available_values` · `count_contacts` (free) · `search_contacts` (1 credit/row, max 100/call) · `export_contacts` + `check_contact_export` (50k cap)
- Counting is free — **always count before you search**; never page an unfiltered industry.
- Keyword filters: `company_description` = company About, `person_description` = person bio; substring match, comma = OR.
- Wallet vs credits: search/export run on plan credits; a low prepaid wallet only blocks paid scrapes — never report it as "out of credits".
- Call GetLeads **serially** — parallel count/search calls time out (`person_description` is the slowest path).
- `CRO` persona also matches **Chief Risk Officers** (banks/insurers) — exclude or budget ~7% pollution on sales-leader briefs.
- `search_contacts` offsets return alphabetically clustered rows (one company can dominate a page) — spread offsets for sampling and rely on `max_per_company` at export.
- **Industry tag + bio are NOT ground truth** (2026-08-03 finding). Broad buckets leak hard: `Business Consulting and Services` → family offices, ERP/NetSuite implementers, asset-management advisory, culture coaches; `Technology; Information and Internet` → ISPs, hosting/colocation, IT-services consultancies; `Software Development` → IT-services/support shops, igaming operators. The clean tags are `Advertising / Marketing / Public Relations / Design Services`. Always WebFetch-verify a company sample (Step 4b) before trusting a shape; ~20–30% of company sites are dead/403 and count as unverified, not on-brief.
- Push: `/list-autopush` · suppression check: `lilly-data` (Supabase `contact_history` + `suppressions`).
- **"Upload to a campaign" = into Smartlead (Bjion, 2026-08-04):** when the ask is to put a list into a campaign, the prospects must land **inside the Smartlead campaign** (`add_leads_to_campaign`), not just be attached as a tool-side source. Do both: register the campaign in the tool AND push the leads to Smartlead (DRAFTED campaign only unless told to launch). See memory [[upload-to-campaign-means-smartlead]].
