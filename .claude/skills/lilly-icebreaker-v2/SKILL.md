---
name: lilly-icebreaker-v2
description: "Streamlined icebreaker writer. State the strategy (which angles, what order) + a Smartlead campaign → it ALWAYS previews real example lines on a small CHEAP sample first (≤8 leads), shows the exact full-batch cost, and waits for your explicit go before running the full batch — every run, no exceptions (even when cached/free/tiny) — then reports and asks 'Upload now?'. Never runs or writes the full batch without a human sample sign-off. No pre-flight menu, minimal commentary, two mandatory single-y/n gates (sample sign-off, then upload). Same five-angle engine as lilly-icebreaker (Colleague → Hiring → Funding → You-joined → Tech → generic fallback that always fires), cache-first (Prospeo > AI Ark, free) before any paid call, Hiring sourced from a free TheirStack per-company job search. Use whenever the user wants to add icebreakers to a Smartlead campaign FAST with minimal input and no risk of a costly full-batch auto-run, fill {{Icebreaker}}, or says 'icebreaker v2'. Trigger phrases: 'add icebreakers to campaign X (fast)', 'fill {{Icebreaker}} quickly', 'lilly icebreaker v2', 'run the fast icebreaker', 'personalise campaign X, colleague-first / hiring-first', or as a quick per-campaign personalisation pass. Costs 0 Prospeo credits per cached company / 1 per cache miss; never leaves a lead with an empty {{Icebreaker}} (the generic fallback always fires last). For the detailed/configurable version use lilly-icebreaker (v1)."
---

# Lilly Icebreaker v2

## Purpose

Strategy + a Smartlead campaign → `{{Icebreaker}}` filled on every lead. **ALWAYS previews a small, cheap sample FIRST and waits for your explicit go before running the full batch — under every circumstance, no exceptions** (cached, free, tiny campaign, re-run: it still shows a sample and still waits). Then on "go" it processes the rest, reports, and waits again before uploading.

**Example flow:** "Add icebreakers to campaign 12345, hiring-first."
→ sample preview (per-signal example tables) + batch cost → **"Make changes, run only, or run + upload?"** → run + upload → full run + report → written (one less prompt because the CSM pre-authorised on the sample). "Run only" instead → report → `Upload? [Enter/n]`.

This is the fast sibling of `lilly-icebreaker` (v1). The generation engine (cache-first sourcing + the 6 angles) is identical; only the orchestration is leaner. Deliberately overrides the v1 pre-flight menu and the "always ask the waterfall order" rule (`feedback_always_confirm_inclusions_exclusions`, `feedback_lilly_icebreaker_waterfall_default`) — strategy is taken from the user's opening instruction, not interrogated. Two mandatory single-y/n human gates, NEVER skipped: **(a) the sample sign-off** before the full batch runs, **(b) the upload** before any live write. Use v1 when the user wants the full configurable pre-flight.

---

## 🛑 Absolute rule — sample + sign-off, always

**The skill must NEVER run the full batch, spend on the full batch, or write anything without first showing a sample and getting an explicit human "go". No exceptions — not when every domain is cached, not when it is free, not on a tiny campaign, not on a re-run, not when the strategy seems obvious.** The sample sign-off (§5b) is mandatory every single time. The write requires explicit human consent too — given either by choosing "run + upload" at §5b (sample already shown) or by clearing the upload gate at §6. The only thing "run + upload" collapses is the *second* prompt, never the sample-first sign-off. If you are ever unsure whether a gate applies: it applies. When in doubt, stop and show the sample.

## ⚠️ Minimal-commentary hard rule

Narration must be as terse as possible. No preamble, no recap of the plan, no per-step play-by-play, no restating defaults at length. Across a whole run, the ONLY things you output are:

1. **The sample-preview block:** consolidated order-to-confirm → **one table PER signal** (each `#### {Signal}` + same columns `# | Lead | Company | Angle | Icebreaker | Source`, ≥3 examples each, real-first then marked placeholders; Company + every person hyperlinked; Source = clickable evidence link) → one-line batch cost. Always tables, never bullets/prose; never one merged table.
2. **The sample sign-off gate (ALWAYS):** `Make changes, run only, or run + upload?` (three choices) — shown every run, even when free.
3. **The report:** one line (angle mix %, fill, credits).
4. At most one grounded angle suggestion (skip if none).
5. **The upload gate:** `Upload {N}/{N}? [Enter = yes, n = no]` — UNLESS the CSM chose "run + upload" at the sign-off gate, in which case the write proceeds with no second prompt.
6. A one-line upload confirmation.

If you find yourself explaining what you are about to do, stop and just do it. Silence on a clean step is correct. The understood-strategy line (in 1) is the only "I heard you" the CSM needs — no separate confirmation of his instruction.

---

## The flow

### 1 — Strategy upfront (no menu)

Read the angles + order from the user's request (e.g. "hiring-first", "colleague then funding only", "skip you-joined"). Apply it as given. Do NOT surface a pre-flight block or ask the user to confirm filters.

