---
name: lilly-email-verification
description: "Verify and enrich a CSV lead list with deliverable emails before Smartlead import. Verifies existing emails via MillionVerifier (skipped when the list comes from AI-ARK, since AI-ARK is pre-verified) and finds missing emails via Prospeo's enrich-person endpoint (MillionVerifier-verifying every Prospeo-found email), falling back to AI Ark's email finder. Drops anything that can't be confirmed deliverable. Trigger whenever the user mentions email verification, email enrichment, finding emails, verifying emails, cleaning a lead CSV before Smartlead import, MillionVerifier, Prospeo, AI Ark, AI-ARK exports, or asks 'can you fill in the missing emails / check these emails / clean this list before I upload it'. Also invoked as the end-of-run hand-off from `lilly-tam` and Phase 3.5 of `lilly-trigify-data-processing` to MV-double-check Prospeo-source emails (Stage 1 only, Stage 2 is a no-op since every row already has an email)."
---

# Lilly Email Verification

## Purpose

Take a raw lead CSV, end up with a CSV where every remaining row has a deliverable email — ready to drop into Smartlead with `lilly-bot` or `lilly-updates-leads`.

**Stage 0 runs first and is free** — it drops suppressed/already-contacted rows via `check_exclusions` + `contact_history`, and checks the central `people` cache (by email and LinkedIn slug) so Stages 1-2 never pay for a lookup we already hold (see Stage 0 below).

Two paid stages:

1. **Verify** rows that already have an email via **MillionVerifier** — unless the list came from AI-ARK, which marks emails as `REAL-TIME VERIFIED` at export time.
2. **Find** emails for rows that are missing one, in this order:
   - **Prospeo** `/enrich-person` with `only_verified_email: true` → then **MillionVerifier-verify the Prospeo-found email** (keep `ok`/`catch_all`, drop otherwise)
   - If Prospeo returns `NO_MATCH` → fall back to the **AI Ark** email finder (AI-Ark emails are real-time-verified at source, so they skip MillionVerifier)
   - If both fail → drop the row

Anything that can't be verified or found is **dropped**. The output is intentionally smaller than the input — that's the job.

### A note on cost

- **MillionVerifier** (Stage 1 verification, and the re-check of every Prospeo-found email) bills **1 credit per call regardless of result** — `ok`, `catch_all`, `invalid`, `unknown`, `disposable` all cost the same. A 1,000-row verification pass = 1,000 credits flat.
- **Prospeo** (Stage 2a) is **pay-per-success** — 0 credits on `NO_MATCH`. **AI Ark** (Stage 2b) bills per record it returns, so filter tightly before sweeping. Try Prospeo first (cheap), sweep the misses with AI Ark.

---

## When to Use

Trigger when the user wants to:

- Clean a lead CSV before importing to Smartlead
- Fill in missing emails on a list
- Verify a batch of emails for deliverability
- Reduce bounce risk on a fresh list

Accept input forms:

- "Enrich this CSV / find emails for this list"
- "Verify these emails before I upload them"
- "Clean up @/path/to/list.csv for Smartlead"
- "I have an AI-ARK export — can you fill the missing ones?"

If the user only hands you a path with no other context, default to the full pipeline.

---

## Source Detection: AI-ARK vs Anything Else

This decides whether Stage 1 runs.

### Auto-detect AI-ARK

AI-ARK exports are recognisable by **two signature columns** that nothing else uses:

- `AI Ark People ID`
- `Company AI Ark account ID`

Plus a `Business Status` column whose values look like `REAL-TIME VERIFIED ON 25 Apr 26`.

**If both signature columns exist → assume AI-ARK, confirm in one sentence with the user, and skip MillionVerifier verification on existing emails.** Don't make the user answer a question they've already implicitly answered with the file format.

> "This looks like an AI-ARK export — I'll trust the existing emails as verified and only run Prospeo on the rows missing one. Sound good?"

