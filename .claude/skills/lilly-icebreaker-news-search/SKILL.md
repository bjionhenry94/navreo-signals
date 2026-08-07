---
name: lilly-icebreaker-news-search
description: "Surface recent news about a list of companies via Serper.dev's `/news` endpoint and convert each hit into a one-line icebreaker for cold-email personalisation. Use this skill whenever the user has a list of companies (or domains, or a Smartlead campaign) and wants time-anchored opener lines (funding, hires, launches, awards, partnerships, customer wins) to fill `{{Icebreaker}}` or a similar custom variable. Trigger on phrases like 'find recent news for these companies', 'pull icebreakers from news', 'generate news-based openers', 'what's happening at these companies', 'serper news', 'time-anchored personalisation', 'news icebreakers for the campaign'. Costs 1 Serper credit per company plus 1 cheap LLM call. Filters out stale (>45d), sensitive (layoffs/lawsuits), and templated wire-service noise. Falls back to podcast/LinkedIn-post searches when no news, and explicitly returns NO_HIT rather than fabricating."
---

# Lilly Icebreaker News Search

## Purpose

Take a list of companies, return a CSV of recent, icebreaker-worthy news hits with a generated one-line opener per company. Fills the `{{Icebreaker}}` Smartlead variable (or equivalent) at scale, cheaply.

The killer signal is **time-anchored news**: funding rounds, senior hires, product launches, M&A, customer wins, awards. These let an opener say "saw your X" with a real referent the prospect just lived through.

This skill replaces the over-reliance on `lilly-personalisation` Why/Icebreaker fields when the goal is specifically to anchor on a recent public event.

---

## When to Use

Trigger when the user wants:
- News-based openers across a campaign list before launch.
- A bulk personalisation pass on already-imported Smartlead leads.
- A pre-flight check on what's "in the news" for a target account list.
- Time-anchored alternative to the generic Why/Icebreaker generation.

Accept input forms:
- "Find recent news for these companies"
- "Pull icebreakers from news"
- "Generate news-based openers for campaign X"
- "What's happening at these companies"
- A CSV / domain list / Smartlead campaign ID.

Do NOT use this skill when:
- The list is full of solo consultants / one-person firms (no news to find).
- The brief calls for non-news personalisation (role-relevant pain point, custom case study).
- Cost matters and the user already has a recent enrichment from another source.

---

## API access

| Endpoint | URL | Method | Cost |
|---|---|---|---|
| News search | `https://google.serper.dev/news` | POST | 1 credit |
| Web search (fallback) | `https://google.serper.dev/search` | POST | 1 credit |
| Webpage scrape (optional) | `https://scrape.serper.dev` | POST | 2-10 credits |

**Auth:** `X-API-KEY: $SERPER_API_KEY` (in `~/.navreo-keys.env`)
**Content-Type:** `application/json`

**Pricing reference:** $50 = 50,000 credits ($0.001 per call). 2,500 free credits on signup.

---

## The 6-step workflow

### Step 1 — Input

Take from the user (or calling skill):
- Company list. Accepts: company names, domains, or Smartlead campaign ID.
- Freshness window (default = 30 days, max useful = 90).
- Output target: CSV (default), or direct push into a Smartlead custom variable.
- Optional ICP / brief context (helps the LLM pick the most relevant hit).

If input is domains-only, hydrate with `lilly-personalisation`'s company-name resolver or a quick `/search` to get the canonical name. Quoted-name search is much higher-precision than domain-search.

### Step 2 — Build the query

**Default (catch-all):**

```json
{
  "q": "\"{Company Name}\"",
  "gl": "us",
  "hl": "en",
  "num": 10,
  "tbs": "qdr:m"
}
```

Quotes are mandatory. Without them, "Apple" matches the fruit, "Square" matches everything, and most short-name companies generate noise.

**`tbs` cheat sheet:**
| Window | `tbs` value |
|---|---|
| Past hour | `qdr:h` |
| Past day | `qdr:d` |
| Past week | `qdr:w` |
| **Past month** | `qdr:m` ← default |
| Past year | `qdr:y` |

**Disambiguation: when the company name is generic.**
Add an industry word or domain stem:
- `"\"Square\" payments"` (vs the geometry word)
- `"\"Apple\" tech"` (vs the fruit / records label)
- For domain-bearing inputs: `"\"{Company}\" {brand-stem}"` where brand-stem is the unique non-tld part of the domain.

### Step 3 — Call `/news` and parse

```bash
curl -sS -X POST "https://google.serper.dev/news" \
  -H "X-API-KEY: $SERPER_API_KEY" \
  -H "Content-Type: application/json" \
  -d "$BODY"
```

Response shape (relevant fields):
```json
{
  "news": [
    {
      "title": "...",
      "link": "https://...",
      "snippet": "...",
      "date": "3 days ago",
      "source": "TechCrunch",
      "imageUrl": "https://..."
    },
    ...
  ]
}
```