**Memory before defaults — reuse the CSM's last setup for this campaign.** Before falling back to generic defaults, check the run log `~/.navreo-cache/lilly-icebreaker-v2-runs.log` (pipe-delimited: `{date} | campaign:{id} | client:{slug} | strategy:{order+flags} | tech:{list-or-none}`). If the user gave NO strategy this turn:
- A prior entry for this **campaign** exists → reuse its strategy + tech list and echo it WITH ITS AGE so staleness is visible: `Using your last setup for this campaign (18 days ago): hiring-first, tech off.` (one line, still overridable at the gate). Campaign-level memory ALWAYS takes precedence over client-level.
- No campaign entry but a prior entry for the same **client** exists → reuse that client's last strategy/tech list and echo `Using your usual setup for {client} (last used 9 days ago): …`.
- Nothing logged → apply silent defaults below.
- **Staleness caution:** if the reused tech list no longer matches any of the campaign's current tech variables, or the last run is >30 days old, add a 4-word nudge (`— mix may have shifted`) so the CSM doesn't autopilot past a stale setup.
Append a fresh log line after every completed run (§5c). The user's explicit strategy this turn always wins over the log.

**Bundle anything genuinely missing into ONE question.** If the campaign is ambiguous (no ID and the name matches >1), or the user invoked the Tech angle without naming any techs, ask a single combined question (`Which campaign — A or B? And which tech names should the Tech angle match?`) rather than a back-and-forth. Remember the answered tech list per client in the log so it is pre-filled next time. Default Tech OFF if they invoked it but skip the tech list.

**Silent defaults** when the user didn't specify and nothing is logged (state in ONE short line, e.g. `Defaults: colleague→hiring→funding→you-joined→fallback, tech off.`):

