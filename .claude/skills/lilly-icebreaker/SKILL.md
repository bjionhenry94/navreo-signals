---
name: lilly-icebreaker
description: "Generate per-lead cold-email icebreaker lines for a Smartlead campaign by reading whatever Prospeo / AI Ark signals are available — recent role change, active hiring, parallel-stature colleagues, recent funding, tech stack — and walking a five-angle waterfall with a generic fallback that always fires. The Hiring angle is sourced from a free TheirStack per-company job search (Prospeo active_titles as fallback). Cache-first (Prospeo > AI Ark, free) before any fresh API call. Use this skill whenever the user wants to add icebreakers to a Smartlead campaign, fill {{Icebreaker}}, personalise a campaign with whatever data is available, or mentions an opener that references a colleague / hire / role change / funding / tech stack. Trigger phrases: 'add icebreakers to campaign X', 'fill {{Icebreaker}}', 'personalise this campaign', 'mention a colleague', 'icebreaker mention a colleague', 'add a recent-role-change icebreaker', 'add a hiring-signal icebreaker', 'lilly icebreaker', or as a per-campaign personalisation pass. Costs 0 Prospeo credits per cached company / 1 credit per cache miss; never leaves a lead with an empty {{Icebreaker}} (the generic fallback always fires last)."
---

# Lilly Icebreaker

## Purpose

Take a Smartlead campaign (or a CSV of leads with first_name + title + company_name + domain), generate a single-line `{{Icebreaker}}` per lead using whatever Prospeo / AI Ark data is already cached, push back into the campaign.

The skill walks a five-angle waterfall in priority order. Each angle checks one Prospeo signal; the first that fires wins. A generic fallback line always fires when none of the five qualify, so `{{Icebreaker}}` is never empty.

Architecture: cache-first reads from `~/.navreo-cache/` (Prospeo + AI Ark trees, both populated by upstream skills like `lilly-tam`, `lilly-tam`, `lilly-tam`). Only on cache miss/stale do we fire a fresh Prospeo `/search-person` (1 credit per unique company). Four of the five signals (colleague, funding, you-joined, tech) derive from that single Prospeo call (or the cache equivalent); the **Hiring** signal is sourced separately from a free TheirStack per-company job search (see Angle 2), with Prospeo's `job_postings.active_titles[]` kept as a zero-cost fallback.

A news-anchored complementary skill (`lilly-icebreaker-news-search`, Serper-driven) exists for time-anchored openers (funding announcements / hires / launches / awards). It's not chained from this skill currently — run it directly when news angle is wanted.

---

## When to Use

Trigger when the user wants:
- Per-lead icebreaker openers for a Smartlead campaign before launch.
- A bulk personalisation pass on already-imported leads (fill missing `{{Icebreaker}}`).
- A specifically Prospeo-derived alternative to news-anchored openers.
- A "mention a colleague" cover line at scale.

Trigger phrases:
- "Add icebreakers from Prospeo for campaign X"
- "Fill `{{Icebreaker}}` via Prospeo signals"
- "Mention-a-colleague icebreaker"
- "Generate openers using Prospeo"

Do NOT use when:
- The campaign client lacks Prospeo coverage (most common at small EU firms in CZ/SK/RO/GR).
- Brief calls for news-anchored openers (use `lilly-icebreaker-news-search`).
- The campaign uses a different icebreaker style entirely (e.g. handwritten via `lilly-personalisation`).

---

## API access

| Endpoint | URL | Method | Cost |
|---|---|---|---|
| Search person | `https://api.prospeo.io/search-person` | POST | 1 credit per page (25 results) |
| Enrich person (optional) | `https://api.prospeo.io/enrich-person` | POST | 1 credit per match |
| Jobs search (Hiring, angle 2) | `https://api.theirstack.com/v1/jobs/search` | POST | **Free** when filtered by `company_domain_or` + `blur_company_data:true` (see Angle 2) |
| Smartlead get leads | `https://server.smartlead.ai/api/v1/campaigns/{ID}/leads` | GET | (Smartlead) |
| Smartlead update leads | `https://server.smartlead.ai/api/v1/campaigns/{ID}/leads` | POST | (Smartlead) |

**Auth:**
- Prospeo: `X-KEY: $PROSPEO_API_KEY` (in `~/.navreo-keys.env`)
- TheirStack: `Authorization: Bearer $THEIRSTACK_API_KEY` (in `~/.navreo-keys.env`)
- Smartlead: `?api_key=$SMARTLEAD_API_KEY` (or Navreo secondary `1417c9a6-...zto0vlj` for Navreo-titled campaigns per `feedback_lilly_optimiser_scope`)

Probe-confirmed (2026-05-05) on a `/search-person` call to `stripe.com`: the response includes per-person `last_job_change_detected_at`, `current_job_title`, `job_history[]`, `linkedin_url` AND nested per-company `funding`, `job_postings`, `technology`, `employee_count`, `employee_range`. All five icebreaker angles derive from this single call.

---

## The 5-step workflow

### Step 1 — Pre-flight checklist (MANDATORY)

Per `feedback_always_confirm_inclusions_exclusions`, every run must surface the literal filter shape to the user for sign-off. Show this block populated with proposed defaults and wait for explicit confirmation. Do not paginate, push, or fire the first paid call without sign-off.