**Persist AI-ARK emails as pre-verified.** AI-ARK verifies every email through BounceBan at source, so an AI-ARK email IS a verification event. Whenever you write an AI-ARK-sourced email to the central `people` table, do it via `navreo_db.upsert_person(email=..., provider="ai_ark", ...)` — the helper stamps `email_verification="good"` + `email_verified_at=<now>` automatically, so the signals deliverability tool (60-day verify cache) never re-spends a ListMint/MillionVerifier credit on it. Never pass a fabricated verdict for a non-AI-ARK email; only real providers set it.

### Ask when ambiguous

If those columns aren't present, ask plainly:

> "Did this list come from AI-ARK? (If yes, I'll skip MillionVerifier verification — AI-ARK marks emails as verified at export. If no, I'll run every email through MillionVerifier.)"

The user's answer drives Stage 1.

### Auto-detect Prospeo DM-finder hand-off

When the caller passes the hint `Source: prospeo_dm_finder (skip Stage 2, run MV Stage 1 on all rows)` — or when the input CSV has a `source` column containing `prospeo` / `ai_ark+prospeo` and no `Email Business` / `AI Ark People ID` columns — treat it as a Prospeo DM-finder hand-off:

- Skip the source-detection prompt entirely.
- Run Stage 1 (MillionVerifier) on every row.
- Stage 2 (find-missing) is a no-op because every row already has an email. Don't fire the Prospeo/AI Ark finders.
- Optional: when the input CSV has a `source` column, filter to rows where `source IN ('prospeo', 'ai_ark+prospeo')` BEFORE the MV pass. Rows with `source = ai_ark_email_fallback` (or similar AI-Ark-direct email values) are exempt from MV — caller already excluded them per the DM-finder hand-off contract.

This entry point is invoked by `lilly-tam` (end-of-run) and `lilly-trigify-data-processing` (Phase 3.5).

---

## Column Mapping

CSVs come in two main shapes. Detect headers and map to a normalised internal schema before processing.

### AI-ARK shape

| Internal | AI-ARK header |
|---|---|
| `email` | `Email Business` |
| `first_name` | `First Name` |
| `last_name` | `Last Name` |
| `full_name` | `Full Name` |
| `title` | `Title` |
| `company_name` | `Company Name` *(or `Org` if blank)* |
| `company_domain` | derived from `Company Website` (strip `http(s)://`, `www.`, trailing slash) |
| `linkedin_url` | `LinkedIn` |
| `country` | `Country` |
| `business_status` | `Business Status` |

### Generic / Smartlead-style shape

Common header variations to accept (case-insensitive, with/without underscores):

- `email`, `email_address`, `Email`
- `first_name`, `firstname`, `First Name`
- `last_name`, `lastname`, `Last Name`, `surname`
- `company_name`, `company`, `organization`
- `company_domain`, `domain`, `website`, `company_website`, `url`
- `linkedin_url`, `linkedin`, `LinkedIn`

**Rule:** when both a `company_domain` and a `company_website` column are present, prefer the explicit domain. When only a website is present, derive the domain.

### Domain derivation

```python
def to_domain(value: str) -> str | None:
    if not value: return None
    v = value.strip().lower()
    for prefix in ("https://", "http://"):
        if v.startswith(prefix): v = v[len(prefix):]
    if v.startswith("www."): v = v[4:]
    return v.split("/")[0].split("?")[0].strip() or None
```

If domain can't be derived and there's no LinkedIn URL, the row is unfindable in Stage 2 — drop it with reason `no_lookup_input`.

---

## API Keys

Stored in `~/.navreo-keys.env` (mode 600), auto-loaded by `~/.zshrc`:

- `MILLIONVERIFIER_API_KEY` — Stage 1 verification
- `PROSPEO_API_KEY` — Stage 2a finder (primary)
- `AI_ARK_API_KEY` — Stage 2b finder (fallback for Prospeo misses; `X-TOKEN` auth)

If any of the three keys are missing, **stop and tell the user which one is missing** before doing any work — partial runs waste credits and produce confusing CSVs. Suggested message:

