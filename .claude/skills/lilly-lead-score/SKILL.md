---
name: lilly-lead-score
description: Score a list of companies against a brief / ICP to verdict each as qualified, borderline, or off-brief. Uses the LLM-first confidence ladder (training knowledge first, WebFetch only when uncertain) borrowed from `lilly-personalisation`. Use this skill whenever the user has a list of companies (from Prospeo / Ocean / AI Ark / a CSV / Sales Nav / a screenshot) and wants to check brief-fit before paginating further or burning DM-enrichment credits. Trigger on phrases like 'check these companies against the brief', 'are these on-brief', 'qualify this list', 'sample-fit check', 'is this SaaS / agency / [vertical]', 'verify these are [ICP]', 'score these leads against my ICP'. Replaces the over-WebFetching pattern of qualifying every company by HTTP fetch — most well-known companies are classifiable from training knowledge in zero web calls.
---

# Lilly Lead Score

## Purpose

Verdict a list of companies against an ICP brief, fast and cheap. Each company gets one of three verdicts (qualified / borderline / off-brief), driven by a confidence ladder that starts in LLM training knowledge and only escalates to WebFetch when the company is genuinely unknown or ambiguous.

Designed as the qualification layer that sits between list-builders (Prospeo / Ocean / AI Ark) and DM enrichment. Replaces the "WebFetch every candidate" pattern that bloats context and burns time on companies the model already knows cold.

---

## When to Use

Trigger when the user has a company list and needs a brief-fit verdict:
- After a list-builder skill returns page 1 candidates (sample-fit gate per the 50% abort rule)
- When the user pastes / uploads / screenshots a list of companies and asks "are these on-brief"
- When verifying a TAM list before passing to `lilly-tam`
- General "qualify this list" against any ICP definition

Accept input forms:
- A pasted list of company names
- A CSV / TSV with at least company name (domain optional but improves accuracy)
- A screenshot / image with company names (extract names first, then process)
- A list embedded in conversation (extract, then process)

Always confirm the brief criteria before scoring if not already established in context. Don't guess the ICP from prior conversation alone if the brief is ambiguous.

---

## The 4-step workflow

### Step 1 — Lock the brief

Before scoring, confirm the qualification criteria. If unclear, ask the user one round of focused questions:
- Target product/service category (SaaS, agency, hardware, marketplace, services consultancy, etc.)
- Target vertical (FinTech, HealthTech, MarTech, etc.) if relevant
- Target headcount band, geography, business model (subscription, one-off services, etc.)
- Hard exclusions (e.g. "not dev shops", "not hardware-led", "not partnership-only")

If the brief is already established (e.g. caller is `lilly-tam` running its sample-fit gate), use the calling context's brief and skip this step.

### Step 2 — Confidence ladder (the core methodology)

For every company in the list, walk this ladder. **Default to High; reserve WebFetch for genuine unknowns.**

| Confidence | What it looks like | Action |
|---|---|---|
| **High** | You can name a specific product, market position, or business model with no hedging (e.g. "Connecteam = deskless workforce SaaS"; "Distech Controls = Acuity Brands HVAC hardware"; "Next Srl - Software house = literally a dev shop, the name says so") | Verdict from training knowledge alone. **Do NOT call WebFetch.** |
| **Medium** | You can place the broad category but not the specific business model (e.g. "this looks like a German lighting company but I'm not sure if they're SaaS or hardware") | One WebFetch on the homepage to confirm. Then verdict. |
| **Low** | You truly do not know the company and the name + URL give no usable signal (e.g. "Taigle", "Linkity", or any generic-sounding 2026-vintage SaaS startup) | WebFetch + WebSearch (parallel). If both fail, mark verdict as ❓ Unknown — never guess. |

**Bias toward High.** WebFetch is slow, frequently 403s on cookie-walled sites, and burns context. Most B2B companies the user prospects against are identifiable from training knowledge. The ladder isn't just a quality choice, it's the throughput choice — High-mode batches of 25-50 companies clear in seconds, vs minutes for an all-fetch approach.

**Self-check question** before deciding High: *"If I write this verdict purely from what I know, would I bet $100 it's accurate?"* If yes → High. If hedging → Medium. If "no idea" → Low.

**Common ambiguity traps that should escalate one tier:**
- Generic single-word names (Touchdown, Linkity, Atlas, Beam, Nexus, Apex)
- Recent rebrands or acquisitions you may not know about
- Two companies sharing the same name (e.g. fetch.com — agency in 2018, consumer rewards platform now)
- Hardware-software hybrids (often miscategorised as SaaS by data sources)
- "X by Y" entries (these are often products, not companies — flag separately)
- Italian "srl", German "GmbH", or any non-English suffix where the company isn't well-known internationally

### Step 3 — Verdict each company

Three pots. Use the same buckets as the list-builder skills for cross-skill consistency.

| Verdict | When to use |
|---|---|
| ✅ **Qualified** | Confidently matches the brief. Pure-play in the right category, right vertical, right business model. Pass to enrichment. |
| ⚠️ **Borderline** | Partial fit. Hybrid business model where SOME revenue matches the brief (e.g. SaaS + heavy services), or right industry but ambiguous on a secondary criterion. User judgment whether to include. |
| ❌ **Off-brief** | Confidently wrong category, wrong business model, wrong vertical, or wrong entity type (e.g. a product name listed as a company). Drop. |
| ❓ **Unknown** | Confidence ladder bottomed out. Mark for manual review; never auto-promote to qualified. |

