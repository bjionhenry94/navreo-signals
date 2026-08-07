# Company Qualification — Confidence Ladder

Adapted from the company-identification pattern in `lilly-personalisation`. This file is the deeper reference for the "company qualification" step in the main `SKILL.md` workflow.

The job in this skill is narrower than in `lilly-personalisation`: we're not generating personalised copy, we're making a **binary in/out decision** — does this company match the ICP, and is it on the avoid-list. So we can be even faster about it.

---

## The Three Confidence Tiers

| Tier | Looks like | Action | Cost |
|---|---|---|---|
| **High** | You can name the company's specific product, service, or business model from training knowledge alone, with no hedging | Score directly. **No web fetch.** | ~0 — pure LLM call |
| **Medium** | You can place the broad industry but not the specific product line | One WebFetch on the homepage to confirm | ~5–10s + tokens |
| **Low** | Name + domain give no usable signal | WebFetch + WebSearch. If still unclear → flag `unknown`, do NOT guess | ~30s + tokens |

**Bias to High.** WebFetches are slow, often 403'd by Cloudflare, and waste tokens. If the file already has a `Linkedin Description` / `Linkedin Specialities` / `Linkedin Industry` column populated, treat that as a free pre-fetched company description and stay at High.

---

## Self-Rating Heuristic

Before you write a verdict, ask yourself:

> "If someone showed me this company name + domain (and any LinkedIn description on file) and asked 'what do they do', would I bet £100 on my answer being correct?"

- **Yes, easily** → High. Score immediately.
- **Maybe — I think they're in [industry] but I'm not sure of their exact product** → Medium. One WebFetch.
- **No idea — the name doesn't trigger anything and the domain isn't telling** → Low. WebFetch + WebSearch.

---

## Scoring Logic

For each company, produce two judgments:

### 1. ICP fit

Does the company match the user-supplied ICP positively?

- `yes` — clearly within the ICP (e.g. "B2B SaaS company" + this company is a B2B SaaS product)
- `no` — clearly outside (e.g. "B2B SaaS" + this is a healthcare practice)
- `unknown` — ambiguous (e.g. ICP is "any B2B services firm" and this is a media agency that sells some services and some product licensing)

If the ICP is broad ("any company above headcount X"), mark `yes` by default and only flag `no` for clear off-ICP categories the user named.

### 2. Avoid-list check

Is the company on the avoid-list?

- `yes` — hits one of the avoid categories (e.g. user said "avoid lead-gen agencies" and this company sells lead-gen services)
- `no` — clearly outside the avoid list
- `unknown` — ambiguous (rare; typically when the company has multiple product lines and one is on the avoid-list)

The combined verdict:

| ICP fit | Avoid hit | Score |
|---|---|---|
| yes | no | `5 - meets ICP, not on avoid list` |
| yes | yes | `1 - competitor: <category>` |
| no | * | `1 - off-ICP: <reason>` |
| unknown | no | `5 - probable ICP match (uncertain), not on avoid list` (kept, with the uncertainty in the reason) |
| unknown | yes | `1 - competitor: <category>` |
| unknown | unknown | `unknown - flag for manual review` |

When in doubt on `unknown - unknown`, keep the row **with the flag**. Never silently drop a row whose verdict you couldn't reach — the flag tells the user to triage manually.

---

## Worked Patterns

### Recognisable competitor brands — instant Low-cost call

- Smartlead, Apollo, Clay, Outreach.io, Instantly, Lemlist, Salesloft, Gong, Reply.io, Lavender, Smartwriter, Hyperise — outbound tooling
- Belkins, Cience, Operatix, MarketStar, Memory.com, Blueteam, Pearl Lemon, Salesforce — sales outsourcing / SDR-as-a-service / agency
- INFUSE, Anteriad, TechTarget, Demand AI, Madison Logic — B2B demand-gen / lead-gen agencies
- Showpad, Highspot, Seismic, Mindtickle — sales enablement platforms

If the company name is in this kind of list, it's a `1 - competitor` call without any fetch.

### Recognisable safe brands — instant pass

- Most NASDAQ-listed B2B SaaS that doesn't sell sales/GTM tooling (Zoom, Atlassian, Slack, ServiceNow, Workday, etc.) — pass
- Major industrial / financial brands (BNP Paribas, Brenntag, Logitech, Toyota, etc.) — pass unless the user specifically named them as off-ICP

### Vague names that need a fetch

- Two-word generic agency names ("Pixel Surge", "Stratnova", "TechTides", "Fibonacci Agency") — Medium confidence. WebFetch homepage. Look for clear self-description in the hero copy ("we help X do Y") to score in/out.
- Suffixed personal-name companies ("Smith & Associates", "Jones Consulting") — usually Low. WebFetch + WebSearch. Often resolves to a small consultancy that is Off-ICP for headcount reasons (already filtered earlier) or matches the avoid-list (consulting on sales/RevOps).

### Genuinely opaque

- Made-up-sounding names with no domain hits ("Taigle", "Nooro", "Vumotec") — Low. If WebFetch + WebSearch return nothing usable, **flag and move on** — don't push a guess through.

---

## Speed Targets

Following the bias-to-High rule, a single agent should clear:

- ~100 leads per minute when ≥80% are High-confidence calls
- ~30 leads per minute when ≥50% are Medium (one fetch each)
- Slower than that = the file is unusually opaque (raw LinkedIn scrape with no domain, generic personal-name companies) — flag this back to the user and ask if they want to enrich the file before qualifying

---

## When the Pipeline Catches It Already

The deterministic pipeline (`scripts/qualify_list.py`) handles the common avoid-list categories with regex matching against company name + description + specialities + domain. About 95% of avoid-list hits are caught at that step without any LLM judgment.

Only the residue — clean-keyword-scan rows that **could** still be competitors based on a non-obvious description (e.g. a small agency whose website pitch contains "we help SaaS companies grow revenue" and whose actual model turns out to be SDR-as-a-service) — needs a confidence-ladder LLM call.

For files >2k rows, batch the residue and process it in a second pass after the deterministic filter. For files <2k, just walk every row through the ladder inline if needed.

---

## Things to Never Do

- **Never** push a "looks fine" verdict on a Low-confidence company. Flag it and let the user decide.
- **Never** WebFetch every row "to be safe" — bias to High.
- **Never** guess on an unrecognisable name; mark `unknown - flag` and move on.
- **Never** rely solely on the company NAME for an avoid-list call when there's a description — the description is more reliable. (A company called "DemandGen Pro" might actually be a recruitment agency; a company called "Acme Software" might actually be a lead-gen tool.)
- **Never** forget: the goal is a clean shortlist for outbound, not perfect classification. If something is borderline, the cheaper outcome is to drop it (or flag it) than to ship outreach to a competitor.