> "I can't find `MILLIONVERIFIER_API_KEY` in `~/.navreo-keys.env`. Add it and `source ~/.navreo-keys.env` (or open a new shell), then ping me to resume."

```python
import os
def find_key(name):
    return os.environ.get(name)
```

---

## Stage 0 — Suppression + Cache Gate (before any paid call)

Run this before Stage 1 or Stage 2 spend a single credit. Two parts.

### 0a. Drop suppressed / already-contacted rows

Using `db/navreo_db.py`:

1. Call `check_exclusions(client_id, emails=[...], domains=[...])` with every email and company domain in the input. **`None` back means the check was unavailable — treat as "unknown," not "no exclusions," and tell the user exclusions couldn't be verified.** Drop any row it flags.
2. Batch-check the `contact_history` table for the same emails via `rest("GET", "/rest/v1/contact_history", params={"select": "email", "email": "in.(<batch>)"})` (batch ~100 emails per call to stay under URL length limits). Drop any row that already has contact history, unless the user explicitly asked for a recontact run.
3. Report both counts to the user: `Suppressed: N (exclusion list), Already contacted: M (contact history)` before continuing.

### 0b. Batch-lookup the `people` cache

For every remaining row, look up whether we already hold this person's email/verification state:

```python
navreo_db.rest(
    "GET", "/rest/v1/people",
    params={
        "select": "email,linkedin_slug,email_verified_at,email_verification",
        "or": "(email.in.(<email_batch>),linkedin_slug.in.(<slug_batch>))",
    },
)
```

Batch by ~100 identifiers per call (emails and LinkedIn slugs separately if the `or` filter gets unwieldy). Build an in-memory lookup keyed by both `email` and `linkedin_slug` — Stage 1 and Stage 2 both consult it before spending a credit.

Rows with **no** email get looked up by `linkedin_slug` only (see Stage 2 change below). Rows **with** an email get looked up by `email` (see the 90-day TTL rule in Stage 1 below).

---

## Stage 1 — Verify Existing Emails (MillionVerifier)

**Skipped entirely** when the list source is AI-ARK.

**90-day TTL skip.** Before calling MillionVerifier on a row, check the Stage 0b `people` lookup for that row's email. If it shows `email_verification` in (`good`, `ok`, `valid`) AND `email_verified_at` is within the last 90 days, **skip the MillionVerifier call** — treat the row as verified, `source: cache_verified_ttl`, carry forward the cached verification value. Rows with no cache hit, an older `email_verified_at`, or an unrecognised `email_verification` value still go through MillionVerifier as normal. Report the TTL-skip count in the final summary (`TTL-skipped: N via cache`). This is separate from and doesn't change the existing AI-ARK skip rule above.

Otherwise, for each row that has a non-empty email value, call:

```bash
curl -G 'https://api.millionverifier.com/api/v3' \
  --data-urlencode 'api='"$MILLIONVERIFIER_API_KEY" \
  --data-urlencode 'email=person@example.com' \
  --data-urlencode 'timeout=20'
```

> Single-email endpoint. Method is `GET` with the API key + email + optional timeout (2–60s, default 20) as query parameters. **No header auth** — the key goes in the query string.

### Response shape

```json
{
  "email": "person@example.com",
  "quality": "good",
  "result": "ok",
  "resultcode": 1,
  "subresult": "",
  "free": false,
  "role": false,
  "didyoumean": "",
  "credits": 9874,
  "executiontime": 1,
  "error": "",
  "livemode": true
}
```

The `result` field is the primary signal. Possible values: `ok`, `catch_all`, `unknown`, `invalid`, `disposable`, `unverified`. The `credits` field is the **running balance**, useful for monitoring burn rate.

### Decision rule

| `result` | Action |
|---|---|
| `ok` | **Keep**, `source: millionverifier_verified` |
| `catch_all` | **Keep**, `source: millionverifier_verified`, flag `verification_method: catch_all` |
| `invalid` | **Drop**, reason `invalid` |
| `disposable` | **Drop**, reason `disposable` (throwaway mailboxes — Mailinator, etc.) |
| `unknown` | **Drop**, reason `unknown` (SMTP probe inconclusive) |
| `unverified` | **Drop**, reason `unverified` (provider explicitly blocks SMTP — rare; treat as not-deliverable) |