Empty `news: []` (or missing key) means no hits. Treat as Step 4 = fail-fast to fallback.

### Step 4 — Filter and rank

Apply in this order:

**(a) Freshness filter.** Parse `date` (relative string, e.g. "3 days ago", "2 weeks ago", "1 month ago"). Convert to absolute days. Drop anything older than `freshness_window`.

Parser rules:
- "X minutes/hours ago" → 0 days
- "X days ago" → X
- "X weeks ago" → X * 7
- "1 month ago" → 30
- "X months ago" → X * 30
- Dated string ("Jan 12, 2026") → calculate from today
- Unparseable → keep, flag for review

**(b) Sensitive-topic filter.** Drop or flag any result whose title or snippet contains (case-insensitive):
- `layoff`, `layoffs`, `laid off`, `cut jobs`, `cuts staff`
- `lawsuit`, `sued`, `sues`, `class action`, `settlement`, `fined`
- `fired`, `ousted`, `resigns`, `steps down`, `departs`, `exit`
- `scandal`, `controversy`, `accused of`, `allegations`
- `data breach`, `hacked`, `exposed`, `leak`
- `bankruptcy`, `chapter 11`, `liquidation`, `closing down`
- `missed earnings`, `disappoints`, `slumps`, `plunges`, `tanks`

Sensitive-topic results are not always wrong (a response to a lawsuit can be a positive partnership pivot), but the LLM will get tone wrong by default. Flag them as `NEEDS_REVIEW` rather than auto-using.

**(c) Wire-service deprioritisation.** Sources to push to bottom of ranking (use only if no other option):
- PR Newswire, Business Wire, GlobeNewswire, Cision, Newswire.com, Newsfile, Accesswire
- The company's own blog/newsroom subdomain (templated, no journalistic distance)

These read like press releases when referenced verbatim. Use when no third-party coverage exists.

**(d) Re-syndication check (optional but recommended).** If `date` says "2 days ago" but the URL slug looks like an old article (e.g. `/2024/...`), WebFetch the article and trust the published date in the article metadata over Serper's freshness label. Re-syndicated old news is the #1 cause of "saw your funding round" referencing a 2-year-old round.

**Rank surviving results by:**
1. Recency (more recent = better).
2. Specificity (named events: funding, hires, launches > generic mentions).
3. Source quality (TechCrunch / Bloomberg / reputable trade pubs > listicles > wires).

Take top 3.

### Step 5 — Optional WebFetch for thin snippets

If the top result's snippet is under ~50 characters or ends in `...` mid-sentence, the snippet alone won't give enough context to write a clean opener. WebFetch the URL with the prompt:

> "Extract the single most concrete fact about [Company Name] from this article. Funding amount, hire name + title, product name + launch date, customer name. One short sentence. Skip context, skip background, skip generic prose."

Cost: free (WebFetch in-session). Adds ~3-5s per company. Run only on companies where the snippet is thin.

### Step 6 — Generate the icebreaker line

For each company with at least one surviving result, send the top hit to a cheap LLM (Haiku via OpenRouter or direct) with this prompt:

```
You are writing a single-line opener for a cold email.

Company: {company_name}
News headline: {title}
Source: {source}
Date: {date}
Snippet: {snippet}
[Optional ICP context: {brief}]

Task: write ONE icebreaker sentence under 15 words.
Rules:
- Reference the specific event in the headline (funding amount, hire name, product, customer, partnership).
- Use a casual past-tense observation: "Saw...", "Noticed...", "Just caught the...".
- No fake enthusiasm ("congrats on the amazing...", "love what you're doing").
- No questions ("how did you...?").
- No CTA. The opener leads into the next sentence which is from the rep, not you.
- If the news is sensitive (layoff, lawsuit, departure, breach, bankruptcy), output: SKIP_SENSITIVE.
- If the news is too vague to anchor on (generic mention, listicle inclusion, syndicated old news), output: SKIP_WEAK.

Output: just the sentence, or SKIP_SENSITIVE / SKIP_WEAK. No preamble.
```

If output is `SKIP_*`, fall to the next-best result. If all 3 fail, mark `NO_HIT`.

### Step 7 (fallback chain) — if no news

If the catch-all `/news` query returns 0 surviving results, run in order:

1. **Widen the window:** retry with `tbs=qdr:y` (past year). Stricter snippet filter (must contain a named entity: amount, person, product, company).
2. **Podcast / interview search:** `q = "\"{Company}\" (podcast OR interview OR fireside)"` on `/search`, `tbs=qdr:y`. If a hit, opener templates: "saw [Founder]'s episode on [Show]".
3. **Founder LinkedIn post:** `q = "\"{Founder name}\" site:linkedin.com/posts"` on `/search`. Requires founder name as input or a pre-pass to find it.
4. **Conference / speaking gig:** `q = "\"{Company}\" (speaking OR keynote OR panel)"` on `/search`, `tbs=qdr:y`.
5. **Mark `NO_HIT`** with reason. Do NOT fabricate. Surface to the user that this company needs a different personalisation angle (or skip it from the campaign).