**The waterfall order is a per-campaign decision — always ask, never assume** (`feedback_lilly_icebreaker_waterfall_default`). Colleague-first (the order shown below) is the suggested default for senior-leader lists, but the right order depends on the campaign: on a thinner or more junior list, Hiring-first (or Hiring jumping ahead only for companies with a live posting) can be the better call. Surface the order as an explicit choice every run and let the user confirm or reorder. Skipping angles entirely is also a per-campaign option (e.g. hiring-signal briefs skip Hiring + You-joined per `feedback_hiring_signal_icebreaker_skip_angles`).

```
Skill: lilly-icebreaker

Inputs:
- Campaign: {ID or name}
- Custom field name: Icebreaker
- API key: {primary | Navreo secondary}

Angle priority (waterfall order):
  1. Colleague mention    — fires if >=1 senior peer found, excluding prospect
  2. Hiring               — fires if a TheirStack job search finds a live sales-role posting (Prospeo active_titles = fallback)
  3. Funding              — fires if latest funding date <= {6} months and stage NOT in exclusion list
  4. You joined           — fires if prospect's tenure <= {3} months
  5. Tech                 — OFF unless opted in (opt-in requires tech-relevance list)
  6. Generic fallback     — always fires last

Parallel-stature title set (for angle 1):
  Director, VP, Vice President, Head, C-Suite, Founder, Owner
  (preference: same department as prospect; fall to adjacent revenue functions
   — Sales / BD / Partnerships / RevOps / Marketing — if same-dept yields <2 candidates)

Hiring source (angle 2): TheirStack per-company job search (FREE, see Angle 2 for the call).
  Lookback window: 60 days (posted_at_max_age_days). Tighten to 30 for fast-moving lists.
  Sales-role titles sent as TheirStack `job_title_or` (also reused for the Prospeo
  `active_titles` fallback substring match):
    Sales Development Representative, SDR, Business Development Representative, BDR,
    Account Executive, AE, Sales Manager, Sales Director, Head of Sales, VP Sales,
    Sales Representative, Inside Sales, Account Manager, Sales Associate, Junior Sales,
    Sales Coordinator
  (extend with German equivalents: vertrieb, vertriebsinnendienst,
   vertriebsmitarbeiter, verkauf, b2b sales, when targeting DACH companies)
  Fallback (0 credits): Prospeo `company.job_postings.active_titles[]` from the same
  /search-person response, if TheirStack returns nothing or the key is unavailable.

Recency thresholds:
  - Recent role change: 3 months (job_history[current=true].start_year/month)
  - Recent funding: 6 months (company.funding.latest_funding_date)

Funding stage exclusions (angle 3 auto-skips these): Acquired, Bankruptcy, M&A, Liquidation, Secondary market

Tech-relevance list (only if angle 5 opted in): {ASK USER}

Optional /enrich-person per-lead toggle (guarantees angle 4 if prospect not in /search-person page 1):
  OFF (default — opportunistic angle 4)

Estimated cost: ~{N_unique_companies} Prospeo credits ≈ ${N_unique_companies × 0.005}
                + TheirStack hiring search: FREE (domain-filtered + blurred)
```

Treat any change to the lists as a hard override; re-confirm before paginating or pushing.

### Step 1.5 — Read the email copy *(MANDATORY before generating)*

The angle templates are fixed (5 angles + fallback), but they don't exist in a vacuum — each rendered line drops INTO an email body. Before generating, fetch the campaign's sequence and verify the body's structure works with the locked templates.

#### Fetch the sequence

```bash
curl -s "https://server.smartlead.ai/api/v1/campaigns/{ID}/sequences?api_key={KEY}"
```

For every step that contains `{{Icebreaker}}`, extract the **carrier sentence** (the sentence containing `{{Icebreaker}}`) AND the sentence immediately after.

#### Echo back to the user

Paste the email-1 body back with `{{Icebreaker}}` highlighted in **bold**, plus the next sentence. Confirm: *"This is the body the icebreaker lands into. Same as you have in mind?"* Catches stale copy, wrong campaign, or unexpected merge variables before any paid call.

#### Sanity-check the templates against the body