**Catch-all kept on purpose.** Prior version of this skill dropped catch-alls; reversed after a recovery run that lost ~30% of an otherwise-valid pool. On B2B catch-all domains the deliverability hit is small enough that losing the lead is the bigger cost. Flag them in `verification_method` so downstream tooling can choose to deprioritise if it wants — don't drop them at this stage.

### Error handling

Branch on the response body's `error` field, **not HTTP status code** — MillionVerifier returns HTTP 200 with `error` populated when the issue is account-level.

| `error` substring | Action |
|---|---|
| empty string | success — read `result` |
| contains "credit" or "insufficient" | **Stop the run.** Report partial result. |
| contains "invalid api key" / "unauthorized" | **Stop the run.** Tell the user. |
| anything else | log the row to audit, drop with reason `verification_error`, continue |

### Pacing

The MillionVerifier docs don't publish a strict rate limit. Default to `time.sleep(0.1)` between calls (~10 rps), which is conservative and tested fine in similar SMTP-probe providers. If responses start coming back with empty `result` + non-empty `error`, back off to `time.sleep(0.5)` and retry the row once.

### Cost note

**1 credit per call, regardless of result.** MillionVerifier charges flat — every call costs the same whatever the verdict. A 1,000-row pass = 1,000 credits. This applies both to Stage 1 and to the re-verification of every Prospeo-found email in Stage 2a.

Monitor the running balance via the `credits` field on each response — surface a warning to the user if balance drops below 10% of the starting balance, and **stop the run** if `credits` hits 0 or the `error` field mentions credits.

### Write-back after every MV verdict

After every real MillionVerifier call (Stage 1 or the Stage 2a re-check) — not the TTL-skipped or AI-ARK-skipped rows, since those didn't call the provider — write the real verdict back to the cache and log the spend:

```python
navreo_db.upsert_person(
    email=row_email,
    email_verification=mv_result,       # the real "ok"/"catch_all"/"invalid"/etc, never fabricated
    email_verified_at=now_iso,
)
navreo_db.log_provider_usage("millionverifier", 1, endpoint="v3", source_id="lilly-email-verification")
```

Batch the `log_provider_usage` call as one row per MV call (1 credit each), or a single call with the batch total — either is fine as long as the credit count matches calls actually made.

---

## Stage 2 — Find Missing Emails (Prospeo → MillionVerifier → AI Ark fallback)

**Cache-first, before any paid finder call.** For each row with a blank email, check the Stage 0b `people` lookup by `linkedin_slug` first:

- **Cache hit with an email** → use that cached email instead of calling Prospeo/AI Ark. Then apply the same 90-day TTL rule as Stage 1: if `email_verification` is good/ok/valid and `email_verified_at` is within 90 days, keep it as-is (`source: cache_found_ttl`, no MV call). Otherwise run it through the normal MillionVerifier check before keeping (`source: cache_found_reverified`).
- **No cache hit** → fall through to the paid waterfall below.

For each row still missing an email after the cache check:

1. Try **Prospeo** first.
2. If Prospeo returns an email, **verify it through MillionVerifier** (the same Stage 1 check) before keeping — keep `ok`/`catch_all`, drop otherwise. (User rule 2026-05-27: every Prospeo-found email gets the MV re-check.)
3. If Prospeo returns `error_code: NO_MATCH` (or any `error: true` apart from credit/auth/rate-limit), fall back to the **AI Ark email finder**.
4. If AI Ark also returns no email, drop the row.

### Write-back after every Prospeo find that passes MV

```python
navreo_db.upsert_person(
    email=found_email,
    linkedin_slug=row_linkedin_slug,
    email_verification=mv_result,
    email_verified_at=now_iso,
)
navreo_db.log_provider_usage("prospeo", 1, endpoint="enrich-person", source_id="lilly-email-verification")
```