---

## Output schema

CSV columns:

| Column | Description |
|---|---|
| `company_name` | Input company name |
| `domain` | If provided in input |
| `status` | `HIT` / `HIT_FALLBACK` / `NEEDS_REVIEW` / `NO_HIT` |
| `query_used` | Exact `q` string sent to Serper |
| `endpoint` | `/news`, `/search` (which fallback) |
| `headline` | News title |
| `source` | Publication |
| `published_date` | Parsed absolute date (YYYY-MM-DD) |
| `link` | Article URL |
| `icebreaker` | Generated one-line opener (or empty if NO_HIT) |
| `notes` | Why fallback was used, sensitive-topic flag, etc. |

**Status definitions:**
- `HIT`: clean news from `/news`, freshness <= window, non-sensitive, third-party source.
- `HIT_FALLBACK`: surfaced via podcast / LinkedIn / conference fallback.
- `NEEDS_REVIEW`: sensitive-topic content detected. Skip auto-use. Surface to user.
- `NO_HIT`: nothing usable found. Either drop from campaign or use non-news personalisation.

---

## Cost calibration

Per 100 companies:
- 100 Serper `/news` credits = $0.10
- ~30 fallback `/search` credits (typical 30% no-news rate for B2B SMBs) = $0.03
- ~5 WebFetch calls for thin snippets = free in-session
- ~70 LLM icebreaker generations on Haiku = $0.07
- **Total: ~$0.20 per 100 companies, or $20 per 10,000.**

For comparison: Clay's native AI-with-web-research enrichment runs $0.05-$0.20 PER ROW. This skill is roughly 25-100x cheaper.

---

## Guardrails

1. **Always quote the company name in the query.** Unquoted "Apple" / "Square" / "Notion" matches the dictionary word.
2. **Default freshness = 30 days, max useful = 90.** Older than 90 reads as "you finally caught up to old news" which is worse than no opener.
3. **Sensitive-topic filter is mandatory** (Step 4b). Auto-flag, never auto-use. Even a positive-sounding lawsuit settlement reads tone-deaf.
4. **Wire-service results deprioritised**, never blocked. PR Newswire is fine when there's no third-party coverage.
5. **Re-syndication trap.** If `date` is recent but URL slug looks old, WebFetch and use the article's published date.
6. **Top 3 → LLM, not all 10.** Saves LLM cost. Top 3 is enough to pick a good hook.
7. **Skip-sensitive / skip-weak escape valves in the LLM prompt.** Better to fall back to next-best result than force a bad opener.
8. **NO_HIT is a valid output.** Do NOT fabricate news. Surface to user with reason. Recommend a different personalisation angle (Why/Icebreaker via `lilly-personalisation`, or drop from campaign).
9. **Fallback chain order matters.** News first (most icebreaker-worthy), then podcast, then LinkedIn post, then conference. Each is a step down in signal quality but still better than generic.
10. **Status-tag every row.** Downstream (`lilly-bot` / Smartlead push) needs to know which leads have icebreakers and which need a different angle.
11. **Disambiguate generic names BEFORE running.** Pre-flight check: if the input list contains short-name cos like "Square", "Notion", "Block", add an industry word or domain stem at query construction time.
12. **Don't WebFetch every result.** Only when the snippet is thin (<50 chars or mid-sentence ellipsis). Otherwise the snippet + headline is enough.
13. **Cap fallback retries at 4.** After news + 3 fallback queries, accept NO_HIT. Don't burn 10+ credits chasing a company that's truly invisible.

---

## Quick reference

| Need | Endpoint | Body |
|---|---|---|
| Recent news (default) | `POST google.serper.dev/news` | `{"q":"\"X\"","tbs":"qdr:m","num":10}` |
| Past-year news (fallback) | `POST google.serper.dev/news` | `{"q":"\"X\"","tbs":"qdr:y","num":10}` |
| Podcast search (fallback) | `POST google.serper.dev/search` | `{"q":"\"X\" (podcast OR interview)","tbs":"qdr:y"}` |
| LinkedIn post (fallback) | `POST google.serper.dev/search` | `{"q":"\"Founder\" site:linkedin.com/posts"}` |
| Conference (fallback) | `POST google.serper.dev/search` | `{"q":"\"X\" (keynote OR speaking)","tbs":"qdr:y"}` |
| Article scrape (thin snippet) | `POST scrape.serper.dev` | `{"url":"..."}` |

See also:
- `lilly-personalisation/SKILL.md` for non-news Why/Icebreaker generation.
- `lilly-bot/SKILL.md` for pushing the resulting `{{Icebreaker}}` into a Smartlead campaign.
- `~/.navreo-keys.env` for `SERPER_API_KEY`.
