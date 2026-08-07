---
name: lilly-data
description: "Talk to Navreo's central Supabase data layer in plain English — the permanent record of every campaign, contacted lead, archived reply, enrichment, signal, and suppression. Use this skill whenever the user asks a question answerable from outreach history or the central database: 'how many people have we contacted at [company]', 'have we ever emailed [person/domain]', 'which campaigns/mechanisms/icebreakers are working', 'what were the positive replies this week', 'show me the reply for [lead]', 'what does [company] do', 'is [lead] suppressed', 'query the database', 'ask the data', 'check the exclusion list', 'pull campaign performance from Supabase', 'what's our winning framework'. Also use it to look up cached enrichments before paying a provider, or to browse/aggregate contact_history, replies, companies, campaigns, suppressions. Read-only by default — writes only when the user explicitly asks to log/store/correct something."
---

# lilly-data — talk to the Navreo data layer

One skill, one job: answer questions from the central Supabase database (project `fnykldftbkrccihdjayl`) and return the answer in plain English. The user never needs SQL — you translate, run, and summarise. Always show the actual numbers behind a conclusion.

## How to connect (two methods)

**Method A — arbitrary SQL (preferred for aggregates, joins, analytics).** POST the SQL to the Management API:

```bash
set -a; source ~/.navreo-keys.env; set +a
python3 - <<'EOF'
import os, requests, json
r = requests.post(
    'https://api.supabase.com/v1/projects/fnykldftbkrccihdjayl/database/query',
    headers={'Authorization': f"Bearer {os.environ['SUPABASE_ACCESS_TOKEN']}",
             'Content-Type': 'application/json'},
    json={'query': "select count(*) from contact_history"}, timeout=60)
print(json.dumps(r.json(), indent=1))
EOF
```

**Method B — the shared helper (simple lookups, exclusion checks, writes).**

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path.home() / ".claude/skills/_shared"))
import navreo_db
navreo_db.get_enrichment("company", "stripe.com")          # cached provider payload or None
navreo_db.check_exclusions("navreo", emails=[...], domains=[...])
navreo_db.rest("GET", "/rest/v1/replies", params={"category": "eq.Interested", "limit": "20"})
```

Both read keys from `~/.navreo-keys.env` themselves. Everything fails soft — `None` means unreachable, never "no data". SQL via Method A can write too; default to **read-only** unless the user explicitly asks to store/correct something.

## Schema cheat sheet

| Table | What it holds | Key columns |
|---|---|---|
| `contact_history` | every lead ever loaded into a campaign, per client | `email` (citext), `company_domain`, `client_id`, `smartlead_campaign_id`, `status`, `lead_category`, `icebreaker`, `custom_fields` jsonb, `first_contacted_at` |
| `replies` | permanent full-text reply archive (Smartlead deletes these; we never do) | `email`, `smartlead_campaign_id`, `category`, `reply_body`, `replied_at` |
| `campaigns` | campaign registry | PK (`workspace`, `smartlead_campaign_id`), `name`, `status`, `client_id` |
| `campaign_versions` | sequence/variant snapshots (backup of copy) | `sequences` jsonb, `content_hash`, `snapshot_at` |
| `companies` | company directory ("what they do") | `domain` PK canonical, `description`, `industry`, `employee_count/range`, location |
| `people` | person registry | `email` unique, `linkedin_slug` unique, `company_domain` |
| `enrichments` | append-only raw provider payloads = the shared cache | `entity_type`, `entity_key` (domain/slug), `provider`, `fetched_at`, `payload` jsonb |
| `signals` | hiring/funding/engagement events | `company_domain`, `signal_type`, `source`, `detected_at`, `detail` jsonb |
| `suppressions` | manual/imported blocks | `email` and/or `domain`, `client_id` (NULL = global), `reason` |
| `clients` | client registry | `id` slug: navreo, asteri, amplifyy, arnic, wordbank, heygrand, qwintiq, krg, sihl |

Views: `v_exclusion` (contact_history ∪ suppressions), `v_reply_performance`, `v_signal_conversion`, `v_company_directory` (the "own Apollo" browse view). RPC: `check_exclusions(client, emails[], domains[])`.

## Semantics you must get right

- **Positive reply** = `category in ('Interested','Meeting Request','Information Request','Call Booked','Re: Interested')`. Negative: Not Interested, Do Not Contact. Neutral/noise: Out Of Office, Wrong Person, Sender Originated Bounce, Uncategorizable by Ai, Contact Forward. Customs also present: 'Not a qualified lead', 'Contact In Future', 'Not right now', 'Added to Subsequence'.
- **Efficiency, not volume**: when comparing campaigns/mechanisms, positives-per-1k-sends beats raw counts. Send counts are NOT stored — fetch live per campaign: `GET https://server.smartlead.ai/api/v1/campaigns/{id}/analytics?api_key=$SMARTLEAD_API_KEY` → `sent_count`. Throttle ~0.35s between calls (200/min cap).
- **Domains are canonical** (lowercase, no www/protocol/path) — normalise with `navreo_db.canonical_domain()` before matching. Emails are citext (case-insensitive) but lowercase them anyway.
- **`workspace` is 'navreo'** for everything currently loaded (Asteri not backfilled). A campaign *named* "Navreo…" may belong to Arnic (known naming quirk) — `campaigns.client_id` is the truth where set.
- **Exclusion questions** ("have we contacted X / is X blocked") → use the `check_exclusions` RPC or `v_exclusion`, filtered `client_id = :client or client_id is null`. Per-client, never global-by-default.
- **Backfill scope caveat**: history covers non-draft campaigns with ≥500 sends created 2026-01-01 or later (plus some older ones pulled before those rules landed; three pre-2026 campaigns are ~90-95% complete by design). Live capture (Make webhook) covers every reply since 2026-07-04 regardless of campaign size. Company `industry`/`employee_range` coverage is sparse (~1.2k of 234k enriched) and grows as skills run — caveat any size/industry cut with its join coverage.

## Canned answers (copy, adapt, run)

**Have we ever contacted someone / a domain (per client)?**
```sql
select * from check_exclusions('navreo', array['jane@acme.com']::citext[], array['acme.com']);
```

**Positive replies in a period, with bodies:**
```sql
select r.replied_at::date, r.email, c.name as campaign, r.category, left(r.reply_body, 200)
from replies r left join campaigns c
  on c.workspace = r.workspace and c.smartlead_campaign_id = r.smartlead_campaign_id
where r.category in ('Interested','Meeting Request','Information Request','Call Booked')
  and r.replied_at >= now() - interval '7 days'
order by r.replied_at desc;
```

**Campaign / mechanism performance:** group `replies` by campaign (join `campaigns` on workspace + id), count positives, then fetch `sent_count` per campaign from Smartlead analytics and report positives per 1k sends. Classify mechanism from campaign name keywords (follower / recontact / hiring signal / vertical / sales list) unless the user gives their own buckets.

**What does a company do / do we know them?**
```sql
select * from v_company_directory where domain = canonical_domain('https://www.acme.com');
```
Then `navreo_db.get_enrichment("company", domain)` for the full raw payload if more depth is needed.

**Recover overwritten campaign copy:**
```sql
select snapshot_at, sequences from campaign_versions
where smartlead_campaign_id = :id order by snapshot_at desc;
```

## Output rules

- Plain English first, then the table of numbers. No jargon, no column names in prose.
- Always state the denominator and period ("316 positives across 85k sends, all-time").
- If a cut relies on sparse data (industry/size joins, immature campaigns), say so rather than presenting it as settled.
- If Supabase is unreachable, say exactly that — never silently answer from memory.