Only write back rows that passed the MV re-check — a Prospeo-found-but-MV-dropped email is not a verified state worth caching.

**AI-Ark-found emails are real-time-verified at source, so they are MV-EXEMPT** — do not re-pipe them through MillionVerifier. Only Prospeo-found emails get the MV re-check.

### Heads-up: AI-ARK lists usually have ~0% Stage 2 recovery

If the source is **AI-ARK and there are missing-email rows**, expect a near-zero hit rate from Prospeo and AI Ark combined. AI-ARK runs its own real-time email finder before export, so the leftover blanks are people the major finders couldn't resolve either — typically niche brands, small/regional companies, fraternal orgs, or roles where the person doesn't surface in finder databases.

**Empirical data point** (April 2026 run on 4,400 missing-email rows from a 3-file AI-ARK export of B2B sales-leadership exporters):

- Prospeo found: **0**
- AI Ark found: **0** (sampled — full sweep aborted after the pattern was clear)

**Recommended behaviour for AI-ARK lists with missing-email rows:**

1. **Surface the pattern early** — after counting missing-email rows, tell the user up front: "These came from AI-ARK; in our experience the missing rows recover near 0% via Prospeo/AI Ark. Want me to run Stage 2 anyway, or skip straight to writing the AI-ARK-verified rows?"
2. **Default to skip** unless the user explicitly says "try anyway" or the list source is non-AI-ARK.
3. **If running anyway**, run a 50-lead sample first and abort if the hit rate is <2%. AI Ark bills per record returned, so don't sweep blindly for 0 returns.

For **non-AI-ARK lists**, the standard Prospeo → AI Ark flow stays the right default — those finders perform much better when the upstream source hasn't already creamed off the easy hits.

### Step 2a: Prospeo `/enrich-person`

**Always** pass `only_verified_email: true` — Prospeo then only returns (and only charges for) emails it has verified.

#### Endpoint

```bash
curl -X POST 'https://api.prospeo.io/enrich-person' \
  -H 'X-KEY: $PROSPEO_API_KEY' \
  -H 'Content-Type: application/json' \
  -d '<see payload below>'
```

> `/email-finder` and `/social-url-enrichment` are **deprecated** (sunset 1 March). Use `/enrich-person` only.

#### Payload — pick the strongest available identifier

Try in this order, falling back as needed:

**1. Name + domain (preferred):**
```json
{
  "only_verified_email": true,
  "data": {
    "first_name": "Alex",
    "last_name": "Stone",
    "company_website": "bloc-group.co.uk"
  }
}
```

**2. LinkedIn URL (when no domain available):**
```json
{
  "only_verified_email": true,
  "data": {
    "linkedin_url": "https://www.linkedin.com/in/alexstone93"
  }
}
```

Use `company_website` (i.e. the domain) — Prospeo's docs explicitly warn against name-only matching, and `company_name` alone produces noisy hits.

#### Branch on `error_code`, not HTTP status

Prospeo returns HTTP 400 with a JSON body for "no match" — don't treat that as a failure to retry.

| `error` / `error_code` | Action |
|---|---|
| `error: false` + `person.email.email` populated | Keep, write the returned email + `verification_method` to a status column. |
| `error: true`, `error_code: NO_MATCH` | **Hand off to Step 2b** (AI Ark finder). No charge. |
| `error: true`, `error_code: INSUFFICIENT_CREDITS` | **Stop the run.** Tell the user. |
| `error: true`, `error_code: INVALID_API_KEY` | **Stop the run.** Tell the user. |
| `error: true`, `error_code: RATE_LIMITED` | Back off (sleep 2s) and retry once; on second 429 stop and tell the user. |
| any other `error: true` | Hand off to Step 2b, log the code. |

#### Cost note

