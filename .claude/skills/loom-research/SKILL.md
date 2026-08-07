---
name: loom-research
description: "Deep-dive company research for Loom prospecting videos. Use whenever the user asks to research a company, look up a prospect, pull an ICP, find clients/events/hiring signals/competitors, or says they're making a Loom video about a company. Trigger on phrases like 'research this company', 'can you look into [URL]', 'loom research on X', 'pull an ICP for', 'find events for', or any request that pairs a company name/URL with intent to understand their business, clients, or buyers. Produces the full 7-task research pack (overview, ICP, named clients with AI Ark lookalike links, events, hiring signals, top 10 competitors on LinkedIn, sales-team structure with ASCII org chart via Prospeo /search-person) plus a one-page cheat sheet — designed to be read aloud on a Loom screen-share."
---

# Loom Research — Company Prospecting Deep-Dive

## Purpose

The user records personalised Loom videos for outbound prospecting. Before each Loom they need a structured research pack about the target company so they can:

1. Speak fluently about what the company does on camera.
2. Identify who their customers are (to find lookalikes).
3. Spot events their customers attend (to scrape exhibitor lists).
4. Spot buying-intent hiring signals **at their customers (the target's ICP)** — roles that, when an ICP-fit company hires them, mean that company is now in-market for the target's product. These are NEVER the target company's own job openings; the Loom uses them to show the prospect how the user would surface their in-market buyers.
5. Know who their competitors are (to position against them on camera and scrape competitor LinkedIn followers as warm prospects).
6. Understand the shape of the target's sales org (CRO / AEs / SDRs / RevOps?) so the Loom message matches their buying sophistication — pitching SDR enablement to a founder-led team is wasted breath.

This skill produces that pack in a predictable format so the user can scan it mid-recording without hunting for information.

## When to trigger

Trigger any time the user:
- Gives you a company URL and asks you to "research", "look into", "dig into", "pull info on" it.
- Mentions they're making a Loom / prospecting video / outbound video about a company.
- Asks for an ICP, lookalike list, client list, or event list for a specific company.
- Asks "what events would {company}'s customers attend?", "what hiring signals show {company}'s buyers are in-market?", or similar buyer-intent questions tied to one company.

If in doubt, trigger. Under-triggering costs more than over-triggering here.

## Required inputs

You need a **company website URL**. If the user gives only a name, ask for the URL (one line) before proceeding.

Current date is in the `currentDate` context variable — use it when reasoning about "upcoming" events.

## Research method

Work in this order. Do not skip steps — each task feeds the next, and the cheat sheet depends on all of them.

### Step 1 — Fetch the homepage
Use `WebFetch` on the provided URL. Extract: what they do, industries served, services/products, positioning claims, any client logos, testimonials, case studies, and the main navigation links.

### Step 2 — Fetch supporting pages in parallel
In a single turn, fan out `WebFetch` calls to the most likely evidence pages — typically `/about`, `/about-us`, `/customers`, `/case-studies`, `/clients`, `/resources`, `/blog`. Skip any that 404. You're hunting for named clients, testimonials, leadership, geography.

### Step 3 — Web search to fill gaps
Run `WebSearch` for:
- `"{company name}" case study` / `"{company name}" customers` / `"{company name}" testimonials` — to surface named clients not on their own site.
- Industry + region + event keywords for Task 4 (e.g. `"{industry} conference {region} 2026 exhibitors"`).
- If the company resells third-party tech, search the underlying vendors' customer lists and flag this caveat in the output.

Run independent searches in parallel, not sequentially.

### Step 4 — Competitor search (for Task 6)
Run `WebSearch` for competitor rankings and LinkedIn follower counts:
- `top {niche/category} agencies 2026 list` to surface the industry's published rankings.
- `"{competitor name}" LinkedIn followers` (batch several competitors per query using `OR`) to get follower counts.
- Aim for 10 competitors with **≥10,000 LinkedIn followers**. If fewer than 10 clear that bar, include the strongest sub-10k direct competitors and flag them as below-threshold — don't pad the list with irrelevant names.

### Step 5 — Sales-team structure via Prospeo (for Task 7)
Run a single Prospeo `/search-person` call against the target domain, sales department, seniority C-Suite through Senior. **Use only Prospeo — do not call AI Ark for this task.** Cost is 1 credit per page returning ≥1 result; cap at 2 pages by default. Full request body, pagination rules, false-positive filtering, and output format are in Task 7 below — read that section before making the call.

### Step 6 — Assemble the output in the exact structure below

---

## Output structure — use this template verbatim

Use the headings, table columns, and section order below without deviation. The user reads this off-screen during Loom recording; consistency matters more than creativity.

### TASK 1 — Company Overview
A 3–5 sentence paragraph covering:
- What the company does
- Their industry / niche
- Core service or product offering
- How they position themselves and who they claim to serve

### TASK 2 — Ideal Customer Profile (ICP)
Present as a table with these exact rows:

| ICP Attribute | Detail |
|---|---|
| Industries | … |
| Company size | … (startup / SMB / mid-market / enterprise) |
| Geography | … |
| Decision-maker titles | … |
| Pain points before | … |
| Outcomes after | … |

Follow the table with a one-sentence **ICP one-liner** in italics.

### TASK 3 — Named Clients & Lookalike Search
Table with these columns: **Client | Industry | Outcome / Mention | LinkedIn | AI Ark Lookalike**.

- Aim for 5–10 named clients. If you can't find any, state it plainly.
- For each client, find the LinkedIn company-page slug (the segment after `/company/` in their LinkedIn URL).
- Build the AI Ark Lookalike link using this exact format, with the LinkedIn URL percent-encoded:
  ```
  https://app.ai-ark.com/search/company?value=https%3A%2F%2Fwww.linkedin.com%2Fcompany%2F{slug}
  ```
- Render the AI Ark link as markdown: `[Search Lookalikes](…)`.
- If the "clients" on the company's site are actually the underlying vendor's customers (common when the target is a reseller/distributor), say so in a short caveat block above the table — don't quietly present them as direct clients.

### TASK 4 — Upcoming Events & Conferences
Table with columns: **Event | Date | Location | Who Exhibits | Why It's Relevant | Website**.

- Minimum 5 events; mix global and niche.
- In-person only.
- Prioritise events in the next 3–6 months from `currentDate`. Recent events in the last ~2 months are acceptable if still useful for exhibitor scraping — flag them as recent.
- Events must match the ICP (industry + geography + buyer profile), not just the company's own sector.

### TASK 5 — Buying-Signal Hires (at the target's customers / ICP)

> **CRITICAL FRAMING — read before writing this task.** These hiring signals are about the **target's CUSTOMERS — i.e. the ICP companies the target sells to (Task 2)** — NOT about the target company itself. A hire of one of these roles **at an ICP-fit company** is a buying-intent trigger for the *target's product*: it means that company now has the pain the target solves and is in-market to buy. The user's Loom uses this to show the prospect "here's how we'd spot the companies ready to buy from you."
>
> **NEVER list the target company's own job openings here.** If you catch yourself writing roles the *target* is hiring (e.g. "{target} is hiring an SDR"), stop — that is the wrong task. Always ask: "when a company in {target}'s ICP hires this role, does it signal they now need {target}'s product?" If yes, it belongs here; if it's just the target staffing up, it does not.
>
> _Worked example — target = a PSA tool for consulting firms:_ the buying signal is a **consulting firm** hiring a Head of Resource Management / PMO Director / Head of Delivery (they're scaling project staffing and outgrowing spreadsheets = ready for PSA), NOT the PSA vendor hiring a Growth Manager.

Group signals by urgency: 🔴 **HIGH URGENCY**, 🟡 **MEDIUM URGENCY**, 🟢 **LOW URGENCY**.

For each signal provide:
- **Signal category** — the type of buying-intent hire (the role/function an ICP company adds that reveals the pain the target solves)
- **Roles to look for** — the ICP-side job titles to scan job boards for, as a single comma-separated list where **every job title is fully spelled out as its own standalone string**. The user pastes this directly into a job-title scanner (LinkedIn Jobs filter / hiring-signal tool), and the tool matches on exact title strings — so compound forms break it.

  **Required format:** `Title One, Title Two, Title Three, ...`

  **Forbidden compound forms** — every one of these breaks the downstream tool:
  - Slashes: ❌ `Head/Director of E-commerce` → ✅ `Head of E-commerce, Director of E-commerce`
  - Slashes between titles: ❌ `Amazon Manager / Brand Manager / Head of Amazon` → ✅ `Amazon Manager, Brand Manager, Head of Amazon`
  - "or": ❌ `Head of Amazon or Amazon Manager` → ✅ `Head of Amazon, Amazon Manager`
  - "&" or "+": ❌ `VP Marketing & Sales` → ✅ `VP Marketing, VP Sales`
  - Parentheticals: ❌ `Head of Amazon (Senior)` → ✅ `Head of Amazon, Senior Head of Amazon`
  - Abbreviations of compound titles: ❌ `D2C lead` → ✅ `Head of D2C, Director of D2C, D2C Manager`
  - "Type X / Type Y Manager": ❌ `Marketplace / E-commerce Manager` → ✅ `Marketplace Manager, E-commerce Manager`

  **Expand every variant explicitly.** If you'd write "Head/Director/VP of X", expand to `Head of X, Director of X, VP of X, VP of X`. If you'd write "X (Sr/Jr)", expand to `Senior X, Junior X`. Spelling matters — match LinkedIn's job-board canonical form, not internal company shorthand.
- **Why it's a signal** — one sentence on why an ICP company making this hire now needs the target's product
- **Strongest in** — which ICP segment / company type the signal fires hardest in
- **Justification** — one-line reasoning for the urgency rating

After the signals, include three short sub-sections:
- **Where to find:** (platforms to find ICP companies making these hires — LinkedIn Jobs, Greenhouse, Lever, JobStreet, eFinancialCareers, regional boards relevant to the ICP's geography)
- **LinkedIn filters to use:** (filters to surface the ICP companies hiring these roles — location / industry / keywords / company size, set to the ICP from Task 2)
- **Outreach hook (email opener):** a one-sentence cold-email opener the **target** would send to an ICP prospect that just made the hire — written in the target's voice, tied to the target's value prop, with `{Company}` (the ICP prospect that made the hire) and `{role title}` placeholders.

### TASK 6 — Top 10 Competitors (LinkedIn Company Accounts)
Table with columns: **# | Competitor | LinkedIn | Followers | Positioning / Relevance**.

- Rank by LinkedIn follower count, largest first.
- Target 10 competitors with **≥10,000 LinkedIn followers**.
- If fewer than 10 clear the threshold, include the strongest sub-10k direct competitors to reach 10 and flag each with *(just below 10k)* or similar — don't pad with irrelevant names.
- Render each LinkedIn as `[linkedin.com/company/{slug}](https://www.linkedin.com/company/{slug})`.
- Include a short **Positioning / Relevance** cell (one line) explaining how each competitor relates to the target company — direct like-for-like, adjacent, bigger-tier, vertical specialist, tooling-with-services, etc.
- Below the table, add a one-line **Bonus** row listing 3–5 additional sub-threshold competitors that still appear on 2026 "top {category}" lists or that cover a vertical niche (e.g. category specialists matching the target's proof-of-fit client).

### TASK 7 — Sales Team Structure (Prospeo)

The **ASCII org chart** is the headline deliverable here — the user reads it aloud on camera. Use only Prospeo. Do NOT call AI Ark for this task.

**API call:**

The `Bash` tool runs in a non-interactive shell that does not auto-load `~/.zshrc`, so source the keys file inline every time:

```bash
source ~/.navreo-keys.env && curl -s -X POST https://api.prospeo.io/search-person \
  -H "X-KEY: $PROSPEO_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "page": 1,
    "filters": {
      "company": {"websites": {"include": ["{TARGET_DOMAIN}"]}},
      "person_seniority": {"include": ["Founder/Owner","C-Suite","Vice President","Head","Director","Manager","Senior"]},
      "person_department": {"include": ["Sales"]}
    }
  }' > /tmp/prospeo_p1.json
```

Replace `{TARGET_DOMAIN}` with the bare domain (e.g. `admortgage.com`). Then inspect with `jq '{total: .pagination.total_count, total_pages: .pagination.total_page, returned: (.results | length)}' /tmp/prospeo_p1.json`.

**Pagination and cost rules:**
- Cost is **1 credit per page that returns ≥1 result**.
- If `pagination.total_count > 25`, also fetch page 2 (set `"page": 2` in the body, write to `/tmp/prospeo_p2.json`).
- **Cap at 2 pages by default** — that's ≤2 credits per Loom.
- If `total_count > 100` (large enterprise), drop `"Manager"` and `"Senior"` from the seniority filter and re-run page 1 only — gives a leadership-only view without bloat.
- If the API returns `{"error":true,"error_code":"INVALID_API_KEY"}`, the env var didn't load. Source `~/.navreo-keys.env` inline (not via parent shell).

**Extract clean records** — merge pages and sort by title:

```bash
jq '[.results[] | {name: .person.full_name, title: .person.current_job_title, headline: .person.headline, linkedin: .person.linkedin_url.linkedin, location: .person.location, seniority: (.person.job_history[0].seniority // "n/a")}]' /tmp/prospeo_p1.json > /tmp/p1_clean.json
# repeat for p2 if fetched, then merge:
jq -s 'add | sort_by(.title)' /tmp/p1_clean.json /tmp/p2_clean.json > /tmp/all_clean.json
```

**False-positive filtering** — exclude (with a one-line caveat in the output) any record where:
- `headline` mentions a different employer (e.g. "at Mr. Cooper" when target is AD Mortgage). Prospeo data lags job changes by months.
- `location` is far outside the target's primary geography AND the headline doesn't confirm a remote role (often offshore VAs or mismatched profiles).
- `title` and `headline` are wildly inconsistent (e.g. `title: "VP of Sales"` + `headline: "Professor"`) — flag with ⚠ but include if the LinkedIn URL is plausible.

LinkedIn slugs that contain a former employer's name (e.g. `chris-bryson-flagstar`) are common when an employee changed jobs and kept their old slug — verify via the headline, don't auto-exclude.

**Output structure** — produce these sections in this order:

#### Headline numbers
One line: total sales-tagged people · leadership-tier count (Director and above) · false positives excluded.

#### Org chart (ASCII)
The visual the user reads aloud. Use this format, infer tiers from titles + locations, and write structural gaps explicitly (don't paper over a missing region):

```
{CEO Name} — CEO/Founder ({location})
│
├── {CMO Name} — CMO ({location})  [if present]
│
├── National BD / Channel leadership (HQ-based)
│   ├── {Name} — SVP/Sr VP Business Development ({location})
│   └── {Name} — SVP/Sr VP Business Development ({location})
│
├── Regional Sales Directors (group by region)
│   ├── EAST — {Name} (SVP, East Regional Sales Director — {location})
│   ├── CENTRAL — {Name} ({location})
│   └── WEST — [no SVP surfaced — flag as gap or data miss]
│
├── VP / AVP — individual-contributor AEs (count: N, scattered across {states})
│
├── Inside Sales / BD layer ({HQ city}-concentrated)
│   ├── {Name} — Sales Development Team Lead
│   ├── {Name} — BD Team Lead
│   └── {N} BD Specialists / BDRs
│
└── Sales Ops / RevOps
    └── {Name} — Sales Operations Manager  [or "no dedicated RevOps surfaced"]
```

Adapt the branches to what's actually in the data: if there's no CMO, drop that line; if there are 4 regional pods, list 4. The goal is a Loom-readable visual, not a fixed template.

#### Senior Leadership table
True managers/leaders only — C-Suite, SVPs, VPs running teams, Directors, Sales Managers. Columns: **Tier | Name | Title | Location | LinkedIn**.

#### AE Bench table
Individual-contributor AEs at VP/AVP/Senior AE level. Columns: **Name | Title | Location | LinkedIn**.

#### Inside Sales / BDR layer
BD Team Leads, BDRs, BD Specialists, Account Managers. Columns: **Name | Title | Location | LinkedIn**.

#### Sales Ops / RevOps
Bullet list (usually 0–2 people). State explicitly if no dedicated RevOps surfaced.

#### ⚠ Caveats
One short bullet per flagged record. Also note structural gaps (e.g. "no West Region SVP surfaced", "no CRO/CSO title visible", "title inflation — most VP/AVP titles are individual-contributor AEs").

#### Strategic takeaways for the Loom
3–6 bullets answering the questions that change how the user pitches:
- Is there a CRO/CSO, or is it founder-led? (changes who the user emails)
- Two-headed BD function? Regional pods? Channel-specific overlay (TPO/correspondent/wholesale)? (frames the Loom intro)
- Already running a BDR motion? (don't pitch BDR tooling if so)
- Sales Ops built or thin? (live opening if thin)
- Title inflation? (warn the user not to over-trust VP/AVP titles in their list)
- Any visible offshore / remote-team presence flagged via locations?

### FINAL SUMMARY — One-Page Cheat Sheet
End with a cheat sheet containing:
- **Company snapshot** — 2 sentences
- **ICP (one sentence)**
- **Top 3 named clients** — each with its AI Ark Lookalike hyperlink
- **Top 3 upcoming events** — name, date, location, website link
- **Top 3 buying-signal hires** — these are ICP-side hires (at the target's customers, per Task 5), never the target's own openings; each with urgency emoji, the roles to look for **(same comma-separated, fully-spelled-out format as Task 5 — no slashes, no compound forms, no abbreviations)**, and a suggested outreach hook
- **Top 3 competitors** — name, follower count, one-line positioning
- **Sales org top line** — one sentence on shape (e.g. "Founder-led, no CRO; two SVPs of BD + 3 regional sales pods; ~15 VP/AVP-level AEs; thin RevOps") and the 1–3 names the user should actually email

### Sources
Finish the response with a `**Sources:**` section listing every URL used as markdown links. `WebSearch` results must be cited — don't strip them.

---

## Style rules

- Use tables where the template calls for tables; don't collapse them into bullets.
- Inline links as markdown `[label](url)` — never paste raw URLs.
- Keep copy dense and factual. No fluff adjectives, no filler sentences. The user reads this while recording.
- When a claim is inferred (e.g. positioning of an unnamed client), flag the inference rather than asserting it as fact.
- When the company's own site shows logos that are really the client base of a third-party tool they resell, surface that caveat explicitly in Task 3. Misleading the user on this leads to bad lookalike targeting.

## Do not

- Do not skip a task because evidence is thin — state what's missing and move on.
- Do not invent named clients. If none can be verified, say "No named clients found on the site or via external search" and still produce the rest of the tasks.
- Do not list online-only webinars in Task 4; in-person only.
- Do not list the **target company's own** job openings as buying signals in Task 5. Task 5 is ALWAYS about hires at the target's customers (their ICP) — roles that signal an ICP company is ready to buy the target's product. The target staffing up is not a buying signal.
- Do not output a TodoWrite list or progress chatter — the user wants the final pack in one message.