For each row, output: company name, verdict tag, one-line reason, confidence-tier used (`High` / `Medium` / `Low`).

### Step 4 — Tally and sample-fit signal

After verdicting all companies, output a tally and the sample-fit percentage:

```
✅ Qualified:  17/25 (68%)
⚠️ Borderline:  3/25
❌ Off-brief:   4/25
❓ Unknown:     1/25

Sample-fit (qualified + borderline) / total: 80%
```

**Sample-fit gates** (mirrors `lilly-tam` Step 3.4 / `lilly-tam`):
- **≥70% qualified** → strong filter; continue paginating, low qualification cost
- **50-69% qualified** → acceptable; continue but tighten on next iteration if possible
- **<50% qualified** → **HARD ABORT** for any caller in pagination mode. Filter is fundamentally wrong; tightening rarely recovers it. Surface the failure with diagnosis (which off-brief categories dominate, suggested filter changes).

If standalone (not called by a list-builder), report the sample-fit but don't abort — the user decides what to do with the result.

---

## Output format

Always return:

1. **Brief recap** (one line, what we scored against)
2. **Verdict table** — one row per company with verdict tag, reason, confidence tier
3. **Tally + sample-fit %**
4. **Anomalies block** — flag entries that are products-not-companies, hardware-led miscategorisations, dev-shop-by-name (literal "software house" / "studio" / "agency"), domain hijacks, dead companies. These are signals about the upstream filter, not just per-row data.
5. **Sources** (only the URLs WebFetched / WebSearched — never list sources for High-confidence rows)

Compact markdown table. Don't bullet-list a per-company rationale paragraph — the table column is enough.

---

## Guardrails

1. **LLM-first is the default, not the fallback.** Walk the confidence ladder honestly. Most companies won't need WebFetch.
2. **Self-rate confidence before fetching.** Apply the $100-bet test. If you're hedging mentally, that's Medium, not High.
3. **Never guess on Low.** Mark ❓ Unknown rather than push a fabricated verdict. Unknown rows do not auto-promote to qualified.
4. **Hybrid ≠ off-brief.** Companies with mixed business models (SaaS + services, hardware + software) go to ⚠️ Borderline, not ❌ Off-brief, unless the non-fitting revenue clearly dominates.
5. **Surface anomalies, not just verdicts.** A "product listed as a company" or "hardware co tagged as Software Development" tells the user something about their upstream filter — flag it visibly.
6. **Sample-fit gate consistency.** Use the same 50% / 70% thresholds as the list-builder skills so callers can route on the verdict without re-translating.
7. **No em dashes** in any output (Navreo style rule). Commas, colons, parentheses, hyphens, arrows.
8. **Source list at the bottom is for fetched URLs only.** Don't pad it with "[Linkity LinkedIn page]" if you didn't fetch — and don't list anything for High-confidence rows.

---

## Common patterns this skill catches

- **Product-as-company entries** (e.g. "Service Suite by Solera") — flag as ❌ Off-brief, note "this is a product, not a company"
- **Literal-name dev shops** ("X Software house", "Y Studio", "Z Digital Agency") — auto ❌ if brief excludes services. The name does the work.
- **Hardware-led hybrids** (Distech Controls, industrial automation cos) — usually ❌ for SaaS briefs even though LinkedIn tags them as Software Development.
- **VARs / resellers / integrators** (Andea reselling DELMIA) — ❌ for product-co briefs, ✅ for systems-integrator briefs.
- **Acquired-and-rebranded** (Cirata = WANdisco, Jint = Mozzaik365, Qwiet = Shiftleft) — ✅ if you know the rebrand, otherwise WebFetch.
- **Domain-hijacks / dead cos** (fetch.com used to be an agency, now a rewards app) — flag and ❌ off-brief.

---

## Cost

- LLM-first verdicts: **0 credits, 0 fetches**, near-instant
- Medium-confidence verdicts: 1 WebFetch each, free
- Low-confidence verdicts: 1 WebFetch + 1 WebSearch each, free

A 25-company list with the average 60-80% High-confidence rate clears in 5-10 seconds and 5-10 fetches max.

---

## Hand-off

**When called by a list-builder** (sample-fit gate):
- Return verdict table + tally + sample-fit %
- Caller routes on the % per its own pagination rule (continue / tighten / abort)

**When called by `lilly-tam` Step 0** (verifying expanded list before DM enrichment):
- Return the qualified pot + borderline pot
- Caller passes both to DM enrichment

**Standalone** (user pasted a list and asked):
- Return the full table + anomalies + tally
- No automatic next step; user decides

---

## Quick reference

| Need | Tool | Cost |
|---|---|---|
| Verdict from training knowledge | none (LLM only) | 0 |
| Verify medium-confidence company | WebFetch homepage | free |
| Identify low-confidence company | WebFetch + WebSearch in parallel | free |

See also:
- `lilly-personalisation/SKILL.md` — source of the confidence-ladder pattern (used there for `Why` text generation; mirrored here for verdict classification)
- `lilly-tam/SKILL.md` — Step 3.4 / 3.5 sample-fit gate; should call this skill instead of fetching every candidate
- `lilly-tam/SKILL.md` — same pattern, same delegation
- `lilly-ocean-tam-builder/SKILL.md` — Phase 4 qualification step
- `lilly-tam/SKILL.md` — Step 0 expansion verification before DM enrichment
