---
name: notion-mailbox-sync
description: Write fresh per-domain mailbox health from a deliverability audit back into the Notion "Mailboxes by Domain" database (the team's human-readable fleet-health mirror). Aggregates the audit's inboxes.csv to per-domain counts (Mailbox Count, # Active, # Blocked, # Disconnected, # Low-rep) and stamps Last Audit, while NEVER touching the user-maintained classification fields (Owner, Provider, Registrar, Batch, Date Purchased). Runs automatically as the final step of every email-deliverability-audit, and can be invoked standalone. Trigger phrases: 'sync mailboxes to Notion', 'update the Mailboxes by Domain DB', 'push the audit results to Notion', 'update the domains in Notion', 'refresh the mailbox tracker', or any time a deliverability audit has just produced an inboxes.csv and the Notion mirror needs to reflect it.
---

# Notion Mailbox Sync

Writes the per-domain health snapshot from a deliverability audit into the Notion **"Mailboxes by Domain"** database, so the human-readable fleet tracker always reflects the latest pull.

## When this runs

- **Automatically: as the final step of every `email-deliverability-audit` run** (standing user instruction, set 2026-05-21). The audit's last step invokes this skill.
- **Standalone:** whenever the user wants the Notion mirror refreshed and a recent `inboxes.csv` exists.

This skill is downstream of an audit — it does NOT pull live Smartlead data itself. It consumes the audit's `inboxes.csv` (and `ns_age.csv` for batch labels on brand-new rows). If no audit has been run this session, run `email-deliverability-audit` first.

## Target database

- Page **"Mailboxes"** (`3656e75598d980b59ba0de99f7d5a10c`) → database **"Mailboxes by Domain"**
- Data source: `collection://3656e755-98d9-8040-892f-000be12396b7`
- If the IDs ever change, `fetch` the Mailboxes page to rediscover the data source from its `<database>` tag.

## What to write — and what NEVER to touch

Write ONLY these six audit-derived fields per domain:

| Notion property | Source (aggregated from `inboxes.csv` by domain) |
|---|---|
| `Mailbox Count` | inbox count on the domain |
| `# Blocked` | count with `flag_blocked = TRUE` |
| `# Disconnected` | count with `flag_smtp_fail = TRUE` OR `flag_imap_fail = TRUE` |
| `# Low-rep` | count with `flag_low_reputation = TRUE` |
| `# Active` | `Mailbox Count − # Blocked − # Disconnected` |
| `date:Last Audit:start` | the audit run date (`date:Last Audit:is_datetime = 0`) |

**NEVER overwrite the classification fields** on existing rows — `Owner`, `Provider`, `Registrar`, `Batch`, `Date Purchased` are user-maintained and the audit does not reproduce them. Only for a brand-new domain not yet in the DB do you set `Domain` + `Batch` (from `ns_age.csv`) alongside the six fields above.

## Scope (default vs full)

- **Default: changed domains only** — every domain with `# Blocked > 0` OR `# Low-rep > 0` this run, plus stamping their `Last Audit`. This captures the news (blocks, reputation drops) without re-writing hundreds of unchanged rows.
- **Full-fleet refresh** — every domain's counts + `Last Audit` bumped. Offer this; only do it when the user asks (it is far heavier — see mechanism).

Always confirm scope with the user if it is not already specified by the calling context.

## Step 1 — Compute per-domain health

Read the audit's `inboxes.csv` (prefer the durable copy, e.g. `_audit_<date>/inboxes.csv`, since `/tmp` can be clobbered by concurrent jobs). Aggregate:

```python
import csv, json
from collections import defaultdict
rows = list(csv.DictReader(open("inboxes.csv")))
ns   = {r["domain"]: r for r in csv.DictReader(open("ns_age.csv"))}  # for batch on new rows
agg = defaultdict(lambda: {"mail":0,"blk":0,"disc":0,"low":0})
for r in rows:
    a = agg[r["domain"]]; a["mail"] += 1
    if r["flag_blocked"]=="TRUE": a["blk"] += 1
    if r["flag_smtp_fail"]=="TRUE" or r["flag_imap_fail"]=="TRUE": a["disc"] += 1
    if r["flag_low_reputation"]=="TRUE": a["low"] += 1
out = []
for d, a in agg.items():
    if a["blk"] > 0 or a["low"] > 0:                       # default scope = changed only
        out.append({"domain": d, "batch": ns.get(d, {}).get("batch",""),
                    "mailbox": a["mail"], "active": a["mail"]-a["blk"]-a["disc"],
                    "blocked": a["blk"], "disconnected": a["disc"], "lowrep": a["low"]})
json.dump(out, open("notion_changed.json","w"), indent=0)
print("changed domains:", len(out))
```

(Drop the `if a["blk"]>0 or a["low"]>0` guard for a full-fleet sync.)

## Step 2 — Pick the write mechanism

The connected Notion MCP has **no bulk read and no bulk update**: `fetch` on the data source returns schema only, `notion-search` caps at ~25 results, and `notion-update-page` is one row per call. So:

- **Full-fleet (~300 rows) → token + script (recommended).** A Notion internal-integration token lets a script page the data source (`POST https://api.notion.com/v1/data_sources/{id}/query`, 100/page) and `PATCH /v1/pages/{id}` each row in one pass. There is **no `NOTION_TOKEN` in `~/.navreo-keys.env` yet** — set one up (create an internal integration, share the Mailboxes DB with it, add the key) before relying on this path. ~300 rows via MCP would be ~600 calls and is not viable.
- **Changed-only (≈ dozens of rows) → MCP, no token.** Practical by hand. Use the procedure below.

## Step 2a — MCP procedure (changed-only)

1. **Harvest page IDs with STEM searches**, not one-per-domain. `notion-search` with `data_source_url = collection://3656e755-98d9-8040-892f-000be12396b7` and a domain-family stem (e.g. `bridgeandscale`, `planandvision`, `gtmnavreo`) returns all variants in a single call. Group the changed domains by stem and search each stem.
2. **Match each result to its EXACT title** to get the page ID. ⚠️ **Confusable-sibling gotcha:** families have look-alike rows (`navreosystems.info` vs `navreosystems.digital`, `navreogtm.info` vs `gtmnavreo.info`). Always pin the page ID to the exact domain string, and sanity-check each `Mailbox Count` against the domain's batch (e.g. Boomerang rows are 3 mailboxes, Zapmail rows are 5, Hypertide rows are ~50) before writing.
3. **Update each row** with `notion-update-page`, `command = update_properties`, e.g.:
   ```
   {"Mailbox Count": 5, "# Active": 0, "# Blocked": 5, "# Disconnected": 0,
    "# Low-rep": 0, "date:Last Audit:start": "<run-date>", "date:Last Audit:is_datetime": 0}
   ```
   (Pass `content_updates: []` and `position: {"type":"end"}` to satisfy the tool schema; they are ignored for `update_properties`.)
4. Batch the update calls in parallel (~12 per message) to keep it moving.

## Step 3 — Verify

`fetch` 3–4 representative rows after writing (especially any you corrected) and confirm: the six fields are right AND the classification fields (`Owner`/`Provider`/`Registrar`/`Batch`/`Date Purchased`) are untouched.

## Communication style

Report to the user in plain English: how many domain rows you updated, which batches they covered, and that classification fields were left alone. If you fell back to changed-only because there is no token, say so and restate the one-time token setup as the path to full-fleet syncs.

## Related

- `email-deliverability-audit` — produces the `inboxes.csv` this skill consumes; invokes this skill as its final step.
- `lilly-email-verification`, `lilly-bot` — other Smartlead-adjacent ops.