1 credit per verified match. No charge on `NO_MATCH` or duplicate enrichments. Mobile phone fields cost 10 credits — **never request them** in this skill (we don't need them).

#### Domain shift — reassign `company_name` and `company_domain`

When Prospeo returns an email at a **different domain** than the input (e.g. input `company_domain=foxit.com` but Prospeo finds `andrew_travis@foxitsoftware.com`), the returned domain is the source of truth — it usually reflects a parent company, rebrand, or operating entity that the input list got wrong.

**Rule:** when the email's domain doesn't match the input `company_domain`:

1. **Overwrite `company_domain`** with the email's domain.
2. **Overwrite `company_name`** using Prospeo's `response.person.company.name` (or the equivalent AI Ark finder field).
3. Leave the original values in audit-only columns (`original_company_name`, `original_company_domain`) so the change is traceable but downstream Smartlead imports use the corrected values.

If Prospeo doesn't return a company name in the response, derive a placeholder from the new domain (e.g. `foxitsoftware.com` → `Foxitsoftware`) and flag it in the audit JSON for manual review — but still emit the corrected domain.

**Why:** the email's domain is what the recipient's mailbox actually lives on. Personalisation merges (`{{company_name}}`, `{{company}}`) need to match what the recipient calls themselves, otherwise an email about "Foxit" lands at someone whose company is now branded "Foxit Software" — small detail, but common enough on rebrands/acquisitions to be worth correcting automatically.

#### Bulk endpoint — use it for >50 rows

`POST /bulk-enrich-person` accepts up to 50 contacts per request. For larger lists, batch — it's much faster than 500 sequential calls. After the bulk call returns, MillionVerifier-verify every email it found, then build the AI Ark-fallback queue from rows that came back with no email (or whose MV check failed).

### Step 2b: AI Ark email finder (fallback)

Runs only on rows that Prospeo couldn't find. AI Ark indexes a different email set than Prospeo, so it recovers a meaningful share of Prospeo's misses — the same Prospeo→AI Ark bidirectional fallback that `lilly-tam` uses (see `reference_dm_finder_apis.md`).

#### Mechanism

For each Prospeo-miss, submit the contact's **name + company domain** (or LinkedIn URL — AI Ark, unlike the old finder, accepts a LinkedIn URL). Two access paths:

- **MCP (preferred when connected):** the `ai-ark` MCP's `email_finder` (submit) → `email_finder_results` (poll) tools.
- **REST (fallback when the MCP is down):** resolve the person via `POST https://api.ai-ark.com/api/developer-portal/v1/people` with header `X-TOKEN: $AI_ARK_API_KEY`, per `reference_dm_finder_apis.md`.

#### Decision rule

| Outcome | Action |
|---|---|
| AI Ark returns an email | Keep, mark `source: ai_ark_found`. **No MV re-check** — AI Ark emails are real-time-verified at source. |
| AI Ark returns no email | Drop the row (or hand to the LinkedIn/HeyReach fallback if it has a LinkedIn URL). |
| HTTP `401` (bad/expired key) | **Stop the run** and tell the user the `AI_ARK_API_KEY` needs refreshing — don't silently skip enrichment. |
| HTTP `429` | Back off + retry once; on second 429 stop. |

**Domain shift applies here too** — when AI Ark returns an email at a domain different from the input `company_domain`, apply the same reassignment rule as Step 2a (overwrite `company_domain`, update `company_name` from the finder's company field, preserve originals in `original_*` columns).

**Ledger every AI Ark find.** On every AI Ark call that returns a record (found or not — AI Ark bills per record returned), call `navreo_db.log_provider_usage("ai_ark", 1, endpoint="people", source_id="lilly-email-verification")`. The `upsert_person(..., provider="ai_ark")` write-back itself is unchanged (see the "Persist AI-ARK emails as pre-verified" note above) — this just adds the spend ledger alongside it.

#### Cost note

AI Ark **bills per record it returns**, so only sweep the genuine Prospeo-miss queue (never the whole list) and tighten any account/contact filters. Unlike the old per-success finder, a returned-but-unwanted record still costs — don't over-fetch.

---

## Output

Write a single CSV next to the input: `<input_basename>_enriched.csv`.

### Columns (kept narrow, Smartlead-import-ready)

```
email, first_name, last_name, company_name, company_domain,
linkedin_url, title, country, source, verification_method,
original_company_name, original_company_domain
```

`original_company_name` and `original_company_domain` are populated **only when a domain shift occurred** — Prospeo or the AI Ark finder returned the email at a different domain than the input, so `company_name` and `company_domain` were overwritten. These columns are audit-only; downstream Smartlead imports should use the corrected (top-level) `company_name` / `company_domain`.

`source` is one of:

- `ai_ark_verified` — Stage 1 skipped, came from AI-ARK
- `millionverifier_verified` — passed Stage 1 verification (existing email confirmed deliverable)
- `prospeo_found` — Stage 2a (Prospeo), then MillionVerifier-confirmed
- `ai_ark_found` — Stage 2b fallback after Prospeo `NO_MATCH` (AI Ark, verified at source)

`verification_method` carries forward whatever the upstream tool reported (e.g. AI-ARK's `Business Status`, Prospeo's `verification_method` field plus the MillionVerifier `result`, AI Ark's verification field).

### Also emit a small audit JSON

`<input_basename>_enrichment_audit.json` capturing per-row outcome. Useful if the user ever asks "why was X dropped":

```json
{
  "summary": {
    "input_rows": 8448,
    "kept": 7102,
    "dropped_invalid": 412,
    "dropped_unknown": 145,
    "dropped_disposable": 14,
    "dropped_unverified": 3,
    "kept_catchall": 89,
    "found_by_prospeo": 480,
    "found_by_ai_ark": 132,
    "dropped_not_found": 612,
    "dropped_no_lookup_input": 88,
    "credits_used": {"millionverifier": 480, "ai_ark_find": 132, "prospeo": 480},
    "source": "ai_ark"
  },
  "rows": [
    {"row_index": 0, "outcome": "kept", "source": "ai_ark_verified"},
    {"row_index": 1, "outcome": "dropped", "reason": "no_match"}
  ]
}
```

### Final summary to the user

After the run, print a short summary:

```
Input:  8,448 rows  (source: AI-ARK, Stage 1 skipped)
Found:    480 via Prospeo (MV-verified), 132 via AI Ark fallback
Dropped: 557 unfindable
Kept:   7,891 deliverable rows
Output: ./Exporters_2_3_enriched.csv
```

---

## Workflow Summary

1. Read the CSV, count rows, detect AI-ARK signature columns.
2. Confirm source with the user (auto-detect → one-line confirm; ambiguous → ask).
3. Check both API keys exist before doing anything else; stop if not.
4. **Stage 0** — before any paid call: drop rows caught by `check_exclusions` or already in `contact_history` (report counts), then batch-lookup the remaining rows in the `people` table by email and `linkedin_slug` to build the cache lookup Stage 1 and Stage 2 both consult.
5. **Stage 1** — if not AI-ARK, verify each existing email via MillionVerifier, **skipping any row whose cached `email_verification` is good/ok/valid within the last 90 days** (report the TTL-skip count). Keep `result=ok` and `result=catch_all`; drop `invalid`, `unknown`, `disposable`, `unverified`. Monitor running `credits` balance; stop on exhaustion. Write every real MV verdict back via `upsert_person` + `log_provider_usage`.
6. **Stage 2a** — for rows missing an email, **check the Stage 0 cache by `linkedin_slug` first** (use the cached email, applying the same 90-day TTL rule, before paying for a finder). For remaining rows, call Prospeo `/enrich-person` with the best identifier (domain > LinkedIn). **MillionVerifier-verify each Prospeo-found email** (keep `ok`/`catch_all`, drop otherwise), then write back via `upsert_person` + `log_provider_usage("prospeo", ...)`. Build a fallback queue from the `NO_MATCH` rows (and any that failed MV). **If the returned email's domain differs from the input `company_domain`, overwrite both `company_name` and `company_domain` with the finder's values and preserve the originals in `original_company_name` / `original_company_domain`.**
7. **Stage 2b** — sweep the fallback queue with the AI Ark email finder (name + domain, or LinkedIn URL). AI-Ark emails are verified at source (no MV re-check); persist via `upsert_person(..., provider="ai_ark")` and ledger via `log_provider_usage("ai_ark", ...)`. Apply the same domain-shift reassignment rule. Drop anything AI Ark also can't find (or hand it to LinkedIn/HeyReach if it has a LinkedIn URL).
8. Write the enriched CSV and audit JSON. Print the summary, including count of rows where domain shift triggered a company-name correction, plus suppressed/already-contacted/TTL-skipped/cache-found counts from Stage 0.

## Hand-off — offer to push the no-email-found leads to LinkedIn (HeyReach)

**Always offer this step before finishing the run.** Every enrichment run produces a "dropped, no email found" pile — those leads still have a LinkedIn URL and could be reached via LinkedIn DM instead of email. Don't let them die silently.

After the final summary, ask the user:

> "We couldn't find emails for **{N}** of your leads. Want me to push them to LinkedIn via HeyReach instead? They have LinkedIn URLs, so they'd land in a new HeyReach list ready to feed a LinkedIn campaign."

Then:
- **If yes** → hand off to `lilly-heyreach-upload`. Pass the no-email rows (preserving LinkedIn URL, first name, last name, company name, title, and any inferred metadata like industry / score). The skill handles list creation, custom-field generation, and the upload.
- **If no** → end the run, report final counts as normal.

Never auto-push without confirmation — the user may not have a LinkedIn campaign set up yet, or the no-email leads may be intentional discards. Always ask.

**Implementation note:** the audit JSON already logs every dropped lead with its outcome — pull the `dropped_not_found` + `dropped_no_lookup_input` rows from the audit as the hand-off pool. Don't re-run the enrichment to identify them; the audit is authoritative.

---

## Guardrails

1. **Drop, don't keep with a flag.** The user picked "drop them entirely" for failed/risky leads — don't reintroduce a quarantine pile via a status column.
2. **MillionVerifier-verify Prospeo-found emails; AI-Ark emails are exempt.** (User rule 2026-05-27, overrides the old "trust Prospeo's own verification" stance.) Every `prospeo_found` email goes through the MillionVerifier check — keep `ok`/`catch_all`, drop otherwise. `ai_ark_found` emails are real-time-verified at source, so they are **MV-EXEMPT** — don't re-check them.
3. **Stop on credit exhaustion or auth failure.** MillionVerifier's `error` field mentioning credits, Prospeo's `INSUFFICIENT_CREDITS`, or an AI Ark `401` / credit error all end the run — don't quietly skip remaining rows.
4. **Never request Prospeo mobile fields** — 10x the credit cost and not needed for email enrichment.
5. **Catch-all detection lives in Stage 1.** Don't try to DIY it from MX records — MillionVerifier's `result == "catch_all"` is the source of truth.
6. **Don't drop the AI-ARK columns the user might want later** (e.g. `Title`, `Country`, `LinkedIn`). Carry them through to the output file even if they're not in the standard column set — Smartlead ignores unknown columns on import.
7. **Always preview before pushing to Smartlead.** This skill only writes a CSV. Hand off to `lilly-bot` / `lilly-updates-leads` for the actual upload — that's where dedupe, campaign settings, and global-block-list checks happen.
8. **Trust the email's domain over the input domain.** When Prospeo or the AI Ark finder returns an email at a domain different from `company_domain`, the returned domain is canonical — overwrite `company_name` and `company_domain` with the finder's values, preserve originals in `original_*` columns. The finder verified the email at that mailbox, which means that's where the recipient actually works. Do NOT reject domain shifts as "wrong company" — they're nearly always rebrands, parent companies, or operating entities the input source had stale.


## Upload gate (MANDATORY)

Before ANY lead push into a Smartlead campaign that results from this skill (`add_leads_to_campaign` or equivalent), hand off to `lilly-upload-gate` and let it run to a green gate: every enabled check PASS or explicitly OVERRIDDEN per-flag, and the audit row written to `list_upload_qa_runs` BEFORE the first add-leads call. Never upload around the gate.