- Order: **Colleague → Hiring → Funding → You-joined → Fallback** (generic fallback always last).
- Parallel-stature titles (angle 1): Director, VP, Vice President, Head, C-Suite, Founder, Owner (prefer prospect's department; fall to Sales / BD / Partnerships / RevOps / Marketing if <2 same-dept).
- Recency: role-change ≤ 3 months; funding ≤ 6 months; hiring lookback 60 days.
- Funding-stage exclusions: Acquired, Bankruptcy, M&A, Liquidation, Secondary market.
- **Tech (angle 5): OFF** unless the user names a tech-relevance list (then it's on for those techs).
- `/enrich-person`: OFF. Cache staleness: 30 days.
- Smartlead key: primary; on 404/empty for a Navreo-titled campaign, retry with the Navreo secondary `1417c9a6-...zto0vlj` (`feedback_lilly_optimiser_scope`).

### 2 — Silent email-body check (blocker-only)

Fetch the sequence and locate `{{Icebreaker}}`:

```bash
curl -s "https://server.smartlead.ai/api/v1/campaigns/{ID}/sequences?api_key={KEY}"
```

For every step containing `{{Icebreaker}}`, read the carrier sentence + the sentence after it. Check internally that the locked templates (all end on a period, start a fresh sentence) slot cleanly. **Proceed silently if they do — say nothing.**

STOP only on a true structural break: the body expects a comma / lowercase continuation right after `{{Icebreaker}}` (e.g. `{{Icebreaker}} and noticed…`), so period-ending templates would produce broken sentences. In that one case, flag it as a blocker and recommend routing to `lilly-bot` to fix the body before running. Do not auto-fix copy.

### 3 — Fetch leads, pick a sample (read-only, no spend yet)

**Fetch + dedup leads.** `GET /api/v1/campaigns/{ID}/leads?api_key={KEY}&offset=0&limit=100`, paginate until empty. Per-lead fields: `email`, `first_name`, `last_name`, `company_name`, `website` (canonical domain), `job_title`, optional `linkedin_url`. Group by canonical domain — one signal pull per unique domain. This step spends nothing.

**Only-fill-empty by default (don't clobber, don't re-pay).** Check each lead's existing `custom_fields.Icebreaker`. By default, **target only leads whose `{{Icebreaker}}` is empty** — leave already-filled ones untouched (they may be hand-edited). Drop any domain where ALL leads are already filled from the work set entirely (no signal pull, no spend). Note it in the cost line: `(N leads already have an icebreaker — left as-is)`. Regenerate filled leads only if the user explicitly says "redo / overwrite / regenerate all".

**Pick the sample (bounded + cheap).** Do NOT process every lead yet. Aim to show the CSM **≥3 real examples of each signal in the chosen order**, but stay cheap: select up to ~8 leads spread across companies, preferring cached domains (free) so more angles can be shown for less, then a few uncached ones for realism. **Hard cap: at most 5 fresh Prospeo `/search-person` calls for the whole sample** (~$0.025). Once the cap is hit, stop fetching — for any signal that didn't reach 3 real examples (thin data, or Prospeo offline), top up to 3 with clearly-marked **placeholder** rows (§5a) rather than spending more. The sample is the only thing generated before the CSM has seen output; bounded by design.

The generation procedure below (§4 engine) runs first on this sample, then — only after the CSM's "go" — on the remaining leads (§5).

### 4 — The generation engine (per lead — runs on the sample first, then the full batch)

**Cache-first sourcing (per unique domain).** Read order, stop at first fresh hit:

1. Prospeo company cache `~/.navreo-cache/prospeo/companies/{domain}.json` (≤ staleness) → **0 credits**.
2. AI Ark cache `~/.navreo-cache/ai_ark/companies/{domain}.json` + `~/.navreo-cache/ai_ark/people/{slug}.json` → **0 credits** (angles 1, 3, 4, 5; schema map below). AI Ark has no hiring data.
3. Miss/stale → fresh Prospeo `/search-person` (1 credit/domain), then write back to cache (`source_skill: "lilly-icebreaker-v2"`, same envelope as `lilly-tam`).

Slice, don't slurp — extract only the relevant fields with `jq`, never `cat` whole cache files into context:

```bash
CACHE_FILE=~/.navreo-cache/prospeo/companies/${DOMAIN}.json
STALENESS_DAYS=30
if [ -f "$CACHE_FILE" ]; then
  AGE_DAYS=$(( ( $(date +%s) - $(date -r "$CACHE_FILE" +%s) ) / 86400 ))
  if [ "$AGE_DAYS" -le "$STALENESS_DAYS" ]; then
    jq '{source:"prospeo_cache", age_days:'"$AGE_DAYS"',
      funding:(.data.funding // {} | {latest_funding_date, latest_funding_stage}),
      job_postings:(.data.job_postings // {} | {active_count, active_titles:(.active_titles // [])[0:30]}),
      technology:(.data.technology // {} | {technology_names:(.technology_names // [])[0:30]}),
      employee_count:.data.employee_count, employee_range:.data.employee_range}' "$CACHE_FILE"
    exit 0   # CACHE_HIT
  fi
fi
# else fall through to AI Ark cache, then fresh /search-person
```

Per-prospect tenure (angle 4, when lead has `linkedin_url`):

```bash
LI_SLUG=$(echo "$lead_linkedin_url" | sed -E 's|.*/in/([^/?]+).*|\1|')
PERSON_FILE=~/.navreo-cache/prospeo/people/${LI_SLUG}.json
[ -f "$PERSON_FILE" ] && jq '.data | {current_job_title, last_job_change_detected_at,
  current_job:(.job_history // [] | map(select(.current==true))[0] | {title, start_year, start_month})}' "$PERSON_FILE"
```

Fresh `/search-person` (cache miss only):

```bash
curl -s -X POST "https://api.prospeo.io/search-person" \
  -H "X-KEY: $PROSPEO_API_KEY" -H "Content-Type: application/json" \
  -d '{"page":1,"filters":{"company":{"websites":{"include":["acme.com"]}},
       "person_seniority":{"include":["Founder/Owner","C-Suite","Vice President","Head","Director","Manager"]}}}'
```

Returns up to 25 senior people + the company object (funding, job_postings, technology, employee_count, employee_range). Angles 1, 3, 4, 5 derive from this one response.

**Distinguish two miss cases — they are NOT the same:**
- **Empty result** (`results: []` but the call succeeded) and no cache → real coverage gap; every lead at this domain → angle 6 (fallback) directly. Normal.
- **API failure** (`{"error":true,"error_code":"INSUFFICIENT_CREDITS"}`, 401/403 bad key, or rate-limit still failing after one retry) → do NOT silently treat as fallback. Mark the domain `api_failed` and STOP firing further fresh calls. Surface it at the sample stage (§5a) before generating an all-fallback batch — see the API-failure guard in §5. A campaign-wide silent fall to fallback because credits ran out is the worst failure mode: it looks like a finished run but every line is generic.

Log per lead: `email, first_name, company_name, domain, angle_fired, signal_data, source_url, icebreaker, source_used` (`source_url` = the evidence link shown in the preview's Source column — job posting / Crunchbase / peer LinkedIn / prospect LinkedIn / empty for fallback; `source_used` = `prospeo_cache | ai_ark_cache | prospeo_fresh`) to `~/Library/.../Navreo/icebreaker_runs/{campaign}_{date}.csv`.

**Per-lead waterfall — walk the angles in the chosen order, first to fire wins.**

#### Angle 1 — Colleague mention
Filter `/search-person` results to seniority in `{Director, Vice President, Head, C-Suite, Founder/Owner, Partner}`, excluding the prospect (by `linkedin_url` or first+last name). **Also exclude peers whose lowercase first_name matches a word in the lowercase company_name** (Prospeo dirty-row guard). Rank by parallel-stature relevance to the prospect's `job_title`: (1) same dept + senior/equal, (2) adjacent revenue function (Sales/BD/Partnerships/RevOps/Marketing), (3) other senior peers. Take top 1–3.

Titles conditional on size — include parenthetical titles only if `employee_count >= 50` OR `employee_range` ∈ `{51-200, 201-500, 501-1000, 1001-5000, 5001-10000, 10000+}`; else names only. Abbreviate titles cleanly (`Business Development`→`BD`, `Revenue Operations`→`RevOps`, `Strategic Accounts`→`Strategic Accts`), truncate at word boundaries.

```
Apologies if this isn't relevant. I wasn't sure if you, Sarah (VP Sales) or Marcus (Head of BD) was the right person at {{company_name}}.
```
(size < 50 / unknown → names only: `…if you, Sarah or Marcus was the right person at {{company_name}}.`)

0 senior peers → skip to next angle.

#### Angle 2 — Hiring (free TheirStack, per-domain, lazy + cached 14d)
```bash
set -a; source ~/.navreo-keys.env 2>/dev/null; set +a
BODY=$(jq -nc --arg d "$DOMAIN" '{posted_at_max_age_days:60, company_domain_or:[$d],
  job_title_or:["Sales Development Representative","SDR","Business Development Representative","BDR","Account Executive","Sales Manager","Sales Director","Head of Sales","VP Sales","Sales Representative","Inside Sales","Account Manager"],
  blur_company_data:true, limit:10}')
curl -s -X POST "https://api.theirstack.com/v1/jobs/search" \
  -H "Authorization: Bearer $THEIRSTACK_API_KEY" -H "Content-Type: application/json" \
  -d "$BODY" | jq -r '.data[]? | "\(.job_title)\t\(.url // .source_url // .final_url // "")"'
```
`company_domain_or` + `blur_company_data:true` = 0 credits, name returned unblurred. Each row carries `.job_title` AND the posting URL (`.url`) — **keep the URL for the chosen title; it becomes the row's Source link** `[Job posting](url)`. From the titles, pick the representative one deterministically: prefer IC/junior (SDR, BDR, AE, Sales Rep, Inside Sales, Sales Associate) over manager+ (Sales Manager/Director, Head of Sales, VP Sales); if only manager+ exist, take the first. DACH lists: also match `vertrieb`, `vertriebsinnendienst`, `vertriebsmitarbeiter`, `verkauf`, `b2b sales`.

Fallback (0 credits): substring-match the sales-title set against Prospeo `company.job_postings.active_titles[]`, pick the FIRST match. Parent-domain caveat: if `company_name` clearly differs from the domain's brand (e.g. subsidiary → parent), treat a hit as low-confidence and prefer to fall through.

**Clean the chosen title before rendering** (feed titles are raw + lowercase — validated 2026-06-27 against cached `active_titles`). Strip parenthetical/region/level qualifiers and sub-team suffixes, then render in natural Title Case so it reads like a human said it:
- `account executive (midwest)` → `Account Executive`
- `solution engineer - grc postsales` → leave — not a sales title, don't match it
- `senior sales development representative` → `Sales Development Representative` (or `SDR`)
- `director, enterprise sales` → `Sales Director` (base role)
- `strategic account executive` → `Strategic Account Executive` (keep a clean leading qualifier only if it reads naturally)
Never emit the raw lowercase feed string or a `(...)`/` - subteam` tail into the line.

`a`/`an`: `an` if the title's first sound is a vowel (SDR, AE, Account Executive), else `a` (BDR, Sales Manager).
```
I noticed {{company_name}} is hiring an SDR, and thought I would reach out.
```
No posting + empty fallback → skip.

#### Angle 3 — Funding
Read `company.funding.latest_funding_date` + `latest_funding_stage`. Fires if date ≤ 6 months AND stage NOT in `{Acquired, Bankruptcy, M&A, Liquidation, Secondary market}`. Phrase: `Series A/B/C…`→`Series A round`; `Seed`→`seed round`; `Pre-Seed`→`pre-seed round`; `Grant`→`grant round`; debt/convertible/other/unknown→`round of funding`.
```
I saw {{company_name}} closed a Series B round recently, and thought I would reach out.
```
Else skip.

#### Angle 4 — You joined
Find the prospect in the `/search-person` response (by `linkedin_url`, else first+last name). Read `job_history[]`, find `current: true`, compute `months_at_company = (today_year - start_year)*12 + (today_month - start_month)`. Fires if `≤ 3`. (Prefer `job_history` over `last_job_change_detected_at`.)
```
I saw you recently joined {{company_name}} as {{title}}, and thought I would reach out.
```
Not found / tenure > 3 / no current entry → skip. (CSV-sourced tenure lags; fresh `/search-person` gives real dates.)

#### Angle 5 — Tech (opt-in only)
Only if the user supplied a tech-relevance list. Tech names must be CANONICAL per the TheirStack technology catalog (32,572 techs; free, no credits): `GET https://api.theirstack.com/v0/catalog/keywords?keyword_type=technology&limit=100000`, cached at `~/.navreo-cache/theirstack/technologies.json` (each entry: name/slug/category/description + companies/jobs counts — also sizes a tech audience for free). Read `company.technology.technology_names[]`, case-insensitive substring match against the list, pick the FIRST match. **The tech-relevance list is `tech → why` pairs, not bare names** — because the line must ALWAYS say WHY the tool is relevant, never just name-drop it (Bjion rule 2026-08-03). Render the tool + its inference:
```
Saw you were using Instantly, assumed you might be doing outreach.
```
Pattern: `Saw {{company_name}} is using {{tech}}, {{why}}.` (the `{{why}}` is the matched tech's relevance from the list — e.g. Clay → "figured you're building lists", Salesforce → "assumed you're running a sales team"). If a matched tech has no `why` supplied, do NOT fire a bare name-drop — skip to the next angle.
No match / not opted in → skip.

#### Angle 6 — Generic fallback (ALWAYS fires)
Rotate deterministically across the 8 approved variants: `variant_index = int(md5(email).hexdigest(), 16) % 8`. Same lead → same variant on re-run.

1. `Apologies if this isn't relevant, I wasn't sure who the best person at {{company_name}} was to speak about this.`
2. `Apologies if this should sit with someone else, I wasn't sure who at {{company_name}} owned this.`
3. `Apologies if you're not the right person, I wasn't sure who to reach at {{company_name}} for this.`
4. `Apologies for the cold reach, I wasn't sure who the right contact at {{company_name}} was for this.`
5. `Apologies if I've got the wrong person, I wasn't sure who at {{company_name}} was the best to speak with about this.`
6. `Apologies if this isn't your area, I wasn't sure who the right person at {{company_name}} was.`
7. `Apologies if I'm off-mark, I wasn't sure who handles this kind of thing at {{company_name}}.`
8. `Apologies for reaching out cold, I wasn't sure who the right person at {{company_name}} was to speak with.`

`{{company_name}}` baked in literal at generation. Strip company-name tails at the first ` — ` or ` | ` before rendering into any template.

### 5 — Sample preview → spend gate → full run → report

**5a. Sample preview — consolidated order + a table (output, nothing more):**

Three parts, in this order: **(1) a consolidated order block to confirm**, **(2) the sample table** (≥3 examples per signal in use), **(3) the one-line batch cost**.

**(1) Consolidated order — restate it back AS A TABLE so the CSM double-checks before anything runs:**

| Order | Signal | Fires when |
|---|---|---|
| 1 | Hiring | live sales job posting |
| 2 | Colleague | senior peer at the company |
| 3 | Funding | funding round in last 6 months |
| 4 | You-joined | prospect joined in last 3 months |
| 5 | Fallback | generic (always last) |
| off | Tech | not in use this run |

This is the waterfall the run will use, top to bottom. The CSM confirms or reorders here (via the gate). It is the explicit "is this the order you want?" check.

**(2) Sample tables — ONE table PER signal, same columns each; ≥3 examples per signal in use:**

Render a **separate table for each signal** in the chosen order, each under its own heading that **starts with "Example"** — `#### Example: {Signal}` — so it is unmistakable these are sample rows, not the finished batch. Each table uses the **same columns**: `# | Lead | Company | Angle | Icebreaker | Source`. Do NOT merge signals into one combined table. Per signal, show **at least 3 example rows so the CSM sees that signal in action**. Prefer REAL examples generated from the bounded sample / cache; if fewer than 3 real fire (thin data, or Prospeo offline), top up that signal's table with clearly-marked **placeholder** rows so it still shows 3. Placeholders exist only to illustrate the copy shape; never present a placeholder as real.

#### Example: Hiring
| # | Lead | Company | Angle | Icebreaker | Source |
|---|---|---|---|---|---|
| 1 | [Russell](https://linkedin.com/in/…) | [MCSG Technologies](https://mcsgtech.com) | Hiring | I noticed MCSG Technologies is hiring a Business Development Representative, and thought I would reach out. | [Job posting](https://…) |
| 2 | [Sheridan](https://linkedin.com/in/…) | [Evry Health](https://evryhealth.com) | Hiring | I noticed Evry Health is hiring an SDR, and thought I would reach out. | [Job posting](https://…) |
| 3 | [Jack](https://linkedin.com/in/…) | [Instant](https://instant.co) | Hiring | I noticed Instant is hiring an Account Executive, and thought I would reach out. | [Job posting](https://…) |

#### Example: Colleague
| # | Lead | Company | Angle | Icebreaker | Source |
|---|---|---|---|---|---|
| 1 | [Christie](https://linkedin.com/in/…) | [CWS ClearWater Solutions](https://clearwatersolutions.com) | Colleague | Apologies if this isn't relevant. I wasn't sure if you or [Mark](https://linkedin.com/in/…) (Head of Sales) was the right person at CWS ClearWater Solutions. | [Mark · LinkedIn](https://…) |
| 2 | _placeholder_ | _Example SaaS Co_ | Colleague | _Apologies if this isn't relevant. I wasn't sure if you or Dana (VP Sales) was the right person at Example SaaS Co._ | _illustrative — no live signal_ |
| 3 | _placeholder_ | _Example SaaS Co_ | Colleague | _Apologies if this isn't relevant. I wasn't sure if you, Priya or Tom was the right person at Example SaaS Co._ | _illustrative — no live signal_ |

#### Example: Funding
| # | Lead | Company | Angle | Icebreaker | Source |
|---|---|---|---|---|---|
| 1 | [Steven](https://linkedin.com/in/…) | [BasePower](https://basepower.com) | Funding | I saw BasePower closed a Series B round recently, and thought I would reach out. | [Crunchbase](https://…) |
| 2 | _placeholder_ | _Example SaaS Co_ | Funding | _I saw Example SaaS Co closed a Series A round recently, and thought I would reach out._ | _illustrative — no live signal_ |
| 3 | _placeholder_ | _Example SaaS Co_ | Funding | _I saw Example SaaS Co closed a seed round recently, and thought I would reach out._ | _illustrative — no live signal_ |

*(…one such table per signal in the order, then Fallback last.)*

```
Full batch: 30 leads · 24 unique domains · 6 cached (free) · 18 fresh Prospeo calls ≈ $0.09
```

**Hard formatting rules (apply to every per-signal table):**
- **One table per signal**, same six columns, `#### Example: {Signal}` heading above each (the word "Example" makes clear these are samples). Never one merged table.
- **Company is ALWAYS hyperlinked** to its website (`[Company](https://domain)`) on real rows.
- **Every individual's name is ALWAYS hyperlinked to their LinkedIn** — the `Lead` column links the prospect's `linkedin_profile`, AND any colleague named inside a Colleague icebreaker links to that peer's `linkedin_url` inline.
- **Source column = a clickable link to the evidence** so the signal is verifiable in one click (see per-angle map below).
- **Real first, placeholder to fill.** Mark placeholder rows in _italics_ with `_placeholder_` in the Lead column and `_illustrative — no live signal_` in Source. Never hyperlink or fabricate a URL on a placeholder.
- The `Angle` column stays (same columns everywhere) even though it repeats the table heading.

**Source link per angle** (capture the URL when the angle fires; render as a markdown link, or `—`/plain text if none):

| Angle | Source link | Where it comes from |
|---|---|---|
| Hiring | `[Job posting](url)` | TheirStack `.data[].url` (the live posting). Capture it alongside `.job_title`. |
| Funding | `[Crunchbase](url)` or `[Funding news](url)` | Prospeo `company.crunchbase_url`, or the funding announcement URL if the source carries one. |
| Colleague | `[{Peer} · LinkedIn](url)` | the named peer's `linkedin_url` from the `/search-person` results — links straight to the person mentioned. |
| You joined | `[{Lead} · LinkedIn](url)` | the prospect's own `linkedin_url` (the role-change evidence). |
| Tech | `[{Tech} detected](url)` or the tech name | the company's site/tech page if available; else just the tech name as plain text (no fabricated link). |
| Fallback | `—` | no signal, no source. |

If a fired angle genuinely has no URL in the data, put the plain evidence text (e.g. the job title, the funding stage+date) rather than inventing a link. **Never fabricate a URL** — placeholders and URL-less signals show plain text, real signals show real links.

**5a-guard. API-failure / all-fallback check (before any gate).** If the sample hit an `api_failed` domain (Prospeo `INSUFFICIENT_CREDITS`, bad key, persistent rate-limit) OR the sample came back **all generic-fallback** (no real signal fired on any sampled lead), do NOT proceed as if normal. Surface it plainly and stop:
```
Prospeo returned INSUFFICIENT_CREDITS — uncached domains can't be personalised and would all fall to the generic fallback.
3 of 30 domains are cached. Options:
  (a) personalise the 3 cached, generic fallback for the other 27
  (b) stop — top up Prospeo credits, then re-run
```
Never spend the upload gate's "y" on a silently-degraded all-fallback batch. (Found in real testing 2026-06-27: Prospeo was out of credits; without this guard the skill would have produced 30 generic lines and presented them as a finished run.)

**5b. Sample sign-off gate (MANDATORY EVERY RUN — never skipped, see the Absolute rule):**

After the sample preview, STOP and ask — every single time, regardless of cost — offering **three choices**:
  `Make changes, run only, or run + upload?`
  *(append the cost as info: `~{M} fresh calls, ~${X}` — or `all cached, free` — but the gate fires either way.)*
  - **Make changes** (reorder the signals, swap angles in/out, adjust a threshold, turn Tech on/off, refine wording) → apply the change, regenerate the **sample only**, re-show 5a. Never run the full batch to try a change.
  - **Run only** → §5c → report → then the upload gate (§6) still asks before writing.
  - **Run + upload** → §5c → report → **write immediately, no second prompt** (the CSM has seen the sample and explicitly pre-authorised the write in the same breath). This is the only way to skip the upload gate, and only the CSM can choose it — never assume it.
  - (The CSM can also just say stop → end, nothing generated or written.)

This satisfies the Absolute rule: the sample is ALWAYS shown and an explicit human "go" is ALWAYS required before any spend or write. "Run + upload" does NOT bypass that — it bundles the sample sign-off and the upload consent into one deliberate choice. What it must never do is run or write without the human picking one of these on a freshly-shown sample.

Do NOT skip this gate when the batch is free/cached, near-free, or tiny. Even on a campaign so small the sample already covers every lead, still pause here for the human choice. Cost is never the reason for the gate — human sign-off is.

**5c. Full run (once, after go):** run the §4 engine on the remaining leads. Log per lead to `~/Library/.../Navreo/icebreaker_runs/{campaign}_{date}.csv`. Then append one line to `~/.navreo-cache/lilly-icebreaker-v2-runs.log` recording this run's setup for next time (§1 memory): `{date} | campaign:{id} | client:{slug} | strategy:{order+flags} | tech:{list-or-none}` (cap the log at 200 lines, trim oldest).

**5d. Report — one line:** `30 leads · hiring 30% · colleague 27% · funding 13% · fallback 30% · fill 100% · 18 credits (6 cache hits).`

**5e. Grounded suggestion — at most one line, only if the data in hand supports it.** E.g. many unused funding hits under the chosen order → `Lots of recent-funding hits here — want funding earlier next time?`; high fallback % from thin Prospeo coverage → note `lilly-icebreaker-news-search` as an alternative. **No real signal → say nothing.**

### 6 — Upload gate + push

**Skip only if the CSM chose "Run + upload" at §5b** (write proceeds straight away). Otherwise ("Run only"), ask — as a single-keystroke prompt, no timer/auto-proceed:
`Upload {N}/{N} to Smartlead campaign {ID}? [Enter = yes, n = no]`
- **n** → stop. Nothing written. **Surface the run-CSV path** so the CSM can eyeball every line before deciding: `Not uploaded. Full run saved to ~/Library/.../Navreo/icebreaker_runs/{campaign}_{date}.csv — open it, then say "upload" to push.`
- **Enter / y** → push (batches of 100):

```bash
curl -s -X POST "https://server.smartlead.ai/api/v1/campaigns/{ID}/leads?api_key={KEY}" \
  -H "Content-Type: application/json" \
  -d '{"lead_list":[{"email":"bob@acme.com","custom_fields":{"Icebreaker":"I saw you recently joined Acme as Sales Director, and thought I would reach out."}}]}'
```
Upserts on email; safe to re-run a failed batch. Then run `lilly-qa/scripts/check_lead_variable_fill.py` — must be 100% fill on `{{Icebreaker}}` (the fallback guarantees it). Confirm in one line: `Uploaded · 30/30 filled.`

---

## AI Ark schema map (reading `~/.navreo-cache/ai_ark/`)

| Angle | Prospeo field | AI Ark equivalent |
|---|---|---|
| 4 — tenure | `person.job_history[current=true].start_year/month` | `position_groups[0].date.start` (ISO; `date.end==null` = current). Name `profile.full_name`, title `profile.title`. |
| 2 — hiring | `company.job_postings.active_titles[]` | **NOT AVAILABLE** — fall through to TheirStack. |
| 1 — colleague | `/search-person` filtered by seniority | `/v1/people` at same `account.domain`; slug at `identifier`. |
| 3 — funding | `company.funding.latest_funding_date` + `latest_funding_stage` | `financial.funding.date` + `financial.funding.rounds[0].type` (reverse-chron). |
| 5 — tech | `company.technology.technology_names[]` | `technologies[]` (`name` + optional `category`). |
| size split | `company.employee_count` | `summary.staff.total` (or `summary.staff.range`). |

AI Ark funding normalisation: `SERIES_A`→`Series A`, `SEED_ROUND`→`seed`, `SECONDARY_MARKET`→skip, `GRANT`→`grant`, `VENTURE_ROUND`→`round of funding`. Same exclusion list applies.

---

## Hard Rules

1. **Sample + sign-off ALWAYS (the absolute rule).** Never run the full batch, spend on it, or write without first showing a sample and getting an explicit human "go" — no exceptions (cached, free, tiny, re-run). The sample sign-off (§5b) fires every single run; the write needs explicit consent too — "run + upload" at §5b or Enter/yes at §6. No pre-flight menu otherwise: strategy comes from the user's request (or the run-log memory for a repeat campaign/client), defaults fill the rest silently, the understood-strategy line is the only echo-back. (Deliberate override of `feedback_always_confirm_inclusions_exclusions` + `feedback_lilly_icebreaker_waterfall_default` for the *menu*, NOT for the sample gate — that is hard-required.)
2. **Minimal commentary** (see the rule near the top). Terse status only.
3. **NEVER auto-run the full batch.** Generate the bounded sample first (≤8 leads, ≤5 fresh Prospeo calls); show real copy + the exact batch cost; only process the full batch after the CSM's "go" at §5b. A thin sample must never silently become a 30- or 1000-lead run — paid OR free.
4. **One signal pull per unique domain; one full pass on go.** Never re-fire `/search-person` to "double-check" a cache hit; never regenerate the full batch to try a different strategy — regenerate the SAMPLE only.
5. **Waterfall is sequential** — first angle to qualify wins; never pick the "strongest" across signals.
6. **`{{Icebreaker}}` is never empty** — angle 6 always fires last.
7. **Write only after an explicit human choice** — either "run + upload" at §5b or Enter/yes at the §6 upload gate. Never write on inference or a timer. On "n"/no, nothing is pushed and the run-CSV path is surfaced for review.
8. **Post-push QA must hit 100% fill** (`lilly-qa/scripts/check_lead_variable_fill.py`).
9. **Never invent a person or a fact.** Only mention peers/hires/funding/tech actually present in the data.
10. **No em-dashes** (`feedback_no_em_dashes`); sentence-cased; strip `company_name` tails at ` — ` / ` | `.
11. **Body check is blocker-only** — speak only on a true structural break; otherwise proceed silently.
12. **Cache precedence:** Prospeo cache > AI Ark cache > fresh Prospeo for angles 1/3/4/5; Angle 2 always TheirStack (free), Prospeo `active_titles` fallback. Write cache after every fresh fetch.
13. **TheirStack:** always `company_domain_or:[domain]` + `blur_company_data:true` (0 credits); fire lazily; cache per domain 14d.
14. **API failure ≠ fallback.** If Prospeo returns `INSUFFICIENT_CREDITS` / bad-key / persistent rate-limit on uncached domains, or the whole sample comes back all-fallback, STOP and surface it (§5a-guard). Never let a credits-out run silently become a 30/1000-line generic-fallback batch that looks finished.
15. **Confirm the order, one table per signal, show 3 per signal, hyperlink everything.** The sample preview always (a) restates the angle order for confirmation, (b) renders a SEPARATE table per in-use signal (same columns) with ≥3 examples each — real first, clearly-marked italic placeholders only to fill the gap, (c) hyperlinks the Company to its site and every individual (lead + any named peer) to their LinkedIn, and (d) links the Source to the evidence. Never merge signals into one table. Placeholders are never hyperlinked and never presented as real. Never fabricate a URL.
16. **Reuse last setup, bundle missing info, offer run + upload.** When no strategy is given, reuse this campaign's (then this client's) last logged setup before generic defaults, and echo it in one line. Ask for any genuinely-missing info (ambiguous campaign, tech-angle-without-list) as ONE bundled question, and remember the tech list per client. Offer "run + upload" at the sign-off gate so a confident CSM clears both consents at once — but only the CSM may pick it; never assume it. Append a run-log line after each completed run.

---

## Quick reference

| Need | Endpoint / Path | Pattern |
|---|---|---|
| Read company cache (Prospeo) | `~/.navreo-cache/prospeo/companies/{domain}.json` | `jq '{funding, job_postings, technology, employee_count, employee_range}'` |
| Read company cache (AI Ark) | `~/.navreo-cache/ai_ark/companies/{domain}.json` | schema map above |
| Read person cache (tenure) | `~/.navreo-cache/prospeo/people/{slug}.json` | `jq '.data.job_history[] \| select(.current==true)'` |
| Senior peers + company data (fresh) | `POST api.prospeo.io/search-person` | seniority-filtered, company website include |
| Hiring (angle 2, free) | `POST api.theirstack.com/v1/jobs/search` | `company_domain_or` + `blur_company_data:true` → `.data[].job_title` |
| Sequence (body check) | `GET server.smartlead.ai/api/v1/campaigns/{ID}/sequences?api_key={KEY}` | locate `{{Icebreaker}}` carrier sentence |
| Get leads | `GET server.smartlead.ai/api/v1/campaigns/{ID}/leads?api_key={KEY}&offset=0&limit=100` | paginate |
| Push `{{Icebreaker}}` | `POST server.smartlead.ai/api/v1/campaigns/{ID}/leads?api_key={KEY}` | `{"lead_list":[{"email","custom_fields":{"Icebreaker"}}]}` |

Keys in `~/.navreo-keys.env` (`PROSPEO_API_KEY`, `THEIRSTACK_API_KEY`, `SMARTLEAD_API_KEY`).

See also: `lilly-icebreaker/SKILL.md` (v1 — full configurable pre-flight, same engine, deeper rationale), `lilly-icebreaker-news-search/SKILL.md` (news-anchored alternative when fallback % is high), `lilly-tam/SKILL.md` (cache-write authority), `lilly-personalisation/SKILL.md` (Smartlead push + QA check).