Walk through each angle template and confirm it slots cleanly:
- **Greeting style** — does the body open with `Hi {{first_name}}, {{Icebreaker}}` (icebreaker is sentence #2 after a greeting)? Or `{{Icebreaker}}` standalone? The locked templates assume the former.
- **Punctuation hand-off** — every template ends with `.` (a period). Verify the body's NEXT sentence after `{{Icebreaker}}` reads cleanly as a new sentence. If the body expects a comma continuation (e.g. `{{Icebreaker}} and noticed…`), the templates won't fit and you must flag.
- **Topical fit** — does the body's pitch contradict any angle's premise? Examples: body pitches a Salesforce-replacement → angle 5 (tech) firing on `Salesforce` would be tone-deaf; body opens by asking *"how long have you been there?"* → angle 4 (you joined) creates incoherence.

#### Suggesting body tweaks (optional output)

If the body's structure fights the templates, surface a tweak suggestion — never auto-apply:

> *"The body's first sentence after `{{Icebreaker}}` opens with 'I recorded a short video for…'. The locked icebreaker templates all end on a period and start a fresh sentence — this works, but reads slightly stiff because the body sentence opens with 'I' immediately after. Two options: (a) tweak the body's next sentence to start with `So I recorded` or `Just recorded`, or (b) accept the slight stiffness and proceed. Want me to suggest the body change for `lilly-bot` to apply, or proceed as-is?"*

If the friction is structural (e.g. body expects a comma continuation, templates produce periods), flag it as a **blocker** — proceeding will produce broken sentences. Recommend the user routes to `lilly-bot` to fix the body before this skill runs.

#### Skip rule

Only skip Step 1.5 if the user pasted email-1 copy into this conversation already AND explicitly said *"don't re-fetch."* Otherwise always fetch fresh.

### Step 2 — Fetch and dedup leads

Pull leads from Smartlead via `GET /api/v1/campaigns/{ID}/leads?api_key={KEY}&offset=0&limit=100`, paginating until empty.

Required per-lead fields: `email`, `first_name`, `last_name`, `company_name`, `website` (canonical domain), `job_title`. Optional but useful: `linkedin_url`.

Group leads by canonical company domain. The skill makes one Prospeo call per unique domain regardless of how many leads sit at that company.

### Step 3 — Cache check FIRST, then fresh `/search-person` only on miss/stale

The list-builder + DM-finder skills (`lilly-tam`, `lilly-tam`, `lilly-tam`) cache every Prospeo and AI Ark response slice they fetch. A campaign's leads have very often passed through one of those skills already, in which case all the icebreaker-relevant fields (funding, job_postings, technology, employee_count, plus per-person tenure) are sitting in `~/.navreo-cache/` for free.

**Read order (per unique domain):**

0. **Supabase central cache** (shared across all machines and skills) → query it FIRST via the shared helper `~/.claude/skills/_shared/navreo_db.py`:
   ```python
   import sys; sys.path.insert(0, str(Path.home() / ".claude/skills/_shared"))
   import navreo_db
   row = navreo_db.get_enrichment("company", domain, max_age_days=30)
   # row["payload"] has the same shape as the local cache file's "data" key
   # (row["provider"] tells you whether to read it as prospeo or ai_ark schema)
   ```
   Hit + fresh → use it. **0 credits.** Returns `None` on miss, stale, or Supabase outage — fall through to the local cache below either way (never let a network failure block the run).
1. **Prospeo cache hit + fresh** (`~/.navreo-cache/prospeo/companies/{domain}.json`, `fetched_at` within staleness window) → use it. **0 credits.**
2. **AI Ark cache hit + fresh** (`~/.navreo-cache/ai_ark/companies/{domain}.json` and/or `~/.navreo-cache/ai_ark/people/{slug}.json`) → use it for angles **1, 3, 4, 5**. **0 credits.** AI Ark's company response carries `financial.funding` (with full rounds + `date`), `technologies[]` (richer than Prospeo for some cos), `summary.staff.total`, `location` — all the fields needed for angle 3 (funding) + angle 5 (tech) + size-conditional angle 1 (colleague). AI Ark's `/v1/people` response carries `position_groups[0].date.start` (current-job ISO start date) — clean tenure data for angle 4 (you joined). Angle **2 (hiring)** does not come from AI Ark or Prospeo cache at all — it is fetched fresh per-company from TheirStack (free, see Angle 2), so cache provider doesn't matter for it; Prospeo `job_postings.active_titles[]` (when a Prospeo cache/response exists) is only the fallback. Schema-mapping reference is at the bottom of this section.
3. **Cache miss or stale on both** → fall through to a fresh Prospeo `/search-person` call (the body below). Write the response to cache per `lilly-tam`'s "Cache writes" section so subsequent runs hit cache.

**Default staleness:** 30 days. Override at pre-flight (some signals — funding, tenure — could safely go to 60-90; job_postings churns faster, could tighten to 14).

**Slice-not-slurp pattern** (cheap on tokens — only the icebreaker-relevant fields enter context):

```bash
CACHE_FILE=~/.navreo-cache/prospeo/companies/${DOMAIN}.json
STALENESS_DAYS=30

if [ -f "$CACHE_FILE" ]; then
  AGE_DAYS=$(( ( $(date +%s) - $(date -r "$CACHE_FILE" +%s) ) / 86400 ))
  if [ "$AGE_DAYS" -le "$STALENESS_DAYS" ]; then
    jq '{
      source: "prospeo_cache",
      age_days: '"$AGE_DAYS"',
      funding: (.data.funding // {} | {latest_funding_date, latest_funding_stage}),
      job_postings: (.data.job_postings // {} | {active_count, active_titles: (.active_titles // [])[0:30]}),
      technology: (.data.technology // {} | {technology_names: (.technology_names // [])[0:30]}),
      employee_count: .data.employee_count,
      employee_range: .data.employee_range
    }' "$CACHE_FILE"
    # CACHE_HIT — skip API
    exit 0
  fi
fi
# fall through to AI Ark cache check, then to fresh /search-person
```

**Per-prospect tenure cache check** (powers angle 4 deterministically when the lead has a `linkedin_url`):

```bash
LI_SLUG=$(echo "$lead_linkedin_url" | sed -E 's|.*/in/([^/?]+).*|\1|')
PERSON_FILE=~/.navreo-cache/prospeo/people/${LI_SLUG}.json
if [ -f "$PERSON_FILE" ]; then
  jq '.data | {current_job_title, last_job_change_detected_at,
       current_job: (.job_history // [] | map(select(.current == true))[0] | {title, start_year, start_month})}' "$PERSON_FILE"
fi
```

**Fresh /search-person call** (only when cache miss/stale):

```bash
curl -X POST "https://api.prospeo.io/search-person" \
  -H "X-KEY: $PROSPEO_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "page": 1,
    "filters": {
      "company": {"websites": {"include": ["acme.com"]}},
      "person_seniority": {"include": ["Founder/Owner","C-Suite","Vice President","Head","Director","Manager"]}
    }
  }'
```

Returns up to 25 senior people at the company AND the company-level object (funding, job_postings, technology, employee_count, employee_range). All five angles derive from this one response.

**After the fresh call, write to cache** via `navreo_db.put_enrichment("company", domain, "prospeo", payload, endpoint="/search-person", source_skill="lilly-icebreaker")` — this dual-writes BOTH the Supabase central cache and the local `~/.navreo-cache` mirror file (same envelope as before). Subsequent runs on any machine hit the cache for free. If the helper is unavailable, fall back to writing the local file per `lilly-tam`'s "Cache writes" section.

If `results: []` and no cache available (company has no Prospeo coverage): every lead at this domain falls to angle 6 (generic fallback). Skip the per-lead waterfall; mark `angle_fired = 6` directly.

**Always log per-lead the data source** in the debug CSV: `source_used = "prospeo_cache" | "ai_ark_cache" | "prospeo_fresh"`. The user wants to see cache hit-rate for every run (informs the cost saving).

#### AI Ark schema mapping (when reading from `~/.navreo-cache/ai_ark/`)

Verified against `/v1/companies` and `/v1/people` probes 2026-05-05. AI Ark wraps fields differently to Prospeo — use this map when reading from AI Ark cache:

| Angle | Prospeo field | AI Ark equivalent |
|---|---|---|
| 1 — tenure | `person.job_history[current=true].start_year/start_month` | `position_groups[0].date.start` (ISO YYYY-MM-DD; `date.end == null` means current). Profile name at `profile.full_name`, `profile.title`. |
| 2 — hiring | `company.job_postings.active_titles[]` | **NOT AVAILABLE on AI Ark.** Fall through. |
| 3 — colleague | `/search-person` results filtered by seniority | `/v1/people` results at same `account.domain` (multi-result response, same query shape). LinkedIn slug at `identifier`. |
| 4 — funding | `company.funding.latest_funding_date` + `latest_funding_stage` | `financial.funding.date` + `financial.funding.rounds[0].type` (rounds reverse-chron; `type` enum like `SERIES_I` / `SECONDARY_MARKET` / `SEED_ROUND`). |
| 5 — tech | `company.technology.technology_names[]` | `technologies[]` (each row has `name` + optional `category`). |
| size split (3a vs 3b) | `company.employee_count` | `summary.staff.total` (or `summary.staff.range.start/end` if total absent). |

Funding-stage normalisation when reading AI Ark: `SERIES_A` → `Series A`, `SECONDARY_MARKET` → (skip per exclusion list), `SEED_ROUND` → `seed`, `GRANT` → `grant`, `VENTURE_ROUND` → (generic `round of funding`), etc. Same exclusion list applies (skip Acquired / Bankruptcy / M&A / Liquidation / Secondary market).

### Step 4 — Per-lead waterfall

For each lead at this company, walk the angles in order. First to fire wins.

#### Angle 1 — Colleague mention

Filter `/search-person` results to: people whose seniority is in `{Director, Vice President, Head, C-Suite, Founder/Owner, Partner}`, excluding the prospect (match by `linkedin_url` or first+last name). **Also exclude peers whose first_name matches a word in the company_name** — Prospeo sometimes returns dirty rows where the first_name field was filled with the company name (e.g. `Enate` listed as a peer at `Enate`).

Rank remaining peers by parallel-stature relevance to the prospect's `job_title` via a short LLM call:
1. Same department + senior or equal rank: highest priority.
2. Adjacent revenue-side function (Sales / BD / Partnerships / RevOps / Marketing): next priority.
3. Other senior peers at the company: lowest priority.

Take top 1, 2, or 3 (capped at 3, minimum 1).

**Title inclusion conditional on company size:**
- If `company.employee_count >= 50` OR `employee_range` is in `{51-200, 201-500, 501-1000, 1001-5000, 5001-10000, 10000+}`: include parenthetical titles.
- Else (`employee_count < 50`, OR range is `1-10` / `11-50`, OR both fields null): names only.

Parenthetical titles should be abbreviated cleanly (`BD` for `Business Development`, `RevOps` for `Revenue Operations`, `Strategic Accts` for `Strategic Accounts`, etc.) and truncated at word boundaries — never mid-word ("Director BD" not "Director Business Developmen").

Generate (size >= 50 example):
```
Apologies if this isn't relevant. I wasn't sure if you, Sarah (VP Sales) or Marcus (Head of BD) was the right person at {{company_name}}.
```

Generate (size < 50 or unknown example):
```
Apologies if this isn't relevant. I wasn't sure if you, Sarah or Marcus was the right person at {{company_name}}.
```

If 0 senior peers found (only prospect in results, or no Director+ at all): skip, fall to angle 2.

#### Angle 2 — Hiring

**Primary source: TheirStack per-company job search (free).** Validated 2026-05-29 on a 20-lead Navreo Sales-Leaders sample: TheirStack surfaced a live sales-role posting at ~5/20 companies vs ~1/20 from Prospeo's own `active_titles`, roughly 4-5x richer, at zero credit cost.

Fire one TheirStack call per unique domain, lazily (only when the waterfall actually reaches angle 2 for a lead at that domain), and cache the result on the domain so other leads there reuse it:

```bash
set -a; source ~/.navreo-keys.env 2>/dev/null; set +a   # Bash tool shell doesn't auto-source
BODY=$(jq -nc --arg d "$DOMAIN" '{
  posted_at_max_age_days: 60,
  company_domain_or: [$d],
  job_title_or: ["Sales Development Representative","SDR","Business Development Representative","BDR","Account Executive","Sales Manager","Sales Director","Head of Sales","VP Sales","Sales Representative","Inside Sales","Account Manager"],
  blur_company_data: true,
  limit: 10
}')
curl -s -X POST "https://api.theirstack.com/v1/jobs/search" \
  -H "Authorization: Bearer $THEIRSTACK_API_KEY" \
  -H "Content-Type: application/json" \
  -d "$BODY" | jq -r '[.data[]?.job_title] | unique | .[]'
```

Why it's free: filtering by `company_domain_or` returns the company name **unblurred** even with `blur_company_data:true`, so a per-company pull over a known list costs 0 credits (confirmed 2026-05-29). `.data[].job_title` carries the live titles; `.metadata.total_companies` is populated but `total_results` came back null in probes, so count off `.data[]`.

From the returned titles, pick the representative one to mention (deterministic): prefer an **IC / junior** role (SDR, BDR, AE, Sales Representative, Inside Sales, Sales Associate) over a **manager+** role (Sales Manager/Director, Head of Sales, VP Sales) — a junior-rep hire is the stronger enablement buying signal. If only manager+ titles exist, use the first of those.

**Fallback (0 credits): Prospeo `company.job_postings.active_titles[]`.** If TheirStack returns no rows (or `$THEIRSTACK_API_KEY` is unavailable), fall back to the old behaviour: substring-match the user's sales-title set against `active_titles[]` from the Prospeo `/search-person` response already in hand, pick the FIRST match. For DACH-targeting campaigns, also match German equivalents (`vertrieb`, `vertriebsinnendienst`, `vertriebsmitarbeiter`, `verkauf`, `b2b sales`).

**Parent-domain caveat:** a lead whose `website` resolves to a shared parent domain (e.g. Servigistics → `ptc.com`) will return the PARENT'S postings, not the subsidiary's. On the validation run, Servigistics' hits were really PTC corporate roles. When the lead's company_name clearly differs from the domain's brand, treat an angle-2 hit as low-confidence and prefer to fall through.

Apply `a` vs `an` logic to the chosen title:
- `an` if the title's first phonetic sound is a vowel: SDR, AE, MBA, Account Executive
- `a` otherwise: BDR, Sales Manager, Sales Coordinator, Junior Sales, B2B Sales role

Generate:
```
I noticed {{company_name}} is hiring an SDR, and thought I would reach out.
```

If TheirStack returns nothing AND the Prospeo `active_titles[]` fallback is empty / no match: skip, fall to angle 3.

#### Angle 3 — Funding

Read `company.funding.latest_funding_date` and `latest_funding_stage`.

If date is within the last 6 months AND `latest_funding_stage` NOT in `{Acquired, Bankruptcy, M&A, Liquidation, Secondary market}`: angle fires. Map raw stage to natural phrasing:

| Raw stage | Phrased as |
|---|---|
| `Series A` / `Series B` / `Series C` / etc. | `Series A round` / `Series B round` |
| `Seed` | `seed round` |
| `Pre-Seed` | `pre-seed round` |
| `Grant` | `grant round` |
| `Debt Financing` / `Convertible Note` / other / unknown | `round of funding` |

Generate:
```
I saw {{company_name}} closed a Series B round recently, and thought I would reach out.
```

If date > 6 months OR stage in exclusion list: skip, fall to angle 4.

#### Angle 4 — You joined

Find the prospect in the `/search-person` response (match by `linkedin_url` if available on the lead, else first_name + last_name).

If found, read `job_history[]`, locate the entry with `current: true`, compute tenure:
```
months_at_company = (today_year - start_year) * 12 + (today_month - start_month)
```
If `months_at_company <= 3` (default; can be loosened at pre-flight): angle fires. Generate:
```
I saw you recently joined {{company_name}} as {{title}}, and thought I would reach out.
```

If prospect not in response, OR tenure > 3 months, OR `current: true` job_history entry missing: angle skips, fall to angle 5 (or 6 if angle 5 OFF).

(Optional toggle from pre-flight: per-lead `/enrich-person` lookup if prospect not in `/search-person` page 1 — adds 1 credit per lead, default OFF.)

Note: when working from a pre-exported Prospeo CSV rather than a fresh `/search-person` call, the `Job start year/month` columns can lag the live data by 6+ months — angle 4 often fires 0 times on CSV-only runs even with a 3-month window. If you need fresh tenure data, run a fresh `/search-person` instead of relying on a CSV.

#### Angle 5 — Tech (opt-in only)

Only fires if user opted in at pre-flight AND supplied a tech-relevance list. If OFF, skip silently to angle 6.

Read `company.technology.technology_names[]`. For each tech, check if any user-supplied tech is a case-insensitive substring match.

If match: pick the FIRST in the array (deterministic). Generate:
```
I noticed {{company_name}} is using Salesforce, and thought I would reach out.
```

If no match: fall to angle 6.

Note: a pre-exported Prospeo CSV's `Company technologies` column is often empty / `"No preferred technology configured"` — angle 5 effectively cannot fire on CSV-only runs. Fresh `/search-person` calls return real tech data.

#### Angle 6 — Generic fallback (ALWAYS fires)

Rotate deterministically across the 8 approved fallback variants below (hash the lead's email to pick — same lead always picks the same variant on re-run). Varying the line across the campaign reduces spam-pattern detection and reads more naturally at scale.

Approved fallback variants (all open with "Apologies, ..." and end on a period that hands off cleanly into the next body sentence):

1. `Apologies if this isn't relevant, I wasn't sure who the best person at {{company_name}} was to speak about this.`
2. `Apologies if this should sit with someone else, I wasn't sure who at {{company_name}} owned this.`
3. `Apologies if you're not the right person, I wasn't sure who to reach at {{company_name}} for this.`
4. `Apologies for the cold reach, I wasn't sure who the right contact at {{company_name}} was for this.`
5. `Apologies if I've got the wrong person, I wasn't sure who at {{company_name}} was the best to speak with about this.`
6. `Apologies if this isn't your area, I wasn't sure who the right person at {{company_name}} was.`
7. `Apologies if I'm off-mark, I wasn't sure who handles this kind of thing at {{company_name}}.`
8. `Apologies for reaching out cold, I wasn't sure who the right person at {{company_name}} was to speak with.`

Selection: `variant_index = int(md5(email).hexdigest(), 16) % len(variants)`. Deterministic per lead, so re-runs produce the same line on the same lead.

`{{company_name}}` is baked in literal at generation time (no nested merge expansion).

`{{Icebreaker}}` is now populated for this lead.

### Step 5 — Push to Smartlead

Batch updates in groups of 100 per `lilly-personalisation`:

```bash
curl -s -X POST "https://server.smartlead.ai/api/v1/campaigns/{ID}/leads?api_key={KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "lead_list": [
      {"email": "bob@acme.com", "custom_fields": {"Icebreaker": "I saw you recently joined Acme as Sales Director, and thought I would reach out."}}
    ]
  }'
```

Smartlead's API upserts on email; safe to re-run if a batch fails partway.

After the push, run `scripts/check_lead_variable_fill.py` (per `feedback_lilly_qa_lead_variable_fill`) to confirm 100% fill rate on `{{Icebreaker}}`. The fallback (angle 6) guarantees this.

---

## Output schema (debug log / CSV)

For QA, log per-lead:

| Column | Description |
|---|---|
| `email` | Lead email (Smartlead key) |
| `first_name` | Lead first name |
| `company_name` | Lead company |
| `domain` | Canonical domain |
| `angle_fired` | 1 / 2 / 3 / 4 / 5 / 6 |
| `signal_data` | The Prospeo field value that triggered (e.g. tenure months, matched job title, peer names, funding date+stage, matched tech) |
| `icebreaker` | Generated `{{Icebreaker}}` line |

Drop into the user's project folder (e.g. `~/Library/.../Navreo/icebreaker_runs/{campaign}_{date}.csv`) for review before the bulk push. Always show the angle distribution to the user (e.g. "12% angle 1, 18% angle 2, 41% angle 3, 9% angle 4, 0% angle 5, 20% angle 6") — high fallback rates mean Prospeo coverage is thin and the user may want to switch to `lilly-icebreaker-news-search` instead.

---

## Cost calibration

Per 1,000-lead campaign with ~700 unique companies (typical Navreo distribution):

**Cold cache (no prior Prospeo / AI Ark fetches for these domains):**
- 700 Prospeo `/search-person` credits = ~$3.50 at $0.005/credit
- 0 enrich credits (default — opportunistic angle 1)
- 0 TheirStack credits (hiring search is free — domain-filtered + blurred)
- 0 AI Ark / Serper / WebFetch
- ~5-10s LLM time for parallel-stature ranking on each company with multiple peers
- **Total: ~$3.50 per 1K leads.**

**Warm cache (typical when leads came through `lilly-tam` or a list-builder first):**
- ~100-200 Prospeo `/search-person` credits for cache misses + stale entries (varies by overlap)
- ~500-600 cache hits = **0 credits**
- **Total: ~$0.50-$1.00 per 1K leads** (60-85% saving vs cold).

Optional: per-lead `/enrich-person` for guaranteed angle 4 firing adds 1 credit per lead, but ONLY for leads not already in the people-cache. Many leads will have a person-cache hit if they came from `lilly-tam` previously — the actual enrich cost on warm cache is typically 200-400 credits (not the full 1,000), so guaranteed angle 4 ends up around +$1-2 instead of +$5.

For comparison, `lilly-icebreaker-news-search` runs ~$0.20 per 100 cos = $2 per 1K cos but needs a NO_HIT fallback path; this skill's fallback is built in.

---

## Guardrails

1. **Pre-flight is mandatory** (`feedback_always_confirm_inclusions_exclusions`). Never fire the first paid call without the user confirming the literal filter lists, priority order, recency thresholds, and tech opt-in. Defaults are documented but always re-surface for sign-off.
2. **Waterfall is sequential.** Each angle is tested in order; the first to qualify wins; subsequent angles are not checked. Never pick the "strongest" angle across multiple qualifying signals — pick the first.
3. **`{{Icebreaker}}` is never empty.** The generic fallback (angle 6) always fires when angles 1-5 miss. If the Prospeo call returned no results at all, every lead at that domain gets angle 6 directly.
4. **No em-dashes** (`feedback_no_em_dashes`). All angle templates use commas, periods, parentheses. Verify on the rendered output before push.
5. **Sentence-cased icebreakers.** Each line starts with a capital letter and reads as a complete sentence (`I wasn't sure who...`, not `wasn't sure who...`). The line stands alone after the greeting in the email body.
6. **Conditional titles for angle 1.** Include `({{Title}})` only when `employee_count >= 50` or `employee_range` is a 50+ bucket. Below 50 or unknown: names only. Titles at small cos signal try-hard, not deliberate research. Also: abbreviate multi-word titles (`Business Development` → `BD`, `Revenue Operations` → `RevOps`, `Strategic Accounts` → `Strategic Accts`) and truncate at word boundaries — never mid-word.
7. **Angle 3 funding stage exclusions.** Auto-skip `Acquired`, `Bankruptcy`, `M&A`, `Liquidation`, `Secondary market`. These read tone-deaf or are too inside-baseball. (Stripe's most-recent stage on the 2026-05-05 probe was "Secondary market" — confirms why the exclusion matters.)
8. **Angle 5 is opt-in only.** Tech-stack opener is the weakest signal; never default-on. User must supply both opt-in toggle and tech-relevance list at pre-flight.
9. **A/an article logic for angle 2.** Pick `an` if the first phonetic sound of the title is a vowel (SDR, AE, Account Executive, MBA), else `a` (BDR, Sales Coordinator, Junior Sales). Implement via a short helper.
10. **Always log angle_fired per lead** in the debug CSV. The user needs to see the distribution (e.g. "70% fell through to fallback") to diagnose whether the campaign's audience has thin Prospeo coverage.
11. **Smartlead API key fallback** (`feedback_lilly_optimiser_scope`). Try primary key first; if `GET campaigns/{ID}` returns 404 or empty sequence on a Navreo-titled campaign, retry with the Navreo secondary key (`1417c9a6-...zto0vlj`).
12. **Post-push QA** (`feedback_lilly_qa_lead_variable_fill`). Run `scripts/check_lead_variable_fill.py` — must show 100% fill on `{{Icebreaker}}`. The fallback (angle 6) guarantees this.
13. **Deterministic angle 2 / angle 5 picks.** When multiple `job_postings.active_titles[]` or `technology.technology_names[]` match the user's relevance list, pick the FIRST in the array (Prospeo's natural ordering). Avoids the same lead getting different lines on a re-run.
14. **Tenure source order.** Prefer `job_history[current=true].start_year/start_month` over `last_job_change_detected_at` (the latter was null on the 2026-05-05 probe; job_history is more reliable). If both are missing, angle 4 skips.

21. **Filter peer-name = company-name from angle 1.** Prospeo occasionally returns dirty rows where the `first_name` field is filled with the company name (e.g. `Enate` listed as a peer at `Enate`). Always exclude peers whose lowercase first_name matches a word in the lowercase company_name before selecting the top 1-3 peers.

22. **Strip em-dash company-name tails before rendering.** Some Prospeo `company_name` values contain em-dash-separated taglines like `CallGear — Business Communication Software`. The full string would leak into icebreaker templates (`I wasn't sure who the best person at CallGear — Business Communication Software was...`). Truncate at the first ` — ` (or ` | `) before rendering into any template.
15. **Cache per-domain.** One `/search-person` call per unique domain regardless of how many leads sit there. Re-using the cached response is free; firing duplicate calls wastes credits.
16. **Read cache before any fresh `/search-person` call.** Step 3 documents the slice-not-slurp pattern: a `jq` one-liner returns only the icebreaker-relevant fields per domain, ~50-200 chars per company. Never `cat ~/.navreo-cache/prospeo/companies/*.json` into context — that explodes token usage. Use jq filters that extract only `funding`, `job_postings.active_titles[0:30]`, `technology.technology_names[0:30]`, `employee_count`, `employee_range` per company.
17. **Write cache after every fresh fetch.** Same envelope as `lilly-tam` writes (see that skill's "Cache writes" section). Mark `source_skill: "lilly-icebreaker"`. Subsequent runs benefit.
18. **Staleness threshold default 30 days.** Override at pre-flight if the user wants tighter (e.g. job_postings churns faster — 14d) or looser (funding/tenure can go to 60-90d).
19. **Cache trumps API.** If a fresh Prospeo cache hit exists for a domain, use it — do NOT fire a fresh call to "double-check." That defeats the cache. Only invalidate on the staleness threshold or an explicit user override.
20. **Provider precedence.** Prospeo cache > AI Ark cache > fresh Prospeo `/search-person` for angles **1, 3, 4, 5** (AI Ark cache verified 2026-05-05). **Angle 2 (hiring) is independent of this precedence** — it comes from a free TheirStack per-company job search (validated 2026-05-29), with Prospeo `job_postings.active_titles[]` as the 0-credit fallback. AI Ark has no `job_postings` field and never serves hiring.

23. **TheirStack hiring is free and per-domain.** Always send `company_domain_or:[domain]` + `blur_company_data:true` — that combination returns the company name unblurred at 0 credits. Never run an unfiltered or blur-off TheirStack search from this skill (that bills credits). Fire it lazily (only when the waterfall reaches angle 2) and cache per domain; job postings churn fast, so use a 14-day staleness if cached.

24. **Per-campaign waterfall order (always confirm).** The angle order is NOT hardcoded — surface it at pre-flight every run and let the user confirm or reorder (`feedback_lilly_icebreaker_waterfall_default`). Colleague-first is the suggested default for senior-leader lists; Hiring-first or hiring-ahead-for-hits suits thinner / junior lists. On a colleague-first run a strong hiring hit is held in reserve (Colleague pre-empts it ~90% on senior lists) — flag this when a campaign has many hiring hits but few colleague misses, so the user can choose to reorder.

---

## Quick reference

| Need | Endpoint / Path | Body / Pattern |
|---|---|---|
| **Read company cache (Prospeo)** | `~/.navreo-cache/prospeo/companies/{domain}.json` | `jq '{funding, job_postings, technology, employee_count, employee_range}' < $f` |
| **Read company cache (AI Ark)** | `~/.navreo-cache/ai_ark/companies/{domain}.json` | provider-aware schema mapping |
| **Read person cache (tenure)** | `~/.navreo-cache/prospeo/people/{linkedin-slug}.json` | `jq '.data.job_history[] \| select(.current==true)'` |
| Find senior peers + company data (fresh) | `POST api.prospeo.io/search-person` | `{"page":1,"filters":{"company":{"websites":{"include":["X.com"]}},"person_seniority":{"include":["Founder/Owner","C-Suite","Vice President","Head","Director","Manager"]}}}` |
| Optional per-lead tenure lookup (fresh) | `POST api.prospeo.io/enrich-person` | `{"linkedin_url":"https://linkedin.com/in/..."}` |
| **Hiring signal (angle 2, free)** | `POST api.theirstack.com/v1/jobs/search` | `{"company_domain_or":["X.com"],"job_title_or":[<sales titles>],"posted_at_max_age_days":60,"blur_company_data":true,"limit":10}` → parse `.data[].job_title` |
| Push `{{Icebreaker}}` to Smartlead | `POST server.smartlead.ai/api/v1/campaigns/{ID}/leads?api_key={KEY}` | `{"lead_list":[{"email":"...","custom_fields":{"Icebreaker":"..."}}]}` |

See also:
- `lilly-icebreaker-news-search/SKILL.md` — Serper-based news-anchored alternative.
- `lilly-tam/SKILL.md` — canonical Prospeo `/search-person` mechanics, full waterfall to AI Ark for DM enrichment, cache-write authority. (This skill uses a tighter subset: broader seniority filter, no department filter, no enrichment, no AI Ark fallback. Reads the cache produced by DM-finder.)
- `lilly-tam/SKILL.md` — primary upstream cache-writer for `/search-company` data (reuses the same `~/.navreo-cache/prospeo/companies/` tree).
- `lilly-tam/SKILL.md` — AI Ark cache-writer (provider-isolated tree).
- `lilly-personalisation/SKILL.md` — Smartlead push patterns and the QA fill check.
- `lilly-theirstack-setup/SKILL.md` — TheirStack mechanics + the ad-hoc `/v1/jobs/search` pattern reused here for the Hiring angle.
- `~/.navreo-keys.env` — `PROSPEO_API_KEY`, `THEIRSTACK_API_KEY`, `SMARTLEAD_API_KEY`.
- `~/.navreo-cache/` — cache root (Prospeo + AI Ark, companies + people).
- `feedback_always_confirm_inclusions_exclusions.md` (memory) — mandatory pre-flight rule.
- `feedback_no_em_dashes.md` (memory) — no em-dashes in angle templates.
- `feedback_lilly_qa_lead_variable_fill.md` (memory) — post-push QA fill check.

---

**Voice:** For email voice: follow lilly-copywriter's "THE NAVREO VOICE" section (canonical) and read ~/.claude/skills/offer-email-voice-match/voice-corpus.md before writing any email copy.
